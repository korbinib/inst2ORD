# inst2ord

Map the XML files produced by a high-throughput chemistry platform (and,
optionally, a machine-actionable Data Management Plan / maDMP) onto the
[Open Reaction Database](https://docs.open-reaction-database.org/) (ORD)
schema, and emit files that can be imported as **templates** into the ORD
reaction editor.

## What it does

```text
instrument XML ─▶ adapter ─▶ ReactionIntent ─▶ CompoundResolver* ─┐
                                                                  ├─▶ build_ord ─▶ validate ─▶ files
maDMP JSON ─────▶ parse_madmp ─▶ MaDmp ───────────────────────────┘      (reuses ord_schema)

* CompoundResolver enriches ReactionIntent.inputs only — the chemical names
  the adapter extracted (name → InChI/InChIKey via curation.csv, cached
  PubChem, RDKit). It does NOT read the maDMP. The maDMP is an independent
  metadata stream that build_ord uses for Dataset fields + provenance.
```

The platform XML describes *what is loaded and how the machine is set up*,
not a finished reaction (no structures, usually no amounts, no products or
outcomes). inst2ord therefore produces **template-grade** ORD reactions:
inputs, setup and provenance are populated; amounts and outcomes are left
blank to be completed in the editor.

## Layout

| Path | Role |
| --- | --- |
| `inst2ord/models.py` | Neutral, instrument-agnostic intermediate (`ReactionIntent`) + maDMP model |
| `inst2ord/adapters/` | One adapter per instrument; `base.py` is the contract, `__init__.py` the registry |
| `inst2ord/adapters/symyx_automation_studio.py` | First instrument: Symyx / Unchained Labs Automation Studio |
| `inst2ord/madmp.py` | maDMP (RDA-DMP-Common 1.2) JSON → `MaDmp` |
| `inst2ord/resolve.py` | Name → InChI/InChIKey via curation table + cached PubChem (+ RDKit) |
| `inst2ord/build_ord.py` | `ReactionIntent` (+ `MaDmp`) → ORD `Dataset` (the only module touching ORD protobufs) |
| `inst2ord/validate.py` | Wrapper over `ord_schema.validations` |
| `inst2ord/cli.py` | Command-line entry point |

### Adding another instrument

Write a new `InstrumentAdapter` subclass that parses its native files into
`ReactionIntent`s and register it in `inst2ord/adapters/__init__.py`.
Nothing downstream (builder, validation, resolver, maDMP merge, CLI)
changes — the instrument mapping is fully exchangeable.

Today the adapter is chosen by `--instrument` or by sniffing the input
directory (`detect_adapter`). **Planned:** when a maDMP is supplied, its
`dataset[].technical_resource` entries could pick the adapter automatically
by matching the resource name/description against each adapter.

## Setup

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
```

## Tests

```bash
pip install -r requirements-dev.txt
pytest
```

The suite is offline — PubChem is monkeypatched, so no network is needed.

## Usage

```bash
# Offline: NAME identifiers only (no network)
python -m inst2ord.cli examples/xmls \
    --madmp examples/madmp/ex9-dmp-long.json --out out

# Enrich compounds via PubChem (InChI/InChIKey, SMILES via RDKit)
python -m inst2ord.cli examples/xmls --madmp examples/madmp/ex9-dmp-long.json \
    --out out --resolve

# Inspect parsing only (neutral intermediate as JSON; no ORD, no network)
python -m inst2ord.cli examples/xmls --dry-run
```

Outputs per run `Exp###`: `out/Exp###.pbtxt` (human-readable / review) and
`out/Exp###.pb.gz` (binary `Dataset` for the editor). `--combined` also
writes a single dataset of all runs.

## Compound resolution & curation

For each chemical name the resolver tries, in order:

1. **`curation.csv`** — a hand-maintained `raw_name → {inchi, inchikey,
   smiles, cas, ...}` table (authoritative; also the place for future CAS or
   ELN identifiers).
2. **PubChem** (only with `--resolve`) — queried by a normalised name and
   cached on disk; canonical SMILES is derived from the InChI via RDKit.
3. Otherwise the name is written to `out/unresolved.csv` (a curation-table
   stub) for manual completion. The raw name is always kept as an ORD
   `NAME` identifier regardless.

## Validation

Validation reuses `ord_schema.validations` directly. Because templates are
incomplete by design, the validator reports some *expected gaps* (no
amounts, no outcomes, and — for setup-only runs — no inputs); these are
counted separately from genuinely unexpected problems.
