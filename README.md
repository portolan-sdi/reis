# reis

A validator and linter for [Portolan](https://www.portolan-sdi.org/) catalogs. Named after [Piri Reis](https://www.unesco.org/en/memory-world/piri-reis-world-map-1513).

Portolan conformance is defined by passing this validator. reis implements two of the spec's separable passes:

- the **metadata pass** — every requirement in the [Portolan spec](https://github.com/portolan-sdi/portolan-spec) checkable from the catalog's JSON metadata alone, without reading asset bytes;
- the **structural pass** — STAC 1.1.0 core validity, delegated to [`stac-validator`](https://github.com/stac-utils/stac-validator) (the maintained `stac-valid` distribution). This validates each object against the STAC 1.1.0 *core* schema only; the extensions an object declares — including the Portolan profile — are the metadata pass's domain, so a not-yet-published extension schema never breaks it.

Not covered here (separate passes):

- the data pass (GeoParquet spatial ordering and row-group statistics, embedded COG statistics)
- live-hosting checks (CORS, HTTP range requests)
- field validation against the published Portolan profile schema

## Install

```bash
uv tool install reis
```

## CLI

```bash
reis check path/to/catalog
reis check --json path/to/catalog
reis check --no-structural path/to/catalog
```

Exit code 0 when the catalog passes (no errors; warnings and infos allowed), 1 when errors were found.

`reis check` runs both passes by default. The structural pass fetches the STAC core schemas from `schemas.stacspec.org` (cached in-process); when it cannot reach them it emits a single `PTL-STR-000` warning rather than failing, so the offline metadata findings still surface. Pass `--no-structural` to skip it and run the metadata pass alone.

## Library

```python
from reis import validate

report = validate("path/to/catalog")
report.passed          # no ERROR findings
for finding in report.findings:
    print(finding.rule_id, finding.severity.value,
          finding.path, finding.message)
```

`validate` runs the metadata pass only. Add `structural=True` to also run the STAC structural pass (this reaches the network); the CLI turns it on by default:

```python
report = validate("path/to/catalog", structural=True)
```

Rules can be disabled or re-severitied:

```python
from reis import RulesConfig, Severity, validate

config = RulesConfig(
    disabled=frozenset({"PTL-PRO-002"}),
    severity_overrides={"PTL-TTL-002": Severity.ERROR},
)
report = validate("path/to/catalog", config=config)
```

## Rules

Findings carry a stable rule id (`PTL-<GROUP>-<NNN>`), a severity, a message, and the offending file path. Severities follow the spec: MUST maps to `error`, SHOULD to `warning`, with three deliberate exceptions:

- `PTL-CNF-002` (schema URI differs from the root catalog's) is a **warning** — the spec's explicit exception; a mixed-version catalog remains valid.
- `PTL-TTL-002` (title looks machine-generated) is a **warning** by default because it is heuristic; promote it with a severity override.
- `PTL-PRO-002` (mirror without a `canonical` link) is **info**, since whether the upstream publishes STAC is unknowable from metadata.
- `PTL-VIZ-004` (large vector without a visual derivative) is **info**: the spec's render-path MUST hinges on whether render-from-source is viable, which metadata cannot prove; the size threshold (100 MB) is heuristic.
- `PTL-VIZ-001` skips collections whose geospatial-vs-tabular nature is undecidable from metadata (the spec identifies tabular by the Parquet's geometry column — a data-pass fact); positive signals are item geometries, a `table:columns` geometry column, or spatial media types.

| Group | Rules | Checks |
|-------|-------|--------|
| `PTL-GEN` | 000–001 | root catalog.json present, every object file parseable |
| `PTL-LNK` | 001–006 | required structural links, child/item completeness, link types, relative-only, no self link, links resolve to the correct object |
| `PTL-TTL` | 001–003 | non-empty title/description, human-readable titles, titled child/item links |
| `PTL-BBX` | 001 | finite, sentinel-free WGS84 bboxes with south ≤ north (2D and 3D) |
| `PTL-TMP` | 001–002 | item datetime or interval present; RFC 3339, start ≤ end |
| `PTL-PRV` | 001–003 | ≥1 producer, exactly one host listed last, host url-or-email |
| `PTL-LIC` | 001–003 | SPDX or `other`, license link for `other`, no `proprietary` |
| `PTL-FIL` | 001–003 | AGENTS.md and README.md on disk, `rel:"agents"` and `rel:"describedby"` markdown links |
| `PTL-AST` | 001–004 | asset href/type/roles, https-not-s3, `file:size`, multihash `file:checksum` |
| `PTL-CNF` | 001–002 | versioned Portolan schema URI declared, consistent with the root |
| `PTL-PRO` | 001–004 | mirror `via`/`canonical` links and `updated` sync time; officials carry no upstream links |
| `PTL-VIZ` | 001–004 | thumbnail on geospatial collections, style assets for visual derivatives, PMTiles `rel:"pmtiles"` registration, large-vector-without-visual nudge |
| `PTL-STR` | 000–001 | STAC 1.1.0 core structural validity (`stac-validator`); `000` warns when the pass could not run |

Validation is local-directory only for now. `CatalogGraph` (`src/reis/catalog.py`) is the single I/O layer, loaded in one pass, so a remote (HTTP) loader can slot in later.

## Development

```bash
uv sync
uv run pytest
uv run ruff check .
uv run mypy
uv run lint-imports
```
