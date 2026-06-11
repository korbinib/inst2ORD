"""Neutral, instrument-agnostic intermediate model + maDMP model.

Instrument adapters (see :mod:`inst2ord.adapters`) parse their own native
files and emit a :class:`ReactionIntent`.  The ORD builder
(:mod:`inst2ord.build_ord`) consumes only :class:`ReactionIntent` and
:class:`MaDmp`, so it never needs to know which instrument produced the
data.  Adding a new instrument therefore means writing a new adapter, with
no change to the builder, validator, resolver or CLI.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Neutral reaction roles (kept close to ORD's ReactionRole vocabulary so the
# builder can translate them directly).
ROLE_REACTANT = "reactant"
ROLE_REAGENT = "reagent"
ROLE_SOLVENT = "solvent"
ROLE_CATALYST = "catalyst"
ROLE_PRODUCT = "product"
ROLE_UNSPECIFIED = "unspecified"


# --- Neutral intermediate --------------------------------------------------

@dataclass
class InputComponent:
    """A substance the instrument loaded as a reaction input.

    Resolution (name -> InChI/InChIKey/...) is filled in later by the
    compound resolver; adapters only populate what the instrument states.
    ``amount_text`` keeps any raw amount fragment (e.g. ``"1.6 mg"``) found
    embedded in the name, which the builder may promote to ``amount_*``.
    """

    name: str
    role: str = ROLE_UNSPECIFIED
    amount_value: float | None = None
    amount_unit: str | None = None
    amount_text: str | None = None
    position: str | None = None
    labware_ref: str | None = None
    # Filled by the resolver when --resolve is used:
    inchi: str | None = None
    inchikey: str | None = None
    smiles: str | None = None
    cas: str | None = None
    resolved_name: str | None = None
    # Instrument-specific fields preserved for the notes dump:
    extra: dict[str, str] = field(default_factory=dict)


@dataclass
class Labware:
    """A plate/rack/vessel the run uses (not a chemical)."""

    kind: str | None = None
    name: str | None = None
    identifier: str | None = None
    rows: int | None = None
    cols: int | None = None
    position: str | None = None


@dataclass
class SetupOption:
    """A neutral key/value run-or-setup option (e.g. a PromptFile entry)."""

    category: str
    name: str
    description: str | None = None
    value: str | None = None
    options: list[str] = field(default_factory=list)


@dataclass
class ProvenanceHints:
    """Provenance the instrument can supply by itself."""

    run_id: str | None = None
    instrument: str | None = None
    operator_emails: list[str] = field(default_factory=list)
    is_automated: bool = True


@dataclass
class ReactionIntent:
    """What one instrument run contributes to a single ORD reaction."""

    run_id: str
    instrument: str
    inputs: list[InputComponent] = field(default_factory=list)
    labware: list[Labware] = field(default_factory=list)
    setup_options: list[SetupOption] = field(default_factory=list)
    provenance: ProvenanceHints = field(default_factory=ProvenanceHints)
    source_files: list[str] = field(default_factory=list)


# --- maDMP (RDA-DMP-Common 1.2) -------------------------------------------

@dataclass
class Person:
    name: str | None = None
    email: str | None = None
    orcid: str | None = None
    identifier: str | None = None
    identifier_type: str | None = None
    roles: list[str] = field(default_factory=list)


@dataclass
class Funding:
    funder_name: str | None = None
    funder_id: str | None = None
    grant_id: str | None = None


@dataclass
class MaDmpProject:
    title: str | None = None
    description: str | None = None
    start: str | None = None
    end: str | None = None
    funding: list[Funding] = field(default_factory=list)


@dataclass
class MaDmp:
    """The subset of a maDMP we map into ORD (Dataset + provenance)."""

    title: str | None = None
    description: str | None = None
    language: str | None = None
    created: str | None = None
    modified: str | None = None
    dmp_id: str | None = None
    dmp_id_type: str | None = None
    contact: Person | None = None
    contributors: list[Person] = field(default_factory=list)
    projects: list[MaDmpProject] = field(default_factory=list)
    source_path: str | None = None
