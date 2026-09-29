"""Stage 6: merge POI sources, collapse cross-source duplicates."""

from __future__ import annotations

from pathlib import Path

from kh_h3_atlas.config import Config


def run(cfg: Config, force: bool = False) -> list[Path]:
    raise NotImplementedError("dedupe stage: planned for Milestone 6")
