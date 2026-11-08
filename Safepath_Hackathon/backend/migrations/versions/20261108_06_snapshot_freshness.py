"""Allow the complete capture-unknown freshness status without truncating it."""
from alembic import op
revision = "20261108_06"
down_revision = "20261108_05"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE camera_snapshots ALTER COLUMN freshness_status TYPE varchar(64)")


def downgrade():
    raise RuntimeError("Retain the wider status column on rollback; shrinking may truncate saved metadata")
