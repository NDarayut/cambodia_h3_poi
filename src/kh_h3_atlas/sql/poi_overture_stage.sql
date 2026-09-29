-- Overture places -> common POI schema (table `staged`).
-- Keeps confidence >= threshold and drops places Overture marks as closed.
CREATE OR REPLACE TEMP TABLE staged AS
SELECT 'overture' AS source,
       id AS source_id,
       names.primary AS name,
       names.common['en'] AS name_en,
       taxonomy.primary AS category,
       taxonomy.hierarchy AS category_hierarchy,
       confidence,
       ST_Y(geometry) AS lat,
       ST_X(geometry) AS lng,
       to_json({{
           'basic_category': basic_category,
           'brand': brand.names.primary,
           'datasets': list_distinct(list_transform(sources, lambda s: s.dataset))
       }})::VARCHAR AS attrs
FROM read_parquet('{raw}')
WHERE confidence >= {min_confidence}
  AND coalesce(operating_status, 'open') = 'open'
  AND taxonomy.primary IS NOT NULL;
