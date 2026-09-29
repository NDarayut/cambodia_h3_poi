-- Country land polygon exploded into parts (mainland + islands), largest first.
COPY (
    WITH country AS (
        SELECT geometry FROM read_parquet('{raw}')
        WHERE subtype = 'country' AND class = 'land'
    ),
    parts AS (
        SELECT UNNEST(ST_Dump(geometry), recursive := true) FROM country
    )
    SELECT row_number() OVER (ORDER BY ST_Area(geom) DESC)::INTEGER AS part_id,
           ST_Area(ST_Transform(geom, 'OGC:CRS84', '{utm}')) / 1e6 AS area_km2,
           geom AS geometry
    FROM parts
    ORDER BY part_id
) TO '{out}' (FORMAT parquet);
