"""Tests for the compound resolver (no network: PubChem is monkeypatched)."""

import pytest

from inst2ord.models import InputComponent
from inst2ord.resolve import CompoundResolver, normalize_name


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("sdt phenol, 1.6 mg in 4 mL H20", "phenol"),
        ("sodium chloride, 5 g", "sodium chloride"),
        ("1,2-dichlorobenzene", "1,2-dichlorobenzene"),   # comma kept
        ("N,N-dimethylformamide", "N,N-dimethylformamide"),
        ("2 guanidine", "2 guanidine"),                   # 'g' not a unit here
        ("water", "water"),
    ],
)
def test_normalize_name(raw, expected):
    assert normalize_name(raw) == expected


def test_summarise_props_single():
    rows = [{"InChIKey": "AAA-1", "InChI": "InChI=x", "IUPACName": "a"}]
    result = CompoundResolver._summarise_props(rows)
    assert result["inchikey"] == "AAA-1"
    assert not result.get("ambiguous")


def test_summarise_props_multiple_is_ambiguous():
    rows = [{"InChIKey": "AAA-1"}, {"InChIKey": "BBB-2"},
            {"InChIKey": "AAA-1"}]
    result = CompoundResolver._summarise_props(rows)
    assert result["ambiguous"] is True
    assert set(result["inchikeys"]) == {"AAA-1", "BBB-2"}


def test_summarise_props_empty_is_miss():
    assert CompoundResolver._summarise_props([]) == {}


def test_curation_takes_precedence(tmp_path):
    table = tmp_path / "curation.csv"
    table.write_text(
        "raw_name,resolved_name,inchi,inchikey,smiles,cas,source,notes\n"
        "Allura Red AC,,,CEZ-key,,1234-56-7,manual,\n",
        encoding="utf-8",
    )
    resolver = CompoundResolver(curation_path=str(table))
    comp = InputComponent(name="allura red ac")  # case-insensitive match
    resolver.resolve(comp)
    assert comp.inchikey == "CEZ-key"
    assert comp.cas == "1234-56-7"
    assert not resolver.unresolved


def test_unresolved_when_offline():
    resolver = CompoundResolver(use_pubchem=False)
    comp = InputComponent(name="mystery reagent")
    resolver.resolve(comp)
    assert comp.inchikey is None
    assert resolver.unresolved == {"mystery reagent": ""}


def test_ambiguous_match_goes_to_unresolved(monkeypatch):
    resolver = CompoundResolver(use_pubchem=True)
    monkeypatch.setattr(
        resolver,
        "_fetch_pubchem",
        lambda name: {"ambiguous": True, "inchikeys": ["A", "B"]},
    )
    comp = InputComponent(name="xylene")
    resolver.resolve(comp)
    assert comp.inchikey is None
    assert "ambiguous" in resolver.unresolved["xylene"]


def test_unique_match_resolves_and_derives_smiles(monkeypatch):
    resolver = CompoundResolver(use_pubchem=True)
    monkeypatch.setattr(
        resolver,
        "_fetch_pubchem",
        lambda name: {
            "inchi": "InChI=1S/H2O/h1H2",
            "inchikey": "XLYOFNOQVPJJNP-UHFFFAOYSA-N",
        },
    )
    comp = InputComponent(name="water")
    resolver.resolve(comp)
    assert comp.inchikey == "XLYOFNOQVPJJNP-UHFFFAOYSA-N"
    assert comp.smiles == "O"  # derived from InChI via RDKit
    assert "water" not in resolver.unresolved


def test_write_unresolved_removes_stale_file(tmp_path):
    out = tmp_path / "unresolved.csv"
    resolver = CompoundResolver()
    resolver._mark_unresolved("foo", "ambiguous PubChem match: A, B")
    resolver.write_unresolved(str(out))
    assert out.exists()
    assert "ambiguous PubChem match" in out.read_text()

    # A later run with nothing unresolved must clear the stale file.
    CompoundResolver().write_unresolved(str(out))
    assert not out.exists()
