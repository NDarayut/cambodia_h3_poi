-- Raw extract of all Overture places in the bbox (no confidence filter), cached locally.
COPY (
    SELECT id, names, confidence, operating_status, basic_category, taxonomy, brand,
           addresses, sources, geometry
    FROM read_parquet('{src}')
    WHERE bbox.xmin < {xmax} AND bbox.xmax > {xmin}
      AND bbox.ymin < {ymax} AND bbox.ymax > {ymin}
) TO '{out}' (FORMAT parquet, COMPRESSION zstd);
