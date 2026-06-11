"""Tests for the validation wrapper / expected-gap classification."""

from inst2ord import validate
from inst2ord.build_ord import build_dataset
from inst2ord.models import (
    InputComponent,
    Labware,
    MaDmp,
    Person,
    ReactionIntent,
    ROLE_REACTANT,
)


class _FakeOutput:
    def __init__(self, errors, warnings):
        self.errors = errors
        self.warnings = warnings


def test_classification_separates_expected_from_unexpected():
    output = _FakeOutput(
        errors=[
            "X: All reaction input components require an amount",
            "Y: Reactions should have at least 1 reaction outcome",
            "Z: ...provenance.record_created: Person must have `email`",
            "W: a genuinely unexpected problem",
        ],
        warnings=["a warning"],
    )
    report = validate._to_report("r", output)
    assert report.unexpected_errors == ["W: a genuinely unexpected problem"]
    assert len(report.expected_errors) == 3
    assert report.warnings == ["a warning"]
    assert report.ok is False


def test_template_has_only_expected_gaps():
    madmp = MaDmp(contact=Person(name="J", email="j@x.org"))
    intent = ReactionIntent(
        run_id="Exp9", instrument="symyx-automation-studio",
        inputs=[InputComponent(name="water", role=ROLE_REACTANT)],
        labware=[Labware(kind="Rack 8x12 1mL Vial")],
    )
    report = validate.validate_dataset(build_dataset([intent], madmp), "Exp9")
    assert report.ok  # nothing beyond expected template gaps
    assert report.expected_errors  # amounts/outcomes are flagged
