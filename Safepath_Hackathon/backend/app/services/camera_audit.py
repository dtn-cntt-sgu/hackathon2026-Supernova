"""
SafePathAI Camera Snapshot Audit & Quarantine Engine.

Scans storage/cams for corrupted, placeholder, or mismatched camera frames:
- Identifies 'IMAGE NOT AVAILABLE' placeholder frames and variants.
- Quarantines invalid files safely into storage/quarantine/placeholders/ with manifest.json.
- Synchronizes PostgreSQL camera_ingestion_state (clearing false LIVE statuses and false AI results).
- Invalidates stale/poisoned Redis evidence keys and URL strategies.
- Preserves 100% of authentic street camera snapshots without data loss.
"""

import asyncio
from datetime import datetime, timezone
import hashlib
import json
import logging
import os
import shutil
from typing import Any, Dict, List, Optional, Set, Tuple
from sqlalchemy import text

from backend.app.db.session import AsyncSessionLocal, get_redis_client
from backend.app.services.image_validator import (
    ImageValidationStatus,
    validate_camera_image_bytes,
)

logger = logging.getLogger("safepath.camera_audit")


async def run_camera_storage_audit(
    storage_dir: str = "storage/cams",
    quarantine_dir: str = "storage/quarantine/placeholders",
    dry_run: bool = False,
) -> Dict[str, Any]:
    """
    Executes a complete audit and quarantine sweep across storage/cams.
    """
    now = datetime.now(timezone.utc)
    os.makedirs(storage_dir, exist_ok=True)
    os.makedirs(quarantine_dir, exist_ok=True)

    manifest_path = os.path.join("storage/quarantine", "manifest.json")
    existing_manifest: List[Dict[str, Any]] = []
    if os.path.exists(manifest_path):
        try:
            with open(manifest_path, "r", encoding="utf-8") as f:
                existing_manifest = json.load(f)
        except Exception:
            existing_manifest = []

    # 1. Discover all unique camera IDs from files in storage_dir
    files = [f for f in os.listdir(storage_dir) if f.endswith(".jpg") or f.endswith(".png")]
    cam_ids: Set[str] = set()
    for fname in files:
        base = fname.split(".")[0]
        for suffix in ("_enhanced", "_analyzed", "_annotated"):  # Exclude legacy derivatives from original evidence.
            if base.endswith(suffix):
                base = base[:-len(suffix)]
        if base:
            cam_ids.add(base)

    logger.info("Auditing %d camera IDs across %d files...", len(cam_ids), len(files))

    quarantined_cameras: List[str] = []
    quarantined_files_total: int = 0
    valid_cameras: List[str] = []
    new_manifest_entries: List[Dict[str, Any]] = []

    redis = get_redis_client()

    for cam_id in sorted(cam_ids):
        raw_path = os.path.join(storage_dir, f"{cam_id}.jpg")
        analyzed_path = os.path.join(storage_dir, f"{cam_id}_analyzed.jpg")
        annotated_path = os.path.join(storage_dir, f"{cam_id}_annotated.jpg")

        is_raw_placeholder = False
        rejection_reason = "VALID_FRAME"

        # Check raw image if present
        if os.path.exists(raw_path):
            with open(raw_path, "rb") as f:
                raw_bytes = f.read()
            val = validate_camera_image_bytes(raw_bytes)
            if not val.is_valid:
                is_raw_placeholder = True
                rejection_reason = f"{val.status.value}: {val.error_message}"

        # If raw image is missing or a confirmed placeholder, all associated files must be quarantined
        if is_raw_placeholder:
            quarantined_cameras.append(cam_id)
            target_files = []
            for candidate in (raw_path, analyzed_path, annotated_path):
                if os.path.exists(candidate):
                    target_files.append(candidate)

            manifest_entry = {
                "cam_id": cam_id,
                "quarantined_at": now.isoformat(),
                "reason": rejection_reason,
                "files": [os.path.basename(p) for p in target_files],
            }
            new_manifest_entries.append(manifest_entry)

            if not dry_run:
                for src in target_files:
                    dst = os.path.join(quarantine_dir, os.path.basename(src))
                    shutil.move(src, dst)
                    quarantined_files_total += 1

                # Invalidate in Redis
                try:
                    await redis.delete(f"camera:evidence:{cam_id}")
                    await redis.delete(f"camera:url_strategy:{cam_id}")
                    await redis.srem("active_viewed_cameras", cam_id)
                    await redis.srem("active_route_cameras", cam_id)
                except Exception as exc:
                    logger.debug("Redis cleanup for %s: %s", cam_id, exc)
        else:
            # Raw image is valid! Check if any derivative files contain residual placeholders
            valid_cameras.append(cam_id)
            for deriv_path in (analyzed_path, annotated_path):
                if os.path.exists(deriv_path):
                    with open(deriv_path, "rb") as f:
                        deriv_bytes = f.read()
                    d_val = validate_camera_image_bytes(deriv_bytes)
                    if d_val.status == ImageValidationStatus.PLACEHOLDER_ERROR_FRAME:
                        # Derivative is contaminated! Quarantine it
                        if not dry_run:
                            dst = os.path.join(quarantine_dir, os.path.basename(deriv_path))
                            shutil.move(deriv_path, dst)
                            quarantined_files_total += 1

    # 2. Update PostgreSQL camera_ingestion_state for quarantined cameras
    if not dry_run and quarantined_cameras:
        async with AsyncSessionLocal() as session:
            # Batch update quarantined cameras in DB
            stmt = text("""
                UPDATE camera_ingestion_state
                SET source_status = 'OFFLINE',
                    validation_status = 'PLACEHOLDER_FRAME',
                    cached_image_path = NULL,
                    image_hash = NULL,
                    last_success_at = NULL,
                    model_status = 'MODEL_UNAVAILABLE',
                    failure_reason = 'Server returned IMAGE NOT AVAILABLE placeholder frame (Audited & Quarantined)'
                WHERE cam_id = ANY(:cams)
            """)
            await session.execute(stmt, {"cams": quarantined_cameras})
            await session.commit()

    # 3. Save updated manifest
    if not dry_run and new_manifest_entries:
        all_manifest = existing_manifest + new_manifest_entries
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(all_manifest, f, indent=2, ensure_ascii=False)

    await redis.aclose()

    report = {
        "timestamp": now.isoformat(),
        "total_cameras_scanned": len(cam_ids),
        "valid_cameras_count": len(valid_cameras),
        "quarantined_cameras_count": len(quarantined_cameras),
        "quarantined_files_count": quarantined_files_total,
        "sample_valid_cameras": valid_cameras[:10],
        "sample_quarantined_cameras": quarantined_cameras[:10],
    }

    logger.info(
        "Audit completed: %d valid cameras preserved, %d cameras quarantined (%d files moved).",
        len(valid_cameras), len(quarantined_cameras), quarantined_files_total
    )

    return report


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    result = asyncio.run(run_camera_storage_audit())
    print("\n--- CAMERA STORAGE AUDIT REPORT ---")
    print(json.dumps(result, indent=2))

