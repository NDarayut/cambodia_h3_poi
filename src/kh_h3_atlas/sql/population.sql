-- Sum WorldPop pixel populations into H3 cells, then left-join onto the grid so every
-- grid cell gets a value (0 where the constrained raster has no people).
COPY (
    WITH hex AS (
        SELECT h3_latlng_to_cell(lat, lng, {res}) AS h3,
               sum(pop) AS population,
               count(*) AS n_pixels
        FROM read_parquet('{pixels}')
        GROUP BY 1
    )
    SELECT g.h3,
           g.h3_str,
           coalesce(hex.population, 0)::DOUBLE AS population,
           coalesce(hex.n_pixels, 0)::INTEGER AS n_pixels
    FROM read_parquet('{grid}') g
    LEFT JOIN hex USING (h3)
    ORDER BY g.h3
) TO '{out}' (FORMAT parquet);
