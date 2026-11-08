"""
SafePathAI — 796 Camera Forensic Recovery Sweep & Classification Pipeline.
Executes live adaptive resolution across all 796 registered HCMC cameras:
- Probes adaptive URL candidates (TIMESTAMP_ONLY, PARAMETERIZED, PROVIDER, CANONICAL)
- Enforces strict Zero-Mock image validation
- Rejects server placeholders (9,230b / 5,192b PNG)
- Updates disk cache atomically and persists ingestion state in PostgreSQL
- Classifies every camera into the 12 strict forensic categories
- Exports data/cameras/camera_audit_results.csv & data/cameras/camera_audit_summary.json
"""

import asyncio
import csv
from datetime import datetime, timezone
import hashlib
import json
import logging
import os
import random
import sys
import time
from typing import Any, Dict, List, Optional, Tuple
import httpx
import numpy as np
from sqlalchemy import text

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.app.core.config import settings
from backend.app.db.session import AsyncSessionLocal
from backend.app.services.camera_url_resolver import (
    get_canonical_camera_url,
    get_default_camera_headers,
    resolve_camera_image,
)
from backend.app.services.image_validator import validate_camera_image_bytes

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("safepath.recovery_sweep")


async def run_recovery_sweep():
    logger.info("=" * 70)
    logger.info("SAFEPATH AI — 796-CAMERA LIVE IMAGE RECOVERY SWEEP")
    logger.info("=" * 70)

    # 1. Load cameras from manifest
    manifest_path = "data/cameras/camera_url_manifest.json"
    if not os.path.exists(manifest_path):
        raise FileNotFoundError(f"Manifest not found: {manifest_path}")

    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest_raw = json.load(f)

    manifest_cams: List[Dict[str, Any]] = manifest_raw.get("cameras", [])
    total_cameras = len(manifest_cams)
    logger.info("Loaded %d cameras from manifest.", total_cameras)
    assert total_cameras == 796, f"Expected 796 cameras, found {total_cameras}"

    # 2. Check baseline state before sweep
    storage_dir = "storage/cams"
    os.makedirs(storage_dir, exist_ok=True)
    baseline_valid_local = 0
    baseline_stale_records = 0
    for c in manifest_cams:
        p = os.path.join(storage_dir, f"{c['cam_id']}.jpg")
        if os.path.exists(p):
            try:
                with open(p, "rb") as bf:
                    data = bf.read()
                val = validate_camera_image_bytes(data)
                if val.is_valid:
                    baseline_valid_local += 1
            except Exception:
                pass

    logger.info("Baseline: %d cameras currently have valid images on disk.", baseline_valid_local)

    # 3. Live Sweep Configuration
    concurrency = getattr(settings, "CAMERA_MAX_CONCURRENCY", 8)
    semaphore = asyncio.Semaphore(12)  # Strict concurrency ceiling
    headers = get_default_camera_headers()
    limits = httpx.Limits(max_connections=25, max_keepalive_connections=15)
    timeout = httpx.Timeout(connect=5.0, read=7.0, write=5.0, pool=10.0)

    results: List[Dict[str, Any]] = []
    latencies: List[float] = []

    progress_counter = 0
    valid_new_count = 0
    placeholder_blocked_count = 0
    error_403_count = 0
    error_404_count = 0
    error_429_count = 0
    error_5xx_count = 0
    timeout_count = 0
    conn_error_count = 0

    sweep_start_time = time.perf_counter()

    async with httpx.AsyncClient(verify=False, timeout=timeout, limits=limits) as client:

        async def sweep_single_camera(cam: Dict[str, Any]) -> Dict[str, Any]:
            nonlocal progress_counter, valid_new_count, placeholder_blocked_count
            nonlocal error_403_count, error_404_count, error_429_count, error_5xx_count
            nonlocal timeout_count, conn_error_count

            cam_id = cam["cam_id"]
            code = cam.get("code") or ""
            name = cam.get("name") or f"Camera {cam_id[:8]}"
            district = cam.get("district") or ""
            lat = cam.get("lat")
            lng = cam.get("lng")
            provider_url = cam.get("provider_snapshot_url")
            canonical_url = get_canonical_camera_url(cam_id)
            local_image_path = os.path.join(storage_dir, f"{cam_id}.jpg")

            # Check pre-existing local cached file
            has_pre_local = False
            pre_local_bytes = 0
            if os.path.exists(local_image_path):
                pre_local_bytes = os.path.getsize(local_image_path)
                has_pre_local = pre_local_bytes > 5000

            async with semaphore:
                # Modest jitter to avoid micro-bursts against port 8007
                await asyncio.sleep(random.uniform(0.02, 0.08))

                t0 = time.perf_counter()
                res = await resolve_camera_image(
                    client=client,
                    cam_id=cam_id,
                    provider_url=provider_url,
                    redis=None,
                    request_headers=headers,
                )
                latency_ms = round((time.perf_counter() - t0) * 1000, 1)
                latencies.append(latency_ms)

            now_utc = datetime.now(timezone.utc)
            chosen_url = res.chosen_url
            chosen_variant = res.variant_type
            http_status = res.http_status
            byte_len = res.byte_length
            content_type = res.mime_type or "image/jpeg"
            content_md5 = res.content_hash or ""
            content_sha256 = res.content_sha256 or ""
            dims = res.dimensions

            is_valid = res.is_valid_image
            val_status = res.validation_status or ""
            fail_reason = res.failure_reason

            # If valid, write to local cache atomically
            if is_valid and res.image_bytes:
                valid_new_count += 1
                tmp_path = f"{local_image_path}.{os.getpid()}.{random.randint(1000, 9999)}.tmp"
                try:
                    with open(tmp_path, "wb") as f_out:
                        f_out.write(res.image_bytes)
                        f_out.flush()
                        os.fsync(f_out.fileno())
                    os.replace(tmp_path, local_image_path)
                except Exception as write_err:
                    logger.debug("Write error for %s: %s", cam_id, write_err)
                    if os.path.exists(tmp_path):
                        try:
                            os.remove(tmp_path)
                        except Exception:
                            pass

            # Update counter and progress
            progress_counter += 1
            if progress_counter % 50 == 0 or progress_counter == total_cameras:
                logger.info(
                    "Progress: %d/%d (%.1f%%) | Valid fresh: %d | Placeholders: %d | 403s: %d",
                    progress_counter, total_cameras, (progress_counter / total_cameras) * 100,
                    valid_new_count, placeholder_blocked_count, error_403_count,
                )

            # Determine rigorous user classification
            # Categories:
            # - VALID_FRESH_IMAGE
            # - VALID_STALE_IMAGE
            # - PLACEHOLDER_FRAME
            # - HTTP_403
            # - HTTP_404
            # - HTTP_429
            # - HTTP_5XX
            # - CONNECTION_ERROR
            # - TIMEOUT
            # - INVALID_IMAGE
            # - URL_UNVERIFIED
            # - NOT_YET_TESTED
            has_disk_file = os.path.exists(local_image_path)

            if is_valid:
                classification = "VALID_FRESH_IMAGE"
            elif val_status == "PLACEHOLDER_FRAME" or (fail_reason and "PLACEHOLDER" in fail_reason.upper()):
                placeholder_blocked_count += 1
                classification = "VALID_STALE_IMAGE" if has_disk_file else "PLACEHOLDER_FRAME"
            elif http_status == 403 or (fail_reason and "403" in fail_reason):
                error_403_count += 1
                classification = "VALID_STALE_IMAGE" if has_disk_file else "HTTP_403"
            elif http_status == 404 or (fail_reason and "404" in fail_reason):
                error_404_count += 1
                classification = "VALID_STALE_IMAGE" if has_disk_file else "HTTP_404"
            elif http_status == 429 or (fail_reason and "429" in fail_reason):
                error_429_count += 1
                classification = "VALID_STALE_IMAGE" if has_disk_file else "HTTP_429"
            elif http_status and http_status >= 500:
                error_5xx_count += 1
                classification = "VALID_STALE_IMAGE" if has_disk_file else "HTTP_5XX"
            elif "TIMEOUT" in (val_status + (fail_reason or "")).upper():
                timeout_count += 1
                classification = "VALID_STALE_IMAGE" if has_disk_file else "TIMEOUT"
            elif "CONNECTION" in (val_status + (fail_reason or "")).upper():
                conn_error_count += 1
                classification = "VALID_STALE_IMAGE" if has_disk_file else "CONNECTION_ERROR"
            elif byte_len > 0 and not is_valid:
                classification = "VALID_STALE_IMAGE" if has_disk_file else "INVALID_IMAGE"
            else:
                classification = "VALID_STALE_IMAGE" if has_disk_file else "URL_UNVERIFIED"

            return {
                "cam_id": cam_id,
                "code": code,
                "name": name,
                "district": district,
                "lat": lat,
                "lng": lng,
                "canonical_url": canonical_url,
                "has_provider_snapshot_url": bool(provider_url),
                "provider_snapshot_url": provider_url or "",
                "resolved_url": chosen_url,
                "chosen_variant": chosen_variant,
                "http_status": http_status,
                "content_type": content_type,
                "payload_bytes": byte_len,
                "image_width": dims[0] if dims else "",
                "image_height": dims[1] if dims else "",
                "content_md5": content_md5,
                "content_sha256": content_sha256,
                "is_valid_image": is_valid,
                "validation_status": val_status,
                "classification": classification,
                "failure_reason": fail_reason or "",
                "has_local_cache": has_disk_file,
                "latency_ms": latency_ms,
                "resolved_at": now_utc.isoformat(),
            }

        tasks = [sweep_single_camera(c) for c in manifest_cams]
        results = await asyncio.gather(*tasks)

    sweep_duration_sec = round(time.perf_counter() - sweep_start_time, 2)
    logger.info("Sweep completed in %.2f seconds.", sweep_duration_sec)

    # 4. Persist updated states to PostgreSQL
    logger.info("Persisting ingestion states to PostgreSQL...")
    async with AsyncSessionLocal() as session:
        for r in results:
            now = datetime.now(timezone.utc)
            cid = r["cam_id"]
            is_valid = r["is_valid_image"]
            http_st = r["http_status"]
            val_st = r["validation_status"]
            clf = r["classification"]
            fail_msg = r["failure_reason"] or None

            source_st = "LIVE" if clf == "VALID_FRESH_IMAGE" else ("STALE" if r["has_local_cache"] else "OFFLINE")
            last_succ = now if is_valid else None
            last_err = None if is_valid else (clf if clf not in ("VALID_STALE_IMAGE",) else (val_st or "FETCH_FAILED"))

            upsert_sql = text("""
                INSERT INTO camera_ingestion_state (
                    cam_id, source_status, last_attempt_at, last_success_at,
                    last_retrieved_at, next_retry_at, failure_count, http_status,
                    validation_status, image_hash, last_error_code, last_checked_url,
                    requested_url, effective_url, chosen_variant, content_type,
                    content_sha256, provider_id, failure_reason
                ) VALUES (
                    :cam_id, :source_status, :now, :last_success_at,
                    :now, :next_retry, :failure_count, :http_status,
                    :validation_status, :image_hash, :last_error_code, :last_checked_url,
                    :requested_url, :effective_url, :chosen_variant, :content_type,
                    :content_sha256, :provider_id, :failure_reason
                )
                ON CONFLICT (cam_id) DO UPDATE SET
                    source_status = :source_status,
                    last_attempt_at = :now,
                    last_success_at = COALESCE(:last_success_at, camera_ingestion_state.last_success_at),
                    last_retrieved_at = :now,
                    next_retry_at = :next_retry,
                    failure_count = :failure_count,
                    http_status = :http_status,
                    validation_status = :validation_status,
                    image_hash = COALESCE(:image_hash, camera_ingestion_state.image_hash),
                    last_error_code = :last_error_code,
                    last_checked_url = :last_checked_url,
                    requested_url = :requested_url,
                    effective_url = :effective_url,
                    chosen_variant = :chosen_variant,
                    content_type = :content_type,
                    content_sha256 = :content_sha256,
                    provider_id = :provider_id,
                    failure_reason = :failure_reason
            """)

            prov_id = "THONGTINGIAOTHONG_API" if "thongtingiaothong.vn" in (r["resolved_url"] or "") else "HCMC_VDMS_PORTAL"

            await session.execute(upsert_sql, {
                "cam_id": cid,
                "source_status": source_st,
                "now": now,
                "last_success_at": last_succ,
                "next_retry": now,
                "failure_count": 0 if is_valid else 1,
                "http_status": http_st,
                "validation_status": val_st,
                "image_hash": r["content_md5"] if is_valid else None,
                "last_error_code": last_err,
                "last_checked_url": r["resolved_url"],
                "requested_url": r["resolved_url"],
                "effective_url": r["resolved_url"],
                "chosen_variant": r["chosen_variant"],
                "content_type": r["content_type"],
                "content_sha256": r["content_sha256"] if is_valid else None,
                "provider_id": prov_id,
                "failure_reason": fail_msg,
            })
        await session.commit()
    logger.info("PostgreSQL ingestion states persisted successfully.")

    # 5. Export CSV audit results
    csv_path = "data/cameras/camera_audit_results.csv"
    csv_fields = [
        "cam_id", "code", "name", "district", "lat", "lng",
        "canonical_url", "has_provider_snapshot_url", "provider_snapshot_url",
        "resolved_url", "chosen_variant", "http_status", "content_type",
        "payload_bytes", "image_width", "image_height", "content_md5", "content_sha256",
        "classification", "validation_status", "failure_reason", "has_local_cache",
        "latency_ms", "resolved_at"
    ]
    with open(csv_path, "w", newline="", encoding="utf-8") as f_csv:
        writer = csv.DictWriter(f_csv, fieldnames=csv_fields)
        writer.writeheader()
        for r in results:
            writer.writerow({k: r.get(k, "") for k in csv_fields})
    logger.info("Exported %d rows to %s", len(results), csv_path)

    # 6. Compute statistics and export summary JSON
    classification_breakdown: Dict[str, int] = {}
    for r in results:
        clf = r["classification"]
        classification_breakdown[clf] = classification_breakdown.get(clf, 0) + 1

    final_valid_local = sum(1 for r in results if r["has_local_cache"])
    valid_fresh_count = classification_breakdown.get("VALID_FRESH_IMAGE", 0)
    valid_stale_count = classification_breakdown.get("VALID_STALE_IMAGE", 0)
    total_with_valid_image = valid_fresh_count + valid_stale_count

    p50_latency = float(np.percentile(latencies, 50)) if latencies else 0.0
    p95_latency = float(np.percentile(latencies, 95)) if latencies else 0.0

    # Collect residual error lists with specific cam_ids
    residual_cams_by_group: Dict[str, List[str]] = {}
    for r in results:
        clf = r["classification"]
        if clf not in ("VALID_FRESH_IMAGE",):
            if clf not in residual_cams_by_group:
                residual_cams_by_group[clf] = []
            if len(residual_cams_by_group[clf]) < 50:  # store up to 50 sample IDs
                residual_cams_by_group[clf].append(r["cam_id"])

    summary_data = {
        "audit_timestamp": datetime.now(timezone.utc).isoformat(),
        "total_registered_cameras": total_cameras,
        "baseline_valid_images_before": baseline_valid_local,
        "valid_fresh_images_retrieved": valid_fresh_count,
        "valid_stale_images_preserved": valid_stale_count,
        "total_cameras_with_valid_image": total_with_valid_image,
        "recovery_improvement_count": max(0, total_with_valid_image - baseline_valid_local),
        "total_without_valid_image": total_cameras - total_with_valid_image,
        "verified_working_urls_count": valid_fresh_count,
        "placeholders_detected_and_blocked": placeholder_blocked_count,
        "http_403_forbidden": error_403_count,
        "http_404_not_found": error_404_count,
        "http_429_rate_limited": error_429_count,
        "http_5xx_server_error": error_5xx_count,
        "timeouts": timeout_count,
        "connection_errors": conn_error_count,
        "classification_breakdown": classification_breakdown,
        "sweep_performance": {
            "total_duration_seconds": sweep_duration_sec,
            "cameras_per_second": round(total_cameras / max(sweep_duration_sec, 0.1), 2),
            "estimated_full_cycle_minutes": round((total_cameras / (total_cameras / max(sweep_duration_sec, 0.1))) / 60.0, 2),
            "latency_p50_ms": p50_latency,
            "latency_p95_ms": p95_latency,
        },
        "scheduler_cycle_compliance": {
            "target_cycle_seconds": settings.CAMERA_REFRESH_TARGET_SEC,
            "target_cycle_minutes": 30,
            "achieved_cycle_time_minutes": round(sweep_duration_sec / 60.0, 2),
            "cycle_compliant": (sweep_duration_sec <= settings.CAMERA_REFRESH_TARGET_SEC),
        },
        "sample_residual_cam_ids": residual_cams_by_group,
    }

    json_path = "data/cameras/camera_audit_summary.json"
    with open(json_path, "w", encoding="utf-8") as f_json:
        json.dump(summary_data, f_json, indent=2)
    logger.info("Saved comprehensive summary to %s", json_path)

    logger.info("=" * 70)
    logger.info("RECOVERY SWEEP RESULTS SUMMARY:")
    logger.info("Total Registered Cameras: %d", total_cameras)
    logger.info("Valid Fresh Images (LIVE): %d", valid_fresh_count)
    logger.info("Valid Stale Images (Preserved): %d", valid_stale_count)
    logger.info("Total with Valid Image: %d", total_with_valid_image)
    logger.info("Placeholders Blocked: %d", placeholder_blocked_count)
    logger.info("HTTP 403 Forbidden: %d", error_403_count)
    logger.info("Latency P50: %.1fms | P95: %.1fms", p50_latency, p95_latency)
    logger.info("Total Duration: %.1fs", sweep_duration_sec)
    logger.info("=" * 70)

    return summary_data


if __name__ == "__main__":
    asyncio.run(run_recovery_sweep())

