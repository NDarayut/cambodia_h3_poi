"""Stage 5 (optional): Foursquare OS Places, same schema as other POI sources."""

from __future__ import annotations

from pathlib import Path

from kh_h3_atlas.config import Config


def run(cfg: Config, force: bool = False) -> list[Path]:
    raise NotImplementedError("poi_fsq stage: planned for Milestone 6")
