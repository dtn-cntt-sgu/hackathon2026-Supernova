"""
SafePathAI Camera Ingestion Scheduler & Fair Queue Manager.

Solves camera starvation across all registered HCMC traffic cameras:
- Rotates dynamically across all 796 verified PostGIS camera nodes.
- Preserves persistent attempt, success, failure count, and next_retry_at state in PostgreSQL.
- Implements exponential backoff for offline/unreachable nodes.
- Enforces multi-tier prioritization:
    Tier 0: Actively viewed cameras on map / dashboard.
    Tier 1: Corridor cameras along actively searched navigation routes.
    Tier 2: Stale cameras requiring refresh.
    Tier 3: Fair round-robin pool ensuring all 796 nodes receive scheduled checks.
- Redis distributed lease locking (prevents duplicate fetches across concurrent workers).
- Decouples raw image fetching from ONNX Computer Vision inference queue.
- Strict Zero-Mock: Excludes error frames ("IMAGE NOT AVAILABLE" / PLACEHOLDER) from AI pipeline.
"""

from datetime import datetime, timedelta, timezone
import hashlib
import json
import logging
import os
from typing import Any, Dict, List, Optional, Set, Tuple
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.config import settings
from backend.app.services.scraper import ScrapedCameraResult

logger = logging.getLogger("safepath.scheduler")


class CameraScheduler:
    """
    Autonomous Camera Ingestion Scheduler managing rotating batches,
    distributed locks, and persistent state.
    """

    def __init__(
        self,
        base_interval_sec: float = 60.0,
        base_backoff_sec: float = 30.0,
        max_backoff_sec: float = 3600.0,
        lease_ttl_sec: int = 120,
    ):
        self.base_interval_sec = base_interval_sec
        self.base_backoff_sec = base_backoff_sec
        self.max_backoff_sec = max_backoff_sec
        self.lease_ttl_sec = lease_ttl_sec

    async def get_active_priority_camera_ids(self, redis: Optional[Redis]) -> Tuple[Set[str], Set[str]]:
        """
        Retrieves real-time high-priority camera IDs from Redis sets/zsets:
        - active_viewed_cameras / active_viewed_cameras_zset: modal open / viewport
        - active_route_cameras / active_route_cameras_zset: navigation corridor
        Automatically prunes expired entries.
        """
        if redis is None:
            return set(), set()
        try:
            now_ts = datetime.now(timezone.utc).timestamp()
            # Clean expired zset members
            await redis.zremrangebyscore("active_viewed_cameras_zset", "-inf", now_ts)
            await redis.zremrangebyscore("active_route_cameras_zset", "-inf", now_ts)

            # Retrieve active from authoritative time-scored zsets
            z_viewed_raw = await redis.zrange("active_viewed_cameras_zset", 0, -1)
            z_route_raw = await redis.zrange("active_route_cameras_zset", 0, -1)

            viewed = {
                (x if isinstance(x, str) else x.decode("utf-8"))
                for x in z_viewed_raw
            }
            route = {
                (x if isinstance(x, str) else x.decode("utf-8"))
                for x in z_route_raw
            }

            s_viewed_raw = await redis.smembers("active_viewed_cameras")
            if s_viewed_raw:
                viewed.update((x if isinstance(x, str) else x.decode("utf-8")) for x in s_viewed_raw)

            s_route_raw = await redis.smembers("active_route_cameras")
            if s_route_raw:
                route.update((x if isinstance(x, str) else x.decode("utf-8")) for x in s_route_raw)

            return viewed, route
        except Exception as exc:
            logger.debug("Failed to read priority sets from Redis: %s", exc)
            return set(), set()

    async def register_active_viewed_cameras(
        self,
        redis: Optional[Redis],
        cam_ids: List[str],
        ttl_seconds: int = 90,
    ) -> int:
        """Registers actively viewed cameras (modal open or viewport) with automatic expiration."""
        if redis is None or not cam_ids:
            return 0
        try:
            now_ts = datetime.now(timezone.utc).timestamp()
            expire_at = now_ts + ttl_seconds
            mapping = {str(cid): expire_at for cid in cam_ids if cid}
            if mapping:
                await redis.zadd("active_viewed_cameras_zset", mapping)
                await redis.sadd("active_viewed_cameras", *mapping.keys())
                await redis.expire("active_viewed_cameras", ttl_seconds)
                await redis.zremrangebyscore("active_viewed_cameras_zset", "-inf", now_ts)
            return len(mapping)
        except Exception as exc:
            logger.warning("Failed to register active viewed cameras: %s", exc)
            return 0

    async def register_active_route_cameras(
        self,
        redis: Optional[Redis],
        cam_ids: List[str],
        ttl_seconds: int = 900,
    ) -> int:
        """Registers cameras along active navigation route corridor with automatic expiration."""
        if redis is None or not cam_ids:
            return 0
        try:
            now_ts = datetime.now(timezone.utc).timestamp()
            expire_at = now_ts + ttl_seconds
            mapping = {str(cid): expire_at for cid in cam_ids if cid}
            if mapping:
                await redis.zadd("active_route_cameras_zset", mapping)
                await redis.sadd("active_route_cameras", *mapping.keys())
                await redis.expire("active_route_cameras", ttl_seconds)
                await redis.zremrangebyscore("active_route_cameras_zset", "-inf", now_ts)
            return len(mapping)
        except Exception as exc:
            logger.warning("Failed to register active route cameras: %s", exc)
            return 0

    async def unregister_active_viewed_camera(
        self,
        redis: Optional[Redis],
        cam_id: str,
    ) -> None:
        """Removes camera from actively viewed priority sets upon modal close."""
        if redis is None or not cam_id:
            return
        try:
            await redis.zrem("active_viewed_cameras_zset", str(cam_id))
            await redis.srem("active_viewed_cameras", str(cam_id))
        except Exception as exc:
            logger.debug("Failed to unregister viewed camera %s: %s", cam_id, exc)

    async def acquire_batch(
        self,
        session: AsyncSession,
        redis: Optional[Redis] = None,
        batch_size: int = 16,
        worker_id: str = "worker-1",
    ) -> List[Dict[str, Any]]:
        """
        Selects a priority-ranked, starvation-free batch of cameras ready for ingestion.
        Guarantees that every camera in the 796-node registry gets rotated fairly.
        Enforces fair quota: at most 2 slots for active modal views, guaranteeing
        at least (batch_size - 2) slots for the sequential 10-minute round-robin sweep.
        """
        now = datetime.now(timezone.utc)
        active_cutoff = now - timedelta(seconds=45)
        viewed_ids, route_ids = await self.get_active_priority_camera_ids(redis)

        acquired_batch: List[Dict[str, Any]] = []
        acquired_ids: set = set()

        # Step 1: Up to 2 slots for active viewed/route cameras (modal priority)
        priority_candidates = []
        if viewed_ids or route_ids:
            priority_sql = text("""
                SELECT 
                    c.cam_id, c.code, c.name, c.district, 
                    ST_Y(c.geom) AS lat, ST_X(c.geom) AS lng,
                    c.source_uri, s.last_attempt_at, s.last_success_at,
                    s.failure_count, s.image_hash, s.content_sha256
                FROM traffic_cameras c
                LEFT JOIN camera_ingestion_state s ON c.cam_id = s.cam_id
                WHERE c.geom IS NOT NULL
                  AND (c.cam_id = ANY(:viewed_ids) OR c.cam_id = ANY(:route_ids))
                  AND (s.last_attempt_at IS NULL OR s.last_attempt_at <= :active_cutoff)
                ORDER BY COALESCE(s.last_attempt_at, '1970-01-01 00:00:00+00'::timestamptz) ASC
                LIMIT 2
            """)
            p_res = await session.execute(priority_sql, {
                "viewed_ids": list(viewed_ids) if viewed_ids else ["__none__"],
                "route_ids": list(route_ids) if route_ids else ["__none__"],
                "active_cutoff": active_cutoff,
            })
            priority_candidates = p_res.fetchall()

        for row in priority_candidates:
            cam_id = row.cam_id
            if redis is not None:
                try:
                    lease_key = f"camera:lease:{cam_id}"
                    acquired = await redis.set(lease_key, worker_id, ex=self.lease_ttl_sec, nx=True)
                    if not acquired:
                        continue
                except Exception as exc:
                    logger.debug("Redis lease check failed for %s: %s", cam_id, exc)

            acquired_batch.append({
                "cam_id": cam_id,
                "code": row.code,
                "name": row.name,
                "district": row.district,
                "lat": row.lat,
                "lng": row.lng,
                "source_uri": row.source_uri,
                "previous_image_hash": row.image_hash,
                "previous_sha256": row.content_sha256,
                "priority_tier": 0,
            })
            acquired_ids.add(cam_id)

            upsert_attempt_sql = text("""
                INSERT INTO camera_ingestion_state (
                    cam_id, source_status, last_attempt_at, next_retry_at, failure_count
                ) VALUES (
                    :cam_id, 'ATTEMPTING', :now, :tentative_retry, 0
                )
                ON CONFLICT (cam_id) DO UPDATE SET
                    last_attempt_at = :now,
                    next_retry_at = :tentative_retry
            """)
            await session.execute(upsert_attempt_sql, {
                "cam_id": cam_id,
                "now": now,
                "tentative_retry": now + timedelta(seconds=self.base_interval_sec),
            })

            if len(acquired_batch) >= 2:
                break

        # Step 2: Sequential Starvation-Free Sweep for remaining batch slots (ordered by least recently attempted)
        remaining_slots = batch_size - len(acquired_batch)
        if remaining_slots > 0:
            sweep_sql = text("""
                SELECT 
                    c.cam_id, c.code, c.name, c.district, 
                    ST_Y(c.geom) AS lat, ST_X(c.geom) AS lng,
                    c.source_uri, s.last_attempt_at, s.last_success_at,
                    s.failure_count, s.image_hash, s.content_sha256,
                    CASE 
                        WHEN s.last_success_at IS NOT NULL AND (:now_epoch - EXTRACT(EPOCH FROM s.last_success_at)) > :ttl THEN 2
                        WHEN s.last_success_at IS NULL THEN 3
                        ELSE 4
                    END AS priority_tier
                FROM traffic_cameras c
                LEFT JOIN camera_ingestion_state s ON c.cam_id = s.cam_id
                WHERE c.geom IS NOT NULL
                  AND (s.next_retry_at IS NULL OR s.next_retry_at <= :now)
                  AND NOT (c.cam_id = ANY(:excluded_ids))
                ORDER BY 
                    COALESCE(s.last_attempt_at, '1970-01-01 00:00:00+00'::timestamptz) ASC,
                    c.cam_id ASC
                LIMIT :limit
            """)
            s_res = await session.execute(sweep_sql, {
                "now": now,
                "now_epoch": now.timestamp(),
                "ttl": settings.CAMERA_IMAGE_TTL_SECONDS,
                "excluded_ids": list(acquired_ids) if acquired_ids else ["__none__"],
                "limit": remaining_slots * 4,
            })
            sweep_candidates = s_res.fetchall()

            for row in sweep_candidates:
                cam_id = row.cam_id
                if redis is not None:
                    try:
                        lease_key = f"camera:lease:{cam_id}"
                        acquired = await redis.set(lease_key, worker_id, ex=self.lease_ttl_sec, nx=True)
                        if not acquired:
                            continue
                    except Exception as exc:
                        logger.debug("Redis lease check failed for %s: %s", cam_id, exc)

                acquired_batch.append({
                    "cam_id": cam_id,
                    "code": row.code,
                    "name": row.name,
                    "district": row.district,
                    "lat": row.lat,
                    "lng": row.lng,
                    "source_uri": row.source_uri,
                    "previous_image_hash": row.image_hash,
                    "previous_sha256": row.content_sha256,
                    "priority_tier": row.priority_tier,
                })
                acquired_ids.add(cam_id)

                upsert_attempt_sql = text("""
                    INSERT INTO camera_ingestion_state (
                        cam_id, source_status, last_attempt_at, next_retry_at, failure_count
                    ) VALUES (
                        :cam_id, 'ATTEMPTING', :now, :tentative_retry, 0
                    )
                    ON CONFLICT (cam_id) DO UPDATE SET
                        last_attempt_at = :now,
                        next_retry_at = :tentative_retry
                """)
                await session.execute(upsert_attempt_sql, {
                    "cam_id": cam_id,
                    "now": now,
                    "tentative_retry": now + timedelta(seconds=self.base_interval_sec),
                })

                if len(acquired_batch) >= batch_size:
                    break

        await session.commit()
        return acquired_batch

    async def purge_expired_camera_snapshots(
        self,
        session: AsyncSession,
        max_age_seconds: int = 3600,
    ) -> int:
        """
        Purges snapshots older than max_age_seconds (default 1 hour) from persistent storage and DB.
        Ensures strict data freshness: frames older than 1 hour are not served to users.
        """
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(seconds=max_age_seconds)

        # 1. Delete expired snapshots from camera_snapshots table
        del_stmt = text("""
            DELETE FROM camera_snapshots
            WHERE fetched_at < :cutoff OR created_at < :cutoff
        """)
        del_res = await session.execute(del_stmt, {"cutoff": cutoff})
        deleted_count = del_res.rowcount or 0

        # 2. Reset ingestion state for cameras whose last successful snapshot has expired past 1 hour
        reset_stmt = text("""
            UPDATE camera_ingestion_state
            SET cached_image_path = NULL,
                latest_snapshot_id = NULL,
                source_status = 'OFFLINE',
                freshness_status = 'OFFLINE'
            WHERE last_success_at IS NOT NULL 
              AND last_success_at < :cutoff
              AND (cached_image_path IS NOT NULL OR latest_snapshot_id IS NOT NULL)
        """)
        await session.execute(reset_stmt, {"cutoff": cutoff})
        await session.commit()

        return deleted_count

    async def record_result(
        self,
        session: AsyncSession,
        res: ScrapedCameraResult,
        redis: Optional[Redis] = None,
    ) -> None:
        """
        Updates persistent camera ingestion state following fetch & validation:
        - Success: resets failure count, schedules next standard cycle.
        - Failure: applies exponential backoff and records truthful error codes.
        - Releases Redis lease lock.
        """
        now = datetime.now(timezone.utc)
        cam_id = res.cam_id

        # 1. Release distributed lease
        if redis is not None:
            try:
                await redis.delete(f"camera:lease:{cam_id}")
            except Exception as exc:
                logger.debug("Failed to release lease for %s: %s", cam_id, exc)

        # 2. Compute backoff & next retry
        is_new_success = res.is_valid_image and getattr(res, "is_new_snapshot", True)

        snapshot_id = getattr(res, "snapshot_id", None)
        freshness_st = getattr(res, "freshness_status", None)
        capture_time_st = getattr(res, "capture_time_status", None)

        if is_new_success:
            new_failure_count = 0
            next_retry = now + timedelta(seconds=self.base_interval_sec)
            status_str = "LIVE"
            if res.captured_at is not None:
                freshness_st = freshness_st or "FRESH_VERIFIED"
                capture_time_st = capture_time_st or "CAPTURE_TIME_VERIFIED"
            else:
                freshness_st = freshness_st or "RECENTLY_FETCHED_UNVERIFIED"
                capture_time_st = capture_time_st or "CAPTURE_TIME_UNKNOWN"
            val_status = res.validation_status or "VALID_FRAME"
            http_status = 200
            err_code = None
            last_success_at_param = now
            last_content_changed_param = now
            last_source_captured_param = res.captured_at
        elif res.is_valid_image and not getattr(res, "is_new_snapshot", True):
            # Duplicate frame or cache hit: stream is active, but frame has not refreshed
            # Keep historical success timestamp; do not set last_content_changed_at = now
            status_str = "LIVE"
            if res.captured_at is not None:
                freshness_st = freshness_st or "FRESH_VERIFIED"
                capture_time_st = capture_time_st or "CAPTURE_TIME_VERIFIED"
            else:
                freshness_st = freshness_st or "RECENTLY_FETCHED_UNVERIFIED"
                capture_time_st = capture_time_st or "CAPTURE_TIME_UNKNOWN"
            val_status = res.validation_status or "DUPLICATE_FRAME"
            http_status = 200
            err_code = (res.image_status_reason or "DUPLICATE_FRAME")[:64]
            last_success_at_param = now
            last_content_changed_param = None
            last_source_captured_param = res.captured_at
            new_failure_count = 0
            next_retry = now + timedelta(seconds=self.base_interval_sec)
        else:
            # Query existing failure count for backoff
            cur_fc = await session.execute(
                text("SELECT failure_count FROM camera_ingestion_state WHERE cam_id = :cam_id"),
                {"cam_id": cam_id},
            )
            val = cur_fc.scalar()
            new_failure_count = (val or 0) + 1

            # Exponential backoff capped at max_backoff_sec (1 hour)
            backoff_sec = min(self.max_backoff_sec, self.base_backoff_sec * (2 ** min(new_failure_count - 1, 6)))
            next_retry = now + timedelta(seconds=backoff_sec)
            val_status = res.validation_status or "VALIDATION_FAILED"
            raw_http = getattr(res, "http_status", None)
            if raw_http and raw_http > 0:
                http_status = raw_http
            elif res.image_status_reason == "PLACEHOLDER_FRAME":
                http_status = 200
            else:
                http_status = 503

            reason_upper = f"{res.error_message or ''} {res.validation_status or ''} {res.image_status_reason or ''}".upper()
            if raw_http == 403 or "403" in reason_upper:
                err_code = "HTTP_403"
                status_str = "RESTRICTED"
            elif raw_http == 429 or "429" in reason_upper:
                err_code = "HTTP_429"
                status_str = "RESTRICTED"
            elif "PLACEHOLDER" in reason_upper:
                err_code = "PLACEHOLDER_FRAME"
                status_str = "PLACEHOLDER"
            elif "TIMEOUT" in reason_upper:
                err_code = res.image_status_reason or "TIMEOUT"
                status_str = "OFFLINE"
            elif "CONNECTION" in reason_upper or "OFFLINE" in reason_upper:
                err_code = res.image_status_reason or "CONNECTION_ERROR"
                status_str = "OFFLINE"
            elif raw_http == 404 or "404" in reason_upper:
                err_code = "HTTP_404"
                status_str = "FETCH_FAILED"
            else:
                err_code = res.image_status_reason or "FETCH_FAILED"
                status_str = "STALE" if res.image_path else "FETCH_FAILED"

            freshness_st = status_str
            capture_time_st = "CAPTURE_TIME_UNKNOWN"
            last_success_at_param = None
            last_content_changed_param = None
            last_source_captured_param = None

        # 3. If new valid snapshot, insert immutable row into camera_snapshots table
        if is_new_success and snapshot_id and res.image_path:
            try:
                async with session.begin_nested():
                    # Mark previous snapshots for this camera as not latest
                    await session.execute(
                        text("UPDATE camera_snapshots SET is_latest = FALSE WHERE camera_id = :cam_id AND is_latest = TRUE"),
                        {"cam_id": cam_id},
                    )
                    # Insert new immutable snapshot record
                    content_sha = res.content_sha256 or (hashlib.sha256(res.image_bytes).hexdigest() if res.image_bytes else "")
                    await session.execute(
                        text("""
                            INSERT INTO camera_snapshots (
                                snapshot_id, camera_id, content_sha256, content_md5, file_path,
                                file_size_bytes, source_captured_at, fetched_at, freshness_status,
                                capture_time_status, is_latest, created_at
                            ) VALUES (
                                :snapshot_id, :cam_id, :content_sha256, :content_md5, :file_path,
                                :file_size_bytes, :source_captured_at, :fetched_at, :freshness_status,
                                :capture_time_status, TRUE, :now
                            )
                            ON CONFLICT (snapshot_id) DO UPDATE SET
                                is_latest = TRUE,
                                freshness_status = EXCLUDED.freshness_status,
                                capture_time_status = EXCLUDED.capture_time_status
                        """),
                        {
                            "snapshot_id": snapshot_id,
                            "cam_id": cam_id,
                            "content_sha256": content_sha,
                            "content_md5": res.etag or (hashlib.md5(res.image_bytes).hexdigest() if res.image_bytes else None),
                            "file_path": res.image_path,
                            "file_size_bytes": res.file_size or 0,
                            "source_captured_at": res.captured_at,
                            "fetched_at": res.retrieved_at or now,
                            "freshness_status": freshness_st or "RECENTLY_FETCHED_UNVERIFIED",
                            "capture_time_status": capture_time_st or "CAPTURE_TIME_UNKNOWN",
                            "now": now,
                        },
                    )
            except Exception as snap_err:
                logger.warning("Failed saving camera snapshot %s for %s: %s", snapshot_id, cam_id, snap_err)
                # Keep the previous latest frame and surface failure before publishing ingestion state.
                raise

        requested_url = getattr(res, "requested_url", None)
        effective_url = getattr(res, "effective_url", None)
        chosen_variant = getattr(res, "chosen_variant", None)
        content_type = getattr(res, "content_type", None)
        content_sha256 = getattr(res, "content_sha256", None)
        provider_id = getattr(res, "provider_id", None)
        last_checked_url = effective_url or requested_url or f"https://giaothong.hochiminhcity.gov.vn:8007/Render/CameraHandler.ashx?id={cam_id}"

        upsert_sql = text("""
            INSERT INTO camera_ingestion_state (
                cam_id, source_status, last_attempt_at, last_success_at,
                last_captured_at, last_retrieved_at, next_retry_at, failure_count,
                http_status, validation_status, image_hash, last_error_code,
                last_checked_url, requested_url, effective_url, chosen_variant,
                content_type, content_sha256, provider_id, cached_image_path, failure_reason,
                latest_snapshot_id, last_content_changed_at, last_source_captured_at
            ) VALUES (
                :cam_id, :source_status, :now, :last_success_at,
                :last_captured_at, :last_retrieved_at, :next_retry_at, :failure_count,
                :http_status, :validation_status, :image_hash, :last_error_code,
                :last_checked_url, :requested_url, :effective_url, :chosen_variant,
                :content_type, :content_sha256, :provider_id, :cached_image_path, :failure_reason,
                :latest_snapshot_id, :last_content_changed_at, :last_source_captured_at
            )
            ON CONFLICT (cam_id) DO UPDATE SET
                source_status = :source_status,
                last_attempt_at = :now,
                last_success_at = COALESCE(:last_success_at, camera_ingestion_state.last_success_at),
                last_captured_at = COALESCE(:last_captured_at, camera_ingestion_state.last_captured_at),
                last_retrieved_at = COALESCE(:last_retrieved_at, camera_ingestion_state.last_retrieved_at),
                next_retry_at = :next_retry_at,
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
                content_sha256 = COALESCE(:content_sha256, camera_ingestion_state.content_sha256),
                provider_id = :provider_id,
                cached_image_path = COALESCE(:cached_image_path, camera_ingestion_state.cached_image_path),
                failure_reason = :failure_reason,
                latest_snapshot_id = COALESCE(:latest_snapshot_id, camera_ingestion_state.latest_snapshot_id),
                last_content_changed_at = COALESCE(:last_content_changed_at, camera_ingestion_state.last_content_changed_at),
                last_source_captured_at = COALESCE(:last_source_captured_at, camera_ingestion_state.last_source_captured_at)
        """)

        await session.execute(upsert_sql, {
            "cam_id": cam_id,
            "source_status": status_str,
            "now": now,
            "last_success_at": last_success_at_param,
            "last_captured_at": res.captured_at,
            "last_retrieved_at": res.retrieved_at,
            "next_retry_at": next_retry,
            "failure_count": new_failure_count,
            "http_status": http_status,
            "validation_status": val_status,
            "image_hash": res.etag if res.is_valid_image else None,
            "last_error_code": (err_code[:64] if err_code else None),
            "last_checked_url": last_checked_url,
            "requested_url": requested_url,
            "effective_url": effective_url,
            "chosen_variant": chosen_variant,
            "content_type": content_type,
            "content_sha256": content_sha256,
            "provider_id": provider_id,
            "cached_image_path": res.image_path if res.is_valid_image else None,
            "failure_reason": res.error_message or (
                "Server returned 'IMAGE NOT AVAILABLE' placeholder frame"
                if (res.image_status_reason == "PLACEHOLDER_FRAME" or val_status == "PLACEHOLDER_FRAME") else None
            ),
            "latest_snapshot_id": snapshot_id if is_new_success else None,
            "last_content_changed_at": last_content_changed_param,
            "last_source_captured_at": last_source_captured_param,
        })
        await session.commit()

    async def record_vision_completion(
        self,
        session: AsyncSession,
        cam_id: str,
        model_status: str,
        image_hash: Optional[str] = None,
        snapshot_id: Optional[str] = None,
        inference_input_sha256: Optional[str] = None,
        overlay_path: Optional[str] = None,
        vehicle_count: Optional[int] = None,
        traffic_density_score: Optional[float] = None,
        flood_ratio: Optional[float] = None,
    ) -> None:
        """Records completion of Computer Vision pipeline execution and links overlay to exact snapshot."""
        now = datetime.now(timezone.utc)
        # 1. Update camera_snapshots record for the specific snapshot (or latest snapshot)
        if snapshot_id:
            snap_stmt = text("""
                UPDATE camera_snapshots
                SET inference_completed_at = :now,
                    inference_input_sha256 = COALESCE(:inference_input_sha256, inference_input_sha256),
                    overlay_path = COALESCE(:overlay_path, overlay_path),
                    model_status = :model_status,
                    vehicle_count = COALESCE(:vehicle_count, vehicle_count),
                    traffic_density_score = COALESCE(:traffic_density_score, traffic_density_score),
                    flood_ratio = COALESCE(:flood_ratio, flood_ratio)
                WHERE snapshot_id = :snapshot_id
            """)
            await session.execute(snap_stmt, {
                "now": now,
                "snapshot_id": snapshot_id,
                "inference_input_sha256": inference_input_sha256,
                "overlay_path": overlay_path,
                "model_status": model_status,
                "vehicle_count": vehicle_count,
                "traffic_density_score": traffic_density_score,
                "flood_ratio": flood_ratio,
            })
        else:
            snap_stmt = text("""
                UPDATE camera_snapshots
                SET inference_completed_at = :now,
                    inference_input_sha256 = COALESCE(:inference_input_sha256, inference_input_sha256),
                    overlay_path = COALESCE(:overlay_path, overlay_path),
                    model_status = :model_status,
                    vehicle_count = COALESCE(:vehicle_count, vehicle_count),
                    traffic_density_score = COALESCE(:traffic_density_score, traffic_density_score),
                    flood_ratio = COALESCE(:flood_ratio, flood_ratio)
                WHERE camera_id = :cam_id AND is_latest = TRUE
            """)
            await session.execute(snap_stmt, {
                "now": now,
                "cam_id": cam_id,
                "inference_input_sha256": inference_input_sha256,
                "overlay_path": overlay_path,
                "model_status": model_status,
                "vehicle_count": vehicle_count,
                "traffic_density_score": traffic_density_score,
                "flood_ratio": flood_ratio,
            })

        # 2. Update ingestion state
        stmt = text("""
            UPDATE camera_ingestion_state
            SET model_status = :model_status,
                image_hash = COALESCE(:image_hash, image_hash)
            WHERE cam_id = :cam_id
        """)
        await session.execute(stmt, {
            "cam_id": cam_id,
            "model_status": model_status,
            "image_hash": image_hash,
        })
        await session.commit()

    async def get_metrics(
        self,
        session: AsyncSession,
        redis: Optional[Redis] = None,
    ) -> Dict[str, Any]:
        """
        Aggregates operational ingestion metrics for administration endpoints.
        Never leaks internal cookies, secrets, or authentication tokens.
        """
        now = datetime.now(timezone.utc)
        recent_cutoff = now - timedelta(hours=1)
        cycle_target_sec = getattr(settings, "CAMERA_REFRESH_TARGET_SEC", 600)
        cycle_cutoff = now - timedelta(seconds=cycle_target_sec)

        stmt = text("""
            SELECT 
                count(*) AS total_registered,
                count(geom) AS with_gps,
                count(*) FILTER (WHERE snapshot_cam_status = 'UP') AS historical_up
            FROM traffic_cameras
        """)
        row_cam = (await session.execute(stmt)).fetchone()

        stmt_state = text("""
            SELECT 
                count(*) AS total_tracked,
                count(*) FILTER (WHERE source_status IN ('LIVE', 'FRESH_VERIFIED')) AS live_count,
                count(*) FILTER (WHERE source_status = 'STALE') AS stale_count,
                count(*) FILTER (WHERE source_status IN ('OFFLINE', 'FETCH_FAILED')) AS offline_count,
                count(*) FILTER (WHERE last_attempt_at >= :recent_cutoff) AS attempted_recent,
                count(*) FILTER (WHERE last_success_at >= :recent_cutoff) AS success_recent,
                count(*) FILTER (WHERE last_attempt_at >= :cycle_cutoff) AS attempted_this_cycle,
                count(*) FILTER (WHERE last_success_at >= :cycle_cutoff) AS success_this_cycle,
                count(*) FILTER (WHERE validation_status = 'PLACEHOLDER_FRAME') AS placeholder_count,
                count(*) FILTER (WHERE model_status = 'INFERENCE_COMPLETED') AS model_analyzed_count,
                max(last_attempt_at) AS latest_attempt_at,
                max(last_success_at) AS latest_success_at
            FROM camera_ingestion_state
        """)
        row_state = (await session.execute(stmt_state, {"recent_cutoff": recent_cutoff, "cycle_cutoff": cycle_cutoff})).fetchone()

        # Section F metrics: Registered, Reachable, Fetched recently, Fresh verified, Stale, Fetch failed, Capture time unknown
        stmt_section_f = text("""
            SELECT 
                count(*) FILTER (WHERE source_status IN ('LIVE', 'FRESH_VERIFIED', 'RECENTLY_FETCHED_UNVERIFIED') OR http_status = 200) AS reachable_count,
                count(*) FILTER (WHERE last_retrieved_at >= :cycle_cutoff) AS fetched_recently_count,
                count(*) FILTER (WHERE source_status = 'FRESH_VERIFIED' OR (last_captured_at IS NOT NULL AND last_success_at >= :cycle_cutoff)) AS fresh_verified_count,
                count(*) FILTER (WHERE source_status = 'STALE' OR (last_success_at IS NOT NULL AND last_success_at < :cycle_cutoff)) AS stale_count,
                count(*) FILTER (WHERE failure_count > 0 OR source_status IN ('FETCH_FAILED', 'OFFLINE', 'RESTRICTED')) AS fetch_failed_count,
                count(*) FILTER (WHERE last_captured_at IS NULL AND (last_success_at IS NOT NULL OR last_retrieved_at IS NOT NULL)) AS capture_time_unknown_count
            FROM camera_ingestion_state
        """)
        row_f = (await session.execute(stmt_section_f, {"cycle_cutoff": cycle_cutoff})).fetchone()

        # Error reason breakdown
        stmt_errors = text("""
            SELECT last_error_code, count(*) as cnt
            FROM camera_ingestion_state
            WHERE last_error_code IS NOT NULL
            GROUP BY last_error_code
            ORDER BY cnt DESC
            LIMIT 10
        """)
        res_errors = await session.execute(stmt_errors)
        error_breakdown = {r.last_error_code: r.cnt for r in res_errors.fetchall()}

        viewed_ids, route_ids = await self.get_active_priority_camera_ids(redis)
        total_registered = row_cam.total_registered if row_cam else 0
        attempted_cycle = row_state.attempted_this_cycle if row_state else 0
        success_cycle = row_state.success_this_cycle if row_state else 0
        attempted_recent = row_state.attempted_recent if row_state else 0
        pending_cycle = max(0, total_registered - attempted_cycle)
        cpm = round(attempted_recent / 60.0, 1)
        sweep_est_min = round(total_registered / max(cpm, 0.5), 1)
        target_sweep_min = round(cycle_target_sec / 60.0, 1)
        cycle_target_met = (sweep_est_min <= target_sweep_min)
        cycle_lag_sec = max(0.0, round((sweep_est_min - target_sweep_min) * 60.0, 1))

        return {
            "status": "healthy",
            "timestamp": now.isoformat(),
            "cycle_target_seconds": cycle_target_sec,
            "cycle_target_met": cycle_target_met,
            "cycle_lag_seconds": cycle_lag_sec,
            "cameras_checked_this_cycle": attempted_cycle,
            "cameras_with_fresh_image": success_cycle,
            "cameras_pending_this_cycle": pending_cycle,
            "cameras_checked_per_minute": cpm,
            "full_registry_sweep_duration_min": sweep_est_min,
            "active_priority_refresh_interval_sec": getattr(settings, "CAMERA_PRIORITY_INTERVAL_SEC", 60),
            "registered_count": total_registered,
            "reachable_count": row_f.reachable_count if row_f else 0,
            "fetched_recently_count": row_f.fetched_recently_count if row_f else 0,
            "fresh_verified_count": row_f.fresh_verified_count if row_f else 0,
            "stale_count": row_f.stale_count if row_f else 0,
            "fetch_failed_count": row_f.fetch_failed_count if row_f else 0,
            "capture_time_unknown_count": row_f.capture_time_unknown_count if row_f else 0,
            "total_registered_cameras": total_registered,
            "geolocated_cameras": row_cam.with_gps if row_cam else 0,
            "historical_up_cameras": row_cam.historical_up if row_cam else 0,
            "tracked_in_scheduler": row_state.total_tracked if row_state else 0,
            "live_cameras": row_state.live_count if row_state else 0,
            "stale_cameras": row_state.stale_count if row_state else 0,
            "offline_cameras": row_state.offline_count if row_state else 0,
            "recent_hour_attempts": attempted_recent,
            "recent_hour_successes": row_state.success_recent if row_state else 0,
            "placeholder_frames_excluded": row_state.placeholder_count if row_state else 0,
            "model_analyzed_cameras": row_state.model_analyzed_count if row_state else 0,
            "active_viewed_cameras_count": len(viewed_ids),
            "active_route_cameras_count": len(route_ids),
            "latest_attempt_at": row_state.latest_attempt_at.isoformat() if (row_state and row_state.latest_attempt_at) else None,
            "latest_success_at": row_state.latest_success_at.isoformat() if (row_state and row_state.latest_success_at) else None,
            "error_breakdown": error_breakdown,
        }


# Singleton Scheduler Instance
camera_scheduler = CameraScheduler(
    base_interval_sec=float(getattr(settings, "CAMERA_SCRAPE_INTERVAL_SEC", 60)),
    base_backoff_sec=30.0,
    max_backoff_sec=3600.0,
    lease_ttl_sec=120,
)
