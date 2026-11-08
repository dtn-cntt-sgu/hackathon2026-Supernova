# Production evidence and Route AI audit

## Scope and reproduction

Read-only inventory captured **8 November 2026, 03:14:49 Asia/Ho_Chi_Minh** (`2026-11-07T20:14:49.877925+00:00`) against the existing local PostgreSQL registry, ingestion state and immutable snapshot records/files. Configuration values below come from the repository's current local settings, not a claim about a remote production deployment.

```sh
python -m scripts.production_evidence_audit
```

Output saved at `/tmp/safepath-production-camera-inventory.json`. The script performs no database writes or camera-provider requests. Optional `--route-base-url http://localhost:8010 --samples 5` sends at most five actual route searches to an explicitly supplied loopback test API. Run it only after that updated test stack is healthy. No city-wide image fetch or inference sweep is needed for this inventory.

## Exact camera inventory

| Condition | Count | Meaning |
|---|---:|---|
| Total registry cameras | 796 | Database records |
| Valid GPS geometry | 796 | Valid geometry, WGS84 longitude/latitude bounds |
| Coordinate provenance fields present | 796 | Nonempty coordinate source URL and verification timestamp; not a new independent revalidation of every external source |
| Verified view provenance | 0 | Nonempty view source, verification timestamp, line-of-sight verification and observed way/edge identity |
| Routing use permitted | 0 | Exact `ROUTING_EVIDENCE_PERMITTED` value |
| Permission unverified | 796 | All registry records remain `PERMISSION_UNVERIFIED` |
| Latest immutable originals recorded | 706 | Distinct camera IDs with latest snapshot rows |
| Latest original files present on this host | 706 | Referenced local files exist; this audit does not certify current capture time or revalidate every image's content |
| Ingestion metadata `LIVE` | 706 | Stored historical scheduler status; **not** a claim of current live provider availability |
| Ingestion metadata `PLACEHOLDER` | 90 | Stored validation result |
| Registry permission + view + matching imported edge ready | 0 | Necessary spatial/provenance prerequisites |
| Fresh capture/retrieval + original + registry prerequisites | 0 | Both timestamps must satisfy the configured 120-second limit |
| Route AI eligible with current configuration | 0 | No permission flags were enabled or registry values upgraded |

A read of `/api/v1/cameras` on the existing local service independently returned 796 entries with 706 `has_image` flags. Those flags describe stored metadata, not a live scan of Vietmap or a guarantee that 706 images are fresh. No arbitrary permission or source timestamp was modified to improve these counts.

**Current operational state: `BLOCKED_BY_EVIDENCE`.** Honest OSRM route results may still be returned with `UNKNOWN` risk. Live visual routing readiness cannot be established until real source permissions, verified camera views, exact route-segment correspondence and fresh captures are available.

## Configuration observed

| Setting | Value |
|---|---|
| `CAMERA_AI_MODE` | `route_only` |
| `ROUTE_CAMERA_AI_ENABLED` | `true` |
| `CAMERA_INGESTION_PERMITTED` | `false` |
| `CAMERA_ROUTING_EVIDENCE_PERMITTED` | `false` |
| `CAMERA_VIEW_AI_ENABLED` | `false` |
| `ROUTE_AI_MAX_CAMERAS` | `4` |
| `ROUTE_AI_MAX_CONCURRENCY` | `2` |
| `ROUTE_AI_TIMEOUT_SECONDS` | `8` |

These are configuration states, not an authorization to collect or reuse provider content. Rights/licence approval remains an external prerequisite. There are no secrets in this inventory.

## Route pipeline and performance findings

`find_safe_route()` obtains real OSRM candidates, batches PostGIS road-edge/camera corridor context, reads weather/news and existing evidence, calls bounded route-only enrichment, then evaluates risk/ranking. The current pipeline uses two spatial queries across candidate steps and a Redis `MGET` for camera evidence, rather than one camera query per step. Geographic expression GiST indexes on `road_edges`, `road_segments` and verified `traffic_cameras` are present in the local database and created by `scripts/import_osm_roads.sql` / `scripts/build_osm_road_edges.sql`; the road-import procedure is therefore part of fresh-server readiness.

The route inference service has a shared lazy model instance, four-camera per-request budget, two executing native slots, bounded pending work, camera/snapshot/model cache identity, local single-flight and Redis leases. A timed-out native call retains its executing slot until completion. Snapshot acquisition rejects unknown/old capture times; repeatedly retrieving the same unknown-time frame cannot make it fresh. Insufficient model/evidence results leave risk unknown.

Three defects were reported to the integration owner for direct fixes and regression verification:

1. **OSRM provider provenance:** `_get_osrm_raw_routes()` silently switched from `localhost:5001` to `router.project-osrm.org` on connection failure while the downstream cache/spatial interpretation retained local graph assumptions. Production must fail with `503 ROUTING_PROVIDER_UNAVAILABLE` unless an explicitly separate, provenance-aware provider path is implemented. Silent public fallback is unacceptable.
2. **Candidate edge versus verified route edge:** the spatial loader explicitly treats edges within eight metres as unverified candidates, but later code preferred a candidate matching a camera's observed way and passed that identity to Risk Engine. Membership in this candidate set cannot prove that the route traverses that exact carriageway, especially for parallel/stacked roads. Inference and route-risk eligibility must remain blocked until independent exact correspondence is verified. A verified camera view alone does not verify the OSRM step mapping.
3. **Duplicate frontend polling:** `useLiveObservations.refresh()` had no in-flight guard, allowing a visibility change during an outstanding request to create another polling chain. `revision > 0` also caused every subsequent sweep to reload the full camera registry after the first manual refresh. Use one polling chain and a one-shot manual refresh condition. Existing `CameraProxySnapshot` already bounds requests, uses intersection visibility, aborts fetches on cleanup and avoids hidden-tab image refresh.

The final readiness report must state the verified regression result for each fix; an audit finding alone is not proof of repair.

## Benchmark limits

An initial five-request local sample overlapped Docker rebuild/OSRM shutdown. Three route requests returned HTTP 200 with `overall_risk=UNKNOWN`, `ROUTE_FOUND_RISK_UNKNOWN`, 14 segments and one alternative; two returned HTTP 503. Recorded elapsed times included approximately 32.5, 6.4 and 8.9 seconds during resource contention. These measurements are **not accepted as a stable latency benchmark or production SLA evidence**. They demonstrate graceful failure/unknown-state responses on the old running service, not acceptance of the updated image.

Raw output: `/tmp/safepath-production-evidence-audit.json`. Updated-image timing, including success rates and a clearly labelled small-sample p50/p95, must be captured after the isolated test backend is started. No favourable latency numbers were invented or inferred from unit mocks.

No production endpoint/domain, production source rights, server capacity or real-world camera routing-eligibility claim was verified by this audit. No production migration, commit, push or deployment was performed.

## Integration outcome

The integration fixed all three reported defects: public OSRM fallback removed, candidate edges require independently verified step correspondence before inference/scoring, and observation polling has one active refresh chain/one-shot registry fetching. Current route responses expose `BLOCKED_BY_EVIDENCE`. Final default backend436PASS/15SKIP, separate liveOSRM/GIS18PASS, current Docker-image browser11PASS. Full evidence, cold/warm smoke timings and limitations are in `PRODUCTION_READINESS_REPORT.md`; the old benchmark above remains historical and invalid for acceptance.
