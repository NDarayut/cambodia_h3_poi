import duckdb
import h3
import pytest

from kh_h3_atlas.stages.grid import check, polyfill

# ~11 x 11 km square near Phnom Penh, plus a tiny "island" smaller than a res-8 cell
SQUARE = "POLYGON((104.85 11.50, 104.95 11.50, 104.95 11.60, 104.85 11.60, 104.85 11.50))"
ISLET = "POLYGON((104.704 11.300, 104.705 11.300, 104.705 11.301, 104.704 11.301, 104.704 11.300))"


@pytest.fixture
def con(tmp_path):
    c = duckdb.connect()
    c.execute("INSTALL h3 FROM community; LOAD h3; INSTALL spatial; LOAD spatial;")
    path = tmp_path / "boundary.parquet"
    c.execute(
        f"COPY (SELECT 1 AS part_id, ST_GeomFromText('{SQUARE}') AS geometry UNION ALL "
        f"SELECT 2, ST_GeomFromText('{ISLET}')) TO '{path}' (FORMAT parquet)"
    )
    return c, path


def _cells(c, out):
    return {r[0] for r in c.execute(f"SELECT h3_str FROM '{out}'").fetchall()}


def test_center_matches_h3py_and_drops_islet(con, tmp_path):
    c, bpath = con
    out = tmp_path / "g.parquet"
    polyfill(c, bpath, 8, "center", 0, out)
    ring = [
        (lat, lng) for lng, lat in [(104.85, 11.5), (104.95, 11.5), (104.95, 11.6), (104.85, 11.6)]
    ]
    islet = [(11.300, 104.704), (11.300, 104.705), (11.301, 104.705), (11.301, 104.704)]
    assert h3.polygon_to_cells(h3.LatLngPoly(islet), 8) == []  # no cell centre inside islet
    assert _cells(c, out) == set(h3.polygon_to_cells(h3.LatLngPoly(ring), 8))


def test_overlap_is_superset_and_keeps_islet(con, tmp_path):
    c, bpath = con
    center, overlap = tmp_path / "c.parquet", tmp_path / "o.parquet"
    polyfill(c, bpath, 8, "center", 0, center)
    polyfill(c, bpath, 8, "overlap", 0, overlap)
    assert _cells(c, center) < _cells(c, overlap)
    assert h3.latlng_to_cell(11.3005, 104.7045, 8) in _cells(c, overlap)


def test_check_rejects_duplicates(tmp_path):
    c = duckdb.connect()
    c.execute("INSTALL h3 FROM community; LOAD h3;")
    out = tmp_path / "dup.parquet"
    cell = h3.str_to_int(h3.latlng_to_cell(11.55, 104.9, 8))
    c.execute(f"COPY (SELECT {cell}::UBIGINT AS h3 FROM range(2)) TO '{out}' (FORMAT parquet)")
    with pytest.raises(AssertionError, match="duplicate"):
        check(c, out, 8, 1.0, "overlap")
