-- Clip staged POIs to Cambodia and index to H3.
-- 1) fast: keep points whose cell is in the grid (grid includes border/coastal cells)
-- 2) exact: of those, keep points inside the country polygon (drops TH/VN/LA points that
--    fall in border cells). Doing (1) first keeps the expensive test to ~10% of points.
COPY (
    WITH ingrid AS (
        SELECT s.*
        FROM staged s
        JOIN read_parquet('{grid}') g ON g.h3 = h3_latlng_to_cell(s.lat, s.lng, {grid_res})
    ),
    inside AS (
        SELECT DISTINCT i.source_id
        FROM ingrid i
        JOIN read_parquet('{boundary}') b
          ON ST_Intersects(ST_Point(i.lng, i.lat)::GEOMETRY('OGC:CRS84'), b.geometry)
    )
    SELECT source, source_id, name, name_en, category, category_hierarchy, confidence,
           lat, lng, {h3_cols}, attrs
    FROM ingrid
    WHERE source_id IN (SELECT source_id FROM inside)
    ORDER BY source_id
) TO '{out}' (FORMAT parquet, COMPRESSION zstd);
