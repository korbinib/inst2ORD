"""Parse a maDMP (RDA-DMP-Common 1.2) JSON file into :class:`MaDmp`.

This is intentionally separate from the instrument adapters: a maDMP is a
cross-cutting metadata source, not instrument output.  The builder merges
it at the ORD ``Dataset`` + ``provenance`` level.  Only the fields ORD can
represent are extracted; the rest is ignored.
"""

from __future__ import annotations

import json

from inst2ord.models import Funding, MaDmp, MaDmpProject, Person


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
        orcid=id_value if id_type == "orcid" else None,
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
