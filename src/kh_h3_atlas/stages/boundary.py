"""Stage 1: Cambodia land polygon(s) from Overture divisions, exploded into parts."""

from __future__ import annotations

import logging
from pathlib import Path

from kh_h3_atlas import db, manifest
from kh_h3_atlas.config import Config
from kh_h3_atlas.sources import overture_release

log = logging.getLogger(__name__)

UTM = "EPSG:32648"  # UTM 48N covers Cambodia; used for areas and buffers in metres
# Sanity range for Cambodia's land area (official ~181,035 km²)
AREA_RANGE_KM2 = (170_000, 190_000)


def raw_path(cfg: Config, release: str) -> Path:
    return cfg.paths.raw / "overture" / release / "division_area.parquet"


def output_path(cfg: Config) -> Path:
    return cfg.paths.interim / "boundary.parquet"


def run(cfg: Config, force: bool = False) -> list[Path]:
    release = overture_release(cfg)
    raw, out = raw_path(cfg, release), output_path(cfg)
    preview = cfg.paths.interim / "qgis" / "boundary.gpkg"
    inputs = {"overture_release": release}
    if not force and manifest.is_fresh(cfg, "boundary", [out, preview], inputs):
        log.info("boundary: cached (%s)", out)
        return [out, preview]

    con = db.connect(cfg)
    if force or not raw.exists():
        raw.parent.mkdir(parents=True, exist_ok=True)
        src = (
            f"s3://{cfg.sources.overture.s3_bucket}/release/{release}"
            "/theme=divisions/type=division_area/*"
        )
        log.info("boundary: extracting %s divisions from %s", cfg.country_iso2, src)
        con.execute(
            db.read_sql(
                "boundary_raw", src=src, iso2=cfg.country_iso2, out=raw, **cfg.bbox.model_dump()
            )
        )

    out.parent.mkdir(parents=True, exist_ok=True)
    con.execute(db.read_sql("boundary_parts", raw=raw, utm=UTM, out=out))

    n_parts, area, n_raw = con.execute(
        f"SELECT count(*), sum(area_km2), (SELECT count(*) FROM '{raw}') FROM '{out}'"
    ).fetchone()
    if n_parts == 0:
        raise AssertionError(f"No {cfg.country_iso2} country land polygon in release {release}")
    lo, hi = AREA_RANGE_KM2
    if not lo <= area <= hi:
        raise AssertionError(f"Boundary area {area:,.0f} km² outside expected {lo:,}-{hi:,}")
    log.info("boundary: %d parts, %.0f km² (%d raw division rows)", n_parts, area, n_raw)

    db.write_gpkg(con, f"SELECT * FROM '{out}'", preview, "boundary")
    manifest.record_stage(
        cfg,
        "boundary",
        rows={"parts": n_parts, "area_km2": round(area), "raw_division_rows": n_raw},
        outputs=[raw, out, preview],
        inputs=inputs,
    )
    return [raw, out, preview]
