"""Local POI comparison app: export pipeline POIs + population as JSON, serve a static page.

The page (web/compare.html) loads a ground-truth file in the browser, assigns it to H3 cells
with h3-js, and compares it hex by hex with the pipeline's POIs. Nothing is uploaded anywhere.
"""

from __future__ import annotations

import contextlib
import functools
import http.server
import json
import logging
import shutil
from pathlib import Path

import duckdb

from kh_h3_atlas.categories import group_case_sql, load_groups
from kh_h3_atlas.config import Config
from kh_h3_atlas.stages import poi_common, population

log = logging.getLogger(__name__)

APP_SRC = Path(__file__).parent / "web" / "compare.html"


def app_dir(cfg: Config) -> Path:
    return cfg.paths.processed / "app"


def export(cfg: Config) -> Path:
    """Write index.html + data/*.json for the app; return the app directory."""
    res = max(cfg.h3.resolutions)
    out = app_dir(cfg)
    (out / "data").mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    groups = load_groups()
    case = group_case_sql(groups)

    pois, sources = [], []
    for source, enabled in cfg.poi.use.items():
        path = poi_common.output_path(cfg, source)
        if not enabled or not path.exists():
            continue
        sources.append(source)
        pois += con.execute(
            f"SELECT round(lat, 6), round(lng, 6), coalesce(name, name_en, ''), category,"
            f" coalesce({case}, 'other'), source_id, '{source}'"
            f" FROM '{path}' ORDER BY source_id"
        ).fetchall()
    if not pois:
        raise FileNotFoundError("no POI tables found; run `kh-atlas poi-osm` first")

    pop_path = population.output_path(cfg, res)
    pop = {}
    if pop_path.exists():
        pop = dict(
            con.execute(
                f"SELECT h3_str, round(population)::INT FROM '{pop_path}' WHERE population >= 1"
            ).fetchall()
        )

    meta = {
        "res": res,
        "reference_date": cfg.reference_date.isoformat(),
        "sources": sources,
        "groups": [*groups, "other"],
        "fields": ["lat", "lng", "name", "category", "group", "id", "source"],
    }
    (out / "data" / "pois.json").write_text(
        json.dumps({"meta": meta, "pois": pois}, ensure_ascii=False, separators=(",", ":"))
    )
    (out / "data" / "population.json").write_text(json.dumps(pop, separators=(",", ":")))
    shutil.copy(APP_SRC, out / "index.html")
    log.info("app: %s POIs, %s populated hexes -> %s", f"{len(pois):,}", f"{len(pop):,}", out)
    return out


def serve(directory: Path, port: int) -> None:
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(directory))
    with http.server.ThreadingHTTPServer(("127.0.0.1", port), handler) as httpd:
        print(f"POI comparison app: http://127.0.0.1:{port}/  (Ctrl+C to stop)")
        with contextlib.suppress(KeyboardInterrupt):
            httpd.serve_forever()
