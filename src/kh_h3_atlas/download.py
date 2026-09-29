"""Checksummed downloads into data/raw."""

from __future__ import annotations

import logging
import shutil
import urllib.request
from pathlib import Path

from kh_h3_atlas.manifest import sha256

log = logging.getLogger(__name__)


def download(url: str, dest: Path, force: bool = False) -> tuple[Path, str]:
    """Download `url` to `dest` (atomic via .part file); return (path, sha256)."""
    if dest.exists() and not force:
        return dest, sha256(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    log.info("downloading %s", url)
    with urllib.request.urlopen(url, timeout=60) as r, open(tmp, "wb") as f:
        shutil.copyfileobj(r, f, length=1 << 20)
    tmp.rename(dest)
    return dest, sha256(dest)
