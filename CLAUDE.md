# kh-h3-atlas — working notes

Full original brief: `docs/BRIEF.md`. Data provenance: `docs/SOURCES.md`. This file records
conventions and the **deviations from the brief** agreed with the user.

## Agreed deviations from the brief
- **Population = WorldPop** (R2025A, 100m constrained raster), not Kontur. Summed directly
  from pixel centres to every H3 resolution, so res 9 gets real values (no `res9_strategy`).
  Constrained raster is nodata where no buildings: grid comes from the Overture boundary and
  hexes without pixels get population 0.
- **POIs = OSM only** (user choice 2026-09-29, after comparing both in QGIS). Overture places
  code stays but `poi.use.overture: false`; Overture is still used for the boundary.
  Category groups: `config/poi_categories.yaml`, first match wins, 9 groups incl. `lodging`.
- **User views everything in QGIS.** Primary output is GeoPackage + `.qml` styles + a
  generated `.qgz` project. GeoParquet/CSV are secondary. No HTML preview.
- **Grid containment = `overlap`** (not the brief's centroid default): with `center`, 14 of 33
  island parts get zero res-8 cells. Grid check compares total cell area to land area, not
  counts: H3 cells over Cambodia are ~16% larger than the global average, so the brief's
  "~245k res-8 cells" is wrong; actual is 215,239.
- **One resolution first (res 8)**, per user. Polyfill cost grows ~7x per resolution
  (res 8 ~70 s, res 9 ~7 min in center mode, slower in overlap). Add 7/9 later.
- **Population per resolution is assigned directly from pixels**, not rolled up from res 8.
  H3 nesting is approximate, so res-7 values differ slightly from summed res-8 children;
  national totals match either way. Revisit if cross-resolution consistency matters.
- **Overture places schema (VERIFIED 2026-09-23.1):** no `categories` column; use
  `taxonomy.primary` / `taxonomy.hierarchy` (hierarchy[1] = top-level group) and
  `basic_category`; filter `operating_status` = open.
- **POI clipping:** grid join first (fast), then exact point-in-country test on survivors,
  because overlap border cells extend into TH/VN/LA.
- **Temporal alignment:** single `reference_date` in config; every source resolves to its
  latest snapshot on/before it (`sources.py`). Never use data newer than `reference_date`.

## Conventions
- Python 3.11, uv. Run: `uv run kh-atlas <stage>`; tests: `uv run pytest -m "not network"`;
  lint: `uv run ruff check . && uv run ruff format .`
- Each stage in `src/kh_h3_atlas/stages/<name>.py` exposes `run(cfg, force) -> list[Path]`:
  skip if cached unless `force`, write under `data/`, call `manifest.record_stage`.
- Prefer SQL files in `src/kh_h3_atlas/sql/` run through DuckDB (`db.connect`, `db.read_sql`).
  Python (rasterio/numpy) only where DuckDB can't do it (e.g. reading GeoTIFF).
- H3 v4 API. Store `h3` as UBIGINT plus `h3_str`.
- Data assertions fail loudly (brief §9); sanity checks only log.
- Raw downloads in `data/raw/<source>/<snapshot>/` with sha256 in the manifest. `data/` is
  gitignored.
- `notebooks/` is exploration only, never imported by `src`.

## Comparison app
`kh-atlas app` exports POIs/population to `data/processed/app/` and serves `web/compare.html`
(MapLibre + h3-js 4.5 + PapaParse from jsDelivr). User's ground truth is parsed client-side only.
Matching: greedy one-to-one by distance, optional trigram name similarity (default on, >= 50%).

## Workflow
Follow milestones in `docs/BRIEF.md` §11. Stop at each checkpoint and summarize for the user.
Status: Milestones 1-3 done (boundary: 33 parts, 181,669 km²; grid res 8: 215,239 cells;
population res 8: 17,951,035 of 17,951,445 raster total, -0.002%).
Milestone 4: OSM POIs 29,397 (88% in a group); draft category groups in use.
Milestone 5 done: features_res8 (215,239 x 43, data_gap 16,111), GeoPackage, CSV,
qgis/kh_atlas.qgz (built with system PyQGIS, /usr/bin/python3). Next: user's ground-truth
comparison (kh-atlas app), then Milestone 6/7.
