"""Explicit schema upgrades, configured from DATABASE_URL without logging credentials."""
from alembic import context
from sqlalchemy import create_engine, pool

from backend.app.core.config import settings
from backend.app.db.models import Base
from backend.app.db.community_models import CommunityIncident  # register migration metadata


def run(connection):
    # Never propose dropping PostGIS/internal/importer/archive tables during autogeneration.
    def include_object(obj, name, kind, reflected, compare_to):
        return not (kind == "table" and reflected and compare_to is None)

    context.configure(connection=connection, target_metadata=Base.metadata, compare_type=True,
                      include_object=include_object)
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    raise RuntimeError("Use an online database: legacy reconciliation requires schema inspection")
elif context.config.attributes.get("connection") is not None:
    run(context.config.attributes["connection"])
else:
    engine = create_engine(settings.sync_database_url, poolclass=pool.NullPool)
    with engine.connect() as connection:
        run(connection)
    engine.dispose()
