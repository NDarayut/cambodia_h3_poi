-- Polyfill every boundary part at one resolution; union + dedupe across parts.
COPY (
    WITH parts AS (
        SELECT part_id, {geom_expr} AS g FROM read_parquet('{boundary}')
    ),
    cells AS (
        SELECT DISTINCT
            UNNEST(h3_polygon_wkt_to_cells_experimental(ST_AsText(g), {res}, '{mode}')) AS h3
        FROM parts
    )
    SELECT h3::UBIGINT AS h3,
           h3_h3_to_string(h3) AS h3_str,
           {res}::TINYINT AS res,
           h3_cell_to_lat(h3) AS lat,
           h3_cell_to_lng(h3) AS lng
    FROM cells
    ORDER BY h3
) TO '{out}' (FORMAT parquet);
