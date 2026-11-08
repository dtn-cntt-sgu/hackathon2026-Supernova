\set ON_ERROR_STOP on
BEGIN;

ALTER TABLE road_segments ADD COLUMN IF NOT EXISTS osm_node_ids jsonb;
ALTER TABLE road_segments ADD COLUMN IF NOT EXISTS highway text;
ALTER TABLE road_segments ADD COLUMN IF NOT EXISTS access text;
ALTER TABLE road_segments ADD COLUMN IF NOT EXISTS oneway text;
ALTER TABLE road_segments ADD COLUMN IF NOT EXISTS bridge text;
ALTER TABLE road_segments ADD COLUMN IF NOT EXISTS tunnel text;
ALTER TABLE road_segments ADD COLUMN IF NOT EXISTS length_meters double precision;
ALTER TABLE road_segments ADD COLUMN IF NOT EXISTS osm_extract_at timestamptz;
ALTER TABLE road_segments ADD COLUMN IF NOT EXISTS source_url text;
ALTER TABLE road_segments ADD COLUMN IF NOT EXISTS source_license text;
ALTER TABLE road_segments ADD COLUMN IF NOT EXISTS source_pbf_md5 text;
ALTER TABLE road_segments ADD COLUMN IF NOT EXISTS imported_at timestamptz;
ALTER TABLE road_segments ALTER COLUMN is_flood_prone_history DROP NOT NULL;
ALTER TABLE road_segments ALTER COLUMN is_flood_prone_history DROP DEFAULT;

-- Retain any pre-existing rows without OSM provenance for audit, never route on them.
CREATE TABLE IF NOT EXISTS road_segments_unverified_archive
    (LIKE road_segments INCLUDING DEFAULTS INCLUDING CONSTRAINTS INCLUDING INDEXES);
ALTER TABLE road_segments_unverified_archive ADD COLUMN IF NOT EXISTS osm_node_ids jsonb;
INSERT INTO road_segments_unverified_archive
    (osm_way_id,street_name,is_flood_prone_history,geom,highway,access,oneway,bridge,tunnel,
     length_meters,osm_extract_at,source_url,source_license,source_pbf_md5,imported_at,osm_node_ids)
SELECT osm_way_id,street_name,is_flood_prone_history,geom,highway,access,oneway,bridge,tunnel,
     length_meters,osm_extract_at,source_url,source_license,source_pbf_md5,imported_at,osm_node_ids
FROM road_segments WHERE source_url IS NULL
ON CONFLICT DO NOTHING;
DELETE FROM road_segments WHERE source_url IS NULL;

INSERT INTO road_segments
    (osm_way_id, street_name, is_flood_prone_history, geom, highway, access,
     oneway, bridge, tunnel, length_meters, osm_extract_at, source_url,
     source_license, source_pbf_md5, imported_at, osm_node_ids)
SELECT way_id, left(street_name, 255), NULL, geom, highway, access,
       oneway, bridge, tunnel, ST_Length(geom::geography), :'extract_timestamp'::timestamptz,
       'https://download.geofabrik.de/asia/vietnam-latest.osm.pbf',
       'ODbL-1.0, OpenStreetMap contributors', :'pbf_md5', now(), osm_node_ids
FROM osm_import_roads
WHERE geom && ST_MakeEnvelope(106.30, 10.35, 107.10, 11.20, 4326)
  AND ST_Intersects(geom, ST_MakeEnvelope(106.30, 10.35, 107.10, 11.20, 4326))
  AND ST_IsValid(geom) AND ST_NPoints(geom) >= 2 AND ST_Length(geom::geography) > 0
ON CONFLICT (osm_way_id) DO UPDATE SET
    street_name = excluded.street_name, geom = excluded.geom,
    is_flood_prone_history = NULL,
    highway = excluded.highway, access = excluded.access, oneway = excluded.oneway,
    bridge = excluded.bridge, tunnel = excluded.tunnel,
    length_meters = excluded.length_meters, osm_extract_at = excluded.osm_extract_at,
    source_url = excluded.source_url, source_license = excluded.source_license,
    source_pbf_md5 = excluded.source_pbf_md5, imported_at = excluded.imported_at,
    osm_node_ids = excluded.osm_node_ids;

CREATE INDEX IF NOT EXISTS idx_road_segments_geom ON road_segments USING gist (geom);
CREATE INDEX IF NOT EXISTS idx_road_segments_geog ON road_segments USING gist ((geom::geography));
CREATE INDEX IF NOT EXISTS idx_road_segments_highway ON road_segments (highway);

ALTER TABLE traffic_cameras ADD COLUMN IF NOT EXISTS coordinate_source_url text;
ALTER TABLE traffic_cameras ADD COLUMN IF NOT EXISTS coordinate_verified_at timestamptz;
ALTER TABLE traffic_cameras ADD COLUMN IF NOT EXISTS bearing_degrees double precision;
ALTER TABLE traffic_cameras ADD COLUMN IF NOT EXISTS field_of_view_degrees double precision;
ALTER TABLE traffic_cameras ADD COLUMN IF NOT EXISTS view_verified_at timestamptz;
ALTER TABLE traffic_cameras ADD COLUMN IF NOT EXISTS view_verification_source_url text;
ALTER TABLE traffic_cameras ADD COLUMN IF NOT EXISTS line_of_sight_verified boolean;
ALTER TABLE traffic_cameras ADD COLUMN IF NOT EXISTS observed_osm_way_id bigint
    REFERENCES road_segments(osm_way_id) ON DELETE SET NULL;
ALTER TABLE traffic_cameras ALTER COLUMN geom DROP NOT NULL;
CREATE TABLE IF NOT EXISTS traffic_camera_unverified_location_archive (
    cam_id varchar(64) PRIMARY KEY,
    previous_geom geometry(Point,4326),
    archived_at timestamptz NOT NULL DEFAULT now()
);
INSERT INTO traffic_camera_unverified_location_archive (cam_id, previous_geom)
SELECT cam_id, geom FROM traffic_cameras
WHERE geom IS NOT NULL AND (coordinate_source_url IS NULL OR coordinate_verified_at IS NULL)
ON CONFLICT (cam_id) DO NOTHING;
UPDATE traffic_cameras SET geom = NULL
WHERE geom IS NOT NULL AND (coordinate_source_url IS NULL OR coordinate_verified_at IS NULL);
UPDATE traffic_cameras SET nearest_osm_way_id = NULL
WHERE coordinate_source_url IS NULL OR coordinate_verified_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_traffic_cameras_verified_geog
    ON traffic_cameras USING gist ((geom::geography))
    WHERE geom IS NOT NULL AND coordinate_source_url IS NOT NULL AND coordinate_verified_at IS NOT NULL;

CREATE OR REPLACE VIEW camera_road_spatial_candidates AS
SELECT c.cam_id, r.osm_way_id,
       ST_Distance(c.geom::geography, r.geom::geography) AS distance_meters,
       CASE WHEN c.observed_osm_way_id = r.osm_way_id
                 AND c.view_verified_at IS NOT NULL
                 AND c.view_verification_source_url IS NOT NULL
                 AND c.line_of_sight_verified IS TRUE
                 AND c.bearing_degrees IS NOT NULL
                 AND c.field_of_view_degrees IS NOT NULL
            THEN 'OBSERVED_SEGMENT_VERIFIED'
            ELSE 'SPATIALLY_NEAR' END AS match_status
FROM traffic_cameras c
JOIN road_segments r ON c.geom IS NOT NULL
    AND c.coordinate_source_url IS NOT NULL
    AND c.coordinate_verified_at IS NOT NULL
    AND r.source_url IS NOT NULL
    AND ST_DWithin(c.geom::geography, r.geom::geography, 80);

DROP TABLE osm_import_roads;

COMMIT;
