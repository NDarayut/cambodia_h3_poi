import duckdb
import pytest

from kh_h3_atlas.categories import group_case_sql, load_groups


def _classify(groups, categories):
    con = duckdb.connect()
    values = ", ".join(f"({c!r})" for c in categories)
    sql = f"SELECT category, {group_case_sql(groups)} FROM (VALUES {values}) t(category)"
    return dict(con.execute(sql).fetchall())


def test_first_match_wins_and_wildcards():
    groups = {
        "health": ["amenity=pharmacy", "healthcare=*"],
        "retail": ["amenity=marketplace", "shop=*"],
    }
    got = _classify(
        groups,
        ["amenity=pharmacy", "healthcare=yes", "shop=clothes", "amenity=bench", "shopx=1"],
    )
    assert got == {
        "amenity=pharmacy": "health",
        "healthcare=yes": "health",
        "shop=clothes": "retail",
        "amenity=bench": None,
        "shopx=1": None,  # prefix match is on "shop=", not "shop"
    }


def test_group_order_decides_overlap():
    both = {"a": ["shop=*"], "b": ["shop=chemist"]}
    assert _classify(both, ["shop=chemist"])["shop=chemist"] == "a"


def test_default_config_is_valid_and_retail_is_last():
    groups = load_groups("config/poi_categories.yaml")
    assert list(groups)[-1] == "retail"
    assert {"health", "education", "finance", "religious"} <= set(groups)


def test_bad_pattern_rejected(tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text("groups:\n  health:\n    osm: ['hospital']\n")
    with pytest.raises(ValueError, match="bad OSM pattern"):
        load_groups(p)
