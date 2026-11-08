-- Run with psql -v route_wkt='LINESTRING(lon lat,...)' -f scripts/check_road_graph.sql.
-- Execute once per OSRM route. Nearby roads remain candidates, never verified IDs.
SELECT e.osm_way_id, e.edge_index, r.highway, r.access, r.oneway, r.bridge, r.tunnel,
       e.length_meters, r.osm_extract_at, r.source_url,
       ST_Distance(e.geom::geography,
           ST_SetSRID(ST_GeomFromText(:'route_wkt'),4326)::geography) AS distance_meters
FROM road_edges e JOIN road_segments r USING (osm_way_id)
WHERE r.source_url IS NOT NULL
  AND ST_DWithin(e.geom::geography,
      ST_SetSRID(ST_GeomFromText(:'route_wkt'),4326)::geography, 8)
ORDER BY distance_meters, e.osm_way_id, e.edge_index
LIMIT 30;

SELECT count(*) AS sourced_roads, min(osm_extract_at) AS extract_at,
       count(*) FILTER (WHERE length_meters <= 0 OR ST_SRID(geom) <> 4326) AS invalid
FROM road_segments WHERE source_url IS NOT NULL;

SELECT count(*) AS osm_edges, count(*) FILTER (WHERE length_meters <= 0) AS invalid_edges
FROM road_edges;

SELECT cam_id, osm_way_id, edge_index, round(distance_meters::numeric, 1), match_status
FROM camera_road_spatial_candidates LIMIT 30;
