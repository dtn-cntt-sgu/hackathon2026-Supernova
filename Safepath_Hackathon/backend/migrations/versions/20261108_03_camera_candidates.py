"""Create the read-only spatial candidate view on clean and adopted databases."""
from alembic import op
revision = "20261108_03"
down_revision = "20261108_02"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""CREATE OR REPLACE VIEW camera_road_spatial_candidates AS
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
""")


def downgrade():
    raise RuntimeError("Retain this additive view on application rollback; use a verified backup for schema rollback")
