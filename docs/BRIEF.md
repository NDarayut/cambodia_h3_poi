# Project Brief: Cambodia H3 + POI Atlas (`kh-h3-atlas`)

> Hand this file to Claude Code to initialize the repo. Read the whole brief first, then follow **Milestones** in order. Anything marked **VERIFY** must be checked against live data or current docs before code depends on it.

## 1. Goal

Build a reproducible, modular pipeline that:

1. Generates a complete H3 hexagon grid covering Cambodia's land area.
2. Attaches open data layers to every cell: population (Kontur), points of interest (Overture Maps, optionally Foursquare OS Places and OSM/HOT exports).
3. Produces a **hex-level feature table** (GeoParquet) usable for both:
   - **Mapping/visualization** (kepler.gl, deck.gl `H3HexagonLayer`, QGIS)
   - **Modeling** (joinable features keyed by H3 cell ID)

The end use is not fixed yet, so the pipeline must support multiple H3 resolutions and a configurable set of POI category features.

## 2. Non-goals (for v1)

- No web app or dashboard. Output is data files plus a simple static preview.
- No routing, travel-time, or road-network features yet (leave a hook for a future Overture `transportation` layer).
- No paid or proprietary data sources.

## 3. Tech stack

- **Python 3.11+**, managed with **uv** (`pyproject.toml`, lockfile committed).
- **DuckDB** as the processing engine, with extensions: `spatial`, `httpfs`, `h3` (community: `INSTALL h3 FROM community;`).
- **h3-py** (v4 API) for Python-side utilities and tests.
- **GeoPandas / pyarrow** only where DuckDB is awkward (e.g., reading GeoPackage edge cases, plotting).
- **Typer** for the CLI, **Pydantic** (v2) for config validation, **pytest** for tests, **ruff** for lint/format.
- Target OS: Ubuntu Linux. No GPU needed.

Design principles: custom and modular, each stage a pure function of config plus inputs, idempotent, cached to disk, runnable individually from the CLI. Prefer SQL files executed by DuckDB over large pandas transforms.

## 4. Data sources

| Layer | Source | Access | License | Notes |
|---|---|---|---|---|
| Country boundary | Overture Maps `divisions/division_area` | S3 `s3://overturemaps-us-west-2/release/<REL>/theme=divisions/type=division_area/*` | ODbL (divisions) | Filter `country='KH'`, `subtype='country'`, `class='land'`. **VERIFY** column names against current Overture schema. |
| Admin levels (province/district/commune) | Overture divisions (`subtype` = region / county / locality), fallback: HDX Cambodia COD-AB | S3 / HDX | varies | Used to tag each hex with admin names. Optional in v1. |
| Population | Kontur Population, Cambodia 400m H3 (res 8) | HDX, org page `https://data.humdata.org/organization/kontur` (look for "Cambodia: Population Density for 400m H3 Hexagons") | CC BY 4.0 | GeoPackage (`.gpkg.gz`), has `h3` (string) and `population` columns. Last update Nov 2023. **VERIFY** column names after download. |
| POIs (primary) | Overture Maps `places/place` | S3 `s3://overturemaps-us-west-2/release/<REL>/theme=places/type=place/*` | CDLA-Permissive-2.0 / Apache-2.0 / CC0 (per source) | Has `confidence`, `categories.primary`, `names.primary`, `sources`. |
| POIs (optional) | Foursquare OS Places | Hugging Face `foursquare/fsq-os-places` (**gated**: requires accepting terms and an HF token) | Apache-2.0 | Implement behind a config flag, disabled by default. |
| POIs (optional, curated) | HOT OSM exports on HDX (health, education, financial services) | HDX | ODbL | Cleaner but sparser. Implement behind a config flag. |

### Overture release handling
Overture keeps public releases on S3 for about 60 days. Do **not** hard-code a release:
- Implement `resolve_overture_release()` that lists `s3://overturemaps-us-west-2/release/` anonymously (e.g., `aws s3 ls --no-sign-request` or DuckDB `glob`) and picks the latest, unless `overture.release` is pinned in config.
- Record the release actually used in a run manifest (see §8).
- Persist raw extracts locally so runs stay reproducible after the release disappears.

### Cambodia bounding box (coarse prefilter only)
`lon 102.3 – 107.7, lat 10.4 – 14.7`. This bbox includes parts of Thailand, Laos and Vietnam, so results **must** be clipped to the country polygon or H3 grid.

## 5. Repository structure

```
kh-h3-atlas/
├── pyproject.toml
├── README.md
├── CLAUDE.md                  # short working notes for Claude Code (generate from this brief)
├── config/
│   ├── default.yaml
│   └── poi_categories.yaml    # category groups -> list of Overture category patterns
├── src/kh_h3_atlas/
│   ├── __init__.py
│   ├── cli.py                 # Typer app: one command per stage + `run-all`
│   ├── config.py              # Pydantic models, YAML loading
│   ├── db.py                  # DuckDB connection factory, extension loading, S3 settings
│   ├── manifest.py            # run manifest read/write
│   ├── stages/
│   │   ├── boundary.py        # Cambodia land polygon(s)
│   │   ├── grid.py            # polygon -> H3 cells per resolution
│   │   ├── population.py      # Kontur download + load + re-aggregation
│   │   ├── poi_overture.py    # extract, clip, index to H3
│   │   ├── poi_fsq.py         # optional
│   │   ├── poi_osm.py         # optional
│   │   ├── dedupe.py          # cross-source POI deduplication
│   │   ├── features.py        # hex-level feature table
│   │   └── export.py          # GeoParquet / GeoJSON / CSV + preview
│   └── sql/                   # .sql files used by stages, parameterized
├── data/                      # gitignored
│   ├── raw/                   # untouched downloads
│   ├── interim/               # cleaned, H3-indexed
│   └── processed/             # final hex tables
├── notebooks/                 # exploration only; never imported by src
└── tests/
```

## 6. Pipeline stages

Each stage reads config, checks for cached output (skip unless `--force`), writes to `data/`, and appends to the run manifest.

1. **boundary**: Extract Cambodia land geometry from Overture divisions. Explode MultiPolygon into parts (islands such as Koh Kong and Koh Rong must be included). Save as GeoParquet.
2. **grid**: For each resolution in `h3.resolutions` (default `[7, 8, 9]`), polyfill each polygon part (`h3_polygon_wkt_to_cells` or h3-py `polygon_to_cells`), union, dedupe. Output: `grid_res{r}.parquet` with columns `h3` (UBIGINT), `h3_str`, `res`, `lat`, `lng`.
   - **VERIFY** polyfill containment semantics (centroid-in-polygon by default). Coastal/border cells whose centroid is outside the polygon get dropped. Add an option `grid.buffer_m` to buffer the polygon slightly before polyfill.
   - Expected size at res 8: roughly 245k cells (Cambodia ≈ 181,000 km², res-8 cell ≈ 0.74 km²). Assert the count lands within a sane range.
3. **population**: Download Kontur Cambodia GPKG, load with `ST_Read`, convert `h3` string to UBIGINT. Native res is 8; derive res 7 by summing children to parent (`h3_cell_to_parent`). For res 9, either leave null or distribute evenly to children (config flag `population.res9_strategy: null | uniform`); document that uniform is an approximation.
4. **poi_overture**: Query places with bbox prefilter plus `confidence >= poi.min_confidence` (default 0.6, configurable). Keep: `id`, `names.primary`, `categories.primary`, `categories.alternate`, `confidence`, `sources`, lon/lat, and H3 cell at the finest configured resolution plus parents. Clip by inner join to the finest grid.
5. **poi_fsq / poi_osm** (optional, flag-gated): Same output schema as Overture, with a `source` column.
6. **dedupe**: Merge POI sources. Candidate duplicates share an H3 res-11 cell (or `grid_disk` k=1) plus normalized-name similarity (casefold, strip punctuation; handle Khmer script without transliteration in v1). Keep the highest-confidence record, retain provenance in `dup_group_id`.
7. **features**: For each resolution, left-join grid ← population ← POIs and compute:
   - `population`, `n_poi`, `poi_per_1k_pop` (null-safe)
   - one count column per category group in `poi_categories.yaml` (e.g., `n_finance`, `n_education`, `n_health`, `n_retail`, `n_food`, `n_religious`, `n_transport`, `n_government`)
   - `poi_category_entropy` (diversity of categories in cell)
   - neighborhood features: sums over `h3_grid_disk(h3, k)` for `k` in config (default `[1, 2]`), suffixed `_k1`, `_k2`
   - optional admin tags: `province`, `district`, `commune`
   - a `data_coverage_flag` for cells with population > threshold but zero POIs (likely missing data, not absence)
8. **export**: Write GeoParquet (with `geometry` from `h3_cell_to_boundary_wkt`), plus CSV without geometry, plus a small GeoJSON sample for Phnom Penh. Generate a static HTML preview (kepler.gl or pydeck) for res 8.

## 7. Configuration (`config/default.yaml` sketch)

```yaml
country_iso2: KH
bbox: {xmin: 102.3, xmax: 107.7, ymin: 10.4, ymax: 14.7}
overture:
  release: latest          # or pin e.g. "2026-09-xx.0"
  s3_region: us-west-2
h3:
  resolutions: [7, 8, 9]
  poi_index_res: 11        # finest res stored on POIs for dedupe
grid:
  buffer_m: 0
population:
  res9_strategy: null
poi:
  min_confidence: 0.6
  sources: {overture: true, fsq: false, osm_hot: false}
features:
  neighborhood_k: [1, 2]
  coverage_flag_min_pop: 200
paths:
  raw: data/raw
  interim: data/interim
  processed: data/processed
```

`poi_categories.yaml` maps group names to Overture category patterns. Seed it by first running a helper command `kh-atlas explore-categories` that prints the top 200 `categories.primary` values in Cambodia with counts, then fill the mapping by hand.

## 8. Reproducibility

- `data/processed/manifest.json` records: Overture release, Kontur file name/date, config hash, row counts per stage, run timestamp, package versions.
- All downloads are checksummed and stored in `data/raw/`.
- `kh-atlas run-all --config config/default.yaml` must work from a clean clone (network required).

## 9. Testing & validation

- **Unit tests** (no network): polyfill on a tiny synthetic polygon, parent/child population aggregation conserves totals, dedupe logic on fixture POIs, category mapping.
- **Data assertions** (run after each stage, fail loudly):
  - Grid cell counts within expected ranges per resolution.
  - Sum of Kontur population across res-8 cells within ±1% of the sum in the source file; res-7 total equals res-8 total.
  - Zero POIs outside the grid after clipping.
  - No duplicate `h3` keys in any feature table.
- **Sanity checks** (logged, not fatal): top 10 hexes by `n_poi` should fall in Phnom Penh, Siem Reap, Sihanoukville, Battambang.

## 10. Known data caveats (document in README)

- POI coverage is highly uneven: dense in cities, sparse rurally. Low counts often mean missing data.
- Overture categories are an English taxonomy. Names mix Khmer, English and transliterations, and duplicates across sources are common.
- Meta-sourced Overture places dominate volume and vary in quality; `confidence` filtering matters.
- Kontur population is a modeled estimate (last updated 2023), not census data.
- Respect attribution requirements: Kontur (CC BY), OSM (ODbL), Overture per-source licenses. Generate an `ATTRIBUTION.md` from the manifest.

## 11. Milestones

1. **Scaffold**: repo structure, `pyproject.toml` with uv, ruff, pytest, Typer CLI skeleton, config loading, DuckDB connection helper that loads `spatial`, `httpfs`, `h3`. Generate `CLAUDE.md` summarizing conventions from this brief.
2. **Boundary + grid**: stages 1–2 with assertions. Checkpoint: print cell counts per resolution.
3. **Population**: stage 3. Checkpoint: population totals match source.
4. **Overture POIs**: `resolve_overture_release`, stage 4, `explore-categories` command. Checkpoint: pause and show category counts so the category mapping can be filled in.
5. **Features + export**: stages 7–8 with Overture only. Checkpoint: res-8 GeoParquet plus HTML preview.
6. **Optional sources + dedupe**: stages 5–6 behind flags.
7. **Admin tagging** and README/attribution polish.

Stop at each checkpoint and summarize results before continuing.