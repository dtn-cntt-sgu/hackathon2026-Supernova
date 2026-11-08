# SafePath — Production readiness, 08/11/2026

> Cập nhật ETA sau báo cáo này: [ETA_CALCULATION.md](ETA_CALCULATION.md) — dùng tốc độ trên phần có dữ liệu và OSRM ước tính phần thiếu; kết quả kiểm thử mới và giới hạn so với Google được ghi riêng.


**Verdict: NOT READY for production release.** Functional fixes and isolated/local acceptance have passed; the backend image vulnerability gate and installation of a graph with verifiable build provenance still block release. Staging deployment has not been performed. No branch, commit, push, GHCR publication or production deployment was made. The local development app is running at http://localhost:3000.

This report supersedes conflicting historical statements in `PRODUCTION_READINESS_REPORT.md`. Statuses describe actual evidence: PASS, FAIL, NOT_RUN, BLOCKED, NOT_APPLICABLE. An implemented workflow is not an executed release.

## Actual architecture and data boundaries

Next.js 15.5.28/React 18 proxies `/api/v1/*` to FastAPI. Google NextAuth sessions produce server-signed identities; backend personal API access uses HMAC session tokens with expiry, issuer/audience and ownership checks. PostgreSQL/PostGIS stores users, cameras, road ways/edges, official hydrology bulletins and community reports. Redis caches raw OSRM geometry and source observations, limits writes, and coordinates bounded workers. Self-hosted OSRM provides actual alternatives, steps and OSM node annotations. ONNX runs vehicle detection and road-surface segmentation outside the API event loop with bounded concurrency.

Viewing a camera is fetch-only. Selecting Overlay or explicitly selecting a landing camera performs real inference on the exact displayed immutable snapshot. Unknown capture time does not become verified routing evidence. Image enhancement and the floating VoiceHUD remain removed. Daily hydrology observations/forecasts/extrema retain issue/event times, datum and source; they are not realtime road flood measurements.

OSRM/PostGIS matching now requires a build-generated graph manifest, same PBF source hash, preserved original OSM node pairs, direction/ambiguity checks and complete step geometry coverage. Nearby road/camera candidates are not proof. Missing endpoint phantom-node coverage remains UNVERIFIED. Every verified edge is scored, including second/later edges in a step. Risk is recalculated each request; cached candidate flags cannot authorize matching. Daily tide bulletins alone never close roads.

Risk score is hazard severity, separate from ETA/traffic confidence/coverage; it is not a probability of safety. Critical/closed alternatives rank after non-critical alternatives, using the existing documented cost weights within that policy. Missing evidence, mixed observed/unobserved edges and scoring failures retain UNKNOWN. All hazardous alternatives return NO_SAFE_ROUTE with no recommendation. The UI labels these reference options and warns explicitly.

## Implemented findings

Twenty groups of behavior/security/functionality gaps were addressed; deployment prerequisites below are separate unresolved acceptance conditions.

| ID | Verified problem or gap | Result |
| --- | --- | --- |
| F01 | Every spatial candidate forced unverified without a positive matching path | PASS — exact annotation-node/PBF/geometry proof, fail-closed otherwise |
| F02 | Only one arbitrary road edge scored per step | PASS — all exact matched edges, strongest hazard and per-edge delay |
| F03 | NO_SAFE_ROUTE still recommended first route | PASS — all recommendations suppressed; API/UI consistent |
| F04 | SAFE could erase an UNKNOWN edge during aggregation | PASS — partial risk evidence remains UNKNOWN |
| F05 | Failed edge scoring dropped the unknown edge | PASS — explicit unknown placeholder preserves incompleteness |
| F06 | Camera with missing observed edge could enter another exact edge | PASS — exact observed-edge equality required |
| F07 | News order/benign evidence could mask stronger closure evidence | PASS — deterministic strongest incident, closure precedence, dedupe |
| F08 | 34-character freshness state exceeded VARCHAR(32) | PASS — additive migration06 widens to64 |
| F09 | Snapshot insert error poisoned transaction/latest-frame state | PASS — savepoint rollback and previous-frame preservation |
| F10 | ETA minutes disagreed with serialized rounded seconds | PASS — derive minutes from serialized seconds |
| F11 | Inactive users could still access personal APIs or sync | PASS — active-account checks and regression tests |
| F12 | Missing Google email_verified accepted | PASS — explicit true and active synced account required |
| F13 | Custom user tokens had no issuer/audience domain separation | PASS — strict safepath/safepath-api claims; refresh via existing sync |
| F14 | Cookie-authenticated proxy mutations lacked origin check | PASS — configured public-origin CSRF guard, including normalized Next internal hosts |
| F15 | Community submission had no persisted moderated backend flow | PASS — DB/API/UI, own-account access, quotas, dedupe, expiry and independent moderation |
| F16 | Reimport could reassign an incident's numeric edge index | PASS — capture/recheck PBF hash and both OSM node IDs |
| F17 | Obsolete frontend lint command; missing timezone/hashlib imports | PASS — actual ESLint gate, accessibility/hooks fixes and fatal Python lint |
| F18 | Independent image workflows bypassed required tests | PASS — publish only the same scanned image after CI gates; manual approved staging |
| F19 | External GET failure retries/cooldowns/backoff incomplete | PASS — bounded idempotent GET helper, jitter, outage cooldown; no permission elevation |
| F20 | No bounded request/operation metrics and structured redacted logs | PASS — protected metrics, request IDs, latency/error counters, dependency/freshness gauges |

Image work additionally removed unused runtime npm/yarn and curl and applied available Debian security updates. The secret scanner no longer prints suspected secret values and recognizes the exact non-secret graph-manifest configuration path. Synthetic flood benchmark no longer advertises an invented 50ms SLA.

## Tests and reproducible evidence

All mutating automated DB tests use a disposable `safepath_readiness_qa_*` database and Redis database15. Actual imported road tests use a readonly transaction setting. A full scan of all physical cameras or a completed Google consent flow is not claimed. After isolated acceptance, the local development database was backed up and additively migrated to07 and the local frontend/backend images updated; no production server or graph rebuild was involved.

| Group | Status | Actual evidence |
| --- | --- | --- |
| Full backend regression | PASS | 471 PASS,15 SKIP,110.91s, including security-scanner regression |
| Default-suite skips | NOT_RUN in default invocation | 14 opt-in live cases executed separately below;1 legacy PyTorch recovery test skipped because torch is not installed. ONNX runtime inference is tested separately |
| Live OSRM + API geometry/ETA, exact PostGIS mapping, migrations, snapshot rollback | PASS | 34 PASS,39.90s after OSRM recovery; real OSRM GETs, disposable PostGIS labelled fixtures |
| Actual imported roads/camera trust/source/index checks | PASS | 5 PASS,8.98s; PGOPTIONS default_transaction_read_only=on; correct host OSRM port5001 |
| External reliability/ops/weather/official bulletin regression | PASS | Worker72 PASS; subsequent full backend includes these |
| Frontend lint | PASS | ESLint src, zero warnings; npm10 tree valid. Host npm11 reports invalid override-tree peers despite matching installed versions; npm10 dependency tree, lint and builds pass. CI/container use Node22/npm10 |
| TypeScript | PASS | next typegen and tsc --noEmit |
| Frontend unit tests | PASS | 12 PASS, including OAuth fail-closed, route labels and CSRF public-origin behavior |
| Native Node22 production build | PASS | Next.js15.5.28 compiled and generated11 pages |
| Browser against isolated native QA app | PASS | 16 PASS,50.5s: map/mobile375/390/768/900, hydrology, real Overlay, landing selection, guest rejection, real routes and persisted report |
| Deterministic CI browser contracts | PASS | 3 PASS: guest reports/account and NO_SAFE_ROUTE warning without safety badge; explicit test fixtures, no provider keys |
| Browser against built Docker app images | PASS | 4 PASS,4.1s: CI contracts plus authenticated report persistence/moderation rejection |
| Docker image build/start | PASS | Both images built; QA backend UID10001 and frontend nextjs healthy. Temporary QA containers removed |
| Frontend image Trivy HIGH/CRITICAL | PASS | Trivy0.76.2,0 findings after removing unused npm/yarn; Alpine3.24.4 |
| Backend image Trivy HIGH/CRITICAL | FAIL | 47 HIGH package findings/11 unique CVEs in Debian13.7; no fixed distro version reported; no Critical. Reduced from53 by patching zlib and removing curl. No ignore-unfixed/allowlist bypass |
| Dependency audits | PASS | npm audit0 known vulnerabilities, strict pip-audit on pinned requirements0 known vulnerabilities |
| Additional compose/scanner regression | PASS | 4 PASS after final shared graph mount; no YAML dependency added |
| Local development app browser smoke | PASS | 3 PASS,17.0s against updated localhost:3000; actual local route/guest protection/source image |
| Workflow/config/security validation | PASS | actionlint, fatal Ruff, compileall, shell syntax, compose validation, credential/redaction scanner and git diff --check |
| Backup/restore rehearsal | PASS | Custom archive from scratch DB revision07 restored into new scratch DB; all table counts, revision and camera-permission hash match; restored scratch DB dropped |
| GitHub-hosted Actions/GHCR | NOT_RUN | No push/workflow execution/publication; cannot claim remote green |
| Approved staging/production acceptance | NOT_RUN | No server deployment or real HTTPS/domain/callback/restore/rollback acceptance |
| Independent review | PASS for bounded follow-up | Reviewer found2 HIGH + frozen-migration issue, all fixed; independently reran mixed-coverage guard. No remaining Critical/High found in that bounded scope; distro CVEs remain release blockers |

Local log evidence: `/tmp/safepath-hardening-final-regression.log`, `integration-recovered.log`, `real-road-readonly-recovered.log`, `browser-accepted.log`, `container-browser.log`, `ci-browser.log`, `docker-{backend2,frontend-final}.log`, `trivy-{backend,frontend}-final.json`, `restore.json`, `benchmark.json`, `concurrency.json` (all prefixed `safepath-hardening-` unless otherwise stated). These local artifacts are not committed and should be archived by the operator before removal.

Initial failures were retained, investigated and rerun: snapshot-width/transaction bug, ETA serialization mismatch, auth fixture missing active-state field, new incident test missing required fixture length, normalized-host CSRF rejection, npm download timeout and OSRM OOM under simultaneous QA-container startup. None was suppressed with continue-on-error. The final readonly road tests and34-case live suite passed after freeing QA containers and restarting OSRM in lower-memory startup order.

## Measurements, not a production SLA

The real-frame ONNX harness asserts manifest hashes/input-output schema/finite tensors and preserves source bytes. `python -m scripts.benchmark_vision --image <source.jpg> --output <result.json> --iterations 6` performs one warmup and six samples with two CPU inference threads, without saving derivatives. On Darwin arm64, the first worker run measured vehicle p95=386.071ms, flood p95=12.758ms, process peak395.91MiB. A later harness run during concurrent validation measured vehicle p95=1959.346ms, flood p95=13.588ms, peak365.39MiB. This variation prohibits a latency SLA claim. One night frame/six calls cannot estimate AP, recall, IoU, flood depth or field accuracy.

Readonly EXPLAIN ANALYZE on an existing edge used `idx_road_edges_geog` (one-row midpoint79.482ms; empty location2.117ms). Exact-node production-plan acceptance remains BLOCKED until node-ID import. Five simultaneous identical warm-cache route requests against scratch DB returned200/UNKNOWN in2650.48–2722.10ms; that DB has no imported road graph, so this is bounded concurrency behavior only, not full-graph load capacity or QPS acceptance.

Docker VM is only3.825GiB. OSRM warm memory is about2.4GiB and startup peaks higher. Adding QA containers caused observed OOM/137; API returned503. QA containers were removed; OSRM was warmed with app containers stopped briefly, then the original app was restored. Provision sufficient host memory for the production-compose limits (about8GiB before host/build overhead); measure on the actual staging host. No production resource/SLA claim.

## Community API and risk policy

See [community API](COMMUNITY_INCIDENTS_API.md). Authenticated users create/list their own reports; service-authorized moderators list pending reports and verify/reject/expire them with an independent HTTPS evidence reference. No public admin UI or media uploads were added. This repo lacks a safe authenticated incident-upload facility. Pending reports never block routes; verified fresh exact-edge BLOCKED reports are critical/closed; FLOOD/ACCIDENT/OTHER are moderate with no invented depth. Duplicate evidence uses the strongest hazard, not an additive incident count. Rebuilt source/hash/node identity invalidates old attribution.

## Remaining blockers and external configuration

| Acceptance condition | Status | Required action |
| --- | --- | --- |
| Backend image security gate | FAIL | Consume patched distro/base packages when available or select and verify a compatible patched base. Current gate correctly blocks publish; do not silently waive47 HIGH findings |
| Existing graph proof and node identities | BLOCKED | Back up roads/calibration, rebuild OSRM and reimport original node IDs from the identical PBF in a maintenance window; do not fabricate a manifest for old artifacts. Mount the same complete graph read-only into OSRM/API |
| Camera rights/calibration for routing | BLOCKED | Existing inventory has no admitted routing/view-verification proof. Obtain permission and verify exact observed road/view and timestamp. Keep ingestion/routing flags false until then; viewing permission does not elevate them |
| Independent field model accuracy | BLOCKED | Obtain representative labelled day/night/weather datasets; model metadata is not independent ground truth |
| Google user consent and production OAuth callback | NOT_RUN | Real provider credentials/authorized HTTPS callback and a user-completed flow; synthetic QA sessions only validate local auth/application integration |
| Traffic provider live acceptance | BLOCKED without credentials | Optional TomTom/HERE keys, contractual rights and target-region validation; missing provider remains UNKNOWN |
| Staging host/environment | NOT_RUN | Dedicated Linuxx64 runner, protected GitHub staging environment/reviewers/main-only policy, approved commit/digests, domain/TLS, private env file, separate DB roles/volumes and backups |
| Production restore/rollback and load acceptance | NOT_RUN | Perform approved drills on target staging hardware and verify data retention, IAM, HTTPS, monitoring and measured load |

Safe defaults remain: camera ingestion/routing evidence disabled pending rights, no mock fallback in production, no inferred road flood from daily tide forecasts, no SAFE classification from absent evidence. Workers remain in the web process; use one ASGI process/container and scrape every replica, rather than assuming this is a new distributed queue platform.

## Run local / staging / production

Local development after a DB backup:

```sh
# Use private .env; generate separate secrets, never reuse these docs as credentials.
docker compose -p safepath-hackathon build backend frontend
docker compose -p safepath-hackathon run --rm --no-deps backend python -m alembic upgrade head
docker compose -p safepath-hackathon up -d
# http://localhost:3000 ; backend readiness /api/v1/ready
```

Use host OSRM port5001 on this Mac because5000 is occupied. Heavy builds on a small VM should stop OSRM first and restart/warm it before live acceptance. The deployment schema head is `20261108_07`; migrations are additive, retain user reports on application rollback, and production startup only checks revision. Do not automatically downgrade or restore over live data.

For graph install, follow [graph proof/import instructions](ROUTE_GRAPH_MATCHING.md). Existing PBF imports are not automatically rebuilt during app startup or this audit. Source rights, backup and camera view re-verification are required when graph topology changes.

Staging uses `docker-compose.prod.yml` + `docker-compose.staging.yml` with project `safepath-staging`, separate secrets/data/domain, immutable GHCR digests and the production security policy. Configure the protected environment/runner; trigger the manual staging workflow only after successful same-commit CI and compatible-migration review. It validates provenance/preflight, backup, explicit migration, app readiness and smoke tests; failure rolls application images back while retaining schema. First deployment requires provisioning dependencies/backups before this update workflow.

Production is **not authorized/executed by this task**. Follow [deployment/backup/rollback guide](DEPLOYMENT_PRODUCTION_GUIDE.md), resolve image/graph/rights blockers, complete staging acceptance and obtain deployment approval. Protect `/api/v1/metrics` with the service token, set alerts for5xx/503/latency/operation errors/dependency down/stale cameras, and scrape each single-process replica. Gauges expose unknown camera age as NaN rather than a fabricated zero. The `route_last_traffic_coverage_ratio` gauge describes the last assessed request, not population-wide coverage.

Scratch-only restore reproduction:

```sh
# Set SAFEPATH_REHEARSAL_DATABASE_URL privately to a safepath_(readiness_)qa_* DB.
python -m scripts.production.restore_rehearsal --container safepath-postgis --output-dir /private/scratch-backups
```

The script refuses non-QA names, restores only into a new random scratch DB, verifies table counts/revision/camera-permission hash, and drops the restored DB. It does not prove a production restore. Archive/checksum/retention/encryption and least-privilege roles must be configured operationally.

## Acceptance checklist

- [x] Implemented matching/risk/status positive and negative paths, tested on real disposable PostGIS.
- [x] Camera viewing/Overlay, auth restrictions and community persistence exercised in browser.
- [x] Local builds, mandatory lint/type/unit/regression and image scans executed.
- [x] Versioned additive migrations and scratch restore verified.
- [x] Protected publication/staging templates and redacted bounded metrics implemented.
- [ ] Backend HIGH vulnerability gate passes.
- [ ] Installed source-consistent graph and actual eligible camera evidence validated.
- [ ] Independent model field accuracy and target-host load accepted.
- [ ] Actual GitHub CI, approved staging deploy/HTTPS/OAuth/backup/rollback accepted.
- [ ] Production deployment authorized and accepted.

## Backend image findings (release blocked)

Trivy reported the following HIGH identifiers with no fixed Debian version. Package findings are deduplicated here by CVE; consult the JSON artifact for installed versions/details. No reachability or exploitability waiver was applied.

| CVE | Affected packages in image |
| --- | --- |
| CVE-2025-69720 | libncursesw6, libtinfo6, ncurses-base, ncurses-bin |
| CVE-2026-119373 | libsqlite3-0 |
| CVE-2026-119374 | libsqlite3-0 |
| CVE-2026-119379 | libsqlite3-0 |
| CVE-2026-16742 | libsystemd0, libudev1 |
| CVE-2026-54369 | libacl1 |
| CVE-2026-76642 | bsdutils, libblkid1, liblastlog2-2, libmount1, libsmartcols1, libuuid1, login, mount, util-linux |
| CVE-2026-78408 | bsdutils, libblkid1, liblastlog2-2, libmount1, libsmartcols1, libuuid1, login, mount, util-linux |
| CVE-2026-78409 | bsdutils, libblkid1, liblastlog2-2, libmount1, libsmartcols1, libuuid1, login, mount, util-linux |
| CVE-2026-78410 | bsdutils, libblkid1, liblastlog2-2, libmount1, libsmartcols1, libuuid1, login, mount, util-linux |
| CVE-2026-9538 | perl-base |

## Local development update

Local DB backup: `/tmp/safepath-local-before-hardening-20261108T074048.dump` (mode0600, pg_restore archive listing validated). Local schema migrated through07 before updating the two app containers. Existing graph/road records/camera permission grants were preserved; new node identity fields remain NULL pending a source-consistent reimport. Both development and production APIs mount the OSRM graph directory read-only. The shared directory mount does not itself prove an old graph. App rollback image IDs are recorded privately in `/tmp/safepath-hardening-local-rollback.json`; database downgrades are not automated. This is not a production deployment.

## Exact changed files

91 paths relative to repository root, including removed `.github/workflows/docker-image.yml`.

- `.env.example`
- `.github/actionlint.yaml`
- `.github/workflows/cd.yml`
- `.github/workflows/ci.yml`
- `.github/workflows/docker-image.yml`
- `README.md`
- `backend/app/api/community.py`
- `backend/app/core/auth.py`
- `backend/app/core/config.py`
- `backend/app/core/external_http.py`
- `backend/app/core/observability.py`
- `backend/app/db/community_models.py`
- `backend/app/db/models.py`
- `backend/app/main.py`
- `backend/app/schemas/contracts.py`
- `backend/app/services/camera_scheduler.py`
- `backend/app/services/community_incidents.py`
- `backend/app/services/hydrology_bulletin.py`
- `backend/app/services/risk_engine.py`
- `backend/app/services/route_camera_ai.py`
- `backend/app/services/route_matching.py`
- `backend/app/services/routing.py`
- `backend/app/services/traffic_providers/here.py`
- `backend/app/services/traffic_providers/tomtom.py`
- `backend/app/services/weather_tide.py`
- `backend/migrations/env.py`
- `backend/migrations/versions/20261108_04_graph_nodes.py`
- `backend/migrations/versions/20261108_05_community_incidents.py`
- `backend/migrations/versions/20261108_06_snapshot_freshness.py`
- `backend/migrations/versions/20261108_07_incident_graph_proof.py`
- `backend/tests/test_community_incidents.py`
- `backend/tests/test_database_migrations.py`
- `backend/tests/test_exact_route_matching.py`
- `backend/tests/test_external_http.py`
- `backend/tests/test_observability.py`
- `backend/tests/test_ops_infra.py`
- `backend/tests/test_production_infrastructure.py`
- `backend/tests/test_production_security.py`
- `backend/tests/test_security_scanner.py`
- `backend/tests/test_snapshot_persistence_regression.py`
- `backend/tests/test_traffic_intelligence_and_eta.py`
- `docker-compose.prod.yml`
- `docker-compose.staging.yml`
- `docker-compose.yml`
- `docker/backend.Dockerfile`
- `docs/AI_AND_DATABASE_AUDIT.md`
- `docs/COMMUNITY_INCIDENTS_API.md`
- `docs/DEPLOYMENT_PRODUCTION_GUIDE.md`
- `docs/PRODUCTION_READINESS.md`
- `docs/PRODUCTION_READINESS_REPORT.md`
- `docs/ROUTE_GRAPH_MATCHING.md`
- `frontend/Dockerfile`
- `frontend/e2e/ci-contracts.spec.ts`
- `frontend/e2e/community-live.spec.ts`
- `frontend/eslint.config.mjs`
- `frontend/package-lock.json`
- `frontend/package.json`
- `frontend/src/app/account/page.tsx`
- `frontend/src/app/api/v1/[...path]/route.ts`
- `frontend/src/app/dashboard/page.tsx`
- `frontend/src/app/news/page.tsx`
- `frontend/src/auth.ts`
- `frontend/src/components/CameraProxyModal.tsx`
- `frontend/src/components/CameraProxySnapshot.tsx`
- `frontend/src/components/CommunityReports.tsx`
- `frontend/src/components/MapContainer.tsx`
- `frontend/src/components/NavigationGuidance.tsx`
- `frontend/src/components/PlaceSearchCombobox.tsx`
- `frontend/src/components/RouteResults.tsx`
- `frontend/src/components/SpatialDashboard.tsx`
- `frontend/src/components/cinematic/NewsEditorialCards.tsx`
- `frontend/src/components/spatial/ObservationImage.tsx`
- `frontend/src/components/ui/AppPageHeader.tsx`
- `frontend/src/components/ui/ChromaticImage.tsx`
- `frontend/src/context/AuthContext.tsx`
- `frontend/src/lib/request-origin.ts`
- `frontend/src/lib/route-status.ts`
- `frontend/src/types/contracts.ts`
- `frontend/tests/request-origin.test.mjs`
- `frontend/tests/route-status.test.mjs`
- `frontend/tests/server-identity.test.mjs`
- `scripts/benchmark_vision.py`
- `scripts/build_osm_road_edges.sql`
- `scripts/import_osm_roads.sql`
- `scripts/ml/benchmark_flood_inference.py`
- `scripts/osm_roads.lua`
- `scripts/production/deploy_staging.py`
- `scripts/production/preflight.py`
- `scripts/production/restore_rehearsal.py`
- `scripts/security_and_redaction_check.py`
- `scripts/setup_osrm_hcm.sh`
