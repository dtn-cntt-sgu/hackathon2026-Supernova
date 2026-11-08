# Versioned database upgrades

Install `requirements.txt`. Configure `DATABASE_URL` explicitly in the deployment environment; never put credentials in `alembic.ini` or command arguments. From the repository root:

```sh
python -m alembic current
python -m alembic upgrade head
python -m alembic current
```

From another directory, pass `-c /absolute/path/to/repository/alembic.ini`; its module and migration paths resolve from the configuration file. The environment's `DATABASE_URL` still determines the target database. Review it privately before executing an upgrade. The deployment account needs extension/schema/index/constraint permissions; the ordinary runtime account should not have those privileges.

Revision `20261108_01` initializes PostGIS before tables and adopts an existing unversioned schema without replacing tables. Revision `20261108_02` adds missing legacy columns, the two daily bulletin tables, model indexes, foreign keys and the scheduler retry index. Revision `20261108_03` creates the read-only camera/road-edge candidate view required on a clean database. The frozen schema is intentionally independent of current application model imports so that future model changes cannot silently alter old revisions. No camera is granted new permissions; old missing permission fields become nullable/unverified.

Missing required fields on populated tables, incompatible primary keys, duplicate unique keys or orphaned references stop the transaction for manual remediation. The migration does not fabricate values or delete conflicting records. Review large-index lock/disk requirements on a restored copy before a production maintenance window. Legacy type/nullable conversions and any future schema changes need explicit reviewed revisions.

## Backup and rollout

Do not run production migrations without an approved maintenance window and a verified backup. For the production Compose stack, save an encrypted/restricted backup outside the repository:

```sh
docker compose -f docker-compose.prod.yml exec -T postgis \
  sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --format=custom' > /secure/backup/safepath-pre-upgrade.dump
```

Verify this dump by restoring it into a **separate scratch database/container** using `pg_restore --no-owner --no-acl --exit-on-error`, then run `python -m alembic upgrade head` against that scratch `DATABASE_URL`. Validate row counts, permission distributions, camera foreign keys, hydrology provenance and representative route queries. Preserve the pre-upgrade image digests and exact revision list. Never use `--clean` against the active database as a smoke test.

In staging/production, `init_db()` only checks the Alembic revision and performs no DDL. Run the explicit migration job before starting the app. Development/test bootstrap remains available for compatibility; it is not an upgrade path for deployed schemas.

## Rollback

These upgrades are additive. Prefer rolling back application images while retaining the added schema/data. Automated destructive `alembic downgrade` is intentionally blocked. If a schema rollback is necessary, stop writers and restore the verified pre-upgrade dump into a **new database**, validate it, then switch the application's secret/configuration to that database. Preserve the failed upgraded database for investigation. A backup restoration loses writes made after the backup; decide how to reconcile them before cutover. Never drop existing tables or permit unverified camera evidence to make rollback pass.

## Tests and inspection

```sh
python -m pytest backend/tests/test_database_migrations.py -q
```

Tests use uniquely named disposable PostGIS databases. They cover a fresh install, a pre-permission/pre-bulletin schema with retained rows, a copy of the real local catalog and registry entry, required-field failure rollback, repeated upgrade, staging/production startup without implicit DDL, frozen/current column agreement and required indexes/foreign keys. The test role must be allowed to create/drop its own disposable databases.

Read-only inspection of the local running database found all current model tables/columns present, no Alembic version table, and two missing `camera_snapshots` indexes (`fetched_at`, `snapshot_id`). The migration repairs these on the disposable copy. No migration was applied to the existing running database or production.

Reference: [Alembic tutorial](https://alembic.sqlalchemy.org/en/latest/tutorial.html), [Alembic cookbook](https://alembic.sqlalchemy.org/en/latest/cookbook.html).
