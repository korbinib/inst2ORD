"""Validate built messages by reusing ``ord_schema.validations``.

We do not re-implement any schema checks.  Because inst2ord produces
*templates* (no amounts or outcomes yet), the ORD validator legitimately
reports some errors; :func:`validate_reaction` separates those *expected
template gaps* from genuinely unexpected problems so the CLI can report
them differently.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ord_schema import validations
from ord_schema.proto import dataset_pb2, reaction_pb2

# Validator messages that are expected for a not-yet-completed template:
# amounts and outcomes are always filled in later, some setup-only runs
# legitimately load no reagents (so have no inputs), and when a maDMP's
# coverage is thin the record-creator provenance can't be fully populated --
# all of these are completed in the editor.  Matching "record_created" is
# scoped: the validator prefixes those errors with the field path.
_EXPECTED_SUBSTRINGS = (
    "at least 1 reaction outcome",
    "at least 1 reaction input",
    "require an amount",
    "requires an amount",
    "record_created",
)


def _is_expected(message: str) -> bool:
    return any(sub in message for sub in _EXPECTED_SUBSTRINGS)


@dataclass
class ValidationReport:
    label: str
    expected_errors: list[str] = field(default_factory=list)
    unexpected_errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """True when nothing beyond expected template gaps was reported."""
        return not self.unexpected_errors


def validate_reaction(
    reaction: reaction_pb2.Reaction, label: str
) -> ValidationReport:
    output = validations.validate_message(reaction, raise_on_error=False)
    return _to_report(label, output)


def validate_dataset(
    dataset: dataset_pb2.Dataset, label: str = "dataset"
) -> ValidationReport:
    output = validations.validate_message(dataset, raise_on_error=False)
    return _to_report(label, output)


def _to_report(label: str, output) -> ValidationReport:
    report = ValidationReport(label=label, warnings=list(output.warnings))
    for error in output.errors:
        if _is_expected(error):
            report.expected_errors.append(error)
        else:
            report.unexpected_errors.append(error)
    return report
