"""Command-line entry point: instrument files -> ORD files.

By default it writes one **template** JSON per run for the ORD web app
(``app.open-reaction-database.org``); ``--format pb``/``pbtxt`` instead write
a protobuf ``Dataset`` (binary/text).

Example
-------
    python -m inst2ord.cli examples/xmls \\
        --madmp examples/madmp/ex9-dmp-long.json --out out

Run ``python -m inst2ord.cli --help`` for all options.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import os
import sys

from inst2ord import export
from inst2ord.adapters import available_adapters, detect_adapter, get_adapter
from inst2ord.build_ord import build_dataset, build_reaction
from inst2ord.madmp import parse_madmp
from inst2ord.resolve import CompoundResolver
from inst2ord.validate import validate_dataset, validate_reaction

# Output format -> filename extension. "template" is the ord-app JSON
# template (one Reaction); the rest are protobuf Datasets.
_EXTENSIONS = {
    "template": "json",
    "pb": "pb.gz",
    "pbtxt": "pbtxt",
}
_DATASET_FORMATS = ("pb", "pbtxt")


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    if not os.path.isdir(args.input_dir):
        print(f"Not a directory: {args.input_dir!r}", file=sys.stderr)
        return 2

    try:
        adapter = (
            get_adapter(args.instrument)
            if args.instrument
            else detect_adapter(args.input_dir)
        )
    except KeyError as exc:
        print(exc.args[0] if exc.args else str(exc), file=sys.stderr)
        return 2
    if adapter is None:
        known = ", ".join(a.name for a in available_adapters())
        print(
            f"No instrument adapter matched files in {args.input_dir!r}. "
            f"Use --instrument (known: {known}).",
            file=sys.stderr,
        )
        return 2
    print(f"Instrument adapter: {adapter.name}")

    intents = adapter.parse_dir(args.input_dir)
    if not intents:
        print(f"No runs found in {args.input_dir!r}.", file=sys.stderr)
        return 1
    run_ids = ", ".join(i.run_id for i in intents)
    print(f"Found {len(intents)} run(s): {run_ids}")

    if args.dry_run:
        json.dump(
            [dataclasses.asdict(i) for i in intents], sys.stdout, indent=2
        )
        sys.stdout.write("\n")
        return 0

    madmp = parse_madmp(args.madmp) if args.madmp else None
    if madmp:
        print(f"maDMP: {madmp.title!r} ({madmp.source_path})")

    resolver = CompoundResolver(
        curation_path=args.curation,
        cache_dir=args.cache,
        use_pubchem=args.resolve,
    )

    os.makedirs(args.out, exist_ok=True)
    overall_ok = True
    for intent in intents:
        resolver.resolve_all(intent.inputs)
        overall_ok &= _print_report(_emit(intent, madmp, args))

    if args.combined and args.format in _DATASET_FORMATS and intents:
        combined = build_dataset(intents, madmp)
        path = os.path.join(args.out, f"combined.{_EXTENSIONS[args.format]}")
        export.write_message(combined, path)
        _print_report(validate_dataset(combined, label="combined"))
    elif args.combined:
        print("\nNote: --combined applies to protobuf formats only; ignored.")

    unresolved_path = os.path.join(args.out, "unresolved.csv")
    resolver.write_unresolved(unresolved_path)
    if resolver.unresolved:
        print(
            f"\n{len(resolver.unresolved)} name(s) need curation -> "
            f"{unresolved_path}"
        )

    print(f"\nWrote {args.format} output to {args.out}/")
    return 0 if overall_ok else 1


def _emit(intent, madmp, args):
    """Build and write one run in the requested format; return its report."""
    filename = f"{intent.run_id}.{_EXTENSIONS[args.format]}"
    path = os.path.join(args.out, filename)
    if args.format == "template":
        reaction = build_reaction(intent, madmp)
        export.write_template(reaction, intent.run_id, path)
        return validate_reaction(reaction, intent.run_id)
    dataset = build_dataset([intent], madmp)
    export.write_message(dataset, path)
    return validate_dataset(dataset, label=intent.run_id)


def _print_report(report) -> bool:
    status = "OK" if report.ok else "PROBLEMS"
    print(f"\n[{report.label}] {status}")
    for error in report.unexpected_errors:
        print(f"  ERROR: {error}")
    if report.expected_errors:
        print(
            f"  (expected template gaps: {len(report.expected_errors)} "
            "- amounts/outcomes/provenance to complete in the editor)"
        )
    for warning in report.warnings[:5]:
        print(f"  warning: {warning}")
    return report.ok


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="inst2ord",
        description="Map instrument XML (+ optional maDMP) to ORD templates.",
    )
    parser.add_argument(
        "input_dir", help="directory containing the instrument's files"
    )
    parser.add_argument(
        "--instrument",
        help="instrument adapter name (default: auto-detect)",
    )
    parser.add_argument("--madmp", help="path to a maDMP JSON file")
    parser.add_argument(
        "--out", default="out", help="output directory (default: out)"
    )
    parser.add_argument(
        "--format",
        choices=["template", "pb", "pbtxt"],
        default="template",
        help="output format: 'template' = ORD web-app JSON template "
        "(default); 'pb'/'pbtxt' = protobuf Dataset (binary/text)",
    )
    parser.add_argument(
        "--resolve",
        action="store_true",
        help="resolve names via PubChem (requires network)",
    )
    parser.add_argument(
        "--curation",
        default="curation.csv",
        help="curation CSV (raw_name -> structure/ids); default: curation.csv",
    )
    parser.add_argument(
        "--cache",
        default="cache/pubchem",
        help="PubChem response cache directory",
    )
    parser.add_argument(
        "--combined",
        action="store_true",
        help="also write one combined Dataset of all runs (pb/pbtxt only)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="parse only; print neutral intents as JSON (no ORD, no network)",
    )
    return parser.parse_args(argv)


if __name__ == "__main__":
    raise SystemExit(main())
