"""Shared POI clip/index/check/export used by every POI source stage.

Common schema: source, source_id, name, name_en, category, category_hierarchy, confidence,
lat, lng, h3_res{r} for each grid resolution plus poi_index_res, attrs (JSON string).
"""

from __future__ import annotations

import logging
from pathlib import Path

import duckdb

from kh_h3_atlas import db, manifest
from kh_h3_atlas.config import Config
from kh_h3_atlas.stages import boundary, grid

log = logging.getLogger(__name__)


def output_path(cfg: Config, source: str) -> Path:
    return cfg.paths.interim / f"poi_{source}.parquet"


def preview_path(cfg: Config, source: str) -> Path:
    return cfg.paths.interim / "qgis" / f"poi_{source}.gpkg"


def index_resolutions(cfg: Config) -> list[int]:
    return sorted({*cfg.h3.resolutions, cfg.h3.poi_index_res})


def clip_and_write(
    cfg: Config, con: duckdb.DuckDBPyConnection, source: str, inputs: dict, raw: list[Path]
) -> list[Path]:
    """Clip the `staged` temp table to Cambodia, add H3 columns, check, write, record."""
    res = max(cfg.h3.resolutions)
    grid_path = grid.output_path(cfg, res)
    if not grid_path.exists():
        raise FileNotFoundError(f"{grid_path} missing; run `kh-atlas grid` first")
    out, preview = output_path(cfg, source), preview_path(cfg, source)
    h3_cols = ", ".join(
        f"h3_latlng_to_cell(lat, lng, {r})::UBIGINT AS h3_res{r}" for r in index_resolutions(cfg)
    )
    n_staged = con.execute("SELECT count(*) FROM staged").fetchone()[0]
    con.execute(
        db.read_sql(
            "poi_clip",
            grid=grid_path,
            grid_res=res,
            boundary=boundary.output_path(cfg),
            h3_cols=h3_cols,
            out=out,
        )
    )

    n, n_ids, outside = con.execute(
        f"SELECT count(*), count(DISTINCT source_id),"
        f" count(*) FILTER (WHERE h3_res{res} NOT IN (SELECT h3 FROM '{grid_path}'))"
        f" FROM '{out}'"
    ).fetchone()
    if outside:
        raise AssertionError(f"{source}: {outside} POIs outside the grid after clipping")
    if n != n_ids:
        raise AssertionError(f"{source}: {n - n_ids} duplicate source_id values")
    if n == 0:
        raise AssertionError(f"{source}: no POIs left after clipping")
    log.info("poi %s: %s staged in bbox -> %s inside Cambodia", source, f"{n_staged:,}", f"{n:,}")

    db.write_gpkg(
        con,
        "SELECT source_id, name, name_en, category, confidence,"
        f" ST_Point(lng, lat) AS geometry FROM '{out}'",
        preview,
        f"poi_{source}",
    )
    manifest.record_stage(
        cfg,
        f"poi_{source}",
        rows={"staged": n_staged, "kept": n},
        outputs=[*raw, out, preview],
        inputs=inputs,
    )
    return [out, preview]
