"""Command-line entry point: instrument files -> ORD web-app files.

By default each run becomes a JSON **template** for the ORD web app
(``app.open-reaction-database.org``), imported via **Templates ▸ Import from
JSON**. ``--format dataset|binpb|txtpb`` instead writes a ``Dataset`` for
**Create Dataset from File**.

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
from inst2ord.build_ord import (
    IDENTIFIER_CHOICES,
    build_dataset,
    build_reaction,
)
from inst2ord.madmp import parse_madmp, validate_madmp
from inst2ord.resolve import CompoundResolver
from inst2ord.ror import RorClient, enrich_affiliations
from inst2ord.validate import validate_dataset, validate_reaction


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

    madmp = None
    if args.madmp:
        if _check_madmp_schema(args.madmp, args.strict_madmp) is False:
            return 2
        madmp = parse_madmp(args.madmp)
        print(f"maDMP: {madmp.title!r} ({madmp.source_path})")
        if args.resolve:
            # Look up affiliation cities (provenance.city) from the ROR API;
            # affiliation names + RORs are mapped regardless of network.
            enrich_affiliations(madmp, RorClient(cache_dir=args.ror_cache))

    resolver = CompoundResolver(
        curation_path=args.curation,
        cache_dir=args.cache,
        use_pubchem=args.resolve,
    )

    ext = export.FORMAT_EXTENSIONS[args.format]
    ids = frozenset(args.identifiers)
    os.makedirs(args.out, exist_ok=True)
    overall_ok = True
    for intent in intents:
        resolver.resolve_all(intent.inputs)
        path = os.path.join(args.out, f"{intent.run_id}.{ext}")
        report = _emit(intent, madmp, args.format, path, ids)
        overall_ok &= _print_report(report)

    if args.combined and args.format in export.DATASET_FORMATS and intents:
        combined = build_dataset(intents, madmp, identifiers=ids)
        export.write_dataset(
            combined, os.path.join(args.out, f"combined.{ext}")
        )
        _print_report(validate_dataset(combined, "combined"))
    elif args.combined:
        print("\nNote: --combined applies to dataset formats; ignored.")

    unresolved_path = os.path.join(args.out, "unresolved.csv")
    resolver.write_unresolved(unresolved_path)
    if resolver.unresolved:
        print(
            f"\n{len(resolver.unresolved)} name(s) need curation -> "
            f"{unresolved_path}"
        )

    print(f"\nWrote {args.format} output to {args.out}/")
    return 0 if overall_ok else 1


def _check_madmp_schema(path: str, strict: bool) -> bool:
    """Validate the maDMP against the RDA schema.

    Returns False only when validation fails and ``strict`` is set (the
    caller should then abort). Schema issues are warnings by default; if
    jsonschema is unavailable the check is skipped.
    """
    try:
        issues = validate_madmp(path)
    except ModuleNotFoundError:
        print(
            "maDMP schema check skipped (pip install jsonschema).",
            file=sys.stderr,
        )
        return True
    if not issues:
        return True
    print(f"maDMP schema: {len(issues)} issue(s):", file=sys.stderr)
    for message in issues[:10]:
        print(f"  - {message}", file=sys.stderr)
    if len(issues) > 10:
        print(f"  ... and {len(issues) - 10} more", file=sys.stderr)
    if strict:
        print("Aborting due to --strict-madmp.", file=sys.stderr)
        return False
    print(
        "Continuing despite schema issues (use --strict-madmp to abort).",
        file=sys.stderr,
    )
    return True


def _emit(intent, madmp, fmt: str, path: str, ids):
    """Build and write one run in ``fmt``; return its validation report."""
    if fmt == "template":
        reaction = build_reaction(intent, madmp, ids)
        export.write_template(reaction, path)
        return validate_reaction(reaction, intent.run_id)
    dataset = build_dataset([intent], madmp, identifiers=ids)
    export.write_dataset(dataset, path)
    return validate_dataset(dataset, intent.run_id)


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
        "--strict-madmp",
        action="store_true",
        help="abort if the maDMP fails RDA 1.2 schema validation "
        "(default: warn and continue)",
    )
    parser.add_argument(
        "--out", default="out", help="output directory (default: out)"
    )
    parser.add_argument(
        "--format",
        choices=["template", "dataset", "binpb", "txtpb"],
        default="template",
        help="'template' (default) = JSON for Templates > Import from JSON "
        "(one Reaction); 'dataset'/'binpb'/'txtpb' = a Dataset for Create "
        "Dataset from File (JSON/binary/text)",
    )
    parser.add_argument(
        "--identifiers",
        nargs="+",
        choices=list(IDENTIFIER_CHOICES),
        default=list(IDENTIFIER_CHOICES),
        metavar="ID",
        help="which optional identifiers to emit (NAME is always included); "
        f"choose from {', '.join(IDENTIFIER_CHOICES)} (default: all). "
        "inchi/inchikey/smiles/cas are per-compound; rinchi is reaction-level "
        "and needs resolved InChIs (--resolve or curation.csv)",
    )
    parser.add_argument(
        "--resolve",
        action="store_true",
        help="resolve compound names via PubChem and maDMP affiliation "
        "cities via the ROR API (requires network)",
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
        "--ror-cache",
        default="cache/ror",
        help="ROR API response cache directory",
    )
    parser.add_argument(
        "--combined",
        action="store_true",
        help="also write one combined Dataset containing all runs",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="parse only; print neutral intents as JSON (no ORD, no network)",
    )
    return parser.parse_args(argv)


if __name__ == "__main__":
    raise SystemExit(main())
