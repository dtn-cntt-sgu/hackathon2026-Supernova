> Báo cáo lịch sử của lần kiểm tra trước. Trạng thái hiện tại, bản sửa và kết quả nghiệm thu mới nằm trong [PRODUCTION_READINESS.md](PRODUCTION_READINESS.md).

# SafePath production readiness report

Subsequent user request supersedes the viewing-inference prohibition in this historical assessment. Explicit Overlay/landing selection now runs observational AI; see [camera interaction and auth fixes](CAMERA_INTERACTION_AND_AUTH_FIXES.md). Route evidence gates remain unchanged.

Assessment date: **8 November 2026, Asia/Ho_Chi_Minh**. Working baseline: `70d89f9`, branch `feature/camera-proxy-route-ai-only`, with uncommitted changes described below. No commit, push, merge or production deployment was performed. This report distinguishes executable local evidence from external deployment prerequisites.

## Executive summary and verdict

**NOT READY FOR DEPLOY** to production. Implementation removes identified code/configuration blockers and supplies a production deployment path, but source rights, exact route-edge correspondence, real production OAuth/TLS/domain and target-server acceptance remain unverified. Route search can operate with UNKNOWN risk; it must not be advertised as verified flood-safe routing when evidence is absent.

A local staging-style backend and production-built frontend are used for acceptance. They do not establish acceptance of an actual production environment. Default production camera permissions remain false. Do not grant rights or forge calibration to turn a blocker green.

## Defects, causes and repairs

| Area | Root cause | Implemented repair |
|---|---|---|
| Python CI | Direct script execution omitted package context; path hacks/cwd-relative datasets differed between scripts | Editable standard Python package, console/module entry points, repository-absolute dataset paths; CI installs package and migrates before seeding |
| Frontend CI | Node20 cannot directly import navigation.ts from an mjs test | tsx runner shared by local/CI unit scripts; verified with actual Node20 and Node22. CI/Docker now use Node22 for MapLibre transitive-engine compatibility |
| Clean TypeScript check | Next15 generated a reference to an ignored isolated build directory | `next typegen && tsc --noEmit`, scoped includes and explicit tracing root; generated files normalized before final acceptance |
| Viewing inference | Opening a map camera automatically called analysis endpoint and a `view_only` executor bypass | Map uses source proxy modal; legacy endpoint always410; helper alwaysdisabled and executor rejects view-only before cache/model access |
| OSRM provenance | Connect failure silently switched local graph to public OSRM | Removed public fallback; return structured503 without fabricated geometry |
| Candidate-edge risk | A nearby edge matching a camera's observed way was treated as the actual OSRM step | Candidate edges remain unverified; admission/scoring requires independent `route_match_verified` proof. Current collector does not manufacture that proof |
| Hydrology write API | Anonymous callers could invoke ingestion | Separate service bearer token, constant-time comparison, rate limits, bounded payload and audit logs without secrets |
| User impersonation | Anonymous identity sync minted session tokens; user-ID headers had a fallback | Trusted server identity signature required for sync; ownership requires signed bearer or proxy identity; no header-only fallback; stable provider ID and email both bind proxy row access |
| Secrets | Fixed development HMAC fallback was accepted | Random per-process development default; explicit independent deployment secrets required; no fixed frontend signing fallback |
| Dependency security | Vulnerable Next14/MapLibre4 and nested PostCSS | Next15.5.28, MapLibre6.16.0, PostCSS8.5.32 override; namespace import/API compatibility updates; npm audit repeated |
| Image rights/cache | Stored image route bypassed permission revocation; one-year public immutable caching | Rights check before DB/files and no-store camera responses; anonymous image viewing cannot bypass revoked flags |
| Priority/refresh state | Arbitrary IDs could allocate Redis priority entries or never-evicted process locks | Shared per-client limits and registry validation before writes/allocation |
| API capacity | Unbounded bodies, local-only rate counters and spoofable forwarded identity | Bounded streamed bodies/timeouts; Redis atomic counters across replicas, signed proxy client identity, fail-closed production limiter outage |
| Database upgrade | create_all never adds legacy columns | Frozen Alembic revisions, non-destructive reconciliation, PostGIS initialization, bulletin schema, indexes/FKs and candidate view; deployed startup requires current revision |
| Import integrity | Flood importer deleted rows before load; reimport overwrote camera permission decisions | Transactional ID upsert preserving unrelated rows; camera reimports preserve existing permissions; seeding no longer mutates schema |
| Bundled MapLibre worker | MapLibre6 ESM worker URL is not inferred reliably by Next webpack | Explicit locally bundled `setWorkerUrl` before map construction, using6.16 worker packaging; browser checks actual rendered camera points |
| Empty-cache map | Client discarded all registry cameras without LIVE/STALE image metadata | Preserve the real GPS registry and show missing-image states; viewing can fetch the source independently |
| Polling/performance | Visibility races created duplicate refresh chains; manual revision reloaded full registry forever; status repeatedly hashed large weights | One in-flight polling chain and one-shot registry refresh; weight digest cache invalidates on size/mtime/ctime/inode changes |
| Infrastructure | Development ports/passwords/source mounts were unsuitable for public hosting | Separate production Compose with HTTPS proxy, private dependencies, required secrets, non-root app image, volumes, memory/CPU limits and backup/preflight tooling |

The framework changes follow the [official Next15 upgrade guide](https://nextjs.org/docs/app/guides/upgrading/version-15) and upstream [Next security advisories](https://github.com/vercel/next.js/security/advisories) / [MapLibre security advisories](https://github.com/maplibre/maplibre-gl-js/security/advisories). Worker setup follows the [official MapLibre6 migration guide](https://maplibre.org/maplibre-gl-js/docs/guides/v5-to-v6-migration-guide/). The dependency audit result is time-specific, not proof that future advisories cannot occur.

## Camera proxy and Route AI evidence

Read-only inventory: **796 registered, 796 GPS/coordinate-proof fields, 0 verified views, 0 routing-permitted cameras**. All796 retain `PERMISSION_UNVERIFIED`. There are706 stored original files; stored ingestion metadata labels706 LIVE and90 PLACEHOLDER, which does **not** prove706 current/live upstream images. Registry/edge/fresh/configured eligible counts are all0: **BLOCKED_BY_EVIDENCE**. See `PRODUCTION_EVIDENCE_AUDIT.md` for exact definitions and timestamp.

The source proxy retains fixed upstream hosts, TLS verification, bounded image bytes/pixels/concurrency/pending frames, cache/stale limits, coalescing and rejection/backoff for403/429. It never invokes a model. Viewing budgets/cache are per process; Redis client limits are shared, but upstream request pacing/coalescing is not a global cross-replica provider quota. Operate one provider-facing replica until an agreed shared quota/distributed image cache is validated. Camera source licence/redistribution rights remain an external blocker.

Route AI remains lazy, bounded to four cameras/two executing native calls/eight-second request budget, deduplicated by camera/snapshot/model identity with Redis leases. Unknown capture age and unverified view/permission/step mapping block admission. Tests exercise admitted inference/ranking with clearly labelled unit fixtures, not fabricated production camera rights. Real-world Route AI cannot be declared operational on eligible cameras because the actual inventory contains none. Failures or absent evidence leave risk UNKNOWN/INSUFFICIENT_EVIDENCE; no SAFE backfill.

## Database, routing and hydrology

Alembic `20261108_01` creates PostGIS/frozen baseline, `_02` reconciles missing evidence columns, bulletin tables/indexes/FKs, `_03` creates the read-only camera/edge candidate view. Migration tests use disposable real PostGIS databases, including legacy schemas and an actual-catalog copy. The working database is not implicitly upgraded in staging/production. Required missing values on populated legacy tables stop the upgrade for manual review. Destructive downgrades are blocked; rollback retains additive schema or restores a verified backup into a new database. Large-table index lock duration needs representative staging measurement.

Default CI no longer assumes a generated Vietnam graph or300,000+ imported road rows. Unit routing contracts use explicit unit-only OSRM responses; clean-database integration checks real seed provenance and truthful missing-road/geocoder states. Real OSRM/GIS tests remain separate and must be run against prepared artifacts. Existing local OSRM graph readiness does not prove a fresh-server graph build. OSM download/checksum/extract/partition/customize and road/edge/index imports are documented in the deployment guide; rebuilding the full graph is not silently claimed.

Official Phú An/Nhà Bè daily PDF discovery, source/timezone provenance, observed/forecast separation, missing-marker handling, backoff/cache and STALE/UNAVAILABLE behavior remain independent of camera AI. The verified311/2026 bulletin contains8 observed historical extrema and40 forecasts. No daily peak is published as the current water level or automatically interpreted as street flooding. The PDF does not specify these stations' datum; it remains unknown. See `HYDROLOGY_BULLETIN_INGESTION.md` for source/hash/parser limitations. No production fixture fallback exists.

## Validation record

Consolidated results and remaining blocked checks are recorded in the final local evidence section below. An initial scratch regression exposed four clean-database/test assumptions; they were corrected rather than disabled: missing candidate view, omitted required snapshot size, full-road-graph row-count assumptions, and geocoder coverage measured without imported streets. Earlier Docker connection failures occurred while an external build exhausted the local VM; Docker Desktop was restarted only after explicit user approval.

### Performance evidence

Five local repeated model-manifest validations before caching took51.8–68.6ms. After the change, first verification took59.6ms and five cached validations took0.09–0.23ms. The cache still detects same-size modified weights using filesystem identity/change timestamps, with a tampering regression. This measures repeated checksum overhead only, not ONNX inference accuracy or end-to-end production latency. Logs: `/tmp/safepath-production-model-validation-{before,after}.json`.

Polling fixes remove a concrete duplicate-timer/full-registry-fetch path; no unsupported Core Web Vitals improvement is claimed. Browser map rendering, mobile controls, source-image requests and route searches are checked against running services. Small route samples, where recorded, must specify database/graph coverage and cannot be described as a production SLA.

## Remaining blockers and acceptance checklist

| Criterion | Evidence/status |
|---|---|
| Known Python/TypeScript CI root causes fixed | Implemented; local clean-install/package/Node20 checks recorded separately |
| GitHub-hosted CI for this uncommitted patch | **NOT VERIFIED**; no push or workflow dispatch |
| Full backend regression | **436 PASS, 0 FAIL, 15 SKIP** on migrated scratch DB; final targeted follow-ups PASS |
| Type-check/unit/production frontend build | **PASS**; Node22,7unit tests, Next15 production build |
| Docker build/runtime | Both final images **PASS**; actual-image Chromium acceptance11PASS |
| Database fresh/legacy migration and persistence | Disposable local tests; no production migration |
| Security HIGH findings | Fixed; independent reviewer and targeted regression results recorded separately |
| Monitor/map/refresh never invoke AI | Backend denial tests and browser network checks |
| Route-only AI and no false SAFE | Admission/ranking tests; actual eligible camera count0, **BLOCKED_BY_EVIDENCE** |
| Camera source rights/calibrated exact step mapping | **BLOCKED/NOT VERIFIED** |
| Local OSRM/PostGIS/Redis | Live readiness; new-server full graph import still requires operator evidence |
| Hydrology provenance | Official source parsing/fixture/integration; no real-time claim |
| Authentication cryptographic/ownership checks | Local tests; actual Google end-to-end login with two accounts **NOT VERIFIED** |
| Real domain/TLS, production secret store, firewall | **NOT VERIFIED** |
| Target-server capacity, multi-replica quota and representative load | **NOT VERIFIED** |
| Runtime PostgreSQL role least privilege | Production template requires a distinct APP_DATABASE_URL/runtime role; migration uses the bootstrap role. Actual grants must still be provisioned/rehearsed by the operator; preflight rejects reused bootstrap credentials |
| Production backup/restore and migration window | Local scratch rehearsal only; production operation **NOT PERFORMED** |
| No unresolved production prerequisites | **NOT MET** |

The standalone Compose and guide prepare an operator-reviewed deployment; they do not satisfy the missing external conditions by assumption. Final verdict remains **NOT READY FOR DEPLOY** to production.

## Files, agents and rollback

Modified/new file inventory is appended from the final Git worktree status. Main agent integrates API/security/route admission/frontend compatibility and documentation; CI/infrastructure, migration/evidence and QA workers own disjoint tasks; an independent reviewer checks the meaningful diff. The review's provider-account ownership finding is addressed with stable-ID row binding and a same-email/different-provider regression.

Follow `DEPLOYMENT_PRODUCTION_GUIDE.md` and `backend/migrations/README.md` for backups, restore rehearsal, explicit migration and rollback. No reset/clean/data deletion or production mutation was used to make acceptance pass. Existing generated test artifacts are restored only when confirmed clean before test generation.

## Final local evidence

- Complete backend suite on disposable migrated/seeded PostGIS + isolated Redis15: **436 PASS, 0 FAIL, 15 SKIP**,98.63s.14 explicitly gated OSRM/GIS cases and one missing-PyTorch case; no configuration-error skip was added. Initial four failures are retained in the earlier log, not erased.
- Additional final security/infrastructure/view regressions after review and final defaults: **25 PASS**. Independent reviewer ran44 targeted tests; HIGH findings resolved, MEDIUM stable-provider ownership binding fixed with regression.
- Fresh/legacy migration tests:8PASS, included in the suite. Real scratch backup/restore: PASS,796camera identities/permissions and revision20261108_03 match; mode0600 custom archive. No working/production database was restored or migrated.
- Frontend clean `npm ci`, type generation/check, unit tests: PASS;7unit tests also PASS on actual Node22 (and separately Node20 for the original regression). The final supported CI/Docker runtime is Node22.
- npm audit:0known vulnerabilities. pip-audit:59pinned packages checked,0vulnerabilities,0skips. OS/base-image CVE scanning is **NOT VERIFIED**, separate from these package audits.
- Frontend Next15 host production build: PASS. Backend Docker image: PASS, UID10001:10001; staging-mode container starts with current schema and read-only root/capabilities dropped.
- Updated backend container restart/persistence: **PASS**;796camera rows and48bulletin events/sourceSHA survive restart, schemaCURRENT and routing readiness recover. Evidence: `/tmp/safepath-production-restart-persistence.json`.
- Actual OSRM-down container test: PASS, readiness reports DEGRADED/routing_readyfalse and route503withoutgeometry/publicfallback.
- Official upstream PDF collection into the scratch DB: PASS, bulletin311/2026,48events, verifiedoriginalSHA; no fixture used by runtime.
- Final frontend Docker image (Node22, Next15.5.28, MapLibre6.16 worker URL): **PASS**. Actual-image Chromium acceptance: **11 PASS, 0 FAIL**,29.7s. Includes rendered map markers/source imagery, open/refresh without inference, responsive375/390/768/900/tablet navigation, Monitor, hydrology, guest auth and rejected anonymous writes. No intercepted/fabricated camera images or route/hydrology responses.
- Real OSRM/GIS suite with both live flags enabled: **18 PASS, 0 SKIP**,27.76s. This separately verifies the14cases gated out of the default suite; counts are not added together as if disjoint. The remaining PyTorch equivalence test was not run because torch is absent.
- Final production Compose/preflight runtime-role separation tests: **8 PASS**. Runtime requires separately provisioned APP_DATABASE_URL; admin migration credentials are not passed to the web runtime. Actual target-server role grants remain NOT VERIFIED.
- Independent reviewer closed all reported findings after fixes; final focused recheck14PASS. No unresolved Critical/High code finding from that review.
- Broader historical Playwright specs were not all rerun; several encode superseded UI/provider/auth assumptions. This report claims only the11listed current acceptance cases, not a blanket all-spec pass. Real Google OAuth consent/login remains NOT VERIFIED.
- Production OS/base-image vulnerability scan, actual HTTPS domain, server restart/restore and load testing remain NOT VERIFIED.

Evidence logs: `/tmp/safepath-production-full-backend.log`, `/tmp/safepath-production-security-final.log`, `/tmp/safepath-production-backup-restore-result.json`, `/tmp/safepath-production-typecheck-clean-final.log`, `/tmp/safepath-production-node22-final.log`, `/tmp/safepath-production-npm-audit-final.json`, `/tmp/safepath-production-python-audit.json`, `/tmp/safepath-production-runtime-outage.json`, `/tmp/safepath-production-hydrology-live.log`.

### Actual-image smoke and performance details

The first small route sample included OSRM cold-start/browser contention:5/5HTTP200, UNKNOWN risk, p50=1308.41ms and nearest-rank p95=12309.41ms. After browser acceptance, a separately recorded warm5-request sample returned5/5HTTP200, UNKNOWN risk, p50=972.45ms and p95=1262.41ms. Each response contained14segments and one alternative. The test database has796real camera rows but **zero imported road edges**, with a real local OSRM graph and no commercial provider/camera inference. These are local smoke measurements, **not** full-graph API throughput, production latency or an SLA; the cold tail is retained rather than discarded. Logs: `/tmp/safepath-production-route-benchmark.json` and `...-warm.json`.

Final image logs: `/tmp/safepath-production-backend-image-final.log`, `/tmp/safepath-production-frontend-image-worker.log`. Browser log: `/tmp/safepath-production-browser-acceptance.log`; actual source-image/modal and mobile bulletin screenshots inspected locally. Live GIS log: `/tmp/safepath-production-live-routing.log`. All temporary acceptance containers bind only loopback host ports and use the disposable database/cache; they are separate from a production deployment.

### Exact modified/new files

- `.dockerignore`
- `.env.example`
- `.github/workflows/ci.yml`
- `.gitignore`
- `Antigravity.md`
- `README.md`
- `alembic.ini`
- `backend/app/core/auth.py`
- `backend/app/core/config.py`
- `backend/app/core/http_limits.py`
- `backend/app/db/session.py`
- `backend/app/main.py`
- `backend/app/schemas/contracts.py`
- `backend/app/services/camera_overlay.py`
- `backend/app/services/route_camera_ai.py`
- `backend/app/services/routing.py`
- `backend/app/services/vision.py`
- `backend/migrations/README.md`
- `backend/migrations/env.py`
- `backend/migrations/schema_20261108.py`
- `backend/migrations/script.py.mako`
- `backend/migrations/versions/20261108_01_baseline.py`
- `backend/migrations/versions/20261108_02_evidence_and_bulletins.py`
- `backend/migrations/versions/20261108_03_camera_candidates.py`
- `backend/tests/test_admin_cli.py`
- `backend/tests/test_camera_ingestion_complete.py`
- `backend/tests/test_camera_metadata_and_snapshot_live.py`
- `backend/tests/test_camera_scheduler.py`
- `backend/tests/test_camera_snapshot_consistency.py`
- `backend/tests/test_database_migrations.py`
- `backend/tests/test_hydrology_ingestion.py`
- `backend/tests/test_phase4_risk_and_routing.py`
- `backend/tests/test_phase5_api.py`
- `backend/tests/test_phase5_weather_tide_risk_live.py`
- `backend/tests/test_phase7_failure_resilience_live.py`
- `backend/tests/test_production_infrastructure.py`
- `backend/tests/test_production_security.py`
- `backend/tests/test_route_camera_ai_only.py`
- `backend/tests/test_traffic_news_nlp_benchmark.py`
- `backend/tests/test_user_auth_api.py`
- `backend/tests/test_view_camera_overlay.py`
- `backend/tests/unit_routing_fixtures.py`
- `docker-compose.prod.yml`
- `docker-compose.yml`
- `docker/Caddyfile`
- `docker/backend.Dockerfile`
- `docs/DEPLOYMENT_PRODUCTION_GUIDE.md`
- `docs/PRODUCTION_EVIDENCE_AUDIT.md`
- `docs/PRODUCTION_READINESS_REPORT.md`
- `docs/UI_WEATHER_OVERLAY_FIXES.md`
- `frontend/.dockerignore`
- `frontend/Dockerfile`
- `frontend/e2e/camera-live-overlay.spec.ts`
- `frontend/e2e/production-readiness.spec.ts`
- `frontend/next-env.d.ts`
- `frontend/next.config.mjs`
- `frontend/package-lock.json`
- `frontend/package.json`
- `frontend/src/app/api/v1/[...path]/route.ts`
- `frontend/src/auth.ts`
- `frontend/src/components/CameraEvidenceModal.tsx`
- `frontend/src/components/MapContainer.tsx`
- `frontend/src/components/SpatialDashboard.tsx`
- `frontend/src/hooks/useLiveObservations.ts`
- `frontend/src/lib/server-identity.ts`
- `frontend/src/types/contracts.ts`
- `frontend/tests/server-identity.test.mjs`
- `frontend/tsconfig.json`
- `pyproject.toml`
- `requirements.txt`
- `scripts/assign_camera_districts_postgis.py`
- `scripts/import_historical_floods.py`
- `scripts/import_vdms_cameras.py`
- `scripts/production/backup.py`
- `scripts/production/preflight.py`
- `scripts/production_evidence_audit.py`
- `scripts/security_and_redaction_check.py`

### Cleanup and current worktree

Temporary acceptance web processes and both temporary acceptance containers were stopped/removed after validation. The existing five development containers were left healthy with OSRM running. Scratch database/restore evidence and protected backup remain available locally for review; the working database was not reset or migrated. Built `safepath-backend:readiness` and `safepath-frontend:readiness` images are retained. No changes were staged, committed, pushed or deployed to production. The updated source is the reviewable result; the original development service was not silently replaced by the acceptance environment.
