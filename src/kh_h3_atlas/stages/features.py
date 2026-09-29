"""Stage 7: hex-level feature table per resolution.

One row per grid cell: population, POI counts (total + one column per category group),
POIs per 1k people, category entropy, neighbourhood sums over h3_grid_disk(k), data_gap flag.
"""

from __future__ import annotations

import logging
from pathlib import Path

import duckdb

from kh_h3_atlas import db, manifest
from kh_h3_atlas.categories import DEFAULT_CATEGORIES, group_case_sql, load_groups
from kh_h3_atlas.config import Config
from kh_h3_atlas.stages import grid, poi_common, population
from kh_h3_atlas.stages.dedupe import enabled_sources

log = logging.getLogger(__name__)

# Sanity check (logged, not fatal): the busiest hexes should be in these cities.
CITIES = {
    "Phnom Penh": (104.75, 105.05, 11.45, 11.70),
    "Siem Reap": (103.75, 103.95, 13.30, 13.45),
    "Sihanoukville": (103.45, 103.60, 10.58, 10.70),
    "Battambang": (103.15, 103.25, 13.05, 13.15),
    "Kampot": (104.14, 104.22, 10.57, 10.65),
}


def output_path(cfg: Config, res: int) -> Path:
    return cfg.paths.processed / f"features_res{res}.parquet"


def count_columns(groups: list[str]) -> list[str]:
    """Columns that get neighbourhood sums."""
    return ["population", "n_poi", *[f"n_{g}" for g in groups]]


def build_sql(cfg: Config, res: int, groups: dict[str, list[str]], out: Path) -> str:
    names = [*groups, "other"]
    poi_union = " UNION ALL ".join(
        f"SELECT h3_res{res}, category FROM read_parquet('{poi_common.output_path(cfg, s)}')"
        for s in enabled_sources(cfg)
    )
    group_counts = ", ".join(f"count(*) FILTER (WHERE grp = '{g}') AS n_{g}" for g in names)
    group_cols = ", ".join(f"coalesce(cp.n_{g}, 0)::INTEGER AS n_{g}" for g in names)

    sums = count_columns(names)
    neighbour_cols, neighbour_joins = [], []
    for k in cfg.features.neighborhood_k:
        neighbour_cols += [f"k{k}.{c}_k{k}" for c in sums]
        aggs = ", ".join(
            f"sum(nb.{c}){'' if c == 'population' else '::INTEGER'} AS {c}_k{k}" for c in sums
        )
        neighbour_joins.append(
            f"LEFT JOIN (SELECT d.h3, {aggs} FROM"
            f" (SELECT h3, unnest(h3_grid_disk(h3, {k})) AS nh FROM base) d"
            f" JOIN base nb ON nb.h3 = d.nh GROUP BY d.h3) k{k} USING (h3)"
        )
    return db.read_sql(
        "features",
        res=res,
        group_case=group_case_sql(groups),
        poi_union=poi_union,
        group_counts=group_counts,
        group_cols=group_cols,
        grid=grid.output_path(cfg, res),
        population=population.output_path(cfg, res),
        neighbour_cols=",\n           ".join(neighbour_cols) if neighbour_cols else "NULL AS no_k",
        neighbour_joins="\n    ".join(neighbour_joins),
        gap_min_pop=cfg.features.coverage_flag_min_pop,
        out=out,
    )


def check(con: duckdb.DuckDBPyConnection, cfg: Config, res: int, out: Path) -> dict:
    n, n_ids, pop, n_poi, gaps = con.execute(
        f"SELECT count(*), count(DISTINCT h3), sum(population), sum(n_poi),"
        f" count(*) FILTER (WHERE data_gap) FROM '{out}'"
    ).fetchone()
    n_grid = con.execute(f"SELECT count(*) FROM '{grid.output_path(cfg, res)}'").fetchone()[0]
    pop_src = con.execute(
        f"SELECT sum(population) FROM '{population.output_path(cfg, res)}'"
    ).fetchone()[0]
    poi_src = sum(
        con.execute(f"SELECT count(*) FROM '{poi_common.output_path(cfg, s)}'").fetchone()[0]
        for s in enabled_sources(cfg)
    )
    if n != n_ids:
        raise AssertionError(f"features res {res}: {n - n_ids} duplicate h3 keys")
    if n != n_grid:
        raise AssertionError(f"features res {res}: {n:,} rows but grid has {n_grid:,} cells")
    if abs(pop - pop_src) > 1:
        raise AssertionError(f"features res {res}: population {pop:,.0f} != source {pop_src:,.0f}")
    if n_poi != poi_src:
        raise AssertionError(
            f"features res {res}: n_poi sums to {n_poi:,}, POI tables have {poi_src:,}"
        )

    top = con.execute(
        f"SELECT lat, lng, n_poi FROM '{out}' ORDER BY n_poi DESC LIMIT 10"
    ).fetchall()
    where = []
    for lat, lng, _ in top:
        city = next(
            (c for c, (x0, x1, y0, y1) in CITIES.items() if x0 <= lng <= x1 and y0 <= lat <= y1),
            None,
        )
        where.append(city or f"elsewhere ({lat:.3f}, {lng:.3f})")
    outside = [w for w in where if w.startswith("elsewhere")]
    (log.warning if outside else log.info)(
        "features res %d: top-10 hexes by n_poi are in %s", res, ", ".join(sorted(set(where)))
    )
    log.info(
        "features res %d: %s hexes, population %s, %s POIs, %s data_gap hexes",
        res,
        f"{n:,}",
        f"{pop:,.0f}",
        f"{n_poi:,}",
        f"{gaps:,}",
    )
    return {f"res{res}_rows": n, f"res{res}_data_gap": gaps}


def run(cfg: Config, force: bool = False) -> list[Path]:
    sources = enabled_sources(cfg)
    for s in sources:
        if not poi_common.output_path(cfg, s).exists():
            raise FileNotFoundError(f"POIs for {s} missing; run `kh-atlas poi-{s}` first")
    groups = load_groups()
    resolutions = cfg.h3.resolutions
    outs = [output_path(cfg, r) for r in resolutions]
    stages = manifest.load(cfg).get("stages", {})
    inputs = {
        "groups": groups,
        "categories_file": str(DEFAULT_CATEGORIES),
        "features": cfg.features.model_dump(),
        "upstream": {
            s: stages.get(s, {}).get("inputs")
            for s in ["grid", "population", *[f"poi_{src}" for src in sources]]
        },
    }
    if not force and manifest.is_fresh(cfg, "features", outs, inputs):
        log.info("features: cached")
        return outs

    con = db.connect(cfg)
    rows: dict = {}
    for res, out in zip(resolutions, outs, strict=True):
        out.parent.mkdir(parents=True, exist_ok=True)
        con.execute(build_sql(cfg, res, groups, out))
        rows |= check(con, cfg, res, out)
    manifest.record_stage(cfg, "features", rows=rows, outputs=outs, inputs=inputs)
    return outs
