-- Raw extract of all division areas for the country (country, regions, counties, localities).
-- Cached locally so runs stay reproducible after the Overture release is removed from S3.
COPY (
    SELECT id, division_id, subtype, admin_level, class, country, region, names,
           is_land, is_territorial, sources, geometry
    FROM read_parquet('{src}', hive_partitioning = 1)
    WHERE country = '{iso2}'
      AND bbox.xmin < {xmax} AND bbox.xmax > {xmin}
      AND bbox.ymin < {ymax} AND bbox.ymax > {ymin}
) TO '{out}' (FORMAT parquet, COMPRESSION zstd);
