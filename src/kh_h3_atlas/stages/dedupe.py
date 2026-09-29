"""Stage 6: merge POI sources, collapse cross-source duplicates."""

from __future__ import annotations

import logging
from pathlib import Path

from kh_h3_atlas.config import Config

log = logging.getLogger(__name__)


def enabled_sources(cfg: Config) -> list[str]:
    return [s for s, on in cfg.poi.use.items() if on]


def run(cfg: Config, force: bool = False) -> list[Path]:
    sources = enabled_sources(cfg)
    if len(sources) < 2:
        log.info("dedupe: only one POI source enabled (%s); nothing to merge", ", ".join(sources))
        return []
    raise NotImplementedError("dedupe stage (multiple POI sources): planned for Milestone 6")
