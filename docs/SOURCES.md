# Data sources

All sources are aligned to one `reference_date` in `config/default.yaml` (currently
**2026-09-23**). Each resolves to its latest snapshot **on or before** that date.
Run `uv run kh-atlas sources` to see exactly what will be used; the result is written to
`data/processed/manifest.json`.

| Component | Used for | Provider | Where it comes from | Snapshot at 2026-09-23 | License |
|---|---|---|---|---|---|
| Country boundary, admin areas | Clipping the grid, province/district/commune tags | Overture Maps Foundation, `divisions` theme | `s3://overturemaps-us-west-2/release/<release>/theme=divisions/type=division_area/` (public, no login) | release `2026-09-23.1` | ODbL |
| POIs (businesses) | Retail, food, general business counts | Overture Maps Foundation, `places` theme | `s3://overturemaps-us-west-2/release/<release>/theme=places/type=place/` | release `2026-09-23.1` | CDLA-Permissive-2.0 / Apache-2.0 / CC0, per source |
| POIs (public facilities) | Health, education, finance, religious, government counts | OpenStreetMap contributors, extract by Geofabrik | `https://download.geofabrik.de/asia/cambodia-<YYMMDD>.osm.pbf` (index: https://download.geofabrik.de/asia/cambodia.html) | `cambodia-260923.osm.pbf` | ODbL |
| Population | Population per hex | WorldPop (University of Southampton), Global 2015–2030 R2025A | `https://data.worldpop.org/GIS/Population/Global_2015_2030/R2025A/<year>/KHM/v1/100m/constrained/` | `khm_pop_2026_CN_100m_R2025A_v1.tif` (2026 estimate) | CC BY 4.0 |
| H3 grid | Hexagon cells | Uber H3 (library, not data) | `h3` Python package / DuckDB `h3` community extension | — | Apache-2.0 |

## Snapshot availability (checked 2026-09-29)
- **Overture** keeps releases on S3 for about 60 days (currently `2026-08-19.0`,
  `2026-09-23.0`, `2026-09-23.1`). The pipeline caches raw extracts in `data/raw/` so a run
  stays reproducible after a release is removed.
- **Geofabrik** keeps daily extracts for about a week, monthly ones (1st of the month) for a
  few months, and yearly ones (Jan 1) back to 2017. For long-lived reproducibility, pin a
  monthly/yearly snapshot or keep the cached file.
- **WorldPop** publishes one estimate per year, 2015–2030 (future years are projections).
  It is matched on `reference_date` year.

## Attribution
- Population: WorldPop (www.worldpop.org), R2025A, CC BY 4.0.
- © OpenStreetMap contributors, ODbL (https://www.openstreetmap.org/copyright).
- Overture Maps Foundation (https://overturemaps.org), per-source licenses.
