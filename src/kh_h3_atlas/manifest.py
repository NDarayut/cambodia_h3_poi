"""Run manifest: records sources, config hash, per-stage row counts, package versions."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from kh_h3_atlas.config import Config

PACKAGES = ["kh-h3-atlas", "duckdb", "h3", "rasterio", "pyarrow", "pydantic"]


def manifest_path(cfg: Config) -> Path:
    return cfg.paths.processed / "manifest.json"


def load(cfg: Config) -> dict:
    p = manifest_path(cfg)
    return json.loads(p.read_text()) if p.exists() else {}


def save(cfg: Config, m: dict) -> None:
    p = manifest_path(cfg)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(m, indent=2, default=str))


def _versions() -> dict[str, str | None]:
    out = {}
    for pkg in PACKAGES:
        try:
            out[pkg] = version(pkg)
        except PackageNotFoundError:
            out[pkg] = None
    return out


def update(cfg: Config, **fields: object) -> dict:
    """Merge top-level fields into the manifest and stamp run metadata."""
    m = load(cfg)
    m.update(fields)
    m["reference_date"] = cfg.reference_date.isoformat()
    m["config_hash"] = cfg.hash()
    m["updated_at"] = datetime.now(UTC).isoformat(timespec="seconds")
    m["packages"] = _versions()
    save(cfg, m)
    return m


def record_stage(
    cfg: Config,
    stage: str,
    rows: dict[str, int],
    outputs: list[Path],
    inputs: dict | None = None,
) -> None:
    m = load(cfg)
    stages = m.setdefault("stages", {})
    stages[stage] = {
        "inputs": inputs or {},
        "rows": rows,
        "outputs": [str(p) for p in outputs],
        "finished_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    update(cfg, stages=stages)


def is_fresh(cfg: Config, stage: str, outputs: list[Path], inputs: dict) -> bool:
    """True if all outputs exist and were built from the same inputs."""
    rec = load(cfg).get("stages", {}).get(stage)
    return bool(rec) and rec.get("inputs") == inputs and all(p.exists() for p in outputs)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()
