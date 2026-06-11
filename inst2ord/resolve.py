"""Resolve free-text chemical names to structures/identifiers.

Resolution order for each name:

1. **Curation table** (``curation.csv``) -- a hand-maintained, authoritative
   ``raw_name -> {inchi, inchikey, smiles, cas, ...}`` mapping.  This is also
   where future CAS numbers or ELN identifiers are added.
2. **PubChem** (only when ``use_pubchem`` is set) -- queried by a normalised
   name and cached on disk so a given name is fetched at most once.  The
   canonical SMILES is derived from the returned InChI via RDKit.
3. Otherwise the name is recorded as *unresolved* for manual curation; the
   raw name is always retained as an ORD ``NAME`` identifier regardless.

Names from the platform often embed amounts/solvents
(``"sdt phenol, 1.6 mg in 4 mL H20"``); :func:`normalize_name` strips those
before lookup.
"""

from __future__ import annotations

import csv
import hashlib
import json
import os
import re
from urllib.parse import quote

from inst2ord.models import InputComponent

_PUBCHEM_URL = (
    "https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/{name}"
    "/property/InChI,InChIKey,IUPACName/JSON"
)
_AMOUNT_RE = re.compile(
    r"\d+(?:\.\d+)?\s*(mg|g|kg|ug|µg|mL|ml|uL|µL|L|mmol|mol|M|wt%|%)"
    r"(?![A-Za-zµ])",  # unit not followed by a letter (avoid "2 guanidine")
    re.IGNORECASE,
)
_CURATION_FIELDS = [
    "raw_name",
    "resolved_name",
    "inchi",
    "inchikey",
    "smiles",
    "cas",
    "source",
    "notes",
]


def normalize_name(name: str) -> str:
    """Reduce a platform name to a query likely to match in PubChem.

    Strips a leading sample code (``"sdt "``), any embedded amount fragments
    (``"1.6 mg"``, ``"4 mL"``) and a trailing ``"in <solvent>"`` clause, then
    tidies leftover separators.  It deliberately does *not* split on commas,
    so IUPAC names such as ``"1,2-dichlorobenzene"`` or
    ``"N,N-dimethylformamide"`` survive intact.
    """
    text = re.sub(r"^\s*sdt\s+", "", name.strip(), flags=re.IGNORECASE)
    text = _AMOUNT_RE.sub("", text)                       # "1.6 mg", "4 mL"
    text = re.sub(r",?\s*\bin\b\s.*$", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s{2,}", " ", text).strip(" ,;")
    return text or name.strip()


class CompoundResolver:
    """Resolve :class:`InputComponent` names to structures/identifiers."""

    def __init__(
        self,
        curation_path: str | None = None,
        cache_dir: str | None = None,
        use_pubchem: bool = False,
        timeout: float = 15.0,
    ) -> None:
        self.cache_dir = cache_dir
        self.use_pubchem = use_pubchem
        self.timeout = timeout
        self.curation = self._load_curation(curation_path)
        # raw name -> reason it needs manual curation (written to notes).
        self.unresolved: dict[str, str] = {}

    # -- public API ---------------------------------------------------------

    def resolve_all(self, components: list[InputComponent]) -> None:
        for component in components:
            self.resolve(component)

    def resolve(self, component: InputComponent) -> None:
        """Fill structure/identifier fields on ``component`` in place.

        A PubChem lookup that maps to several distinct structures (multiple
        InChIKeys) is treated as ambiguous and sent to manual curation
        rather than guessed.
        """
        cured = self.curation.get(component.name.strip().lower())
        if cured:
            self._apply(component, cured)
            return
        if self.use_pubchem:
            found = self._lookup_pubchem(normalize_name(component.name))
            if found and found.get("ambiguous"):
                keys = ", ".join(found.get("inchikeys", []))
                self._mark_unresolved(
                    component.name, f"ambiguous PubChem match: {keys}"
                )
                return
            if found and found.get("inchikey"):
                self._apply(component, found)
                return
        self._mark_unresolved(component.name, "")

    def _mark_unresolved(self, name: str, reason: str) -> None:
        # Record the name; keep the first non-empty reason seen for it.
        if name not in self.unresolved:
            self.unresolved[name] = reason
        elif reason and not self.unresolved[name]:
            self.unresolved[name] = reason

    def write_unresolved(self, path: str) -> None:
        """Write names needing manual curation as a curation-table stub.

        When nothing is unresolved any stale file is removed, so the file
        always reflects the current run.
        """
        if not self.unresolved:
            if os.path.exists(path):
                os.remove(path)
            return
        with open(path, "w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=_CURATION_FIELDS)
            writer.writeheader()
            for name, reason in self.unresolved.items():
                writer.writerow({"raw_name": name, "notes": reason})

    # -- internals ----------------------------------------------------------

    @staticmethod
    def _load_curation(path: str | None) -> dict[str, dict]:
        if not path or not os.path.exists(path):
            return {}
        table: dict[str, dict] = {}
        with open(path, newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                raw = (row.get("raw_name") or "").strip().lower()
                if raw:
                    table[raw] = row
        return table

    @staticmethod
    def _apply(component: InputComponent, data: dict) -> None:
        component.inchi = data.get("inchi") or component.inchi
        component.inchikey = data.get("inchikey") or component.inchikey
        component.smiles = data.get("smiles") or component.smiles
        component.cas = data.get("cas") or component.cas
        component.resolved_name = (
            data.get("resolved_name") or data.get("iupac_name") or None
        )
        if component.inchi and not component.smiles:
            component.smiles = _smiles_from_inchi(component.inchi)

    def _lookup_pubchem(self, name: str) -> dict | None:
        """Return a result dict (possibly ``{"ambiguous": True}``) or ``None``.

        ``None`` means a transient failure (e.g. network/throttling) and is
        not cached; an empty dict is a cached "known miss".
        """
        cached = self._cache_read(name)
        if cached is not None:
            return cached
        result = self._fetch_pubchem(name)
        if result is None:
            return None  # do not cache transient failures as misses
        self._cache_write(name, result)
        return result

    def _fetch_pubchem(self, name: str) -> dict | None:
        import requests  # local import keeps the dep optional

        url = _PUBCHEM_URL.format(name=quote(name, safe=""))
        try:
            response = requests.get(url, timeout=self.timeout)
        except requests.RequestException:
            return None
        if response.status_code != 200:
            return None
        try:
            props = response.json()["PropertyTable"]["Properties"]
        except (ValueError, KeyError, IndexError):
            return None
        return self._summarise_props(props)

    @staticmethod
    def _summarise_props(props: list[dict]) -> dict:
        """Reduce PubChem property rows to one result, flagging ambiguity."""
        distinct: dict[str, dict] = {}
        for entry in props:
            key = entry.get("InChIKey")
            if key:
                distinct.setdefault(key, entry)
        if not distinct:
            return {}  # known miss
        if len(distinct) > 1:
            return {
                "ambiguous": True,
                "inchikeys": list(distinct)[:10],
                "source": "pubchem",
            }
        match = next(iter(distinct.values()))
        return {
            "inchi": match.get("InChI"),
            "inchikey": match.get("InChIKey"),
            "iupac_name": match.get("IUPACName"),
            "source": "pubchem",
        }

    def _cache_path(self, name: str) -> str | None:
        if not self.cache_dir:
            return None
        digest = hashlib.sha1(name.encode("utf-8")).hexdigest()
        return os.path.join(self.cache_dir, f"{digest}.json")

    def _cache_read(self, name: str) -> dict | None:
        path = self._cache_path(name)
        if not path or not os.path.exists(path):
            return None
        try:
            with open(path, encoding="utf-8") as handle:
                return json.load(handle)
        except (OSError, ValueError):
            return None

    def _cache_write(self, name: str, data: dict) -> None:
        path = self._cache_path(name)
        if not path:
            return
        os.makedirs(self.cache_dir, exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2)


def _smiles_from_inchi(inchi: str) -> str | None:
    """Derive a canonical SMILES from an InChI using RDKit, if available."""
    try:
        from rdkit import Chem
    except ImportError:
        return None
    mol = Chem.MolFromInchi(inchi)
    return Chem.MolToSmiles(mol) if mol is not None else None
