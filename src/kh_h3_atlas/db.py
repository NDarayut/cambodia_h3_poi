"""DuckDB connection factory with spatial, httpfs and h3 extensions loaded."""

from __future__ import annotations

from pathlib import Path

import duckdb

from kh_h3_atlas.config import Config

SQL_DIR = Path(__file__).parent / "sql"


def connect(cfg: Config, database: str = ":memory:") -> duckdb.DuckDBPyConnection:
    con = duckdb.connect(database)
    con.execute("INSTALL spatial; LOAD spatial;")
    con.execute("INSTALL httpfs; LOAD httpfs;")
    con.execute("INSTALL h3 FROM community; LOAD h3;")
    # Anonymous access to the public Overture bucket
    con.execute(
        f"CREATE OR REPLACE SECRET overture (TYPE s3, PROVIDER config, "
        f"REGION '{cfg.sources.overture.s3_region}')"
    )
    return con


def write_gpkg(con: duckdb.DuckDBPyConnection, query: str, path: Path, layer: str) -> None:
    """Write a query with a `geometry` column to a GeoPackage layer (for QGIS)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.unlink(missing_ok=True)
    con.execute(
        f"COPY ({query}) TO '{path}' "
        f"(FORMAT GDAL, DRIVER 'GPKG', SRS 'EPSG:4326', LAYER_NAME '{layer}')"
    )


def read_sql(name: str, **params: object) -> str:
    """Load sql/<name>.sql and substitute {placeholders} with trusted config values."""
    return (SQL_DIR / f"{name}.sql").read_text().format(**params)
