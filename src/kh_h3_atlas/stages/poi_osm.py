"""Stage 4a: POIs from the Geofabrik OSM extract, clipped and H3-indexed."""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

from kh_h3_atlas import db, manifest
from kh_h3_atlas.config import Config
from kh_h3_atlas.download import download
from kh_h3_atlas.sources import GEOFABRIK_BASE, list_osm_snapshots, pick_osm_snapshot
from kh_h3_atlas.stages import poi_common

log = logging.getLogger(__name__)

# Tag keys that make a feature a POI, in priority order: the first key present sets the
# category (e.g. a pharmacy tagged amenity=pharmacy + healthcare=pharmacy -> amenity=pharmacy).
POI_KEYS = [
    "amenity",
    "healthcare",
    "shop",
    "office",
    "tourism",
    "leisure",
    "craft",
    "historic",
    "emergency",
    "public_transport",
    "railway",
    "aeroway",
]
# Street furniture and infrastructure, not places people visit.
EXCLUDED = [
    "amenity=parking",
    "amenity=parking_space",
    "amenity=parking_entrance",
    "amenity=bench",
    "amenity=waste_basket",
    "amenity=waste_disposal",
    "amenity=recycling",
    "amenity=bicycle_parking",
    "amenity=motorcycle_parking",
    "amenity=drinking_water",
    "amenity=fire_hydrant",
    "amenity=shelter",
    "amenity=water_point",
    "amenity=vending_machine",
    "emergency=fire_hydrant",
    "emergency=yes",
    "leisure=pitch",
    "leisure=garden",
    "leisure=swimming_pool",
    "leisure=nature_reserve",
    "railway=rail",
    "railway=abandoned",
    "railway=level_crossing",
    "railway=crossing",
    "railway=switch",
    "railway=buffer_stop",
    "aeroway=runway",
    "aeroway=taxiway",
    "aeroway=apron",
    "public_transport=platform",
    "public_transport=stop_position",
    "historic=yes",
    # airport internals and linear-infrastructure markers
    "aeroway=parking_position",
    "aeroway=jet_bridge",
    "aeroway=holding_position",
    "aeroway=gate",
    "aeroway=hangar",
    "aeroway=helipad",
    "railway=milestone",
    # street furniture
    "amenity=toilets",
    "amenity=fountain",
    "amenity=post_box",
    "amenity=telephone",
    "amenity=shower",
    "leisure=outdoor_seating",
    "leisure=fitness_station",
    "tourism=information",
    "shop=vacant",
]


def category_expr() -> str:
    whens = " ".join(f"WHEN tags['{k}'] IS NOT NULL THEN '{k}=' || tags['{k}']" for k in POI_KEYS)
    return f"CASE {whens} END"


def snapshot(cfg: Config) -> str:
    osm = cfg.sources.osm
    if osm.snapshot != "auto":
        return osm.snapshot
    for s in manifest.load(cfg).get("sources", []):
        if s["name"].startswith("OpenStreetMap"):
            return datetime.fromisoformat(s["snapshot_date"]).strftime("%y%m%d")
    return pick_osm_snapshot(list_osm_snapshots(osm.region_path), cfg.reference_date)[1]


def run(cfg: Config, force: bool = False) -> list[Path]:
    osm = cfg.sources.osm
    stamp = snapshot(cfg)
    region = osm.region_path.rsplit("/", 1)[-1]
    url = f"{GEOFABRIK_BASE}/{osm.region_path}-{stamp}.osm.pbf"
    pbf = cfg.paths.raw / "osm" / stamp / f"{region}-{stamp}.osm.pbf"
    outs = [poi_common.output_path(cfg, "osm"), poi_common.preview_path(cfg, "osm")]
    inputs = {
        "osm_url": url,
        "poi_keys": POI_KEYS,
        "excluded": EXCLUDED,
        "resolutions": poi_common.index_resolutions(cfg),
        "grid": manifest.load(cfg).get("stages", {}).get("grid", {}).get("inputs"),
    }
    if not force and manifest.is_fresh(cfg, "poi_osm", outs, inputs):
        log.info("poi_osm: cached")
        return outs

    pbf, digest = download(url, pbf)
    manifest.update(
        cfg,
        downloads={
            **manifest.load(cfg).get("downloads", {}),
            "osm": {"url": url, "path": str(pbf), "sha256": digest},
        },
    )
    con = db.connect(cfg)
    con.execute(
        db.read_sql(
            "poi_osm_stage",
            pbf=pbf,
            category_expr=category_expr(),
            excluded=", ".join(f"'{c}'" for c in EXCLUDED),
        )
    )
    return poi_common.clip_and_write(cfg, con, "osm", inputs, [pbf])
