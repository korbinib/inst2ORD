# inst2ord

Map the XML files produced by a high-throughput chemistry platform (and,
optionally, a machine-actionable Data Management Plan / maDMP) onto the
[Open Reaction Database](https://docs.open-reaction-database.org/) (ORD)
schema, and emit files that can be imported as **templates** or **datasets** into the ORD
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
# Default: one JSON template per run for the online ORD reaction editor (no network) - only reaction level information 
python -m inst2ord.cli examples/xmls --out out
```

```bash
# one JSON template per run for the online ORD reaction editor - only reaction level information; enriched compounds via PubChem (InChI/InChIKey, SMILES via RDKit)
python -m inst2ord.cli examples/xmls --out out --resolve
```

```bash
# Choose which identifiers to emit (NAME is always kept); see Identifiers
python -m inst2ord.cli examples/xmls --resolve --identifiers inchi inchikey rinchi --out out
```

```bash
# Export as a Dataset instead (Create Dataset from File in online ORD reaction editor) including information from a maDMP for contributors and proverance information
python -m inst2ord.cli examples/xmls --madmp examples/madmp/ex9-dmp-long.json --out out --resolve --format dataset  # or binpb/txtpb
```

```bash
# Inspect parsing only (neutral intermediate as JSON; no ORD, no network)
python -m inst2ord.cli examples/xmls --dry-run
```

The resulting files can be directly used in an  [ORD submission](https://docs.open-reaction-database.org/en/latest/submissions.html), e.g. via the the [online ORD reaction editor](https://app.open-reaction-database.org/).

## Template vs Dataset export

The [online ORD reaction editor](https://app.open-reaction-database.org/)  has **two** import paths that take **different, non-interchangeable**
formats. inst2ord can target either (`--format`):

| | **Template** (`--format template`, default) | **Dataset** (`--format dataset` / `binpb` / `txtpb`) |
| --- | --- | --- |
| ORD message | a single `Reaction` | a `Dataset` (one reaction per run) |
| File | `Template` as `.json` | `Dataset` as `.json` / `.binpb` / `.txtpb` |
| Import via | **Templates ▸ Import from JSON** (you type the name in the dialog) | **Create Dataset from File** |
| `--combined` | n/a (templates are single reactions) | writes `out/combined.<ext>` with all runs |

The formats are not interchangeable: the template importer reads
`{binpb, variables}` (and requires `variables` to be a JSON **array**); the
dataset importer parses the whole file as a `Dataset`. Feeding one to the
other fails.

### What information each carries

Both formats contain the same per-reaction content built from the
instrument files + maDMP, please read more in the 
[ORD schema documentation](https://docs.open-reaction-database.org/en/latest/schema.html):

- **Reaction inputs** — one component per loaded chemical, with a `NAME`
  identifier and (after `--resolve`) `INCHI`/`INCHI_KEY`/`SMILES`/`CAS`
  (selectable with `--identifiers`, see below); amounts recovered from the
  name where present.
- **Identifiers (reaction-level)** — a `CUSTOM` identifier holding the run
  id (e.g. `Exp333`), plus a `RINCHI` assembled from the resolved input
  InChIs when available (opt-in via `--identifiers`, see below).
- **Setup** — vessel type/details/position, `is_automated`, automation
  platform.
- **Conditions** — qualitative `temperature`/`stirring` inferred from deck
  station names (`Heat-Stir` → heated + stir bar, `Vortex` → agitation),
  flagged low-confidence in `conditions.details`; no setpoints/rpm invented.
- **Provenance** — `experimenter` (with their affiliation as
  `organization`) and `record_created` (person + time + DOI) from the
  maDMP; `city` from the experimenter's affiliation ROR (see below).
- **Notes** — a free-text dump of labware, run/setup options, source files,
  the experimenter, and the full maDMP contributor roster (roles, ORCID,
  affiliation + ROR).

The **Dataset** format additionally carries **Dataset-level maDMP
metadata** that a single-reaction template has nowhere to put: `Dataset.name`
(maDMP title) and `Dataset.description` (maDMP description, project, funding,
contributor list, DMP id). **Choose `--format dataset` if you need that
metadata preserved at import; choose the default template to drop a reaction
straight into the editor's template library.**

## maDMP usage

When `--madmp` is given, the following attributes are mapped from a 
[RDA-DMP-Common 1.2 JSON](https://github.com/RDA-DMP-Common/RDA-DMP-Common-Standard)
(everything else, including the `dataset[]`/distribution/license block, is ignored):

- `provenance.experimenter` ← a contributor with a DataCite **experimenter**
  role (`DataCollector`, `ProjectMember`, `Producer`, `Researcher`); else the
  `contact`; else the first contributor.
- `provenance.record_created.person` ← a contributor with a **record-creator**
  role (`DataManager` preferred, then `ContactPerson`, `DataCurator`, `DataSteward`, `ProjectManager`,
  `ProjectLeader`, `WorkPackageLeader`); else the `contact`; else the
  experimenter. So up to **two** distinct people are represented (ORD
  provenance has no contributor list).
- the experimenter's first `affiliation` `name` → `provenance.experimenter.organization`.
- `provenance.city` ← the experimenter's affiliation **city**, looked up
  from the ROR API (`locations[].geonames_details.name`) when the
  affiliation has a `ror` id and `--resolve` is given. The lookup is cached
  (`--ror-cache`, default `cache/ror`); affiliation names and RORs are
  mapped with or without network, only the city needs it.
- `dmp_id` (when `type == "doi"`) → `provenance.doi`; `created` →
  `record_created.time`.
- `title` → `Dataset.name`; `description` + `project` + `funding` +
  contributor names → `Dataset.description` (Dataset formats only).
- the full contributor roster (roles, ORCID, affiliation name + city +
  ROR) and the named experimenter are preserved in the reaction notes
  regardless of format.

The maDMP is validated against the bundled **RDA-DMP-Common 1.2 JSON
schema** before use: issues are printed as warnings and processing
continues, unless `--strict-madmp` is passed, which aborts on any schema
violation. (Validation needs the `jsonschema` package; if it is missing the
check is skipped.)

## Identifiers (`--identifiers`)

Choose which optional identifiers to emit; **`NAME` is always included**.
The default is all of them.

| value | level | ORD identifier |
| --- | --- | --- |
| `inchi` | compound | `INCHI` |
| `inchikey` | compound | `INCHI_KEY` |
| `smiles` | compound | `SMILES` (derived from the InChI via RDKit) |
| `cas` | compound | `CAS_NUMBER` (from the curation table) |
| `rinchi` | reaction | `RINCHI`, assembled from the resolved input InChIs |

```bash
# InChI + InChIKey + reaction RInChI only (no SMILES/CAS); needs resolution
python -m inst2ord.cli examples/xmls --resolve \
    --identifiers inchi inchikey rinchi --out out
```

Notes:

- The structure identifiers (`inchi`/`inchikey`/`smiles`/`cas`) and `rinchi`
  are only populated once names are resolved (via `--resolve` or
  `curation.csv`); without resolution only `NAME` is emitted.
- `rinchi` is **reaction-level** and coexists with the per-compound
  identifiers — it does not replace `smiles`. It is built from the component
  InChIs in the RInChI 1.00 string format and is reactant-only for a template
  (no products). Canonical RInChIKeys still require the official IUPAC RInChI
  toolkit.

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

### Planned: downstream analysis data (NMR / HPLC) → outcomes & products

The platform XML only describes the *setup* side, so inst2ord deliberately
leaves the outcome side of every reaction blank (see *What it does*). A
natural extension is a second, **downstream** input stream — the analytical
files a separate instrument produces *after* the reaction (e.g. an NMR or
HPLC/LC-MS run) — used to populate `Reaction.outcomes[]` and so close the
loop from loaded reagents to identified, quantified products.

Mapping target in the [ORD schema](https://docs.open-reaction-database.org/en/latest/schema.html):

- **`ReactionOutcome.products[]`** (`ProductCompound`) — one per detected
  product, carrying the same `NAME`/`INCHI`/`INCHI_KEY`/`SMILES` identifiers
  as inputs (reusing the resolver), with `is_desired_product` and
  `reaction_role = PRODUCT`.
- **Yield** → `ProductCompound.measurements[]` (`ProductMeasurement`) with
  `type = YIELD` and `percentage`; related quantities map to `AREA`/`COUNTS`
  (HPLC integration), `PURITY` or `IDENTITY`. Flags such as
  `uses_internal_standard` / `is_normalized` / `uses_authentic_standard`
  record *how* the yield was determined.
- **`ReactionOutcome.analyses`** — one `Analysis` per technique
  (`type = NMR_1H` / `NMR_13C` / `LC` / `LCMS` / `HRMS` …), referenced from
  each measurement via `ProductMeasurement.analysis_key`, so a yield is
  traceable to the run that produced it.
- **`ReactionOutcome.conversion`** and **`reaction_time`** where the
  analysis reports them.

Architecturally this fits the existing exchangeable-adapter design: an
**analysis adapter** would parse the instrument's native export into an
outcome counterpart of `ReactionIntent` (a new `outcomes` block on the
model), `build_ord` would emit the ORD messages above, and the resolver is
reused to identify products. The open question is **correlation** — matching
each analysis file back to its reaction run (by run id, well/position, or
sample label) so outcomes attach to the right `Reaction`; the maDMP
`dataset[].technical_resource` entries (see above) could also flag which
runs carry downstream analysis. Adding outcomes would also let these
reactions pass full ORD validation rather than reporting the *expected gaps*
noted under *Validation*.

