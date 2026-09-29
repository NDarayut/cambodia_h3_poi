"""Resolve every data source to a dated snapshot aligned to `reference_date`.

Rule: each source uses its latest snapshot ON OR BEFORE the reference date, so no layer
contains data newer than the others. Listing functions hit the network; the `pick_*`
functions are pure and unit-tested.
"""

from __future__ import annotations

import logging
import re
import time
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from datetime import date, datetime

from kh_h3_atlas import manifest
from kh_h3_atlas.config import Config

log = logging.getLogger(__name__)

OVERTURE_DOCS = "https://docs.overturemaps.org/"
GEOFABRIK_BASE = "https://download.geofabrik.de"
WORLDPOP_BASE = "https://data.worldpop.org/GIS/Population/Global_2015_2030"

_RELEASE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})\.(\d+)$")
_OSM_RE = re.compile(r"(\w+)-(\d{6})\.osm\.pbf")


@dataclass
class ResolvedSource:
    name: str
    provides: str
    snapshot: str  # release / file identifier
    snapshot_date: date
    url: str
    license: str
    lag_days: int

    def to_dict(self) -> dict:
        d = asdict(self)
        d["snapshot_date"] = self.snapshot_date.isoformat()
        return d


def _get(url: str, attempts: int = 3) -> str:
    for i in range(attempts):
        try:
            with urllib.request.urlopen(url, timeout=30) as r:
                return r.read().decode()
        except OSError as e:  # URLError, TimeoutError, connection resets
            if i == attempts - 1:
                raise
            log.warning("fetch failed (%s), retrying: %s", e, url)
            time.sleep(2 * (i + 1))
    raise AssertionError("unreachable")


def _cached(cfg: Config, source: str) -> list[str]:
    """Snapshot directory names already downloaded under data/raw/<source>/."""
    d = cfg.paths.raw / source
    return sorted(p.name for p in d.iterdir() if p.is_dir()) if d.exists() else []


def _listing_or_cache(cfg: Config, source: str, fetch, parse_cached):
    """Online listing; if the index is unreachable, fall back to cached raw snapshots."""
    try:
        return fetch()
    except OSError as e:
        cached = parse_cached(_cached(cfg, source))
        if not cached:
            raise
        log.warning("%s index unreachable (%s); using cached snapshots: %s", source, e, cached)
        return cached


# --- Overture ---------------------------------------------------------------------------


def list_overture_releases(bucket: str, region: str) -> list[str]:
    """List release prefixes (e.g. '2026-09-23.1') via anonymous S3 ListObjectsV2."""
    ns = {"s3": "http://s3.amazonaws.com/doc/2006-03-01/"}
    base = f"https://{bucket}.s3.{region}.amazonaws.com/?list-type=2&prefix=release/&delimiter=/"
    releases, token = [], None
    while True:
        url = base + (f"&continuation-token={urllib.request.quote(token)}" if token else "")
        root = ET.fromstring(_get(url))
        for p in root.findall("s3:CommonPrefixes/s3:Prefix", ns):
            name = p.text.removeprefix("release/").strip("/")
            if _RELEASE_RE.match(name):
                releases.append(name)
        if root.findtext("s3:IsTruncated", namespaces=ns) != "true":
            return releases
        token = root.findtext("s3:NextContinuationToken", namespaces=ns)


def pick_overture_release(releases: list[str], ref: date) -> str:
    """Latest release dated on/before `ref`; highest patch number wins within a date."""
    candidates = []
    for r in releases:
        m = _RELEASE_RE.match(r)
        if m and date.fromisoformat(m[1]) <= ref:
            candidates.append((date.fromisoformat(m[1]), int(m[2]), r))
    if not candidates:
        raise LookupError(
            f"No Overture release on/before {ref}. Available: {sorted(releases)}. "
            "Overture keeps releases ~60 days; pin a cached release or move reference_date."
        )
    return max(candidates)[2]


def overture_release_date(release: str) -> date:
    return date.fromisoformat(release.split(".")[0])


# --- OSM (Geofabrik) --------------------------------------------------------------------


def list_osm_snapshots(region_path: str) -> dict[date, str]:
    """Dated extracts listed on the Geofabrik region page, e.g. cambodia-260923.osm.pbf."""
    html = _get(f"{GEOFABRIK_BASE}/{region_path}.html")
    out = {}
    for _, stamp in set(_OSM_RE.findall(html)):
        out[datetime.strptime(stamp, "%y%m%d").date()] = stamp
    return out


def pick_osm_snapshot(snapshots: dict[date, str], ref: date) -> tuple[date, str]:
    eligible = [d for d in snapshots if d <= ref]
    if not eligible:
        raise LookupError(f"No Geofabrik snapshot on/before {ref}. Available: {sorted(snapshots)}")
    d = max(eligible)
    return d, snapshots[d]


# --- WorldPop ---------------------------------------------------------------------------


def worldpop_url(cfg: Config) -> str:
    wp = cfg.sources.worldpop
    iso3, year = cfg.country_iso3, cfg.worldpop_year
    kind, tag = ("constrained", "CN") if wp.constrained else ("unconstrained", "UC")
    fname = f"{iso3.lower()}_pop_{year}_{tag}_{wp.resolution}_{wp.release}_{wp.version}.tif"
    return f"{WORLDPOP_BASE}/{wp.release}/{year}/{iso3}/{wp.version}/{wp.resolution}/{kind}/{fname}"


# --- All sources ------------------------------------------------------------------------


def resolve_sources(cfg: Config) -> list[ResolvedSource]:
    ref = cfg.reference_date
    ov = cfg.sources.overture
    out: list[ResolvedSource] = []

    rel = ov.release
    if rel == "auto":
        releases = _listing_or_cache(
            cfg,
            "overture",
            lambda: list_overture_releases(ov.s3_bucket, ov.s3_region),
            lambda names: [n for n in names if _RELEASE_RE.match(n)],
        )
        rel = pick_overture_release(releases, ref)
    s3 = f"s3://{ov.s3_bucket}/release/{rel}"
    rel_date = overture_release_date(rel)
    out.append(
        ResolvedSource(
            "Overture divisions",
            "country boundary, admin areas",
            rel,
            rel_date,
            f"{s3}/theme=divisions/type=division_area/",
            "ODbL",
            (ref - rel_date).days,
        )
    )
    if cfg.poi.use.get("overture"):
        out.append(
            ResolvedSource(
                "Overture places",
                "POIs",
                rel,
                rel_date,
                f"{s3}/theme=places/type=place/",
                "CDLA-Permissive-2.0 / Apache-2.0 / CC0 (per source)",
                (ref - rel_date).days,
            )
        )

    if cfg.poi.use.get("osm"):
        osm = cfg.sources.osm
        if osm.snapshot == "auto":
            snapshots = _listing_or_cache(
                cfg,
                "osm",
                lambda: list_osm_snapshots(osm.region_path),
                lambda names: {
                    datetime.strptime(n, "%y%m%d").date(): n
                    for n in names
                    if re.fullmatch(r"\d{6}", n)
                },
            )
            snap_date, stamp = pick_osm_snapshot(snapshots, ref)
        else:
            stamp = osm.snapshot
            snap_date = datetime.strptime(stamp, "%y%m%d").date()
        region = osm.region_path.rsplit("/", 1)[-1]
        out.append(
            ResolvedSource(
                "OpenStreetMap (Geofabrik)",
                "POIs",
                f"{region}-{stamp}.osm.pbf",
                snap_date,
                f"{GEOFABRIK_BASE}/{osm.region_path}-{stamp}.osm.pbf",
                "ODbL",
                (ref - snap_date).days,
            )
        )

    # WorldPop is a modelled estimate FOR a year, not a dated snapshot: use mid-year.
    wp_date = date(cfg.worldpop_year, 7, 1)
    out.append(
        ResolvedSource(
            "WorldPop",
            f"population ({cfg.sources.worldpop.resolution} raster)",
            f"{cfg.sources.worldpop.release} {cfg.worldpop_year}",
            wp_date,
            worldpop_url(cfg),
            "CC BY 4.0",
            (ref - wp_date).days,
        )
    )

    if cfg.worldpop_year != ref.year:
        log.warning(
            "WorldPop year %d differs from reference_date year %d", cfg.worldpop_year, ref.year
        )
    for s in out:
        if s.name != "WorldPop" and abs(s.lag_days) > cfg.max_source_lag_days:
            log.warning(
                "%s snapshot %s is %d days from reference_date %s",
                s.name,
                s.snapshot,
                s.lag_days,
                ref,
            )
    return out


def overture_release(cfg: Config) -> str:
    """Overture release for this run: pinned, else from the manifest, else resolved online."""
    ov = cfg.sources.overture
    if ov.release != "auto":
        return ov.release
    m = manifest.load(cfg)
    if m.get("reference_date") == cfg.reference_date.isoformat():
        for s in m.get("sources", []):
            if s["name"].startswith("Overture"):
                return s["snapshot"]
    resolved = resolve_sources(cfg)
    manifest.update(cfg, sources=[s.to_dict() for s in resolved])
    return next(s.snapshot for s in resolved if s.name.startswith("Overture"))
