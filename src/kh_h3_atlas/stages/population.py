"""Stage 3: WorldPop raster -> pixel centres -> population summed per H3 cell."""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import rasterio

from kh_h3_atlas import db, manifest
from kh_h3_atlas.config import Config
from kh_h3_atlas.download import download
from kh_h3_atlas.sources import worldpop_url
from kh_h3_atlas.stages import grid

log = logging.getLogger(__name__)

TOLERANCE = 0.01  # brief §9: hex totals within ±1% of the source raster total


def raw_path(cfg: Config) -> Path:
    url = worldpop_url(cfg)
    wp = cfg.sources.worldpop
    return cfg.paths.raw / "worldpop" / f"{wp.release}_{cfg.worldpop_year}" / url.rsplit("/", 1)[1]


def pixels_path(cfg: Config) -> Path:
    return cfg.paths.interim / "worldpop_pixels.parquet"


def output_path(cfg: Config, res: int) -> Path:
    return cfg.paths.interim / f"population_res{res}.parquet"


def raster_to_pixels(tif: Path, out: Path) -> float:
    """Write every populated pixel's centre (lat, lng) and value to Parquet; return the total.

    Pixel centres are assigned whole to one H3 cell. At res 8 (~0.86 km²) a cell holds ~100
    pixels, so the edge error is small; at res 9 (~12 pixels/cell) it becomes noticeable.
    """
    with rasterio.open(tif) as r:
        arr = r.read(1, masked=True)
        t = r.transform
    if t.b != 0 or t.d != 0:
        raise ValueError("rotated rasters are not supported")
    rows, cols = np.nonzero(~np.ma.getmaskarray(arr) & (arr.filled(0) > 0))
    pop = arr.data[rows, cols].astype("float64")
    table = pa.table(
        {
            "lat": t.f + (rows + 0.5) * t.e,
            "lng": t.c + (cols + 0.5) * t.a,
            "pop": pop,
        }
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, out, compression="zstd")
    total = float(arr.sum(dtype="float64"))  # includes zero pixels; same total
    log.info("population: %s populated pixels, total %s", f"{len(pop):,}", f"{total:,.0f}")
    return total


def run(cfg: Config, force: bool = False) -> list[Path]:
    resolutions = cfg.h3.resolutions
    for r in resolutions:
        if not grid.output_path(cfg, r).exists():
            raise FileNotFoundError(f"grid res {r} missing; run `kh-atlas grid` first")
    url = worldpop_url(cfg)
    tif = raw_path(cfg)
    pixels = pixels_path(cfg)
    outs = [output_path(cfg, r) for r in resolutions]
    previews = [cfg.paths.interim / "qgis" / f"population_res{r}.gpkg" for r in resolutions]
    inputs = {
        "worldpop_url": url,
        "grid": manifest.load(cfg).get("stages", {}).get("grid", {}).get("inputs"),
    }
    if not force and manifest.is_fresh(cfg, "population", [*outs, *previews], inputs):
        log.info("population: cached")
        return [*outs, *previews]

    tif, digest = download(url, tif, force=force)
    source_total = raster_to_pixels(tif, pixels)

    con = db.connect(cfg)
    rows: dict[str, int | float] = {"source_total": round(source_total)}
    for res, out, preview in zip(resolutions, outs, previews, strict=True):
        con.execute(
            db.read_sql(
                "population", res=res, pixels=pixels, grid=grid.output_path(cfg, res), out=out
            )
        )
        n, n_pop, total, max_pop = con.execute(
            f"SELECT count(*), count(*) FILTER (WHERE population > 0), sum(population),"
            f" max(population) FROM '{out}'"
        ).fetchone()
        diff = (total - source_total) / source_total
        log.info(
            "population res %d: %s cells (%s populated), total %s (%+.3f%% vs raster), max %s",
            res,
            f"{n:,}",
            f"{n_pop:,}",
            f"{total:,.0f}",
            diff * 100,
            f"{max_pop:,.0f}",
        )
        if abs(diff) > TOLERANCE:
            raise AssertionError(
                f"res {res}: hex total {total:,.0f} differs from raster {source_total:,.0f}"
                f" by {diff:+.2%} (limit ±{TOLERANCE:.0%})"
            )
        rows[f"res{res}_cells_populated"] = n_pop
        rows[f"res{res}_total"] = round(total)
        db.write_gpkg(
            con,
            "SELECT h3_str, population, n_pixels,"
            " ST_GeomFromText(h3_cell_to_boundary_wkt(h3)) AS geometry"
            f" FROM '{out}' WHERE population > 0",
            preview,
            f"population_res{res}",
        )

    manifest.update(
        cfg,
        downloads={
            **manifest.load(cfg).get("downloads", {}),
            "worldpop": {"url": url, "path": str(tif), "sha256": digest},
        },
    )
    manifest.record_stage(
        cfg, "population", rows=rows, outputs=[tif, pixels, *outs, *previews], inputs=inputs
    )
    return [*outs, *previews]
