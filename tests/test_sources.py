from datetime import date

import pytest

from kh_h3_atlas.config import load_config
from kh_h3_atlas.sources import pick_osm_snapshot, pick_overture_release, worldpop_url

RELEASES = ["2026-08-19.0", "2026-09-23.0", "2026-09-23.1", "not-a-release"]


def test_overture_picks_latest_patch_on_reference_date():
    assert pick_overture_release(RELEASES, date(2026, 9, 23)) == "2026-09-23.1"


def test_overture_never_picks_future_release():
    assert pick_overture_release(RELEASES, date(2026, 9, 22)) == "2026-08-19.0"


def test_overture_none_available():
    with pytest.raises(LookupError):
        pick_overture_release(RELEASES, date(2026, 1, 1))


def test_osm_picks_latest_on_or_before():
    snaps = {date(2026, 9, 1): "260901", date(2026, 9, 23): "260923", date(2026, 9, 28): "260928"}
    assert pick_osm_snapshot(snaps, date(2026, 9, 23)) == (date(2026, 9, 23), "260923")
    assert pick_osm_snapshot(snaps, date(2026, 9, 20)) == (date(2026, 9, 1), "260901")


def test_worldpop_url_matches_known_file():
    cfg = load_config("config/default.yaml")
    assert worldpop_url(cfg) == (
        "https://data.worldpop.org/GIS/Population/Global_2015_2030/R2025A/2026/KHM/v1/100m/"
        "constrained/khm_pop_2026_CN_100m_R2025A_v1.tif"
    )
