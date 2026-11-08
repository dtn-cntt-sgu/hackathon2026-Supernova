"""Add missing legacy evidence fields, daily bulletins and operational indexes safely."""
import sqlalchemy as sa
from alembic import op

from backend.migrations.schema_20261108 import metadata

revision = "20261108_02"
down_revision = "20261108_01"
branch_labels = None
depends_on = None


def upgrade():
    connection = op.get_bind()
    metadata.create_all(connection, checkfirst=True)
    for table in metadata.sorted_tables:
        inspector = sa.inspect(connection)
        actual = {column["name"] for column in inspector.get_columns(table.name)}
        for column in table.columns:
            if column.name in actual:
                continue
            if column.primary_key:
                raise RuntimeError(f"Manual review required: missing primary key {table.name}.{column.name}")
            if not column.nullable and column.server_default is None:
                populated = connection.scalar(sa.text(f'SELECT EXISTS (SELECT 1 FROM "{table.name}" LIMIT 1)'))
                if populated:
                    raise RuntimeError(f"Manual backfill required: {table.name}.{column.name}; no values were fabricated")
            # Foreign keys are reconciled below after every column exists.
            op.add_column(table.name, sa.Column(column.name, column.type, nullable=column.nullable,
                                                server_default=column.server_default))
        actual_pk = sa.inspect(connection).get_pk_constraint(table.name)["constrained_columns"]
        if actual_pk != [column.name for column in table.primary_key.columns]:
            raise RuntimeError(f"Manual review required: primary key differs on {table.name}")
        existing_indexes = {index["name"] for index in sa.inspect(connection).get_indexes(table.name)}
        for index in sorted(table.indexes, key=lambda value: value.name):
            if index.name not in existing_indexes:
                index.create(connection)
        foreign_keys = sa.inspect(connection).get_foreign_keys(table.name)
        for constraint in table.foreign_key_constraints:
            local = [element.parent.name for element in constraint.elements]
            remote = [element.column.name for element in constraint.elements]
            target = constraint.elements[0].column.table.name
            if any(fk["constrained_columns"] == local and fk["referred_table"] == target
                   and fk["referred_columns"] == remote for fk in foreign_keys):
                continue
            name = f"fk_{table.name}_{'_'.join(local)}"
            op.create_foreign_key(name[:63], table.name, target, local, remote, ondelete=constraint.ondelete)
    op.execute("CREATE INDEX IF NOT EXISTS ix_camera_ingestion_state_status_retry "
               "ON camera_ingestion_state (source_status, next_retry_at)")


def downgrade():
    raise RuntimeError("Additive evidence migration is retained on app rollback; restore backup for schema rollback")
