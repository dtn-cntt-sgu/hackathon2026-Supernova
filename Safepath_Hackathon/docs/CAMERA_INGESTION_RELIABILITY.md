# SAFEPATHAI — 796-CAMERA INGESTION RELIABILITY & CORRIDOR PRIORITIZATION

**Author:** Principal Distributed Systems Engineer, Senior Backend Architect  
**Project:** SafePathAI (Phase P0: Complete Camera Ingestion & Corridor Routing)  
**Date:** October 2026  
**Status:** Implemented · Multi-Tier Queued · PostGIS Corridor Filtered · Verified

---

## 1. Executive Summary

SafePathAI monitors traffic and road flood conditions across a verified registry of **796 PostGIS camera nodes** spanning Ho Chi Minh City. Ensuring continuous freshness without starving inactive nodes or overloading compute requires a robust ingestion and queueing architecture.

In Phase P0, the camera ingestion engine was fortified with:
1. **Multi-Tier Dynamic Prioritization (Tiers 0–3)** ensuring active modal views and route corridors receive top-priority 60-second updates, while the background pool rotates fairly without starvation.
2. **Atomic Disk Snapshot Storage** replacing direct writes with temporary files (`.tmp`), sync flushing, and atomic POSIX replacement (`os.replace`) to eliminate file corruption under concurrent read requests.
3. **Last Known Good (LKG) Preservation** preventing `evict_stale_disk_images` from deleting valid snapshots of inactive or offline cameras.
4. **4 Distinct Timestamps** (`last_attempt_at`, `last_success_at`, `last_retrieved_at`, `last_captured_at`) enforcing strict Zero-Mock data provenance.
5. **Route-Aware Corridor Scoping** using PostGIS spatial queries (`ST_DWithin`) to dynamically register corridor cameras into Tier 1 and focus computer vision inference exclusively along commuters' routes.
6. **Telemetry & Admin Observability** via `/api/v1/admin/cameras/metrics`.

---

## 2. Multi-Tier Prioritization Hierarchy

```
[Tier 0: Actively Viewed] ──> Modal Open / Viewport (Redis ZSet: active_viewed_cameras_zset, TTL: 90s, Target: 60s)
           │
           ▼
[Tier 1: Route Corridor]  ──> PostGIS ST_DWithin Buffer (Redis ZSet: active_route_cameras_zset, TTL: 900s, Target: 60-120s)
           │
           ▼
[Tier 2: Stale Refresh]   ──> Existing Valid Snapshot older than TTL (Target: 180-300s)
           │
           ▼
[Tier 3: Fair Round-Robin] ──> Full 796-Node PostGIS Pool (Ordered by last_attempt_at ASC, No Starvation)
```

### Redis Authoritative State:
- `active_viewed_cameras_zset`: Member = `cam_id`, Score = Epoch UTC expiration timestamp. Auto-pruned via `zremrangebyscore("-inf", now)`.
- `active_route_cameras_zset`: Member = `cam_id`, Score = Epoch UTC expiration timestamp. Auto-pruned via `zremrangebyscore("-inf", now)`.
- Distributed Lease: `camera:lease:{cam_id}` acquired via `SET NX EX 120` prevents concurrent worker collisions.

---

## 3. Storage Architecture: Atomic Swap & LKG Preservation

### Non-Atomic vs Atomic File Write

| Dimension | Legacy Direct Write | Phase P0 Atomic Swap |
| :--- | :--- | :--- |
| **I/O Mechanism** | `with open(path, "wb") as f: f.write(...)` | `with open(tmp, "wb"): write -> flush -> fsync; os.replace(tmp, path)` |
| **Race Conditions** | High risk (User receives partial/corrupt JPEG while writing) | Zero risk (File inode swapped atomically by POSIX kernel) |
| **Eviction Policy** | Blindly deleted all files older than 24h by `getmtime` | Strictly preserves active snapshot of all registered cameras; only cleans stale `.tmp` files |
| **Offline Fallback** | Failed if file evicted (reported black screen) | Fallback smoothly serves Last Known Good image with `source_status = STALE` |

---

## 4. Route-Aware Corridor PostGIS Integration

When a user calculates a route (origin to destination), SafePathAI executes a batched spatial query across all route steps:

```sql
SELECT s.route_idx, s.step_idx, c.cam_id, c.code, c.name, c.district,
       ST_Y(c.geom) AS lat, ST_X(c.geom) AS lng,
       c.nearest_osm_way_id AS osm_way_id, c.coordinate_source_url
FROM step_lines s JOIN traffic_cameras c
  ON c.geom IS NOT NULL AND c.coordinate_source_url IS NOT NULL
 AND c.coordinate_verified_at IS NOT NULL
 AND ST_DWithin(c.geom::geography, s.geog, 100.0);
```

### Zero-Mock Efficiency:
1. Matching corridor camera IDs are automatically promoted to Tier 1 via `register_active_route_cameras(unique_ids)`.
2. AI inference (YOLO26n vehicle counting and FloodUNet water segmentation) is scheduled **only** for these corridor cameras. Non-route cameras in distant districts are not subjected to wasteful inference during route planning.

---

## 5. Telemetry & Admin Endpoints

- **Endpoint:** `GET /api/v1/admin/cameras/metrics` (alias `/api/v1/admin/camera-ingestion/status`)
- **Key Metrics Returned:**
  - `total_registered_cameras`: 796 verified PostGIS nodes.
  - `geolocated_cameras`: 796 nodes with EPSG:4326 coordinates.
  - `live_cameras`: Cameras with fresh verified snapshots.
  - `stale_cameras`: Cameras utilizing Last Known Good fallback.
  - `offline_cameras`: Cameras with consecutive network timeouts.
  - `placeholder_frames_excluded`: Count of rejected "IMAGE NOT AVAILABLE" frames.
  - `active_viewed_cameras_count`: Number of cameras currently open in client viewports.
  - `active_route_cameras_count`: Number of cameras currently inside navigation corridors.
  - `error_breakdown`: Aggregated count by HTTP / network error codes.

---

## 6. Automated Test Verification

Execution results from `backend/tests/test_camera_ingestion_complete.py` and `backend/tests/test_route_camera_corridor.py`:
- `test_atomic_file_replacement` — **PASSED** (write-to-temp + os.replace verified).
- `test_last_known_good_preservation` — **PASSED** (LKG snapshot preserved across eviction).
- `test_scheduler_starvation_free_rotation` — **PASSED** (acquire_batch advances candidate rotation without overlap).
- `test_circuit_breaker_resilience` — **PASSED** (trips on repeated errors, resets on recovery).
- `test_admin_cameras_metrics_endpoint` — **PASSED** (returns 200 OK with full metric schema).
- `test_corridor_postgis_camera_matching` — **PASSED** (ST_DWithin identifies corridor nodes).
- `test_route_corridor_scheduler_tier1_elevation` — **PASSED** (corridor camera elevated to Tier 1).

