# AI and database evidence audit — 8 November 2026

This is a bounded local audit, not production certification or model accuracy
validation. No production snapshot/derivative, model, database row or schema was
changed. Database statements ran in an explicit read-only transaction with a
10-second statement timeout.

## Real ONNX execution — PASS

Evidence: `/tmp/safepath-ai-audit-20261108.json`, transcript
`/tmp/safepath-ai-audit-run.log`, reproducible local harness
`/tmp/safepath_ai_audit.py`. These local files are temporary and are not published.

The original public traffic snapshot
`storage/cams/58175c81edeb6c0012a2d5c2.jpg` is 306×236, 17,274 bytes,
SHA-256 `6e62dad00e31ebe7b2026488bc46d70203757f39178265650897aab608986174`.
The validator returned VALID. Visual inspection confirmed an actual intersection,
no TEST FRAME label and no identifiable person visible. The source file hash was
checked unchanged after inference. No overlay was generated or persisted.

Hardware/runtime: Darwin arm64, 8 logical CPUs, ONNX Runtime 1.31.0. The benchmark
explicitly selected CPUExecutionProvider, two intra-operation threads and one
inter-operation thread. Available CoreML/Azure providers were not benchmarked.
The application preprocessing, multiscale vehicle detector and flood segmentation
methods ran with heuristic fallback disabled. Each model had one warmup followed
by six measured calls; initialization and an additional tensor verification were
outside measured calls.

| Model | Verified input → output (float32) | Initialization | p50 | p95 | p99 |
|---|---|---:|---:|---:|---:|
| VGG16 SSD HCMC | images [1,3,300,300] → output0 [1,8732,9] | 89.142 ms | 370.059 ms | 386.071 ms | 387.984 ms |
| Flood U-Net | input [1,3,256,256] → output [1,1,256,256] | 2.797 ms | 12.076 ms | 12.758 ms | 12.767 ms |

Both actual tensors matched manifest names/shapes/dtypes; raw outputs contained
finite values. Both constructors reported VERIFIED_ONNX_INFERENCE and matched
manifest SHA-256 hashes. Whole-process peak RSS was **395.91 MiB**, including both
models and Python/OpenCV runtime. This is not per-model/container RSS or a memory
limit under concurrent load.

This frame yielded zero detected vehicles and suspected-water pixel ratio 0.073.
Without labeled ground truth these are inference outputs, not accuracy findings,
water depth, verified road flooding or route safety evidence. Six samples from
one nighttime frame cannot establish a latency SLA, robust p99, field precision,
recall, rain/night performance or production throughput.

## Existing benchmark/manifest limitations

- `scripts/ml/benchmark_flood_inference.py` uses random synthetic tensors. Its
  printed 50-ms “SLA compliance” is a configured microbenchmark threshold, not an
  accepted end-to-end production SLA or field validation.
- `scripts/benchmark_yolo26_hcmc.py` has a historical YOLO26 name/comments although
  current manifest and runtime use VGG16 SSD HCMC. It must not be cited as proof
  that the production checkpoint is YOLO26.
- The manifest explicitly records flood field calibration as
  PENDING_LIVE_FIELD_CALIBRATION and an 80-frame controlled synthetic/curated
  validation split. Its PRODUCTION_HCMC_ROAD_SURFACE label does not establish
  independent real-world field accuracy. No new accuracy claim is made here.
- Representative multi-camera/night/rain/reflective-road annotated evaluation,
  accelerated providers, container limits and concurrent queue pressure: NOT_RUN.

## Read-only database plans — PASS / BLOCKED

Evidence: `/tmp/safepath-db-audit-20261108.json`; harness
`/tmp/safepath_db_audit.py`. Credentials and personal rows were not logged.

Working development database has eleven relevant road indexes, including GiST
indexes on `road_edges.geom`, `road_edges.geom::geography`, road segment equivalents
and the unique `(osm_way_id, edge_index)` primary key. EXPLAIN (ANALYZE, BUFFERS,
FORMAT JSON) for the actual 8-metre geography candidate predicate used
**Index Scan on idx_road_edges_geog**, not a sequential table scan.

| Probe | Rows | Planning | Execution | Buffers |
|---|---:|---:|---:|---|
| HCMC point 10.795,106.7218 | 0 | 35.587 ms | 2.117 ms | 36 hit / 2 read |
| Midpoint of an existing imported edge | 1 | 0.202 ms | 79.482 ms | 70 hit / 8 read |

These are individual cold/warm cache observations, not route-query p95 or load
measurements. A zero-row point says nothing about complete graph coverage.

**BLOCKED:** the working development database has no Alembic marker and lacks
revision-04 source/target OSM node columns. No migration was attempted. A meaningful
EXPLAIN for the new exact-node-pair matching query requires an approved migrated
and reimported database from the verified same-PBF graph. Empty/synthetic node
fixtures would not establish production plan performance; no such claim is made.

## Security inspection

Read-only code inspection confirmed NextAuth Google OIDC discovery with PKCE/state
checks, session cookies defaulting to HttpOnly/SameSite=Lax and Secure for configured
HTTPS NEXTAUTH_URL. Backend session tokens bind issuer, audience, HMAC and expiry;
proxy assertions have bounded clock skew. The REST proxy strips caller-supplied
identity signatures and adds trusted assertions after session validation, with an
Origin check on cookie-authenticated mutations. Real Google callback/cookie
round-trip and two-account browser ownership tests were NOT_RUN in this audit.

Two findings were sent to the parent agent for fixes/review rather than editing
its files concurrently: Google sign-in accepts missing email_verified instead of
requiring explicit true; legacy profile/preferences/saved-place/history endpoints
lack the inactive-user rejection already present in community authorization.
Final resolution and regression evidence belong in the consolidated readiness
report.

Targeted regression: manifest/integrity tests plus
`backend/tests/test_phase5_truth_and_models.py` ran with the existing isolated QA
context: **8 PASS in 13.71 seconds**. Synthetic unit fixtures remain test-only;
they are separate from the real stored-frame benchmark above.

## Local schema update after these measurements

The local development DB was subsequently backed up and additively migrated through `20261108_07`. Road records were preserved:343,610 ways and1,858,355 edges, with0 imported original node identities. Exact-node production-plan/attribution acceptance therefore still requires a verified reimport and build-produced graph manifest. The earlier unversioned-schema observation describes the measurement time, not the current schema revision.
