"""Stage 8: GeoPackage (QGIS), CSV, and a styled QGIS project.

The feature table itself (GeoParquet-ready Parquet) is written by the features stage. The
QGIS project is built with the system's PyQGIS (qgis_project.py runs under /usr/bin/python3,
not the uv environment); if PyQGIS is missing that step is skipped with a warning.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
from pathlib import Path

from kh_h3_atlas import db, manifest
from kh_h3_atlas.config import Config
from kh_h3_atlas.stages import features, poi_common
from kh_h3_atlas.stages.dedupe import enabled_sources

log = logging.getLogger(__name__)

QGIS_SCRIPT = Path(__file__).resolve().parents[1] / "qgis_project.py"
QGIS_PROJECT = Path("qgis/kh_atlas.qgz")
SYSTEM_PYTHON = "/usr/bin/python3"


def gpkg_path(cfg: Config, res: int) -> Path:
    return cfg.paths.processed / f"kh_atlas_res{res}.gpkg"


def csv_path(cfg: Config, res: int) -> Path:
    return cfg.paths.processed / f"features_res{res}.csv"


def build_qgis_project(cfg: Config, res: int, gpkg: Path, poi_gpkgs: list[Path]) -> Path | None:
    if not shutil.which(SYSTEM_PYTHON):
        log.warning("export: %s not found; skipping QGIS project", SYSTEM_PYTHON)
        return None
    probe = subprocess.run(
        [SYSTEM_PYTHON, "-c", "import qgis.core"], capture_output=True, text=True, check=False
    )
    if probe.returncode != 0:
        log.warning("export: PyQGIS not available (install QGIS); skipping QGIS project")
        return None
    QGIS_PROJECT.parent.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, "QT_QPA_PLATFORM": "offscreen"}
    cmd = [
        SYSTEM_PYTHON,
        str(QGIS_SCRIPT),
        str(QGIS_PROJECT.resolve()),
        str(gpkg.resolve()),
        f"features_res{res}",
        *[str(p.resolve()) for p in poi_gpkgs],
    ]
    r = subprocess.run(cmd, capture_output=True, text=True, env=env, check=False)
    if r.returncode != 0:
        raise RuntimeError(f"QGIS project build failed:\n{r.stdout}\n{r.stderr}")
    log.info(
        "export: %s", r.stdout.strip().splitlines()[-1] if r.stdout.strip() else "project built"
    )
    return QGIS_PROJECT


def run(cfg: Config, force: bool = False) -> list[Path]:
    resolutions = cfg.h3.resolutions
    res = max(resolutions)
    outs = [p for r in resolutions for p in (gpkg_path(cfg, r), csv_path(cfg, r))]
    if cfg.output.qgis_project:
        outs.append(QGIS_PROJECT)
    inputs = {
        "features": manifest.load(cfg).get("stages", {}).get("features", {}).get("finished_at"),
        "output": cfg.output.model_dump(),
    }
    if not force and manifest.is_fresh(cfg, "export", outs, inputs):
        log.info("export: cached")
        return outs

    con = db.connect(cfg)
    for r in resolutions:
        src = features.output_path(cfg, r)
        if not src.exists():
            raise FileNotFoundError(f"{src} missing; run `kh-atlas features` first")
        db.write_gpkg(
            con,
            f"SELECT * EXCLUDE (h3), ST_GeomFromText(h3_cell_to_boundary_wkt(h3)) AS geometry"
            f" FROM '{src}'",
            gpkg_path(cfg, r),
            f"features_res{r}",
        )
        con.execute(f"COPY (SELECT * EXCLUDE (h3) FROM '{src}') TO '{csv_path(cfg, r)}' (HEADER)")
        log.info("export: wrote %s and %s", gpkg_path(cfg, r), csv_path(cfg, r))

    written = [p for r in resolutions for p in (gpkg_path(cfg, r), csv_path(cfg, r))]
    if cfg.output.qgis_project:
        poi_gpkgs = [
            poi_common.preview_path(cfg, s)
            for s in enabled_sources(cfg)
            if poi_common.preview_path(cfg, s).exists()
        ]
        project = build_qgis_project(cfg, res, gpkg_path(cfg, res), poi_gpkgs)
        if project:
            written.append(project)
    manifest.record_stage(cfg, "export", rows={}, outputs=written, inputs=inputs)
    return written
