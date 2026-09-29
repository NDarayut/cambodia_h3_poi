-- OSM nodes and ways carrying a POI tag -> common POI schema (table `staged`).
-- Way location = mean of its node coordinates (good enough for building/area POIs).
-- Relations (multipolygons) are skipped; they are rare for POIs.
CREATE OR REPLACE TEMP TABLE staged AS
WITH osm AS (
    SELECT * FROM ST_ReadOSM('{pbf}') WHERE kind IN ('node', 'way')
),
poi AS (
    SELECT kind, id, tags, refs, lat, lon, {category_expr} AS category
    FROM osm
    WHERE tags IS NOT NULL AND cardinality(tags) > 0
),
poi_f AS (
    SELECT * FROM poi WHERE category IS NOT NULL AND category NOT IN ({excluded})
),
way_xy AS (
    SELECT w.id, avg(n.lat) AS lat, avg(n.lon) AS lon
    FROM (SELECT id, unnest(refs) AS ref FROM poi_f WHERE kind = 'way') w
    JOIN osm n ON n.kind = 'node' AND n.id = w.ref
    GROUP BY w.id
)
SELECT 'osm' AS source,
       p.kind || '/' || p.id AS source_id,
       p.tags['name'] AS name,
       p.tags['name:en'] AS name_en,
       p.category,
       [split_part(p.category, '=', 1), p.category] AS category_hierarchy,
       NULL::DOUBLE AS confidence,
       coalesce(p.lat, w.lat) AS lat,
       coalesce(p.lon, w.lon) AS lng,
       to_json(p.tags)::VARCHAR AS attrs
FROM poi_f p
LEFT JOIN way_xy w ON p.kind = 'way' AND w.id = p.id
WHERE coalesce(p.lat, w.lat) IS NOT NULL;
