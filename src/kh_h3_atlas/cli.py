"""kh-atlas CLI: one command per stage, plus `sources` and `run-all`."""

from __future__ import annotations

import logging
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Annotated

import typer

from kh_h3_atlas import manifest
from kh_h3_atlas.config import DEFAULT_CONFIG, Config, load_config
from kh_h3_atlas.sources import resolve_sources
from kh_h3_atlas.stages import (
    boundary,
    dedupe,
    export,
    features,
    grid,
    poi_fsq,
    poi_osm,
    poi_overture,
    population,
)

app = typer.Typer(no_args_is_help=True, help="Cambodia H3 + POI atlas pipeline.")
state: dict[str, Config] = {}

ConfigOpt = Annotated[Path, typer.Option("--config", "-c", help="YAML config file.")]
ForceOpt = Annotated[bool, typer.Option("--force", help="Rebuild even if output is cached.")]


@app.callback()
def main(config: ConfigOpt = DEFAULT_CONFIG, verbose: bool = False) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    state["cfg"] = load_config(config)


def _cfg() -> Config:
    return state["cfg"]


@app.command()
def sources() -> None:
    """Resolve each source to a snapshot aligned with reference_date; show where it comes from."""
    cfg = _cfg()
    resolved = resolve_sources(cfg)
    typer.echo(f"reference_date: {cfg.reference_date}\n")
    for s in resolved:
        typer.echo(f"{s.name}  [{s.provides}]")
        when = (
            f"annual estimate for {s.snapshot_date.year}"
            if s.name == "WorldPop"
            else f"{s.snapshot_date}, {s.lag_days:+d} days"
        )
        typer.echo(f"  snapshot : {s.snapshot}  ({when})")
        typer.echo(f"  url      : {s.url}")
        typer.echo(f"  license  : {s.license}\n")
    manifest.update(cfg, sources=[s.to_dict() for s in resolved])


def _stage(name: str, fn: Callable[[Config, bool], list[Path]]) -> None:
    def cmd(force: ForceOpt = False) -> None:
        outputs = fn(_cfg(), force)
        for p in outputs:
            typer.echo(f"wrote {p}")

    cmd.__doc__ = sys.modules[fn.__module__].__doc__
    app.command(name)(cmd)


STAGES: list[tuple[str, Callable[[Config, bool], list[Path]]]] = [
    ("boundary", boundary.run),
    ("grid", grid.run),
    ("population", population.run),
    ("poi-osm", poi_osm.run),
    ("poi-overture", poi_overture.run),
    ("poi-fsq", poi_fsq.run),
    ("dedupe", dedupe.run),
    ("features", features.run),
    ("export", export.run),
]
OPTIONAL = {"poi-osm": "osm", "poi-overture": "overture", "poi-fsq": "fsq"}

for _name, _fn in STAGES:
    _stage(_name, _fn)


@app.command("explore-categories")
def explore_categories(top: int = 200) -> None:
    """Print the most common POI categories per source (seeds poi_categories.yaml).

    Also writes the full counts to data/interim/categories_<source>.csv.
    """
    import duckdb

    from kh_h3_atlas.stages import poi_common

    cfg = _cfg()
    con = duckdb.connect()
    for source in ("osm", "overture", "fsq"):
        path = poi_common.output_path(cfg, source)
        if not cfg.poi.use.get(source) or not path.exists():
            continue
        csv = cfg.paths.interim / f"categories_{source}.csv"
        # Top of the hierarchy: OSM key (amenity, shop, ...) or Overture top-level group
        con.execute(
            f"COPY (SELECT category_hierarchy[1] AS top_level, category, count(*) AS n"
            f" FROM '{path}' GROUP BY ALL ORDER BY n DESC, category) TO '{csv}' (HEADER)"
        )
        total = con.execute(f"SELECT count(*) FROM '{path}'").fetchone()[0]
        typer.echo(f"\n=== {source}: {total:,} POIs; full list in {csv}")
        typer.echo("-- by top level")
        for lvl, n in con.execute(
            f"SELECT top_level, sum(n)::INT FROM '{csv}' GROUP BY 1 ORDER BY 2 DESC"
        ).fetchall():
            typer.echo(f"{n:>8,}  {lvl}")
        typer.echo(f"-- top {top} categories")
        for lvl, cat, n in con.execute(f"SELECT * FROM '{csv}' LIMIT {top}").fetchall():
            typer.echo(f"{n:>8,}  {cat}  [{lvl}]")


@app.command("app")
def compare_app(
    port: int = 8765,
    serve: Annotated[bool, typer.Option(help="Start a local web server.")] = True,
) -> None:
    """Open the POI comparison app: hexagons + our POIs vs your ground-truth file."""
    from kh_h3_atlas import app as poi_app

    out = poi_app.export(_cfg())
    typer.echo(f"app files in {out}")
    if serve:
        poi_app.serve(out, port)


@app.command("run-all")
def run_all(force: ForceOpt = False) -> None:
    """Resolve sources, then run every enabled stage in order."""
    cfg = _cfg()
    sources()
    for name, fn in STAGES:
        if name in OPTIONAL and not cfg.poi.use.get(OPTIONAL[name]):
            typer.echo(f"skip {name} (disabled in config)")
            continue
        typer.echo(f"== {name}")
        try:
            fn(cfg, force)
        except NotImplementedError as e:
            typer.echo(f"stop: {e} (all earlier stages finished)")
            return


if __name__ == "__main__":
    app()
