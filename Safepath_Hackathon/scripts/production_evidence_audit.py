"""Read-only local evidence inventory; optional real-route timing, never bulk-fetch cameras."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import statistics
import time
from urllib.parse import urlsplit

import httpx
from sqlalchemy import text

from backend.app.core.config import settings
from backend.app.db.session import sync_engine


def inventory() -> dict:
    with sync_engine.connect() as connection:
        counts = dict(connection.execute(text("""
            SELECT count(*) AS total,
              count(*) FILTER (WHERE geom IS NOT NULL AND ST_IsValid(geom)
                AND ST_Y(geom) BETWEEN -90 AND 90 AND ST_X(geom) BETWEEN -180 AND 180) AS valid_gps,
              count(*) FILTER (WHERE coordinate_source_url IS NOT NULL AND coordinate_source_url <> ''
                AND coordinate_verified_at IS NOT NULL) AS coordinate_proof,
              count(*) FILTER (WHERE view_verification_source_url IS NOT NULL
                AND view_verification_source_url <> '' AND view_verified_at IS NOT NULL
                AND line_of_sight_verified IS TRUE AND observed_osm_way_id IS NOT NULL
                AND observed_edge_index IS NOT NULL) AS view_proof,
              count(*) FILTER (WHERE permitted_use = 'ROUTING_EVIDENCE_PERMITTED') AS routing_permission
            FROM traffic_cameras
        """)).mappings().one())
        counts["permission_distribution"] = dict(connection.execute(text(
            "SELECT COALESCE(permitted_use, 'NULL_UNVERIFIED'), count(*) FROM traffic_cameras GROUP BY permitted_use"
        )).all())
        counts["stored_ingestion_statuses"] = dict(connection.execute(text(
            "SELECT source_status, count(*) FROM camera_ingestion_state GROUP BY source_status"
        )).all())
        snapshots = connection.execute(text("""
            SELECT DISTINCT ON (s.camera_id) s.camera_id, s.file_path, s.source_captured_at,
                   s.fetched_at, s.content_sha256, c.permitted_use,
                   (c.geom IS NOT NULL AND c.coordinate_source_url IS NOT NULL
                    AND c.coordinate_source_url <> '' AND c.coordinate_verified_at IS NOT NULL) AS coordinates_verified,
                   (c.view_verification_source_url IS NOT NULL AND c.view_verification_source_url <> ''
                    AND c.line_of_sight_verified IS TRUE AND c.view_verified_at IS NOT NULL) AS view_verified,
                   EXISTS (SELECT 1 FROM road_edges e JOIN road_segments r USING(osm_way_id)
                     WHERE e.osm_way_id=c.observed_osm_way_id AND e.edge_index=c.observed_edge_index
                       AND r.source_url='https://download.geofabrik.de/asia/vietnam-latest.osm.pbf') AS existing_observed_edge
            FROM camera_snapshots s JOIN traffic_cameras c ON c.cam_id=s.camera_id
            WHERE s.is_latest IS TRUE ORDER BY s.camera_id, s.created_at DESC
        """)).mappings().all()
        registry_edge_ready = connection.scalar(text("""
            SELECT count(*) FROM traffic_cameras c
            WHERE c.permitted_use='ROUTING_EVIDENCE_PERMITTED'
              AND c.geom IS NOT NULL AND c.coordinate_source_url IS NOT NULL AND c.coordinate_verified_at IS NOT NULL
              AND c.view_verification_source_url IS NOT NULL AND c.view_verified_at IS NOT NULL
              AND c.line_of_sight_verified IS TRUE
              AND EXISTS (SELECT 1 FROM road_edges e JOIN road_segments r USING(osm_way_id)
                WHERE e.osm_way_id=c.observed_osm_way_id AND e.edge_index=c.observed_edge_index
                  AND r.source_url='https://download.geofabrik.de/asia/vietnam-latest.osm.pbf')
        """))
        counts["registry_and_edge_ready"] = registry_edge_ready
    now = datetime.now(timezone.utc)
    def fresh(value):
        return value is not None and value.tzinfo is not None and 0 <= (now-value).total_seconds() <= settings.ROUTE_AI_MAX_FRAME_AGE_SECONDS
    stored_files = [row for row in snapshots if row.file_path and Path(row.file_path).is_file()]
    frame_ready = [row for row in stored_files if fresh(row.source_captured_at) and fresh(row.fetched_at)
                   and row.content_sha256 and row.permitted_use == "ROUTING_EVIDENCE_PERMITTED"
                   and row.coordinates_verified and row.view_verified and row.existing_observed_edge]
    flags = {name: getattr(settings, name) for name in (
        "CAMERA_AI_MODE", "ROUTE_CAMERA_AI_ENABLED", "CAMERA_INGESTION_PERMITTED",
        "CAMERA_ROUTING_EVIDENCE_PERMITTED", "CAMERA_VIEW_AI_ENABLED",
        "ROUTE_AI_MAX_CAMERAS", "ROUTE_AI_MAX_CONCURRENCY", "ROUTE_AI_TIMEOUT_SECONDS")}
    enabled = (flags["CAMERA_AI_MODE"] == "route_only" and flags["ROUTE_CAMERA_AI_ENABLED"]
               and flags["CAMERA_INGESTION_PERMITTED"] and flags["CAMERA_ROUTING_EVIDENCE_PERMITTED"])
    counts.update(latest_stored_snapshot_cameras=len(snapshots), stored_original_files_present=len(stored_files),
                  fresh_frame_and_registry_ready=len(frame_ready),
                  route_ai_eligible_with_config=len(frame_ready) if enabled else 0,
                  flags=flags, status="BLOCKED_BY_EVIDENCE" if not enabled or not frame_ready else "REQUIRES_ROUTE_CORRIDOR_MATCH",
                  image_count_scope="Stored immutable originals on this host only; not a live-provider availability survey",
                  inventory_at=now.isoformat())
    assert sum(counts["permission_distribution"].values()) == counts["total"]
    assert counts["route_ai_eligible_with_config"] <= counts["fresh_frame_and_registry_ready"] <= counts["total"]
    return counts


def benchmark(base_url: str, samples: int) -> dict:
    url = urlsplit(base_url)
    if url.scheme not in ("http", "https") or url.hostname not in ("localhost", "127.0.0.1", "::1") or url.username or url.password:
        raise ValueError("Route benchmark is restricted to an explicitly supplied local test API")
    if not 1 <= samples <= 5:
        raise ValueError("Route benchmark is limited to five samples")
    payload = {"origin": {"lat": 10.7725, "lng": 106.6980},
               "destination": {"lat": 10.7950, "lng": 106.7218}, "transport_mode": "car"}
    results = []
    with httpx.Client(base_url=base_url, timeout=45, follow_redirects=False) as client:
        for _ in range(samples):
            start = time.perf_counter()
            response = client.post("/api/v1/routes/search", json=payload)
            elapsed = round((time.perf_counter()-start)*1000, 2)
            body = response.json()
            results.append({"http_status": response.status_code, "latency_ms": elapsed,
                            "risk": body.get("overall_risk"), "route_status": body.get("route_status"),
                            "alternatives": len(body.get("alternative_routes") or []),
                            "segments": len(body.get("segments") or [])})
    durations = sorted(item["latency_ms"] for item in results)
    return {"samples": results, "p50_ms": statistics.median(durations),
            "p95_nearest_rank_ms": durations[math.ceil(.95*len(durations))-1],
            "note": "Small local smoke benchmark, includes first request and subsequent cache use; not a load/SLA result"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--route-base-url", help="Optional running local API; sends up to five real route searches")
    parser.add_argument("--samples", type=int, choices=range(1, 6), default=5)
    args = parser.parse_args()
    result = {"inventory": inventory()}
    if args.route_base_url:
        result["route_benchmark"] = benchmark(args.route_base_url, args.samples)
    print(json.dumps(result, indent=2))
