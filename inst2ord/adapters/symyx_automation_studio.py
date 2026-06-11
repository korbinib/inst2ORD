"""Adapter for the Symyx / Unchained Labs "Automation Studio" platform.

It reads the platform's two XML file types and emits a neutral
:class:`~inst2ord.models.ReactionIntent` per experiment:

* ``*ChemFile.xml``  -- chemicals loaded on the deck + plate/rack layout.
* ``*Prompt[File].xml`` -- run/setup options (instrument configuration).

Files are grouped into a logical run by the ``Exp###`` token in the
filename.  See :mod:`inst2ord.models` for the neutral target types.
"""

from __future__ import annotations

import os
import re
import xml.etree.ElementTree as ET

from inst2ord.adapters.base import InstrumentAdapter
from inst2ord.models import (
    InputComponent,
    Labware,
    ProvenanceHints,
    ReactionIntent,
    SetupOption,
    ROLE_REACTANT,
    ROLE_SOLVENT,
    ROLE_UNSPECIFIED,
)
from inst2ord.parsers import load_xml_root, text_or_none

# Dotted container tags (matched literally against ``element.tag``; we avoid
# ElementTree's find() XPath for these because the dots are path operators).
_CM = "Symyx.AutomationStudio.Core.ChemicalManager"
_CHEMICALS = _CM + ".Chemicals"
_CHEMICAL = _CM + ".Chemical"
_LIBRARIES = _CM + ".Libraries"
_LIBRARY = _CM + ".Library"

_EXP_RE = re.compile(r"Exp(\d+)", re.IGNORECASE)
# Amount fragments embedded in free-text names, e.g. "1.6 mg", "4 mL".
_AMOUNT_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*(mg|g|kg|ug|µg|mL|ml|uL|µL|L|mmol|mol|M|wt%|%)"
    r"(?![A-Za-zµ])",  # unit not followed by a letter (avoid "2 guanidine")
    re.IGNORECASE,
)

# Platform substrate type -> neutral reaction role.
_TYPE_TO_ROLE = {
    "stNormal": ROLE_REACTANT,
    "stBackingSolvent": ROLE_SOLVENT,
}


def _children(element: ET.Element | None, tag: str) -> list[ET.Element]:
    """Direct children with tag ``tag`` (``None`` element yields ``[]``)."""
    if element is None:
        return []
    return [child for child in element if child.tag == tag]


def _first(element: ET.Element | None, tag: str) -> ET.Element | None:
    for child in _children(element, tag):
        return child
    return None


def _int(element: ET.Element, tag: str) -> int | None:
    value = text_or_none(element.find(tag))
    try:
        return int(value) if value is not None else None
    except ValueError:
        return None


def _float(element: ET.Element, tag: str) -> float | None:
    value = text_or_none(element.find(tag))
    try:
        return float(value) if value is not None else None
    except ValueError:
        return None


def _bool(element: ET.Element, tag: str) -> bool | None:
    value = text_or_none(element.find(tag))
    if value is None:
        return None
    return value.strip().lower() == "true"


class SymyxAutomationStudioAdapter(InstrumentAdapter):
    name = "symyx-automation-studio"
    description = "Symyx / Unchained Labs Automation Studio XML files"

    # -- InstrumentAdapter contract ----------------------------------------

    def sniff(self, path: str) -> bool:
        if not path.lower().endswith(".xml"):
            return False
        try:
            with open(path, "r", encoding="utf-8-sig") as handle:
                head = handle.read(2048)
        except OSError:
            return False
        return (
            "Symyx.AutomationStudio" in head
            or "promptsOptionsConfiguration" in head
        )

    def parse_dir(self, input_dir: str) -> list[ReactionIntent]:
        runs = self._discover(input_dir)
        intents: list[ReactionIntent] = []
        for exp_id in sorted(runs, key=lambda x: int(x)):
            files = runs[exp_id]
            intents.append(self._parse_run(exp_id, files))
        return intents

    # -- discovery ----------------------------------------------------------

    def _discover(self, input_dir: str) -> dict[str, dict[str, str]]:
        """Group files by Exp number into {exp_id: {chem, prompt}} paths."""
        runs: dict[str, dict[str, str]] = {}
        for name in sorted(os.listdir(input_dir)):
            path = os.path.join(input_dir, name)
            if not os.path.isfile(path) or not self.sniff(path):
                continue
            match = _EXP_RE.search(name)
            if not match:
                continue  # orphan template (e.g. promptspart1mod2.xml)
            exp_id = match.group(1)
            slot = "chem" if "chem" in name.lower() else "prompt"
            runs.setdefault(exp_id, {})[slot] = path
        return runs

    # -- per-run parsing ----------------------------------------------------

    def _parse_run(self, exp_id: str, files: dict[str, str]) -> ReactionIntent:
        intent = ReactionIntent(
            run_id=f"Exp{exp_id}",
            instrument=self.name,
            provenance=ProvenanceHints(
                run_id=f"Exp{exp_id}", instrument=self.name, is_automated=True
            ),
            source_files=[files[k] for k in ("chem", "prompt") if k in files],
        )
        if "chem" in files:
            self._parse_chemfile(files["chem"], intent)
        if "prompt" in files:
            self._parse_promptfile(files["prompt"], intent)
        return intent

    def _parse_chemfile(self, path: str, intent: ReactionIntent) -> None:
        root = load_xml_root(path)
        manager = _first(root, _CM)
        dispense_modes = self._parse_dispense_modes(root)
        if manager is None:
            return

        chemicals_node = _first(manager, _CHEMICALS)
        for node in _children(chemicals_node, _CHEMICAL):
            name = text_or_none(node.find("Name"))
            if not name:
                continue
            ctype = text_or_none(node.find("Type"))
            position = self._position_label(node)
            if ctype == "stPlate":
                intent.labware.append(
                    Labware(
                        kind=text_or_none(node.find("SubstrateType")),
                        name=name,
                        rows=_int(node, "Rows"),
                        cols=_int(node, "Columns"),
                        position=text_or_none(node.find("SubstratePosition")),
                    )
                )
                continue
            component = InputComponent(
                name=name,
                role=_TYPE_TO_ROLE.get(ctype, ROLE_UNSPECIFIED),
                amount_text=self._extract_amount(name),
                position=position,
                extra=self._chemical_extra(node, dispense_modes.get(name)),
            )
            intent.inputs.append(component)

        libraries_node = _first(manager, _LIBRARIES)
        for node in _children(libraries_node, _LIBRARY):
            intent.labware.append(
                Labware(
                    kind=text_or_none(node.find("SubstrateType")),
                    name=text_or_none(node.find("Name")),
                    identifier=text_or_none(node.find("LibraryID")),
                    rows=_int(node, "NumOfRows"),
                    cols=_int(node, "NumOfCols"),
                    position=text_or_none(node.find("SubstratePosition")),
                )
            )

    @staticmethod
    def _parse_dispense_modes(root: ET.Element) -> dict[str, str]:
        modes: dict[str, str] = {}
        section = _first(root, "ChemicalsAndAssociatedDispenseModes")
        if section is None:
            return modes
        manager = _first(section, "ChemicalManager")
        for chem in _children(manager, "Chemical"):
            name = chem.get("Name")
            mode = chem.get("Mode")
            if name and mode:
                modes[name] = mode
        return modes

    @staticmethod
    def _position_label(node: ET.Element) -> str | None:
        row, col = _int(node, "Row"), _int(node, "Column")
        if row is None or col is None:
            return None
        return f"r{row}c{col}"

    @staticmethod
    def _chemical_extra(
        node: ET.Element, dispense_mode: str | None
    ) -> dict[str, str]:
        extra: dict[str, str] = {}
        for tag in ("Type", "SubstrateType", "SubstratePosition", "Units"):
            value = text_or_none(node.find(tag))
            if value:
                extra[tag] = value
        if dispense_mode:
            extra["DispenseMode"] = dispense_mode
        return extra

    @staticmethod
    def _extract_amount(name: str) -> str | None:
        match = _AMOUNT_RE.search(name)
        return match.group(0) if match else None

    def _parse_promptfile(self, path: str, intent: ReactionIntent) -> None:
        root = load_xml_root(path)
        config = _first(root, "promptsOptionsConfiguration")
        categories = _first(config, "categories")
        if categories is None:
            return
        for category in _children(categories, "category"):
            cat_name = category.get("name") or ""
            prompts = _first(category, "prompts")
            for prompt in _children(prompts, "prompt"):
                value, options = self._parse_prompt_value(prompt.text)
                intent.setup_options.append(
                    SetupOption(
                        category=cat_name,
                        name=prompt.get("name") or "",
                        description=prompt.get("description"),
                        value=value,
                        options=options,
                    )
                )
        self._collect_operator_emails(intent)

    @staticmethod
    def _parse_prompt_value(raw: str | None) -> tuple[str | None, list[str]]:
        """Resolve a prompt value: ``@`` marks the selected list choice."""
        if raw is None:
            return None, []
        if ";" not in raw:
            return raw.strip() or None, []
        options: list[str] = []
        selected: str | None = None
        for token in (t.strip() for t in raw.split(";")):
            if not token:
                continue
            clean = token[1:].strip() if token.startswith("@") else token
            options.append(clean)
            if token.startswith("@"):
                selected = clean
        value = selected if selected is not None else (raw.strip() or None)
        return value, options

    @staticmethod
    def _collect_operator_emails(intent: ReactionIntent) -> None:
        for option in intent.setup_options:
            if option.name == "EmailNotificationList" and option.value:
                intent.provenance.operator_emails = [
                    e.strip() for e in option.value.split(";") if "@" in e
                ]
                return
