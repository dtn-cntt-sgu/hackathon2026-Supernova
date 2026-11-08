# SafePath production deployment guide

Status: operator runbook, **not an authorization or record of production deployment**. The independent `docker-compose.prod.yml` must never be combined with development Compose. Never use the development database password or published dependency ports on a server.

## Prerequisites and capacity

Use Linux with Docker Engine/Compose, a real DNS hostname, inbound TCP 80/443, working outbound HTTPS and a protected secret store. Default memory limits total approximately 7.75 GiB; provision additional host/OS headroom (at least 12 GiB is a starting capacity estimate, not a load-test result). The local 3.8 GiB Docker VM cannot run this production resource budget. Tune capacity after representative staging load testing.

Required private environment values:

```dotenv
PUBLIC_HOST=your-public-host.example.org
POSTGRES_USER=safepath
POSTGRES_DB=safepath
POSTGRES_PASSWORD=
APP_DATABASE_URL=
BACKEND_IMAGE=ghcr.io/OWNER/REPOSITORY/backend@sha256:REPLACE_WITH_APPROVED_DIGEST
FRONTEND_IMAGE=ghcr.io/OWNER/REPOSITORY/frontend@sha256:REPLACE_WITH_APPROVED_DIGEST
AUTH_SECRET=
SERVICE_AUTH_TOKEN=
AUTH_GOOGLE_ID=
AUTH_GOOGLE_SECRET=
OSRM_DATA_DIR=/absolute/path/to/verified/osrm
OSRM_GRAPH_VERSION=
CAMERA_PROXY_ENABLED=false
CAMERA_ALLOW_VIEW_ONLY=false
CAMERA_INGESTION_PERMITTED=false
CAMERA_ROUTING_EVIDENCE_PERMITTED=false
CAMERA_VIEW_AI_ENABLED=true
```

Generate each secret independently with `python -c 'import secrets; print(secrets.token_urlsafe(48))'`, store outside Git and restrict the environment file to mode 600. Use a URI-safe database password (letters/digits/underscore/hyphen, at least 32 characters). AUTH_SECRET signs both NextAuth sessions and trusted Next.js-to-FastAPI identity assertions; the separate SERVICE_AUTH_TOKEN authorizes service writes. All replicas must share the configured values. Rotation invalidates existing signed sessions. Never put them in `NEXT_PUBLIC_*`, command output or build arguments.

Configure Google's exact HTTPS callback `https://YOUR_HOST/api/auth/callback/google`, consent screen and approved users/domain. Production sets `NEXTAUTH_URL=https://PUBLIC_HOST`, uses NextAuth's secure-cookie behavior on HTTPS and same-origin browser REST requests. REST passes through Next.js; `/ws/*` passes through the HTTPS reverse proxy and clients derive WSS. Database, Redis, OSRM, backend and frontend have no published host ports. Caddy handles HTTPS, body limits, HSTS and security headers. Verify real certificate issuance and OAuth before accepting a deployment.

Public camera registry/CDN access does not grant redistribution or inference rights. Keep all camera access flags false until documented permission exists. Record `CAMERA_SOURCE_PERMISSION_REFERENCE` for preflight when enabling authorized viewing. Per-camera routing permission, coordinate proof, viewing proof, segment mapping and fresh capture proof remain independent requirements; do not bulk-grant them. The retired `/cameras/{id}/analysis` endpoint returns 410 regardless of flags.

## Graph and road data on a new server

Read `data/osrm/README.md`, `scripts/setup_osrm_hcm.sh` and `scripts/import_osm_roads_hcm.sh` before execution. The setup downloads the real Geofabrik Vietnam PBF and checksum, verifies it and runs pinned-image `osrm-extract` with car.lua, `osrm-partition`, then `osrm-customize`. These operations need significant RAM/disk and were not repeated as part of the current code fix. Do not assume Git contains generated graph files.

Keep the original PBF/checksum, graph generation timestamp, OSRM image digest and profile together; set a unique `OSRM_GRAPH_VERSION` for that artifact set. Use the same source PBF for the PostGIS import, then run road-segment/edge import and spatial-index SQL. Verify counts, source hashes, GiST indexes and `scripts/check_road_graph.sql`. Proximity candidates do not prove an exact OSRM step/edge match; they cannot authorize camera inference/risk scoring. Unknown mappings remain blocked.

No automatic public OSRM fallback is used. Local OSRM failure returns 503; an explicitly different graph must have separately validated provenance. `car.lua` is not a verified motorcycle-specific legal routing profile.

## Read-only checks and builds

From the repository root:

```sh
python -m pip install -r requirements.txt
python -m pip install --no-deps -e .
python scripts/production/preflight.py --env-file /protected/safepath.env

docker compose --env-file /protected/safepath.env -f docker-compose.prod.yml config --quiet
docker compose --env-file /protected/safepath.env -f docker-compose.prod.yml pull backend frontend
```

Preflight validates configuration, model hashes and graph components. It does not prove DNS, TLS, OAuth, source permission, road coverage or production readiness. Image pulls do not start services. Pin reviewed backend/frontend release images by immutable digest for an approved deployment. CI/CD builds/packages images; no workflow is invoked by this runbook automatically. Configure GitHub Environment protection before a production release.

## Backup, migration and clean initialization

These commands change server state and are for an explicitly approved maintenance window. For an existing installation, first create a backup and rehearse restore in a new, isolated database; never restore over the working database as a test.

```sh
python scripts/production/backup.py --env-file /protected/safepath.env --project safepath-production --output /protected/backups/before-upgrade.dump
```

The backup command refuses overwrite, writes mode-600 custom-format data and checksum, fsyncs the dump and checks its archive directory with `pg_restore --list`. Archive listing is not a restore rehearsal. Restore it into a separately created scratch database with `pg_restore --exit-on-error --no-owner --dbname=SCRATCH_DB`; compare application table counts, camera permissions, bulletin provenance and foreign keys. Encrypt and retain backups under the operator's policy.

Fresh installation: after approval, start only PostgreSQL and Redis, then run the explicit migration tool. Existing installation: back up and rehearse first.

```sh
docker compose --env-file /protected/safepath.env -f docker-compose.prod.yml up -d postgis redis
docker compose --env-file /protected/safepath.env -f docker-compose.prod.yml --profile tools run --rm migrate
```

Alembic revisions create PostGIS first, adopt a frozen baseline, add missing columns/bulletin tables/indexes/FKs, and create the spatial candidate view. They preserve rows and do not fabricate permission/calibration values. A missing required field on a populated legacy table fails transactionally for manual backfill review. Index creation can lock large tables; measure on a representative restored database before scheduling. Staging/production startup refuses an unversioned/outdated schema rather than silently calling `create_all()`.

After migrations and before starting the app, provision an independent runtime login (for example `safepath_app`) using an operator-controlled SQL session. Use `\password safepath_app` to set its independent random password without putting it in command-line history. Grant only database CONNECT, schema USAGE, SELECT/INSERT/UPDATE/DELETE on application tables, and USAGE/SELECT on sequences; revoke CREATE on public from PUBLIC and the runtime role. Do not grant SUPERUSER, CREATEDB, CREATEROLE, table ownership or schema DDL. Set `APP_DATABASE_URL=postgresql+asyncpg://safepath_app:ENCODED_PASSWORD@postgis:5432/safepath` privately. The migration tool uses the separate bootstrap role; runtime services use APP_DATABASE_URL. After future migrations, review grants on new tables/sequences. Preflight verifies distinct credentials/role naming, while actual SQL grants still require operator inspection and a staging permission test.

After migrations, import real camera/flood/district datasets into the intended environment using packaged module entry points, not ad-hoc import path patches:

```sh
python -m scripts.import_vdms_cameras
python -m scripts.import_historical_floods
python -m scripts.assign_camera_districts_postgis --no-manifest
```

Run these inside the approved backend tools environment with the intended DATABASE_URL. Importers require an already migrated schema; flood upserts are transactional and preserve unrelated rows, and camera reimports preserve existing permission decisions. Road graph import is a separate prerequisite described above. Do not seed fake SAFE roads, images or water levels.

## Approved start and smoke acceptance

Only after approval and passing the backup/migration checks:

```sh
docker compose --env-file /protected/safepath.env -f docker-compose.prod.yml up -d
python scripts/production/preflight.py --env-file /protected/safepath.env --check-running --project safepath-production
```

`/api/v1/live` checks the event loop. `/api/v1/ready` returns 503 if core dependencies/schema are unavailable; OSRM failure is reported as DEGRADED with `routing_ready=false`, while non-routing browsing can remain available. Model hash verification does not claim inference accuracy or readiness of provider evidence. Inspect `/models/status` and the actual route response's `route_ai_status`.

Verify HTTPS homepage, Monitor, map/mobile, authorized proxy, camera open/refresh without an analysis POST, real OSRM candidate geometry/alternatives, UNKNOWN risk when evidence is missing, official observed/forecast bulletin separation and stale/outage behavior. Test successful OAuth and ownership rejection with two real accounts; test anonymous ingest/admin rejection and authorized worker ingestion. Confirm no secrets in logs. Restart services in staging and verify database/Redis/volume persistence. Benchmark representative load before promoting a release.

Daily Phú An/Nhà Bè bulletins are not instantaneous gauges. `/hydrology/bulletin` exposes observed historical extrema and forecasts; `/weather-tide` never substitutes a daily peak as current water level. Missing/old source data remains UNAVAILABLE/STALE. See `HYDROLOGY_BULLETIN_INGESTION.md`.

## Rollback

Stop traffic or enter maintenance mode. Roll back application images to the previously verified digest; retain additive schema revisions. Automatic destructive Alembic downgrade is deliberately blocked. If a schema rollback is truly necessary, restore the verified backup to a new database, validate it, then switch DATABASE_URL during an approved maintenance window. Retain the old database until acceptance. Do not run `docker compose down -v`, reset, clean or drop working data as a rollback shortcut.

Rotate compromised secrets, invalidate sessions, review audit logs and separately verify provider permissions after any security incident. Real production restore, TLS, OAuth and server capacity must be recorded with date, release SHA and operator evidence before claiming READY FOR PRODUCTION.

## CI image gates and staging approval

`ci.yml` runs credential scanning, strict Python dependency audit, fatal Python lint,
frontend ESLint, TypeScript, unit tests, build and production npm audit. Backend
migration/seeding/pytest use isolated CI PostGIS/Redis services. Docker images load
locally and Trivy scans both OS and language packages with HIGH/CRITICAL failures
blocking publication (including unfixed findings). Only a successful `push` to main
publishes the exact scanned images under `sha-FULL_COMMIT_SHA`; no independent tag
or manual workflow can bypass these gates. Pin the resulting registry digests, not
the mutable SHA tag. Scan failures must be fixed/reviewed; no ignore-all bypass.
Infrastructure image digests are pinned in production Compose; their operator
vulnerability reviews and updates are still separate release prerequisites.

`cd.yml` is a manual **staging** template. Before enabling it, configure the GitHub
`staging` Environment with required reviewers and a main-only deployment branch
policy. Provision a dedicated Linux x64 self-hosted runner labelled `safepath-staging`,
Docker, Python with repository requirements, `gh`, protected mode-600 environment
file and encrypted backup destination. Environment variables `STAGING_ENV_FILE`
and `STAGING_BACKUP_DIR` contain only host paths. Use a distinct staging DNS name,
database, secrets and Compose project; never point this runner at production.
GitHub YAML cannot enforce the administrator's Environment reviewer policy itself.

Bootstrap staging infrastructure, runtime SQL grants and graph assets under the
maintenance runbook first. The deployment workflow verifies a successful push CI
run for the exact approved main SHA, validates same-repository immutable image
digests and checks OCI revision labels. It runs preflight, protected database
backup, explicit migrations, `up --no-build --wait`, readiness, frontend and camera
API smoke checks. Failure rolls back previous application image IDs when available;
schema remains unchanged. The operator must explicitly attest migration backward
compatibility. First-install failure has no previous images to restore. Never
approve a destructive migration on the assumption that image rollback restores
schema. No workflow here deploys production.

The backend mounts the same verified OSRM artifact directory at `/app/data/osrm`
read-only, including `graph-manifest.json`; manifest graph/version/hash proof is
required for positive camera-to-route evidence. Regenerate graph artifacts with the
approved setup pipeline; do not invent a manifest for an unverified old graph.

## Metrics, logs and external reliability

`GET /api/v1/metrics` requires the existing service authorization token. Scrape each
backend replica privately every 30 seconds; do not expose this endpoint publicly
or place credentials in query strings. `safepath_http_requests_total` uses route
templates, method and HTTP status (no camera IDs/user URLs). The cumulative
`safepath_duration_seconds` histogram reports request and fixed operation timings.
Run one ASGI worker per container: metrics are process-local and reset on restart.
Use `rate(safepath_http_requests_total{status=~"5.."}[5m])` for errors and
`histogram_quantile(0.95, sum by (le,kind,name) (rate(safepath_duration_seconds_bucket[5m])))`
for p95. Alert on readiness failures, rising source error counts and sustained
latency after establishing representative staging baselines. Metrics alone do not
prove model accuracy or source freshness; inspect model/source status endpoints.

Application JSON request logs include request ID, route template, status and
elapsed milliseconds. The formatter redacts URL credentials/query strings and
common token fields; never intentionally log provider responses or secrets. Debug
exception stacks are omitted from JSON output to avoid disclosing token-bearing
transport URLs. Container rotation remains 10 MiB × 3.

Open-Meteo/HERE/TomTom idempotent JSON GETs have at most two attempts with jitter
inside their original 6/3-second total budget. Auth/permission/quota responses are
not retried. Hashed request keys keep a bounded 128-entry per-process outage cache:
20 seconds for transport/malformed payloads, 60 seconds for auth/quota. Existing
provider circuits, Redis success-cache and freshness decisions remain in force;
missing data stays unavailable. Bulletin polling retains distributed locking,
size/time limits and bounded exponential cooldown with jitter. Camera proxy keeps
its own byte/permission checks and retry schedule; no POST is automatically retried.

## Reproducing CI locally

Use Python 3.12 and Node 22; install `requirements.txt`, the editable repository
(`python -m pip install --no-deps -e .`), `ruff==0.14.4`, `pip-audit==2.9.0`, and
run `npm ci` in frontend. Point `DATABASE_URL` at a disposable migrated/seeded
PostGIS database and `REDIS_URL` at its isolated Redis DB; set `TESTING=true`.
Never run database tests against working production data.

```sh
ruff check backend/app scripts/production --select E9,F63,F7,F82
python -m compileall -q backend/app
python scripts/security_and_redaction_check.py
pip-audit -r requirements.txt --strict
pytest backend/tests/ -v --tb=short
npm --prefix frontend run lint
npm --prefix frontend run type-check
npm --prefix frontend run test:unit
npm --prefix frontend audit --omit=dev --audit-level=high
npm --prefix frontend run build
```

Use the workflow's Docker load/Trivy commands on a machine with sufficient memory
for the remaining image gates. Passing host tests does not prove image scan or
staging deployment passed. Base images are pinned to official registry digests;
review/update digests regularly and re-run scans rather than assuming immutability
implies absence of vulnerabilities.
