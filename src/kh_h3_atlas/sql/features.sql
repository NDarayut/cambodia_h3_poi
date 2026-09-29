-- Hex-level feature table for one resolution. Every grid cell gets a row.
CREATE OR REPLACE TEMP TABLE pois AS
SELECT h3_res{res} AS h3, category, coalesce({group_case}, 'other') AS grp
FROM ({poi_union});

CREATE OR REPLACE TEMP TABLE base AS
WITH cell_poi AS (
    SELECT h3, count(*) AS n_poi, {group_counts}
    FROM pois GROUP BY h3
),
cat AS (
    SELECT h3, category, count(*) AS c, sum(count(*)) OVER (PARTITION BY h3) AS tot
    FROM pois GROUP BY h3, category
),
entropy AS (
    -- Shannon entropy (bits) of raw categories in the cell: 0 = one type only
    SELECT h3, greatest(-sum((c / tot) * log2(c / tot)), 0) AS poi_category_entropy
    FROM cat GROUP BY h3
)
SELECT g.h3, g.h3_str, g.lat, g.lng,
       coalesce(p.population, 0) AS population,
       coalesce(cp.n_poi, 0)::INTEGER AS n_poi,
       {group_cols},
       e.poi_category_entropy
FROM read_parquet('{grid}') g
LEFT JOIN read_parquet('{population}') p USING (h3)
LEFT JOIN cell_poi cp USING (h3)
LEFT JOIN entropy e USING (h3);

COPY (
    SELECT b.*,
           CASE WHEN b.population > 0 THEN b.n_poi * 1000.0 / b.population END AS poi_per_1k_pop,
           {neighbour_cols},
           (b.population >= {gap_min_pop} AND b.n_poi = 0) AS data_gap
    FROM base b
    {neighbour_joins}
    ORDER BY b.h3
) TO '{out}' (FORMAT parquet, COMPRESSION zstd);
