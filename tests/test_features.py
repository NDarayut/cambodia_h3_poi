import duckdb
import h3
import pytest

from kh_h3_atlas.config import load_config
from kh_h3_atlas.stages import features

CENTER = h3.latlng_to_cell(11.55, 104.92, 8)
RING = sorted(h3.grid_disk(CENTER, 1))


@pytest.fixture
def cfg(tmp_path):
    base = load_config("config/default.yaml")
    c = base.model_copy(deep=True)
    c.paths.interim = tmp_path / "interim"
    c.paths.processed = tmp_path / "processed"
    c.paths.interim.mkdir()
    c.poi.use = {"osm": True, "overture": False, "fsq": False}
    c.features.neighborhood_k = [1]
    c.features.coverage_flag_min_pop = 200
    con = duckdb.connect()
    con.execute("INSTALL h3 FROM community; LOAD h3;")
    cells = ", ".join(f"('{x}')" for x in RING)
    con.execute(
        f"COPY (SELECT h3_string_to_h3(s)::UBIGINT AS h3, s AS h3_str, 8::TINYINT AS res,"
        f" h3_cell_to_lat(h3_string_to_h3(s)) AS lat, h3_cell_to_lng(h3_string_to_h3(s)) AS lng"
        f" FROM (VALUES {cells}) t(s))"
        f" TO '{c.paths.interim / 'grid_res8.parquet'}' (FORMAT parquet)"
    )
    # centre: 1000 people; one neighbour: 300 people (no POIs -> data_gap); others 0
    other = next(x for x in RING if x != CENTER)
    con.execute(
        f"COPY (SELECT h3_string_to_h3(s)::UBIGINT AS h3, s AS h3_str,"
        f" CASE s WHEN '{CENTER}' THEN 1000 WHEN '{other}' THEN 300 ELSE 0 END::DOUBLE"
        " AS population,"
        f" 0 AS n_pixels FROM (VALUES {cells}) t(s))"
        f" TO '{c.paths.interim / 'population_res8.parquet'}' (FORMAT parquet)"
    )
    # centre: 2 pharmacies + 1 school
    pois = [(CENTER, "amenity=pharmacy"), (CENTER, "amenity=pharmacy"), (CENTER, "amenity=school")]
    rows = ", ".join(f"('{x}', '{cat}')" for x, cat in pois)
    con.execute(
        f"COPY (SELECT h3_string_to_h3(s)::UBIGINT AS h3_res8, cat AS category"
        f" FROM (VALUES {rows}) t(s, cat)) TO '{c.paths.interim / 'poi_osm.parquet'}'"
        " (FORMAT parquet)"
    )
    return c, other


def test_counts_neighbours_entropy_and_gap(cfg):
    c, other = cfg
    out = c.paths.processed / "f.parquet"
    out.parent.mkdir()
    con = duckdb.connect()
    con.execute("INSTALL h3 FROM community; LOAD h3;")
    from kh_h3_atlas.categories import load_groups

    con.execute(features.build_sql(c, 8, load_groups("config/poi_categories.yaml"), out))
    rows = {
        r[0]: r[1:]
        for r in con.execute(
            f"SELECT h3_str, n_poi, n_health, n_education, poi_per_1k_pop, poi_category_entropy,"
            f" n_health_k1, population_k1, data_gap FROM '{out}'"
        ).fetchall()
    }
    assert len(rows) == 7
    n_poi, n_health, n_edu, per1k, entropy, health_k1, pop_k1, gap = rows[CENTER]
    assert (n_poi, n_health, n_edu) == (3, 2, 1)
    assert per1k == pytest.approx(3.0)
    # 2 of one category, 1 of another: H = -(2/3 log2 2/3 + 1/3 log2 1/3) ≈ 0.918 bits
    assert entropy == pytest.approx(0.9183, abs=1e-3)
    assert health_k1 == 2 and pop_k1 == pytest.approx(1300)
    assert gap is False
    # neighbour: 300 people, no POIs -> gap; sees the centre's POIs within k=1
    assert rows[other][0] == 0 and rows[other][7] is True
    assert rows[other][5] == 2
    assert rows[other][4] is None  # entropy undefined without POIs
