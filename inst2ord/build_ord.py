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
from inst2ord.rinchi import build_rinchi

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

# Optional identifiers the user can choose (NAME is always emitted). The
# first four are per-compound structure ids; "rinchi" is reaction-level.
IDENTIFIER_CHOICES = ("inchi", "inchikey", "smiles", "cas", "rinchi")
_DEFAULT_IDENTIFIERS = frozenset(IDENTIFIER_CHOICES)


def build_dataset(
    intents: list[ReactionIntent],
    madmp: MaDmp | None = None,
    name: str | None = None,
    identifiers: frozenset[str] | None = None,
) -> dataset_pb2.Dataset:
    """Assemble a ``Dataset`` (one ``Reaction`` per intent)."""
    dataset = dataset_pb2.Dataset()
    dataset.name = name or _dataset_name(madmp, intents)
    description = _dataset_description(madmp)
    if description:
        dataset.description = description
    for intent in intents:
        dataset.reactions.append(build_reaction(intent, madmp, identifiers))
    return dataset


def build_reaction(
    intent: ReactionIntent,
    madmp: MaDmp | None = None,
    identifiers: frozenset[str] | None = None,
) -> reaction_pb2.Reaction:
    """Build one template ``Reaction`` from a single intent.

    ``identifiers`` selects which optional identifiers to emit (see
    :data:`IDENTIFIER_CHOICES`); ``None`` means all. NAME is always emitted.
    """
    ids = _DEFAULT_IDENTIFIERS if identifiers is None else identifiers
    reaction = reaction_pb2.Reaction()

    identifier = reaction.identifiers.add()
    identifier.type = reaction_pb2.ReactionIdentifier.CUSTOM
    identifier.details = "instrument run id"
    identifier.value = intent.run_id

    for index, comp in enumerate(intent.inputs):
        key = _input_key(comp.name, index)
        reaction_input = reaction.inputs[key]
        reaction_input.addition_order = index + 1
        reaction_input.components.append(_build_compound(comp, ids))

    # Reaction-level RInChI from the resolved input InChIs (reactant-only for
    # a template; unresolved inputs count as no-structure). Coexists with the
    # per-compound SMILES/InChI identifiers.
    if "rinchi" in ids:
        rinchi = build_rinchi([comp.inchi for comp in intent.inputs])
        if rinchi:
            rinchi_id = reaction.identifiers.add()
            rinchi_id.type = reaction_pb2.ReactionIdentifier.RINCHI
            rinchi_id.value = rinchi

    _build_setup(reaction.setup, intent)
    _build_conditions(reaction.conditions, intent)
    reaction.notes.procedure_details = _procedure_details(intent, madmp)
    _build_provenance(reaction.provenance, intent, madmp)
    return reaction


# --- compounds -------------------------------------------------------------

def _build_compound(comp, ids: frozenset[str]) -> reaction_pb2.Compound:
    compound = reaction_pb2.Compound()
    _add_identifier(compound, _CID.NAME, comp.name)  # always
    if "inchi" in ids:
        _add_identifier(compound, _CID.INCHI, comp.inchi)
    if "inchikey" in ids:
        _add_identifier(compound, _CID.INCHI_KEY, comp.inchikey)
    if "smiles" in ids:
        _add_identifier(compound, _CID.SMILES, comp.smiles)
    if "cas" in ids:
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


# --- conditions (qualitative, inferred from deck names; low confidence) ----

_LOW_CONFIDENCE = (
    "Inferred by inst2ord from the instrument's deck-station names; "
    "qualitative and low-confidence -- no setpoints or rates were recorded "
    "in the source. Verify/complete in the editor."
)
_TEMP_CONTROL = reaction_pb2.TemperatureConditions.TemperatureControl
_STIRRING = reaction_pb2.StirringConditions


def _build_conditions(conditions, intent: ReactionIntent) -> None:
    """Populate qualitative temperature/stirring from deck-station names.

    The platform encodes hardware in deck labels like ``Heat-Stir`` /
    ``Heat-Cool-Stir`` / ``Vortex``. Only what the label implies is asserted
    (heating present, stirring vs vortexing); no setpoint or rpm is invented.
    """
    decks = " ".join(_deck_descriptors(intent)).lower()
    has_heat = "heat" in decks
    has_cool = "cool" in decks
    has_stir = "stir" in decks
    has_vortex = "vortex" in decks
    if not (has_heat or has_cool or has_stir or has_vortex):
        return

    if has_heat or has_cool:
        # No specific ORD enum for a heated stir block; use CUSTOM + details.
        conditions.temperature.control.type = _TEMP_CONTROL.CUSTOM
        kind = "heat/cool" if has_cool else "heated"
        conditions.temperature.control.details = (
            f"{kind} stir station (setpoint not recorded)"
        )
    if has_stir:
        conditions.stirring.type = _STIRRING.STIR_BAR
        conditions.stirring.details = "magnetic stir station"
    elif has_vortex:
        conditions.stirring.type = _STIRRING.AGITATION
        conditions.stirring.details = "vortex mixing"
    conditions.details = _LOW_CONFIDENCE


def _deck_descriptors(intent: ReactionIntent) -> list[str]:
    """Deck/station strings from labware and chemical substrate positions."""
    descriptors = [lw.position for lw in intent.labware if lw.position]
    descriptors += [
        comp.extra["SubstratePosition"]
        for comp in intent.inputs
        if comp.extra.get("SubstratePosition")
    ]
    return descriptors


# --- notes (free-text dump of everything not structurally mapped) ----------

def _procedure_details(intent: ReactionIntent, madmp: MaDmp | None) -> str:
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
    if madmp:
        # Name the experimenter (the person mapped into provenance) with
        # their affiliation and ROR -- the ROR has no ORD provenance slot,
        # so the notes are the only place a template can keep it.
        experimenter_src, _ = _provenance_sources(madmp)
        note = _experimenter_note(experimenter_src)
        if note:
            lines.append("")
            lines.append(f"Experimenter (from maDMP): {note}")
    if madmp and madmp.contributors:
        # ORD provenance has no contributor list, so keep the full roster
        # here -- this is the only place templates can retain it.
        lines.append("")
        lines.append("Contributors (from maDMP):")
        for label in _contributor_labels(madmp):
            lines.append(f"  - {label}")
    return "\n".join(lines)


# --- provenance ------------------------------------------------------------

def _build_provenance(
    provenance, intent: ReactionIntent, madmp: MaDmp | None
) -> None:
    experimenter_src, creator_src = _provenance_sources(madmp)
    experimenter = _to_ord_person(experimenter_src) or _operator_person(intent)
    if experimenter is not None:
        provenance.experimenter.CopyFrom(experimenter)
    primary = _primary_affiliation(experimenter_src)
    if primary is not None and primary.city:
        provenance.city = primary.city
    if madmp and madmp.dmp_id and (madmp.dmp_id_type or "").lower() == "doi":
        provenance.doi = madmp.dmp_id
    created = (madmp.created if madmp else None) or _now_iso()
    provenance.record_created.time.value = created
    creator = _to_ord_person(creator_src) or experimenter
    if creator is not None:
        provenance.record_created.person.CopyFrom(creator)
    provenance.record_created.details = (
        f"Converted from {_platform_label(intent.instrument)} by inst2ord"
    )


# DataCite contributor roles -> ORD provenance slot.
# A person who handled the science becomes the experimenter:
_EXPERIMENTER_ROLES = {
    "datacollector", "projectmember", "producer", "researcher",
}
# A person who manages/owns the record becomes record_created.person;
# ordered by preference (DataManager wins when several roles match):
_RECORD_CREATOR_ROLES = (
    "datamanager", "contactperson", "projectmanager",
    "projectleader", "workpackageleader", "datacurator",
    "datasteward",
)


def _provenance_sources(madmp: MaDmp | None):
    """Pick (experimenter, record_creator) maDMP people; may be the same.

    ORD provenance has only one ``experimenter`` and the ``record_created``
    person, so at most two distinct maDMP people are mapped, by DataCite
    contributor role:

    * experimenter: a DataCollector/ProjectMember/Producer/Researcher,
      else the DMP contact, else the first contributor.
    * record creator: a DataManager (preferred) / ContactPerson /
      ProjectManager / ProjectLeader / WorkPackageLeader, else the contact,
      else the experimenter.

    The full roster is also kept in the notes / dataset description.
    """
    if not madmp:
        return None, None
    contributors = list(madmp.contributors)
    experimenter = (
        _first_with_roles(contributors, _EXPERIMENTER_ROLES)
        or madmp.contact
        or (contributors[0] if contributors else None)
    )
    creator = _record_creator(contributors) or madmp.contact or experimenter
    return experimenter, creator


def _first_with_roles(contributors, roles: set[str]):
    for contributor in contributors:
        if {role.lower() for role in contributor.roles} & roles:
            return contributor
    return None


def _record_creator(contributors):
    """First contributor matching a record-creator role, DataManager first."""
    for wanted in _RECORD_CREATOR_ROLES:
        match = _first_with_roles(contributors, {wanted})
        if match is not None:
            return match
    return None


def _to_ord_person(source) -> reaction_pb2.Person | None:
    """Convert a maDMP :class:`Person` to an ORD Person, or None if empty."""
    if source is None:
        return None
    person = reaction_pb2.Person()
    if source.name:
        person.name = source.name
    if source.email:
        person.email = source.email
    if source.orcid:
        person.orcid = source.orcid
    primary = _primary_affiliation(source)
    if primary is not None:
        person.organization = primary.name
    if person.name or person.email or person.orcid or person.organization:
        return person
    return None


def _primary_affiliation(source):
    """The affiliation that speaks for a maDMP person in ORD provenance.

    ORD provenance carries a single ``organization`` and ``city``, so one
    affiliation must represent the person.  We take the first with a name
    (the schema requires a name on every affiliation) and source *both*
    fields from it, so ``provenance.city`` always belongs to the same
    organisation recorded as ``experimenter.organization`` -- picking the
    name and city from different affiliations would mismatch them.
    """
    if source is None:
        return None
    for affiliation in source.affiliations:
        if isinstance(affiliation.name, str) and affiliation.name:
            return affiliation
    return None


def _operator_person(intent: ReactionIntent) -> reaction_pb2.Person | None:
    if intent.provenance.operator_emails:
        person = reaction_pb2.Person()
        person.email = intent.provenance.operator_emails[0]
        return person
    return None


def _contributor_labels(madmp: MaDmp) -> list[str]:
    """Readable labels for each named contributor.

    Of the form ``Name (Role; ORCID ...; Affiliation, City (ROR ...))`` --
    role, ORCID and each affiliation (name, resolved city and ROR) are
    appended only when present, so contributors without an affiliation keep
    their original ``Name (Role; ORCID ...)`` form.
    """
    labels = []
    for contributor in madmp.contributors:
        if not contributor.name:
            continue
        bits = []
        if contributor.roles:
            bits.append("/".join(contributor.roles))
        if contributor.orcid:
            bits.append(f"ORCID {contributor.orcid}")
        for affiliation in contributor.affiliations:
            label = _affiliation_label(affiliation)
            if label:
                bits.append(label)
        suffix = f" ({'; '.join(bits)})" if bits else ""
        labels.append(f"{contributor.name}{suffix}")
    return labels


def _experimenter_note(source) -> str:
    """One-line 'Name; Affiliation, City (ROR ...)' for the experimenter."""
    if source is None:
        return ""
    bits = [source.name] if isinstance(source.name, str) and source.name else []
    for affiliation in source.affiliations:
        label = _affiliation_label(affiliation)
        if label:
            bits.append(label)
    return "; ".join(bits)


def _affiliation_label(affiliation) -> str:
    """'Name, City (ROR https://ror.org/..)' from the parts that are set.

    Only string parts are joined, so a malformed (non-string) affiliation
    name from the maDMP is dropped rather than crashing the join.
    """
    parts = [part for part in (affiliation.name, affiliation.city)
             if isinstance(part, str) and part]
    text = ", ".join(parts)
    if affiliation.ror:
        ror = f"ROR {affiliation.ror}"
        text = f"{text} ({ror})" if text else ror
    return text


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
        labels = _contributor_labels(madmp)
        if labels:
            lines.append(f"Contributors: {', '.join(labels)}")
        if madmp.dmp_id:
            lines.append(f"DMP: {madmp.dmp_id} ({madmp.dmp_id_type})")
    lines.append(_DEFAULT_DESCRIPTION)
    return "\n".join(lines)


def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()
