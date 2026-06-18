"""Parse a maDMP (RDA-DMP-Common 1.2) JSON file into :class:`MaDmp`.

This is intentionally separate from the instrument adapters: a maDMP is a
cross-cutting metadata source, not instrument output.  The builder merges
it at the ORD ``Dataset`` + ``provenance`` level.  Only the fields ORD can
represent are extracted; the rest is ignored.
"""

from __future__ import annotations

import json
import os

from inst2ord.models import Funding, MaDmp, MaDmpProject, Person

# Bundled RDA-DMP-Common 1.2 JSON schema (public domain / Unlicense).
SCHEMA_PATH = os.path.join(
    os.path.dirname(__file__), "schemas", "maDMP-schema-1.2.json"
)


def validate_madmp(path: str) -> list[str]:
    """Validate a maDMP file against the RDA 1.2 JSON schema.

    Returns a (possibly empty) list of human-readable violation messages;
    an empty list means the document is schema-valid.  Requires the
    ``jsonschema`` package -- ``ModuleNotFoundError`` propagates so the
    caller can decide whether to skip the check.
    """
    from jsonschema.validators import validator_for

    with open(SCHEMA_PATH, encoding="utf-8") as handle:
        schema = json.load(handle)
    with open(path, encoding="utf-8") as handle:
        document = json.load(handle)
    validator = validator_for(schema)(schema)
    messages = []
    for error in sorted(validator.iter_errors(document),
                        key=lambda e: list(e.path)):
        location = "/".join(str(p) for p in error.path) or "(root)"
        messages.append(f"{location}: {error.message}")
    return messages


def parse_madmp(path: str) -> MaDmp:
    """Read a maDMP JSON file and return the mapped subset.

    maDMPs vary in coverage, so every field is optional: missing, null or
    unexpectedly typed values are tolerated and simply yield ``None``/empty
    rather than an error.
    """
    with open(path, "r", encoding="utf-8") as handle:
        document = json.load(handle)
    if not isinstance(document, dict):
        raise ValueError(f"maDMP root is not a JSON object: {path}")
    # The "dmp" wrapper is conventional but tolerate its absence or a null.
    dmp = document.get("dmp")
    if not isinstance(dmp, dict):
        dmp = document

    madmp = MaDmp(
        title=dmp.get("title"),
        description=dmp.get("description"),
        language=dmp.get("language"),
        created=dmp.get("created"),
        modified=dmp.get("modified"),
        source_path=path,
    )

    dmp_id = dmp.get("dmp_id") or {}
    if isinstance(dmp_id, dict):
        madmp.dmp_id = dmp_id.get("identifier")
        madmp.dmp_id_type = dmp_id.get("type")

    contact = dmp.get("contact")
    if isinstance(contact, dict):
        madmp.contact = _person(contact, "contact_id")

    for entry in dmp.get("contributor") or []:
        if isinstance(entry, dict):
            madmp.contributors.append(_person(entry, "contributor_id"))

    for entry in dmp.get("project") or []:
        if isinstance(entry, dict):
            madmp.projects.append(_project(entry))

    return madmp


def _person(entry: dict, id_key: str) -> Person:
    identifier = entry.get(id_key)
    identifier = identifier if isinstance(identifier, dict) else {}
    id_value = identifier.get("identifier") or None
    id_type = identifier.get("type")
    return Person(
        name=entry.get("name"),
        email=_clean_email(entry.get("mbox")),
        orcid=_clean_orcid(id_value) if id_type == "orcid" else None,
        identifier=id_value,
        identifier_type=id_type,
        roles=_roles(entry.get("role")),
    )


def _roles(role) -> list[str]:
    """Normalise the ``role`` field, which may be missing, a string or list."""
    if role is None:
        return []
    if isinstance(role, str):
        return [role]
    return [r for r in role if isinstance(r, str)]


def _clean_email(mbox) -> str | None:
    """Return a bare email, stripping any ``mailto:`` prefix."""
    if not isinstance(mbox, str) or not mbox:
        return None
    return mbox[7:] if mbox.lower().startswith("mailto:") else mbox


def _clean_orcid(value) -> str | None:
    """Return a bare ORCID identifier, stripping any ``orcid.org`` URL prefix.

    maDMPs express an ORCID either as the bare ``0000-0001-2345-6789`` or as
    the resolvable URL ``https://orcid.org/0000-0001-2345-6789``.  ORD's
    ``Person.orcid`` expects the bare identifier, so strip the scheme,
    optional ``www.`` and the ``orcid.org/`` host before returning it.
    """
    if not isinstance(value, str):
        return None
    bare = value.strip()
    if not bare:
        return None
    lowered = bare.lower()
    for scheme in ("https://", "http://"):
        if lowered.startswith(scheme):
            bare = bare[len(scheme):]
            lowered = bare.lower()
            break
    if lowered.startswith("www."):
        bare = bare[4:]
        lowered = bare.lower()
    if lowered.startswith("orcid.org/"):
        bare = bare[len("orcid.org/"):]
    return bare.strip("/") or None


def _project(entry: dict) -> MaDmpProject:
    project = MaDmpProject(
        title=entry.get("title"),
        description=entry.get("description"),
        start=entry.get("start"),
        end=entry.get("end"),
    )
    for fund in entry.get("funding") or []:
        if not isinstance(fund, dict):
            continue
        project.funding.append(
            Funding(
                funder_name=fund.get("funder_name"),
                funder_id=_nested_id(fund, "funder_id"),
                grant_id=_nested_id(fund, "grant_id"),
            )
        )
    return project


def _nested_id(entry: dict, key: str) -> str | None:
    """Return ``entry[key]["identifier"]`` if present and non-empty."""
    nested = entry.get(key)
    if not isinstance(nested, dict):
        return None
    return nested.get("identifier") or None
