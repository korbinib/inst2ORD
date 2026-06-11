# inst2ord

Map the XML files produced by a high-throughput chemistry platform (and,
optionally, a machine-actionable Data Management Plan / maDMP) onto the
[Open Reaction Database](https://docs.open-reaction-database.org/) (ORD)
schema, and emit files that can be imported as **templates** into the ORD
reaction editor.

## What it does

```text
instrument XML ─▶ adapter ─▶ ReactionIntent ─▶ CompoundResolver* ─┐
                                                                  ├─▶ build_ord ─▶ validate ─▶ export
maDMP JSON ─────▶ parse_madmp ─▶ MaDmp ───────────────────────────┘      (reuses ord_schema)

* CompoundResolver enriches ReactionIntent.inputs only — the chemical names
  the adapter extracted (name → InChI/InChIKey via curation.csv, cached
  PubChem, RDKit). It does NOT read the maDMP. The maDMP is an independent
  metadata stream that build_ord uses for Dataset fields + provenance.

export writes a per-run JSON template by default (Templates > Import from
JSON), or a Dataset (--format dataset/binpb/txtpb) for Create Dataset from
File.
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
| `inst2ord/madmp.py` | maDMP (RDA-DMP-Common 1.2) JSON → `MaDmp`, + schema validation against the bundled `schemas/maDMP-schema-1.2.json` |
| `inst2ord/resolve.py` | Name → InChI/InChIKey via curation table + cached PubChem (+ RDKit) |
| `inst2ord/build_ord.py` | `ReactionIntent` (+ `MaDmp`) → ORD `Reaction`/`Dataset` (the only module touching ORD protobufs) |
| `inst2ord/validate.py` | Wrapper over `ord_schema.validations` |
| `inst2ord/export.py` | Serialise to a web-app JSON template or a protobuf `Dataset` |
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
# Default: one JSON template per run for the ORD web app (no network)
python -m inst2ord.cli examples/xmls \
    --madmp examples/madmp/ex9-dmp-long.json --out out

# Enrich compounds via PubChem (InChI/InChIKey, SMILES via RDKit)
python -m inst2ord.cli examples/xmls --madmp examples/madmp/ex9-dmp-long.json \
    --out out --resolve

# Import as a Dataset instead (Create Dataset from File)
python -m inst2ord.cli examples/xmls --out out --format dataset  # or binpb/txtpb
python -m inst2ord.cli examples/xmls --out out --format binpb --combined

# Inspect parsing only (neutral intermediate as JSON; no ORD, no network)
python -m inst2ord.cli examples/xmls --dry-run
```

## Template vs Dataset export

The web app has **two** import paths that take **different, non-interchangeable**
formats. inst2ord can target either (`--format`):

| | **Template** (`--format template`, default) | **Dataset** (`--format dataset` / `binpb` / `txtpb`) |
| --- | --- | --- |
| ORD message | a single `Reaction` | a `Dataset` (one reaction per run) |
| File | `{"binpb": <base64 Reaction>, "variables": []}` | `Dataset` as `.json` / `.binpb` / `.txtpb` |
| Import via | **Templates ▸ Import from JSON** (you type the name in the dialog) | **Create Dataset from File** |
| `--combined` | n/a (templates are single reactions) | writes `out/combined.<ext>` with all runs |

The importers are not interchangeable: the template importer reads
`{binpb, variables}` (and requires `variables` to be a JSON **array**); the
dataset importer parses the whole file as a `Dataset`. Feeding one to the
other fails.

### What information each carries

Both formats contain the same per-reaction content built from the
instrument files + maDMP:

- **Reaction inputs** — one component per loaded chemical, with a `NAME`
  identifier and (after `--resolve`) `INCHI`/`INCHI_KEY`/`SMILES`; amounts
  recovered from the name where present.
- **Setup** — vessel type/details/position, `is_automated`, automation
  platform.
- **Provenance** — `experimenter` and `record_created` (person + time +
  DOI) from the maDMP (see below).
- **Notes** — a free-text dump of labware, run/setup options, source files,
  and the full maDMP contributor roster (roles + ORCID).

The **Dataset** format additionally carries **Dataset-level maDMP
metadata** that a single-reaction template has nowhere to put: `Dataset.name`
(maDMP title) and `Dataset.description` (maDMP description, project, funding,
contributor list, DMP id). **Choose `--format dataset` if you need that
metadata preserved at import; choose the default template to drop a reaction
straight into the editor's template library.**

## maDMP usage

When `--madmp` is given, the following attributes are mapped (everything
else, including the `dataset[]`/distribution/license block, is ignored):

- `contact` (or, if absent, the first contributor) → `provenance.experimenter`
  (name / email / orcid).
- a contributor with a data-steward role (`ContactPerson`, `DataManager`,
  `DataCurator`) → `provenance.record_created.person` — so up to **two**
  distinct people are represented (ORD provenance has no contributor list).
- `dmp_id` (when `type == "doi"`) → `provenance.doi`; `created` →
  `record_created.time`.
- `title` → `Dataset.name`; `description` + `project` + `funding` +
  contributor names → `Dataset.description` (Dataset formats only).
- the full contributor roster (roles + ORCID) is preserved in the reaction
  notes regardless of format.

The maDMP is validated against the bundled **RDA-DMP-Common 1.2 JSON
schema** before use: issues are printed as warnings and processing
continues, unless `--strict-madmp` is passed, which aborts on any schema
violation. (Validation needs the `jsonschema` package; if it is missing the
check is skipped.)

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
