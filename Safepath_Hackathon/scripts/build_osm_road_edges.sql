\set ON_ERROR_STOP on
BEGIN;

-- edge_index is the 1-based vertex-pair position inside the original OSM Way.
-- It is a local edge key, never an OSM identifier or an OSRM edge identifier.
CREATE TABLE IF NOT EXISTS road_edges (
    osm_way_id bigint NOT NULL REFERENCES road_segments(osm_way_id) ON DELETE CASCADE,
    edge_index integer NOT NULL CHECK (edge_index > 0),
    geom geometry(LineString,4326) NOT NULL,
    length_meters double precision NOT NULL CHECK (length_meters > 0),
    PRIMARY KEY (osm_way_id, edge_index)
);
ALTER TABLE road_edges ADD COLUMN IF NOT EXISTS source_node_id bigint;
ALTER TABLE road_edges ADD COLUMN IF NOT EXISTS target_node_id bigint;
-- An edge rebuild invalidates camera edge references via ON DELETE SET NULL.
DELETE FROM road_edges;

INSERT INTO road_edges (osm_way_id, edge_index, geom, length_meters, source_node_id, target_node_id)
SELECT r.osm_way_id, (d.path)[1], d.geom, ST_Length(d.geom::geography),
       CASE WHEN jsonb_array_length(r.osm_node_ids) = ST_NPoints(r.geom)
            THEN (r.osm_node_ids->>((d.path)[1]-1))::bigint END,
       CASE WHEN jsonb_array_length(r.osm_node_ids) = ST_NPoints(r.geom)
            THEN (r.osm_node_ids->>((d.path)[1]))::bigint END
FROM road_segments r
CROSS JOIN LATERAL ST_DumpSegments(r.geom) AS d
WHERE r.source_url IS NOT NULL AND ST_Length(d.geom::geography) > 0;
CREATE INDEX IF NOT EXISTS idx_road_edges_nodes ON road_edges
    (LEAST(source_node_id,target_node_id),GREATEST(source_node_id,target_node_id));

CREATE INDEX IF NOT EXISTS idx_road_edges_geom ON road_edges USING gist (geom);
CREATE INDEX IF NOT EXISTS idx_road_edges_geog ON road_edges USING gist ((geom::geography));
CREATE INDEX IF NOT EXISTS idx_road_edges_length ON road_edges (length_meters);

ALTER TABLE traffic_cameras ADD COLUMN IF NOT EXISTS observed_edge_index integer;
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'traffic_cameras_observed_edge_fk') THEN
        ALTER TABLE traffic_cameras ADD CONSTRAINT traffic_cameras_observed_edge_fk
            FOREIGN KEY (observed_osm_way_id, observed_edge_index)
            REFERENCES road_edges(osm_way_id, edge_index) ON DELETE SET NULL;
    END IF;
END $$;

CREATE OR REPLACE VIEW camera_road_spatial_candidates AS
SELECT c.cam_id, e.osm_way_id,
       ST_Distance(c.geom::geography, e.geom::geography) AS distance_meters,
       CASE WHEN c.observed_osm_way_id = e.osm_way_id
                 AND c.observed_edge_index = e.edge_index
                 AND c.view_verified_at IS NOT NULL
                 AND c.view_verification_source_url IS NOT NULL
                 AND c.line_of_sight_verified IS TRUE
                 AND c.bearing_degrees IS NOT NULL
                 AND c.field_of_view_degrees IS NOT NULL
            THEN 'OBSERVED_SEGMENT_VERIFIED'
            ELSE 'SPATIALLY_NEAR' END AS match_status,
       e.edge_index
FROM traffic_cameras c
JOIN road_edges e ON c.geom IS NOT NULL
    AND c.coordinate_source_url IS NOT NULL
    AND c.coordinate_verified_at IS NOT NULL
    AND ST_DWithin(c.geom::geography, e.geom::geography, 80);

COMMIT;
