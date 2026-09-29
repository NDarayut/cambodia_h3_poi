import duckdb
import numpy as np
import pyarrow.parquet as pq
import rasterio
from rasterio.transform import from_origin

from kh_h3_atlas.db import read_sql
from kh_h3_atlas.stages.population import raster_to_pixels


def _tif(path, arr, nodata=-99999.0):
    t = from_origin(104.90, 11.60, 1 / 1200, 1 / 1200)  # ~100 m pixels near Phnom Penh
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=arr.shape[1],
        height=arr.shape[0],
        count=1,
        dtype="float32",
        crs="EPSG:4326",
        transform=t,
        nodata=nodata,
    ) as dst:
        dst.write(arr.astype("float32"), 1)


def test_pixels_conserve_total_and_skip_nodata(tmp_path):
    rng = np.random.default_rng(0)
    arr = rng.uniform(0, 50, (40, 40))
    arr[:5, :5] = -99999.0  # nodata
    _tif(tmp_path / "p.tif", arr)
    total = raster_to_pixels(tmp_path / "p.tif", tmp_path / "px.parquet")
    expected = arr[arr >= 0].sum()
    assert np.isclose(total, expected)
    t = pq.read_table(tmp_path / "px.parquet")
    assert t.num_rows == (arr > 0).sum()
    assert np.isclose(t["pop"].to_numpy().sum(), expected)


def test_hex_sum_conserves_total_at_each_res(tmp_path):
    rng = np.random.default_rng(1)
    arr = rng.uniform(0, 50, (60, 60))
    _tif(tmp_path / "p.tif", arr)
    total = raster_to_pixels(tmp_path / "p.tif", tmp_path / "px.parquet")
    con = duckdb.connect()
    con.execute("INSTALL h3 FROM community; LOAD h3; INSTALL spatial; LOAD spatial;")
    px = tmp_path / "px.parquet"
    for res in (7, 8):
        grid = tmp_path / f"grid{res}.parquet"
        con.execute(
            f"COPY (SELECT DISTINCT h3_latlng_to_cell(lat, lng, {res})::UBIGINT AS h3,"
            f" h3_h3_to_string(h3_latlng_to_cell(lat, lng, {res})) AS h3_str FROM '{px}')"
            f" TO '{grid}' (FORMAT parquet)"
        )
        out = tmp_path / f"pop{res}.parquet"
        con.execute(read_sql("population", res=res, pixels=px, grid=grid, out=out))
        assert np.isclose(con.execute(f"SELECT sum(population) FROM '{out}'").fetchone()[0], total)
    # H3 nesting is approximate: pixels assigned directly at res 7 do NOT exactly equal
    # res-8 children summed to parents, but the national total is identical either way.
    t7, t8 = (
        con.execute(f"SELECT sum(population) FROM '{tmp_path / f'pop{r}.parquet'}'").fetchone()[0]
        for r in (7, 8)
    )
    assert np.isclose(t7, t8)
