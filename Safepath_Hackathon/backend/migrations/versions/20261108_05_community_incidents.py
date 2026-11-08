"""Persist moderated reports. Schema frozen independently of current ORM models."""
from alembic import op
import sqlalchemy as sa

revision = "20261108_05"
down_revision = "20261108_04"
branch_labels = None
depends_on = None


def upgrade():
    if sa.inspect(op.get_bind()).has_table("community_incidents"):
        return
    op.create_table("community_incidents",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(64), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("incident_type", sa.String(16), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("lat", sa.Float(), nullable=False), sa.Column("lng", sa.Float(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("moderated_at", sa.DateTime(timezone=True)), sa.Column("moderation_note", sa.Text()),
        sa.Column("evidence_url", sa.String(1024)), sa.Column("osm_way_id", sa.BigInteger()), sa.Column("edge_index", sa.Integer()),
        sa.CheckConstraint("status IN ('PENDING','VERIFIED','REJECTED','EXPIRED')", name="ck_incident_status"),
        sa.CheckConstraint("incident_type IN ('FLOOD','ACCIDENT','BLOCKED','OTHER')", name="ck_incident_type"),
        sa.CheckConstraint("lat BETWEEN 10.3 AND 11.3 AND lng BETWEEN 106.2 AND 107.1", name="ck_incident_location"),
    )
    op.create_index("ix_incidents_user_created", "community_incidents", ["user_id", "created_at"])
    op.create_index("ix_incidents_status_expiry", "community_incidents", ["status", "expires_at"])


def downgrade():
    raise RuntimeError("Retain user reports on application rollback")
