"""Tests for maDMP parsing, including partial/odd coverage."""

import json

from inst2ord.madmp import parse_madmp


def _write(tmp_path, doc):
    path = tmp_path / "dmp.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    return str(path)


def test_full_example(madmp_example):
    madmp = parse_madmp(madmp_example)
    assert madmp.title == "DMP for our new project"
    assert madmp.contact.name == "John Smith"
    assert madmp.contact.email == "john.smith@tuwien.ac.at"
    assert len(madmp.contributors) == 3
    assert madmp.dmp_id == "10.0000/00.0.1234"
    assert madmp.dmp_id_type == "doi"
    assert madmp.projects[0].funding[0].grant_id == "EO-2-2017"


def test_title_only(tmp_path):
    madmp = parse_madmp(_write(tmp_path, {"dmp": {"title": "Minimal"}}))
    assert madmp.title == "Minimal"
    assert madmp.contact is None
    assert madmp.contributors == []


def test_role_as_string_and_mailto_prefix(tmp_path):
    doc = {"dmp": {"contributor": [{
        "name": "Ada", "mbox": "mailto:ada@example.org",
        "role": "ContactPerson",
        "contributor_id": {"identifier": "0000-0001-2345-6789",
                           "type": "orcid"},
    }]}}
    madmp = parse_madmp(_write(tmp_path, doc))
    person = madmp.contributors[0]
    assert person.roles == ["ContactPerson"]      # string -> list
    assert person.email == "ada@example.org"      # mailto: stripped
    assert person.orcid == "0000-0001-2345-6789"


def test_null_dmp_wrapper(tmp_path):
    madmp = parse_madmp(_write(tmp_path, {"dmp": None}))
    assert madmp.title is None
    assert madmp.contributors == []


def test_junk_entries_are_skipped(tmp_path):
    doc = {"dmp": {
        "title": "Robust",
        "dmp_id": None,
        "contributor": ["not-a-dict", {"name": "Bob"}],
        "project": [
            {"title": "P", "funding": ["junk", {"funder_name": "NSF"}]}
        ],
    }}
    madmp = parse_madmp(_write(tmp_path, doc))
    assert [c.name for c in madmp.contributors] == ["Bob"]
    assert madmp.projects[0].funding[0].funder_name == "NSF"
    assert madmp.dmp_id is None
