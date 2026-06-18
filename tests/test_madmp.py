"""Tests for maDMP parsing, including partial/odd coverage."""

import json

from inst2ord.madmp import parse_madmp, validate_madmp


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


def test_orcid_url_prefix_stripped(tmp_path):
    doc = {"dmp": {"contact": {
        "name": "John Smith", "mbox": "john@example.org",
        "contact_id": {"identifier": "https://orcid.org/0000-0001-2345-6789",
                       "type": "orcid"},
    }}}
    madmp = parse_madmp(_write(tmp_path, doc))
    # orcid is the bare identifier; the raw URL is kept on .identifier.
    assert madmp.contact.orcid == "0000-0001-2345-6789"
    assert madmp.contact.identifier == "https://orcid.org/0000-0001-2345-6789"


def test_affiliation_with_ror_parsed(tmp_path):
    doc = {"dmp": {"contributor": [{
        "name": "Ada", "role": "Researcher",
        "contributor_id": {"identifier": "0000-1", "type": "orcid"},
        "affiliation": [{
            "name": "TU Wien",
            "affiliation_id": {
                "identifier": "https://ror.org/04d836q62", "type": "ror"},
        }],
    }]}}
    aff = parse_madmp(_write(tmp_path, doc)).contributors[0].affiliations[0]
    assert aff.name == "TU Wien"
    assert aff.ror == "https://ror.org/04d836q62"   # canonical URL
    assert aff.identifier_type == "ror"
    assert aff.city is None                          # not resolved at parse


def test_affiliation_non_ror_id_has_no_ror(tmp_path):
    doc = {"dmp": {"contact": {
        "name": "Bo", "contact_id": {"identifier": "x", "type": "orcid"},
        "affiliation": {  # a lone object (not an array) is tolerated
            "name": "Some Lab",
            "affiliation_id": {"identifier": "0000 0001", "type": "isni"},
        },
    }}}
    aff = parse_madmp(_write(tmp_path, doc)).contact.affiliations[0]
    assert aff.name == "Some Lab"
    assert aff.ror is None                # only 'ror' type yields a ROR
    assert aff.identifier == "0000 0001"


def test_affiliation_non_string_id_type_is_tolerated(tmp_path):
    # A non-string affiliation_id.type must not crash the parse (the module
    # promises unexpectedly typed values yield None/empty, not an error).
    doc = {"dmp": {"contributor": [{
        "name": "Ada", "role": "Researcher",
        "contributor_id": {"identifier": "0000-1", "type": "orcid"},
        "affiliation": [{
            "name": "X", "affiliation_id": {"identifier": "y", "type": 5}}],
    }]}}
    aff = parse_madmp(_write(tmp_path, doc)).contributors[0].affiliations[0]
    assert aff.ror is None
    assert aff.name == "X"


def test_null_dmp_wrapper(tmp_path):
    madmp = parse_madmp(_write(tmp_path, {"dmp": None}))
    assert madmp.title is None
    assert madmp.contributors == []


def test_schema_validation_accepts_example(madmp_example):
    assert validate_madmp(madmp_example) == []


def test_schema_validation_reports_violations(tmp_path):
    # 'created' should be a date-time string and dmp has required fields.
    path = tmp_path / "bad.json"
    path.write_text(json.dumps({"dmp": {"created": 12345}}), encoding="utf-8")
    issues = validate_madmp(str(path))
    assert issues  # non-empty list of human-readable messages


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
