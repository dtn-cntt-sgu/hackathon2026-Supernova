"""Real PostGIS migration tests use disposable databases, never production fixtures."""
from pathlib import Path
from types import SimpleNamespace
import uuid

from alembic import command
from alembic.config import Config
import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine

from backend.app.db import community_models  # Registers additive tables even for isolated schema tests.
from backend.app.db.models import Base
from backend.app.db.session import check_schema_revision, sync_engine
from backend.migrations.schema_20261108 import metadata


ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def migration_db():
    name = "safepath_migration_test_" + uuid.uuid4().hex[:12]
    admin = sa.create_engine(sync_engine.url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        connection.execute(sa.text(f'CREATE DATABASE "{name}"'))
    engine = sa.create_engine(sync_engine.url.set(database=name))
    try:
        yield engine
    finally:
        engine.dispose()
        with admin.connect() as connection:
            connection.execute(sa.text(f'DROP DATABASE "{name}" WITH (FORCE)'))
        admin.dispose()


def upgrade(engine, target="head"):
    cfg = Config(str(ROOT / "alembic.ini"))
    with engine.begin() as connection:
        cfg.attributes["connection"] = connection
        command.upgrade(cfg, target)


def test_fresh_database_has_postgis_schema_indexes_and_revision(migration_db):
    upgrade(migration_db)
    inspector = sa.inspect(migration_db)
    assert set(Base.metadata.tables).issubset(inspector.get_table_names())
    for table in Base.metadata.sorted_tables:
        assert {column.name for column in table.columns} == {
            column["name"] for column in inspector.get_columns(table.name)
        }
        assert set(table.primary_key.columns.keys()) == set(
            inspector.get_pk_constraint(table.name)["constrained_columns"]
        )
        assert {index.name for index in table.indexes}.issubset(
            {index["name"] for index in inspector.get_indexes(table.name)}
        )
        actual_indexes = {index["name"]: index for index in inspector.get_indexes(table.name)}
        for index in table.indexes:
            assert actual_indexes[index.name]["unique"] == index.unique
        actual_foreign_keys = inspector.get_foreign_keys(table.name)
        for constraint in table.foreign_key_constraints:
            assert any(
                fk["constrained_columns"] == [element.parent.name for element in constraint.elements]
                and fk["referred_table"] == constraint.elements[0].column.table.name
                and fk["referred_columns"] == [element.column.name for element in constraint.elements]
                for fk in actual_foreign_keys
            )
    with migration_db.connect() as connection:
        assert connection.scalar(sa.text("SELECT postgis_version()"))
        check_schema_revision(connection)
    upgrade(migration_db)  # Repeated deployment must not duplicate objects.


def test_legacy_database_keeps_data_and_does_not_grant_permissions(migration_db):
    # Reconstruct a copy of the former unversioned schema, then simulate older columns.
    with migration_db.begin() as connection:
        connection.execute(sa.text("CREATE EXTENSION IF NOT EXISTS postgis"))
        metadata.create_all(connection)
        connection.execute(sa.text("DROP TABLE hydrology_bulletin_events"))
        connection.execute(sa.text("DROP TABLE hydrology_bulletins"))
        connection.execute(sa.text("ALTER TABLE traffic_cameras DROP COLUMN permitted_use"))
        connection.execute(sa.text("ALTER TABLE traffic_cameras DROP COLUMN view_verified_at"))
        connection.execute(sa.text("ALTER TABLE camera_ingestion_state DROP COLUMN last_source_captured_at"))
        foreign_key = next(fk for fk in sa.inspect(connection).get_foreign_keys("traffic_cameras")
                           if fk["constrained_columns"] == ["observed_osm_way_id"])
        connection.execute(sa.text(f'ALTER TABLE traffic_cameras DROP CONSTRAINT "{foreign_key["name"]}"'))
        connection.execute(sa.text("INSERT INTO traffic_cameras (cam_id, name) VALUES ('migration-camera', 'Existing camera')"))
    upgrade(migration_db)
    with migration_db.connect() as connection:
        row = connection.execute(sa.text("SELECT name, permitted_use, view_verified_at FROM traffic_cameras WHERE cam_id='migration-camera'")).one()
        assert tuple(row) == ("Existing camera", None, None)
        assert connection.scalar(sa.text("SELECT count(*) FROM hydrology_bulletin_events")) == 0
        check_schema_revision(connection)
    assert "last_source_captured_at" in {column["name"] for column in sa.inspect(migration_db).get_columns("camera_ingestion_state")}
    assert any(fk["constrained_columns"] == ["observed_osm_way_id"]
               for fk in sa.inspect(migration_db).get_foreign_keys("traffic_cameras"))


def test_missing_required_data_aborts_and_preserves_old_schema(migration_db):
    upgrade(migration_db, "20261108_01")
    with migration_db.begin() as connection:
        connection.execute(sa.text("ALTER TABLE traffic_cameras DROP COLUMN name"))
        connection.execute(sa.text("INSERT INTO traffic_cameras (cam_id) VALUES ('needs-manual-backfill')"))
    with pytest.raises(RuntimeError, match="Manual backfill required"):
        upgrade(migration_db)
    with migration_db.connect() as connection:
        assert connection.scalar(sa.text("SELECT count(*) FROM traffic_cameras")) == 1
        assert connection.scalar(sa.text("SELECT version_num FROM alembic_version")) == "20261108_01"


def test_deployed_schema_check_rejects_unversioned_and_outdated(migration_db):
    with migration_db.connect() as connection:
        with pytest.raises(RuntimeError, match="migrations required"):
            check_schema_revision(connection)
    upgrade(migration_db, "20261108_01")
    with migration_db.connect() as connection:
        with pytest.raises(RuntimeError, match="migrations required"):
            check_schema_revision(connection)
    upgrade(migration_db)
    with migration_db.connect() as connection:
        check_schema_revision(connection)


def test_frozen_schema_matches_current_application_columns():
    additive_columns = {"road_segments": {"osm_node_ids"},
                        "road_edges": {"source_node_id", "target_node_id"}}
    additive_tables = {"community_incidents"}
    assert set(Base.metadata.tables) == set(metadata.tables) | additive_tables
    for name, frozen in metadata.tables.items():
        assert set(Base.metadata.tables[name].columns.keys()) == set(frozen.columns.keys()) | additive_columns.get(name, set())


def test_upgrade_actual_catalog_copy_preserves_camera_permissions(migration_db):
    # Clone actual schema definitions and one public registry row into a disposable DB.
    copied = sa.MetaData()
    copied.reflect(sync_engine, only=list(metadata.tables))
    source = copied.tables["traffic_cameras"]
    with sync_engine.connect() as connection:
        camera = connection.execute(sa.select(source.c.cam_id, source.c.name, source.c.permitted_use).limit(1)).mappings().first()
    with migration_db.begin() as connection:
        connection.execute(sa.text("CREATE EXTENSION IF NOT EXISTS postgis"))
        copied.create_all(connection)
        if camera:
            connection.execute(source.insert().values(**dict(camera)))
        connection.execute(sa.text("DROP TABLE hydrology_bulletin_events"))
        connection.execute(sa.text("DROP TABLE hydrology_bulletins"))
    upgrade(migration_db)
    with migration_db.connect() as connection:
        check_schema_revision(connection)
        if camera:
            migrated = connection.execute(sa.select(source.c.cam_id, source.c.name, source.c.permitted_use)).mappings().one()
            assert dict(migrated) == dict(camera)
    snapshot_indexes = {index["name"] for index in sa.inspect(migration_db).get_indexes("camera_snapshots")}
    assert {"ix_camera_snapshots_fetched_at", "ix_camera_snapshots_snapshot_id"}.issubset(snapshot_indexes)


@pytest.mark.asyncio
@pytest.mark.parametrize("environment", ["staging", "production"])
async def test_deployed_startup_does_not_run_ddl(migration_db, monkeypatch, environment):
    import backend.app.db.session as sessions
    engine = create_async_engine(migration_db.url.set(drivername="postgresql+asyncpg"))
    monkeypatch.setattr(sessions, "async_engine", engine)
    monkeypatch.setattr(sessions, "settings", SimpleNamespace(APP_ENV=environment))
    try:
        with pytest.raises(RuntimeError, match="migrations required"):
            await sessions.init_db()
        assert sa.inspect(migration_db).get_table_names() == []
        upgrade(migration_db)
        before = set(sa.inspect(migration_db).get_table_names())
        await sessions.init_db()
        assert set(sa.inspect(migration_db).get_table_names()) == before
    finally:
        await engine.dispose()
