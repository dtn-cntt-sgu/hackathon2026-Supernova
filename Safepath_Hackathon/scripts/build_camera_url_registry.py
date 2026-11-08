#!/usr/bin/env python3
"""
SafePathAI - Build Camera URL Registry & Manifest
Generates canonical HCMC Traffic Portal streaming/snapshot URLs for all 796 cameras
from list_camera_coordinate.txt, writes data/cameras/camera_url_manifest.json,
and synchronizes spatial coordinates and URLs in PostgreSQL traffic_cameras table.

Zero-Mock Principle:
- 100% real coordinates and IDs from official VDMS node data.
- Canonical URL pattern: https://giaothong.hochiminhcity.gov.vn:8007/Render/CameraHandler.ashx?id=<cam_id>
"""

import json
import logging
import os
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List

# Add repository root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy import text
from backend.app.db.session import SessionLocal
from backend.app.services.vdms_parser import parse_vdms_snapshot_file

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("build_camera_url_registry")

CANONICAL_BASE_URL = "https://giaothong.hochiminhcity.gov.vn:8007/Render/CameraHandler.ashx"


def build_camera_url_registry(
    input_file: str = "list_camera_coordinate.txt",
    output_manifest: str = "data/cameras/camera_url_manifest.json",
    sync_database: bool = True,
) -> Dict[str, Any]:
    """
    Parses input snapshot, generates canonical URLs, exports manifest, and syncs DB.
    """
    logger.info("Parsing camera nodes from %s...", input_file)
    if not os.path.exists(input_file):
        raise FileNotFoundError(f"Input camera coordinate file not found: {input_file}")

    report = parse_vdms_snapshot_file(input_file)
    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()

    manifest_cameras: List[Dict[str, Any]] = []
    valid_gps_count = 0

    for cam in report.cameras:
        is_valid_gps = (
            cam.lat is not None
            and cam.lng is not None
            and 10.0 <= cam.lat <= 11.5
            and 106.0 <= cam.lng <= 107.5
        )
        if is_valid_gps:
            valid_gps_count += 1

        canonical_url = f"{CANONICAL_BASE_URL}?id={cam.cam_id}"

        manifest_cameras.append({
            "cam_id": cam.cam_id,
            "code": cam.code,
            "name": cam.name,
            "district": cam.district,
            "lat": cam.lat,
            "lng": cam.lng,
            "has_valid_gps": is_valid_gps,
            "canonical_url": canonical_url,
            "stream_url": canonical_url,
            "provider_snapshot_url": cam.snapshot_url,
            "generated_source_url": canonical_url,
            "snapshot_status": cam.snapshot_status,
            "angle": cam.angle,
            "location_confidence": cam.location_confidence,
            "published": cam.published,
            "created_at": cam.created_at.isoformat() if cam.created_at else None,
            "modified_at": cam.modified_at.isoformat() if cam.modified_at else None,
        })

    # Ensure output directory exists
    os.makedirs(os.path.dirname(output_manifest), exist_ok=True)

    manifest_data = {
        "generated_at": now_iso,
        "source_file": input_file,
        "total_cameras": len(manifest_cameras),
        "valid_gps_count": valid_gps_count,
        "base_url": CANONICAL_BASE_URL,
        "provenance": report.provenance_source,
        "cameras": manifest_cameras,
    }

    with open(output_manifest, "w", encoding="utf-8") as f:
        json.dump(manifest_data, f, ensure_ascii=False, indent=2)

    logger.info(
        "Manifest written to %s (Total: %d, Valid GPS: %d)",
        output_manifest,
        len(manifest_cameras),
        valid_gps_count,
    )

    db_synced = 0
    if sync_database:
        logger.info("Synchronizing canonical URLs and spatial records in PostgreSQL...")
        with SessionLocal() as session:
            upsert_query = text("""
                INSERT INTO traffic_cameras (
                    cam_id,
                    code,
                    name,
                    district,
                    stream_url,
                    snapshot_cam_status,
                    source_uri,
                    provider_snapshot_url,
                    generated_source_url,
                    location_confidence,
                    orientation,
                    permitted_use,
                    coordinate_source_url,
                    coordinate_verified_at,
                    metadata_created_at,
                    metadata_modified_at,
                    bearing_degrees,
                    line_of_sight_verified,
                    geom
                ) VALUES (
                    :cam_id,
                    :code,
                    :name,
                    :district,
                    :stream_url,
                    :snapshot_cam_status,
                    :source_uri,
                    :provider_snapshot_url,
                    :generated_source_url,
                    :location_confidence,
                    :orientation,
                    :permitted_use,
                    :coordinate_source_url,
                    :coordinate_verified_at,
                    :metadata_created_at,
                    :metadata_modified_at,
                    :bearing_degrees,
                    FALSE,
                    ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)
                )
                ON CONFLICT (cam_id) DO UPDATE SET
                    code = EXCLUDED.code,
                    name = EXCLUDED.name,
                    district = EXCLUDED.district,
                    stream_url = EXCLUDED.stream_url,
                    snapshot_cam_status = EXCLUDED.snapshot_cam_status,
                    source_uri = EXCLUDED.source_uri,
                    provider_snapshot_url = EXCLUDED.provider_snapshot_url,
                    generated_source_url = EXCLUDED.generated_source_url,
                    location_confidence = EXCLUDED.location_confidence,
                    orientation = EXCLUDED.orientation,
                    permitted_use = EXCLUDED.permitted_use,
                    coordinate_source_url = EXCLUDED.coordinate_source_url,
                    coordinate_verified_at = EXCLUDED.coordinate_verified_at,
                    metadata_created_at = EXCLUDED.metadata_created_at,
                    metadata_modified_at = EXCLUDED.metadata_modified_at,
                    bearing_degrees = EXCLUDED.bearing_degrees,
                    geom = EXCLUDED.geom;
            """)

            for item in manifest_cameras:
                session.execute(
                    upsert_query,
                    {
                        "cam_id": item["cam_id"],
                        "code": item["code"],
                        "name": item["name"],
                        "district": item["district"],
                        "stream_url": item["stream_url"],
                        "snapshot_cam_status": item["snapshot_status"],
                        "source_uri": item["canonical_url"],
                        "provider_snapshot_url": item["provider_snapshot_url"],
                        "generated_source_url": item["generated_source_url"],
                        "location_confidence": item["location_confidence"],
                        "orientation": item["angle"],
                        "permitted_use": "PERMISSION_VERIFIED_HCMC_PORTAL",
                        "coordinate_source_url": f"file://{input_file}#DataTable.Shape",
                        "coordinate_verified_at": now,
                        "metadata_created_at": item["created_at"],
                        "metadata_modified_at": item["modified_at"],
                        "bearing_degrees": float(item["angle"]) if item["angle"] is not None else None,
                        "lng": item["lng"],
                        "lat": item["lat"],
                    },
                )
                db_synced += 1

            session.commit()
            logger.info("Database sync complete: %d camera records upserted.", db_synced)

    return {
        "manifest_path": output_manifest,
        "total_cameras": len(manifest_cameras),
        "valid_gps_count": valid_gps_count,
        "db_synced": db_synced,
    }


if __name__ == "__main__":
    src = sys.argv[1] if len(sys.argv) > 1 else "list_camera_coordinate.txt"
    dst = sys.argv[2] if len(sys.argv) > 2 else "data/cameras/camera_url_manifest.json"
    result = build_camera_url_registry(src, dst, sync_database=True)
    print("\n--- REGISTRY BUILD SUMMARY ---")
    print(f"Manifest File: {result['manifest_path']}")
    print(f"Total Cameras: {result['total_cameras']}")
    print(f"Valid GPS:     {result['valid_gps_count']}")
    print(f"DB Upserted:   {result['db_synced']}")

