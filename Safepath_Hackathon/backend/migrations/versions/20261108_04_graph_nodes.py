"""Preserve original OSM node identities; existing rows remain unverified until reimport."""
from alembic import op
revision = "20261108_04"
down_revision = "20261108_03"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE road_segments ADD COLUMN IF NOT EXISTS osm_node_ids jsonb")
    op.execute("ALTER TABLE road_edges ADD COLUMN IF NOT EXISTS source_node_id bigint")
    op.execute("ALTER TABLE road_edges ADD COLUMN IF NOT EXISTS target_node_id bigint")
    op.execute("CREATE INDEX IF NOT EXISTS idx_road_edges_nodes ON road_edges (LEAST(source_node_id,target_node_id), GREATEST(source_node_id,target_node_id))")


def downgrade():
    raise RuntimeError("Keep additive graph provenance on application rollback")
