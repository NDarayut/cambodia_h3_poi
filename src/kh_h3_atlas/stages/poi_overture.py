"""Stage 4b: POIs from Overture places, clipped and H3-indexed.

Overture's places schema uses `taxonomy` (primary + hierarchy) and `basic_category`; the
`categories` column named in the original brief no longer exists.
"""

from __future__ import annotations

import logging
from pathlib import Path

from kh_h3_atlas import db, manifest
from kh_h3_atlas.config import Config
from kh_h3_atlas.sources import overture_release
from kh_h3_atlas.stages import poi_common

log = logging.getLogger(__name__)


def raw_path(cfg: Config, release: str) -> Path:
    return cfg.paths.raw / "overture" / release / "place.parquet"


def run(cfg: Config, force: bool = False) -> list[Path]:
    release = overture_release(cfg)
    raw = raw_path(cfg, release)
    outs = [poi_common.output_path(cfg, "overture"), poi_common.preview_path(cfg, "overture")]
    inputs = {
        "overture_release": release,
        "min_confidence": cfg.poi.min_confidence,
        "resolutions": poi_common.index_resolutions(cfg),
        "grid": manifest.load(cfg).get("stages", {}).get("grid", {}).get("inputs"),
    }
    if not force and manifest.is_fresh(cfg, "poi_overture", outs, inputs):
        log.info("poi_overture: cached")
        return outs

    con = db.connect(cfg)
    if force or not raw.exists():
        raw.parent.mkdir(parents=True, exist_ok=True)
        src = f"s3://{cfg.sources.overture.s3_bucket}/release/{release}/theme=places/type=place/*"
        log.info("poi_overture: extracting bbox from %s", src)
        con.execute(db.read_sql("poi_overture_raw", src=src, out=raw, **cfg.bbox.model_dump()))
    con.execute(db.read_sql("poi_overture_stage", raw=raw, min_confidence=cfg.poi.min_confidence))
    return poi_common.clip_and_write(cfg, con, "overture", inputs, [raw])
