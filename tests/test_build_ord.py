"""Tests for the instrument-agnostic ORD builder."""

import pytest
from ord_schema.proto import reaction_pb2

from inst2ord.build_ord import build_dataset, build_reaction
from inst2ord.models import (
    InputComponent,
    Labware,
    MaDmp,
    Person,
    ProvenanceHints,
    ReactionIntent,
    ROLE_REACTANT,
    ROLE_SOLVENT,
)

_CID = reaction_pb2.CompoundIdentifier


def _intent(**kw):
    base = dict(run_id="Exp9", instrument="symyx-automation-studio")
    base.update(kw)
    return ReactionIntent(**base)


def test_reaction_identifier_carries_run_id():
    rxn = build_reaction(_intent())
    assert rxn.identifiers[0].type == reaction_pb2.ReactionIdentifier.CUSTOM
    assert rxn.identifiers[0].value == "Exp9"


def test_inputs_identifiers_roles_and_amounts():
    intent = _intent(
        inputs=[
            InputComponent(
                name="phenol", role=ROLE_REACTANT,
                inchi="InChI=1S/C6H6O/c7-6-4-2-1-3-5-6/h1-5,7H",
                inchikey="ISWSIDIOOBJBQZ-UHFFFAOYSA-N",
                smiles="Oc1ccccc1", amount_text="1.6 mg",
            ),
            InputComponent(
                name="water", role=ROLE_SOLVENT, amount_text="4 mL"
            ),
        ],
        labware=[Labware(kind="Rack 8x12 1mL Vial",
                         position="Deck 8-9 Heat-Stir 2")],
    )
    rxn = build_reaction(intent)
    assert len(rxn.inputs) == 2
    keys = sorted(rxn.inputs)

    phenol = rxn.inputs[keys[0]].components[0]
    types = {i.type for i in phenol.identifiers}
    assert {_CID.NAME, _CID.INCHI, _CID.INCHI_KEY, _CID.SMILES} <= types
    assert phenol.reaction_role == reaction_pb2.ReactionRole.REACTANT
    assert phenol.amount.mass.value == pytest.approx(1.6)
    assert phenol.amount.mass.units == reaction_pb2.Mass.MILLIGRAM

    water = rxn.inputs[keys[1]].components[0]
    assert water.amount.volume.value == pytest.approx(4.0)
    assert water.amount.volume.units == reaction_pb2.Volume.MILLILITER


def test_setup_vessel_inferred_from_labware():
    intent = _intent(labware=[Labware(kind="Rack 8x12 1mL Vial",
                                      position="Deck 1")])
    rxn = build_reaction(intent)
    assert rxn.setup.is_automated is True
    assert rxn.setup.vessel.type == reaction_pb2.Vessel.VIAL
    assert rxn.setup.vessel.position == "Deck 1"


def test_dataset_description_always_set_without_madmp():
    intent = _intent(inputs=[InputComponent(name="water", role=ROLE_SOLVENT)])
    dataset = build_dataset([intent], madmp=None)
    assert dataset.name
    assert dataset.description  # ORD requires a non-empty description


def test_experimenter_prefers_contact_and_sets_doi():
    madmp = MaDmp(
        dmp_id="10.0/abc", dmp_id_type="doi",
        contact=Person(name="John Smith", email="john@x.org"),
    )
    rxn = build_reaction(_intent(), madmp)
    assert rxn.provenance.experimenter.name == "John Smith"
    assert rxn.provenance.doi == "10.0/abc"


def test_maps_two_distinct_people_into_provenance():
    madmp = MaDmp(
        contact=Person(name="Contact", email="c@x.org"),
        contributors=[
            Person(name="Steward", email="s@x.org", roles=["DataManager"]),
        ],
    )
    rxn = build_reaction(_intent(), madmp)
    assert rxn.provenance.experimenter.name == "Contact"
    assert rxn.provenance.record_created.person.name == "Steward"


def test_experimenter_picked_by_datacite_role():
    # A Researcher/Producer/... contributor becomes the experimenter, even
    # when a contact is present; a record-creator role becomes the creator.
    madmp = MaDmp(
        contact=Person(name="Contact", email="c@x.org"),
        contributors=[
            Person(name="Rex", email="rex@x.org", roles=["Researcher"]),
            Person(name="Dana", email="dana@x.org", roles=["DataManager"]),
        ],
    )
    rxn = build_reaction(_intent(), madmp)
    assert rxn.provenance.experimenter.name == "Rex"
    assert rxn.provenance.record_created.person.name == "Dana"


def test_record_creator_prefers_datamanager():
    madmp = MaDmp(contributors=[
        Person(name="Cassie", email="c@x.org", roles=["ContactPerson"]),
        Person(name="Dana", email="d@x.org", roles=["DataManager"]),
    ])
    rxn = build_reaction(_intent(), madmp)
    assert rxn.provenance.record_created.person.name == "Dana"


def test_contributor_roster_kept_in_notes():
    bob = Person(name="Bob", roles=["DataCurator"], orcid="0000-1")
    madmp = MaDmp(contributors=[bob])
    notes = build_reaction(_intent(), madmp).notes.procedure_details
    assert "Contributors (from maDMP):" in notes
    assert "Bob (DataCurator; ORCID 0000-1)" in notes


def test_experimenter_falls_back_to_contributor_then_operator():
    madmp = MaDmp(contributors=[Person(name="Bob", email="bob@x.org",
                                       roles=["DataManager"])])
    rxn = build_reaction(_intent(), madmp)
    assert rxn.provenance.experimenter.name == "Bob"

    intent = _intent(
        provenance=ProvenanceHints(operator_emails=["op@lab.org"])
    )
    rxn = build_reaction(intent, madmp=None)
    assert rxn.provenance.experimenter.email == "op@lab.org"
