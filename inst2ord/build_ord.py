"""Build ORD messages from the neutral intermediate model.

This module is the *only* place that touches the ``ord_schema`` protobufs,
and it depends only on :class:`~inst2ord.models.ReactionIntent` and
:class:`~inst2ord.models.MaDmp` -- never on any instrument's native format.
The output is a template-grade ``Dataset``: inputs, setup and provenance
are populated from the source data, while amounts/outcomes are left blank
for completion in the ORD reaction editor.
"""

from __future__ import annotations

import datetime
import re

from ord_schema.proto import dataset_pb2, reaction_pb2

from inst2ord.models import (
    MaDmp,
    ReactionIntent,
    ROLE_CATALYST,
    ROLE_PRODUCT,
    ROLE_REACTANT,
    ROLE_REAGENT,
    ROLE_SOLVENT,
)

_CID = reaction_pb2.CompoundIdentifier  # shorthand for identifier types

_ROLE_TO_ORD = {
    ROLE_REACTANT: reaction_pb2.ReactionRole.REACTANT,
    ROLE_REAGENT: reaction_pb2.ReactionRole.REAGENT,
    ROLE_SOLVENT: reaction_pb2.ReactionRole.SOLVENT,
    ROLE_CATALYST: reaction_pb2.ReactionRole.CATALYST,
    ROLE_PRODUCT: reaction_pb2.ReactionRole.PRODUCT,
}

_MASS_UNITS = {
    "kg": reaction_pb2.Mass.KILOGRAM,
    "g": reaction_pb2.Mass.GRAM,
    "mg": reaction_pb2.Mass.MILLIGRAM,
    "ug": reaction_pb2.Mass.MICROGRAM,
    "µg": reaction_pb2.Mass.MICROGRAM,
}
_VOLUME_UNITS = {
    "l": reaction_pb2.Volume.LITER,
    "ml": reaction_pb2.Volume.MILLILITER,
    "ul": reaction_pb2.Volume.MICROLITER,
    "µl": reaction_pb2.Volume.MICROLITER,
}
_AMOUNT_RE = re.compile(r"(\d+(?:\.\d+)?)\s*([a-zµ%]+)", re.IGNORECASE)


def build_dataset(
    intents: list[ReactionIntent],
    madmp: MaDmp | None = None,
    name: str | None = None,
) -> dataset_pb2.Dataset:
    """Assemble a ``Dataset`` (one ``Reaction`` per intent)."""
    dataset = dataset_pb2.Dataset()
    dataset.name = name or _dataset_name(madmp, intents)
    description = _dataset_description(madmp)
    if description:
        dataset.description = description
    for intent in intents:
        dataset.reactions.append(build_reaction(intent, madmp))
    return dataset


def build_reaction(
    intent: ReactionIntent, madmp: MaDmp | None = None
) -> reaction_pb2.Reaction:
    """Build one template ``Reaction`` from a single intent."""
    reaction = reaction_pb2.Reaction()

    identifier = reaction.identifiers.add()
    identifier.type = reaction_pb2.ReactionIdentifier.CUSTOM
    identifier.details = "instrument run id"
    identifier.value = intent.run_id

    for index, comp in enumerate(intent.inputs):
        key = _input_key(comp.name, index)
        reaction_input = reaction.inputs[key]
        reaction_input.addition_order = index + 1
        reaction_input.components.append(_build_compound(comp))

    _build_setup(reaction.setup, intent)
    reaction.notes.procedure_details = _procedure_details(intent)
    _build_provenance(reaction.provenance, intent, madmp)
    return reaction


# --- compounds -------------------------------------------------------------

def _build_compound(comp) -> reaction_pb2.Compound:
    compound = reaction_pb2.Compound()
    _add_identifier(compound, _CID.NAME, comp.name)
    _add_identifier(compound, _CID.INCHI, comp.inchi)
    _add_identifier(compound, _CID.INCHI_KEY, comp.inchikey)
    _add_identifier(compound, _CID.SMILES, comp.smiles)
    _add_identifier(compound, _CID.CAS_NUMBER, comp.cas)
    role = _ROLE_TO_ORD.get(comp.role)
    if role is not None:
        compound.reaction_role = role
    _set_amount(compound, comp)
    return compound


def _add_identifier(compound, id_type, value) -> None:
    if value:
        identifier = compound.identifiers.add()
        identifier.type = id_type
        identifier.value = value


def _set_amount(compound, comp) -> None:
    value, unit = comp.amount_value, comp.amount_unit
    if value is None and comp.amount_text:
        value, unit = _parse_amount(comp.amount_text)
    if value is None or not unit:
        return
    key = unit.lower()
    if key in _MASS_UNITS:
        compound.amount.mass.value = value
        compound.amount.mass.units = _MASS_UNITS[key]
    elif key in _VOLUME_UNITS:
        compound.amount.volume.value = value
        compound.amount.volume.units = _VOLUME_UNITS[key]


def _parse_amount(text: str) -> tuple[float | None, str | None]:
    match = _AMOUNT_RE.search(text)
    if not match:
        return None, None
    return float(match.group(1)), match.group(2)


def _input_key(name: str, index: int) -> str:
    """A unique, readable map key for a reaction input.

    The ``NN_`` index prefix guarantees uniqueness even if two component
    names sanitise to the same slug or are truncated.
    """
    base = re.sub(r"[^0-9a-zA-Z]+", "_", name).strip("_") or "input"
    return f"{index + 1:02d}_{base}"[:60]


# --- setup -----------------------------------------------------------------

def _build_setup(setup, intent: ReactionIntent) -> None:
    setup.is_automated = intent.provenance.is_automated
    setup.automation_platform = _platform_label(intent.instrument)
    vessel_kind = _dominant_vessel_kind(intent)
    if vessel_kind:
        setup.vessel.type = _vessel_type(vessel_kind)
        setup.vessel.details = vessel_kind
    position = _first_position(intent)
    if position:
        setup.vessel.position = position


def _dominant_vessel_kind(intent: ReactionIntent) -> str | None:
    for labware in intent.labware:
        if labware.kind:
            return labware.kind
    return None


def _vessel_type(kind: str):
    lowered = kind.lower()
    if "vial" in lowered:
        return reaction_pb2.Vessel.VIAL
    if "plate" in lowered or "rack" in lowered or "well" in lowered:
        return reaction_pb2.Vessel.WELL_PLATE
    return reaction_pb2.Vessel.CUSTOM


def _first_position(intent: ReactionIntent) -> str | None:
    for labware in intent.labware:
        if labware.position:
            return labware.position
    return None


def _platform_label(instrument: str) -> str:
    if instrument == "symyx-automation-studio":
        return "Symyx / Unchained Labs Automation Studio"
    return instrument


# --- notes (free-text dump of everything not structurally mapped) ----------

def _procedure_details(intent: ReactionIntent) -> str:
    lines = [
        f"Imported from {_platform_label(intent.instrument)} by inst2ord.",
        f"Run: {intent.run_id}",
    ]
    if intent.source_files:
        names = ", ".join(p.rsplit("/", 1)[-1] for p in intent.source_files)
        lines.append(f"Source files: {names}")
    if intent.labware:
        lines.append("")
        lines.append("Labware:")
        for lw in intent.labware:
            parts = [p for p in (lw.name, lw.kind, lw.position) if p]
            ident = f" [{lw.identifier}]" if lw.identifier else ""
            lines.append(f"  - {' | '.join(parts)}{ident}")
    selected = [o for o in intent.setup_options if o.value]
    if selected:
        lines.append("")
        lines.append("Run/setup options:")
        for option in selected:
            label = option.description or option.name
            lines.append(f"  - [{option.category}] {label}: {option.value}")
    return "\n".join(lines)


# --- provenance ------------------------------------------------------------

def _build_provenance(
    provenance, intent: ReactionIntent, madmp: MaDmp | None
) -> None:
    experimenter = _experimenter(intent, madmp)
    if experimenter is not None:
        provenance.experimenter.CopyFrom(experimenter)
    if madmp and madmp.dmp_id and (madmp.dmp_id_type or "").lower() == "doi":
        provenance.doi = madmp.dmp_id
    created = (madmp.created if madmp else None) or _now_iso()
    provenance.record_created.time.value = created
    if experimenter is not None:
        provenance.record_created.person.CopyFrom(experimenter)
    provenance.record_created.details = (
        f"Converted from {_platform_label(intent.instrument)} by inst2ord"
    )


def _experimenter(
    intent: ReactionIntent, madmp: MaDmp | None
) -> reaction_pb2.Person | None:
    source = _primary_person(madmp)
    if source is not None:
        person = reaction_pb2.Person()
        if source.name:
            person.name = source.name
        if source.email:
            person.email = source.email
        if source.orcid:
            person.orcid = source.orcid
        if person.name or person.email or person.orcid:
            return person
    if intent.provenance.operator_emails:
        person = reaction_pb2.Person()
        person.email = intent.provenance.operator_emails[0]
        return person
    return None


def _primary_person(madmp: MaDmp | None):
    """Pick the best available person: contact, else a contributor.

    maDMP coverage varies -- some have only a contact, some only
    contributors.  Among contributors a 'ContactPerson' is preferred.
    """
    if not madmp:
        return None
    if madmp.contact:
        return madmp.contact
    for contributor in madmp.contributors:
        if any("contact" in role.lower() for role in contributor.roles):
            return contributor
    return madmp.contributors[0] if madmp.contributors else None


# --- dataset metadata ------------------------------------------------------

def _dataset_name(madmp: MaDmp | None, intents: list[ReactionIntent]) -> str:
    if madmp and madmp.title:
        return madmp.title
    if intents:
        return f"{_platform_label(intents[0].instrument)} import"
    return "inst2ord dataset"


_DEFAULT_DESCRIPTION = (
    "ORD templates generated by inst2ord from instrument run data. "
    "Complete amounts, outcomes and any missing provenance in the editor."
)


def _dataset_description(madmp: MaDmp | None) -> str:
    """Build the dataset description, always non-empty (ORD requires it)."""
    lines: list[str] = []
    if madmp:
        if madmp.description:
            lines.append(madmp.description)
        for project in madmp.projects:
            if project.title:
                lines.append(f"Project: {project.title}")
            for fund in project.funding:
                grant = f" (grant {fund.grant_id})" if fund.grant_id else ""
                if fund.funder_name:
                    lines.append(f"Funding: {fund.funder_name}{grant}")
        names = ", ".join(c.name for c in madmp.contributors if c.name)
        if names:
            lines.append(f"Contributors: {names}")
        if madmp.dmp_id:
            lines.append(f"DMP: {madmp.dmp_id} ({madmp.dmp_id_type})")
    lines.append(_DEFAULT_DESCRIPTION)
    return "\n".join(lines)


def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()
