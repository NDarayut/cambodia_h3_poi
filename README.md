# kh-h3-atlas

Cambodia H3 hexagon atlas: population (WorldPop) and points of interest (OpenStreetMap,
Overture) aggregated to H3 cells at resolutions 7, 8 and 9, for viewing in QGIS and for modelling.

## Quick start
```bash
uv sync
uv run kh-atlas sources      # show which dated snapshot of each source will be used
uv run kh-atlas run-all      # full pipeline (network required)
uv run pytest -m "not network"
```

All sources are aligned to `reference_date` in `config/default.yaml`. See `docs/SOURCES.md`
for where each dataset comes from and its license, and `docs/BRIEF.md` for the full design.
