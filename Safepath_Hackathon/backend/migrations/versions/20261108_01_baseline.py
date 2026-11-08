"""Adopt existing unversioned databases and initialize an empty PostGIS database."""
import sqlalchemy as sa
from alembic import op

from backend.migrations.schema_20261108 import metadata

revision = "20261108_01"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    connection = op.get_bind()
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")
    tables = [table for table in metadata.sorted_tables if not table.name.startswith("hydrology_bulletin")]
    # Existing tables are preserved; the next revision reconciles missing columns/indexes.
    metadata.create_all(connection, tables=tables, checkfirst=True)


def downgrade():
    raise RuntimeError("Baseline downgrade would destroy data; restore a verified backup instead")
