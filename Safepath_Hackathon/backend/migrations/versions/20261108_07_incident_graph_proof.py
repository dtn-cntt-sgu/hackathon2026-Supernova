"""Bind moderated incident attribution to the exact imported graph."""
from alembic import op
revision = "20261108_07"
down_revision = "20261108_06"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE community_incidents ADD COLUMN IF NOT EXISTS road_source_pbf_md5 varchar(32)")
    op.execute("ALTER TABLE community_incidents ADD COLUMN IF NOT EXISTS source_node_id bigint")
    op.execute("ALTER TABLE community_incidents ADD COLUMN IF NOT EXISTS target_node_id bigint")


def downgrade():
    raise RuntimeError("Keep additive graph proof on application rollback")
