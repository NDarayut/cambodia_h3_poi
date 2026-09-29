"""Stage 2: polyfill boundary parts into H3 cells for each configured resolution."""

from __future__ import annotations

import logging
from pathlib import Path

import duckdb

from kh_h3_atlas import db, manifest
from kh_h3_atlas.config import Config
from kh_h3_atlas.stages import boundary

log = logging.getLogger(__name__)

# Total cell area / land area. Uses real cell areas: H3 cells over Cambodia are ~16% larger
# than the global average, so counts from h3.average_hexagon_area would be ~16% too high.
# overlap adds a ring of coastal/border cells, so it covers more than the land area.
COVERAGE_RANGE = {"center": (0.97, 1.03), "overlap": (1.0, 1.2)}
PREVIEW_MAX_RES = 8  # res 9 (~1.7M polygons) is too heavy for a quick QGIS preview


def output_path(cfg: Config, res: int) -> Path:
    return cfg.paths.interim / f"grid_res{res}.parquet"


def geom_expr(buffer_m: float) -> str:
    if not buffer_m:
        return "geometry"
    utm = boundary.UTM
    return (
        f"ST_Transform(ST_Buffer(ST_Transform(geometry, 'OGC:CRS84', '{utm}'), {buffer_m}), "
        f"'{utm}', 'OGC:CRS84')"
    )


def polyfill(
    con: duckdb.DuckDBPyConnection,
    boundary_path: Path,
    res: int,
    mode: str,
    buffer_m: float,
    out: Path,
) -> None:
    con.execute(
        db.read_sql(
            "grid",
            boundary=boundary_path,
            geom_expr=geom_expr(buffer_m),
            res=res,
            mode=mode,
            out=out,
        )
    )


def check(con: duckdb.DuckDBPyConnection, out: Path, res: int, area_km2: float, mode: str) -> int:
    n, n_distinct, bad_res, cell_km2 = con.execute(
        "SELECT count(*), count(DISTINCT h3),"
        f" count(*) FILTER (WHERE h3_get_resolution(h3) <> {res}),"
        f" sum(h3_cell_area(h3, 'km^2')) FROM '{out}'"
    ).fetchone()
    if n != n_distinct:
        raise AssertionError(f"res {res}: {n - n_distinct} duplicate h3 keys")
    if bad_res:
        raise AssertionError(f"res {res}: {bad_res} cells at the wrong resolution")
    coverage = cell_km2 / area_km2
    lo, hi = COVERAGE_RANGE[mode]
    if not lo <= coverage <= hi:
        raise AssertionError(
            f"res {res}: cells cover {coverage:.3f}x the land area, expected {lo}-{hi}"
        )
    log.info("grid res %d: %s cells covering %.3fx land area", res, f"{n:,}", coverage)
    return n


def run(cfg: Config, force: bool = False) -> list[Path]:
    bpath = boundary.output_path(cfg)
    if not bpath.exists():
        raise FileNotFoundError(f"{bpath} missing; run `kh-atlas boundary` first")
    g = cfg.grid
    resolutions = cfg.h3.resolutions
    outs = [output_path(cfg, r) for r in resolutions]
    inputs = {
        "boundary": manifest.load(cfg).get("stages", {}).get("boundary", {}).get("inputs"),
        "resolutions": resolutions,
        "containment": g.containment,
        "buffer_m": g.buffer_m,
    }
    if not force and manifest.is_fresh(cfg, "grid", outs, inputs):
        log.info("grid: cached")
        return outs

    con = db.connect(cfg)
    area = con.execute(f"SELECT sum(area_km2) FROM '{bpath}'").fetchone()[0]
    rows = {}
    for res, out in zip(resolutions, outs, strict=True):
        polyfill(con, bpath, res, g.containment, g.buffer_m, out)
        rows[f"res{res}"] = check(con, out, res, area, g.containment)
        if g.containment == "overlap":
            missed = con.execute(
                f"SELECT list(part_id) FROM '{bpath}' b ANTI JOIN '{out}' c"
                f" ON h3_latlng_to_cell(ST_Y(ST_PointOnSurface(b.geometry)),"
                f" ST_X(ST_PointOnSurface(b.geometry)), {res}) = c.h3"
            ).fetchone()[0]
            if missed:
                raise AssertionError(f"res {res}: boundary parts with no cells: {missed}")

    # Every parent of a finer cell should be in the coarser grid (nesting sanity check, logged)
    for coarse, fine in zip(resolutions, resolutions[1:], strict=False):
        fine_p, coarse_p = output_path(cfg, fine), output_path(cfg, coarse)
        orphans = con.execute(
            f"SELECT count(DISTINCT h3_cell_to_parent(f.h3, {coarse})) FROM '{fine_p}' f"
            f" ANTI JOIN '{coarse_p}' c ON h3_cell_to_parent(f.h3, {coarse}) = c.h3"
        ).fetchone()[0]
        if orphans:
            log.warning(
                "grid: %d res-%d parents of res-%d cells not in res-%d grid",
                orphans,
                coarse,
                fine,
                coarse,
            )

    previews = []
    for res in (r for r in resolutions if r <= PREVIEW_MAX_RES):
        p = cfg.paths.interim / "qgis" / f"grid_res{res}.gpkg"
        db.write_gpkg(
            con,
            "SELECT h3_str, res, ST_GeomFromText(h3_cell_to_boundary_wkt(h3)) AS geometry"
            f" FROM '{output_path(cfg, res)}'",
            p,
            f"grid_res{res}",
        )
        previews.append(p)

    manifest.record_stage(cfg, "grid", rows=rows, outputs=[*outs, *previews], inputs=inputs)
    return [*outs, *previews]
