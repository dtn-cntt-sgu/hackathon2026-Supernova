"""
SafePathAI Multi-Tier Priority Camera Queue & Inference Worker Manager.

Provides:
- Strict multi-tier prioritization:
    P0 (0): Actively viewed cameras (modal open / viewport).
    P1 (1): Route corridor cameras along active navigation routes.
    P2 (2): Stale cameras requiring scheduled refresh.
    P3 (3): Fair background rotation across all 796 nodes.
- Job lifecycle with explicit states:
    QUEUED -> FETCHING -> VALIDATING -> FETCHED -> INFERENCE_PENDING
    -> INFERENCING -> INFERENCE_COMPLETED -> RISK_EVALUATION_PENDING -> COMPLETED
    (or FAILED_RETRYABLE / FAILED_PERMANENTLY / EXPIRED).
- Redis-backed persistent priority queue (ZSET) with in-memory fallback.
- Job coalescing: updates existing pending jobs for the same camera to avoid stale frame backlog.
- Idempotency key deduplication: skips redundant inference on unchanged frames.
- Dead-Letter Queue (DLQ) for permanently failed tasks.
- Fault isolation: vision exceptions never interrupt camera fetching.
"""

import asyncio
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
import json
import logging
import time
from typing import Any, Dict, List, Optional, Tuple
import uuid

from redis.asyncio import Redis

logger = logging.getLogger("safepath.queue")

PRIORITY_P0_VIEWED = 0
PRIORITY_P1_ROUTE = 1
PRIORITY_P2_STALE = 2
PRIORITY_P3_BACKGROUND = 3


class CameraJobStatus(str, Enum):
    QUEUED = "QUEUED"
    FETCHING = "FETCHING"
    VALIDATING = "VALIDATING"
    FETCHED = "FETCHED"
    INFERENCE_PENDING = "INFERENCE_PENDING"
    INFERENCING = "INFERENCING"
    INFERENCE_COMPLETED = "INFERENCE_COMPLETED"
    RISK_EVALUATION_PENDING = "RISK_EVALUATION_PENDING"
    COMPLETED = "COMPLETED"
    FAILED_RETRYABLE = "FAILED_RETRYABLE"
    FAILED_PERMANENTLY = "FAILED_PERMANENTLY"
    EXPIRED = "EXPIRED"


@dataclass
class CameraJob:
    """Detailed unit of work passing through ingestion and inference pipelines."""
    job_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    cam_id: str = ""
    priority: int = PRIORITY_P3_BACKGROUND
    status: str = CameraJobStatus.QUEUED.value
    image_path: Optional[str] = None
    frame_sha256: Optional[str] = None
    frame_md5: Optional[str] = None
    model_version: str = "vgg16-ssd-hcmc"
    provider_url: Optional[str] = None
    attempt_count: int = 0
    max_attempts: int = 3
    error_code: Optional[str] = None
    captured_at: Optional[str] = None
    retrieved_at: Optional[str] = None
    snapshot_id: Optional[str] = None
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    completed_at: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CameraJob":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


class CameraQueueManager:
    """
    Manages prioritized task queues in Redis with in-memory asyncio fallback.
    Supports atomic job pops, deduplication, coalescing, and ACK lifecycles.
    """

    def __init__(
        self,
        queue_key: str = "vision:priority_zset",
        job_prefix: str = "camera:job:",
        pending_prefix: str = "camera:pending_job:",
        idempotency_prefix: str = "vision:idempotency:",
        dlq_key: str = "vision:dlq",
        job_ttl_sec: int = 3600,
        idempotency_ttl_sec: int = 600,
    ):
        self.queue_key = queue_key
        self.job_prefix = job_prefix
        self.pending_prefix = pending_prefix
        self.idempotency_prefix = idempotency_prefix
        self.dlq_key = dlq_key
        self.job_ttl_sec = job_ttl_sec
        self.idempotency_ttl_sec = idempotency_ttl_sec

        # In-memory priority queue fallback for testing or Redis unavailability
        self._memory_queue: asyncio.PriorityQueue[Tuple[float, str]] = asyncio.PriorityQueue()
        self._memory_jobs: Dict[str, CameraJob] = {}
        self._memory_pending: Dict[str, str] = {}
        self._memory_idempotency: Dict[str, float] = {}

    def _compute_score(self, priority: int, timestamp: Optional[float] = None) -> float:
        """
        Computes composite ranking score:
        Lower value = higher priority.
        Tier 0: [0.0 * 1e12 + ts]
        Tier 1: [1.0 * 1e12 + ts]
        Tier 2: [2.0 * 1e12 + ts]
        Tier 3: [3.0 * 1e12 + ts]
        """
        ts = timestamp if timestamp is not None else time.time()
        return float(priority * 1_000_000_000_000.0 + ts)

    async def check_idempotency(
        self,
        cam_id: str,
        frame_sha256: str,
        model_version: str = "vgg16-ssd-hcmc",
        redis: Optional[Redis] = None,
    ) -> bool:
        """Returns True if this exact frame has already been analyzed by this model version."""
        if not frame_sha256:
            return False
        key = f"{self.idempotency_prefix}{cam_id}:{frame_sha256}:{model_version}"
        if redis is not None:
            try:
                val = await redis.get(key)
                return bool(val)
            except Exception as exc:
                logger.debug("Redis idempotency check error: %s", exc)
        else:
            now = time.time()
            exp = self._memory_idempotency.get(key, 0.0)
            if exp > now:
                return True
        return False

    async def mark_idempotency(
        self,
        cam_id: str,
        frame_sha256: str,
        model_version: str = "vgg16-ssd-hcmc",
        redis: Optional[Redis] = None,
    ) -> None:
        """Marks this frame and model combination as completed to suppress redundant inference."""
        if not frame_sha256:
            return
        key = f"{self.idempotency_prefix}{cam_id}:{frame_sha256}:{model_version}"
        if redis is not None:
            try:
                await redis.set(key, "COMPLETED", ex=self.idempotency_ttl_sec)
            except Exception as exc:
                logger.debug("Redis mark idempotency error: %s", exc)
        else:
            self._memory_idempotency[key] = time.time() + self.idempotency_ttl_sec

    async def enqueue_vision_job(
        self,
        cam_id: str,
        image_path: str,
        priority: int = PRIORITY_P3_BACKGROUND,
        frame_sha256: Optional[str] = None,
        frame_md5: Optional[str] = None,
        model_version: str = "vgg16-ssd-hcmc",
        provider_url: Optional[str] = None,
        captured_at: Optional[str] = None,
        retrieved_at: Optional[str] = None,
        snapshot_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        redis: Optional[Redis] = None,
    ) -> Optional[CameraJob]:
        """
        Enqueues a camera frame for vision inference:
        1. Checks idempotency (skips if exact frame was already inferred).
        2. Coalesces with existing pending job for this camera if present.
        3. Adds to priority queue and persistent job store.
        """
        # 1. Idempotency Check
        if frame_sha256:
            is_dup = await self.check_idempotency(cam_id, frame_sha256, model_version, redis=redis)
            if is_dup:
                logger.debug("Frame %s for camera %s already analyzed; skipping enqueue.", frame_sha256[:8], cam_id)
                return None

        # 2. Coalescing: Check if an unfinished job is already queued for this camera
        pending_key = f"{self.pending_prefix}{cam_id}"
        existing_job_id: Optional[str] = None
        if redis is not None:
            try:
                existing_raw = await redis.get(pending_key)
                if existing_raw:
                    existing_job_id = existing_raw if isinstance(existing_raw, str) else existing_raw.decode("utf-8")
            except Exception:
                pass
        else:
            existing_job_id = self._memory_pending.get(cam_id)

        job_id = existing_job_id or uuid.uuid4().hex
        job = CameraJob(
            job_id=job_id,
            cam_id=cam_id,
            priority=priority,
            status=CameraJobStatus.INFERENCE_PENDING.value,
            image_path=image_path,
            frame_sha256=frame_sha256,
            frame_md5=frame_md5,
            model_version=model_version,
            provider_url=provider_url,
            attempt_count=0,
            captured_at=captured_at,
            retrieved_at=retrieved_at,
            snapshot_id=snapshot_id or (metadata.get("snapshot_id") if metadata else None),
            metadata=metadata or {},
        )

        score = self._compute_score(priority)
        job_data = json.dumps(job.to_dict())

        # 3. Store in Redis or Memory
        if redis is not None:
            try:
                pipe = redis.pipeline()
                pipe.set(f"{self.job_prefix}{job_id}", job_data, ex=self.job_ttl_sec)
                pipe.set(pending_key, job_id, ex=self.job_ttl_sec)
                pipe.zadd(self.queue_key, {job_id: score})
                await pipe.execute()
            except Exception as exc:
                logger.warning("Failed enqueueing vision job to Redis: %s", exc)
                # Fallback to memory
                self._memory_jobs[job_id] = job
                self._memory_pending[cam_id] = job_id
                if not existing_job_id:
                    await self._memory_queue.put((score, job_id))
        else:
            self._memory_jobs[job_id] = job
            self._memory_pending[cam_id] = job_id
            if not existing_job_id:
                await self._memory_queue.put((score, job_id))

        return job

    async def pop_vision_job(
        self,
        redis: Optional[Redis] = None,
        timeout: float = 2.0,
    ) -> Optional[CameraJob]:
        """
        Pops the highest priority job from the queue:
        Atomically removes from ZSET and updates status to INFERENCING.
        """
        if redis is not None:
            try:
                # Atomically pop element with minimum score
                res = await redis.zpopmin(self.queue_key, count=1)
                if not res:
                    return None

                member, score = res[0]
                job_id = member if isinstance(member, str) else member.decode("utf-8")

                raw_job = await redis.get(f"{self.job_prefix}{job_id}")
                if not raw_job:
                    return None

                job_dict = json.loads(raw_job)
                job = CameraJob.from_dict(job_dict)
                job.status = CameraJobStatus.INFERENCING.value
                await redis.set(f"{self.job_prefix}{job_id}", json.dumps(job.to_dict()), ex=self.job_ttl_sec)
                return job
            except Exception as exc:
                logger.debug("Redis pop_vision_job fallback: %s", exc)

        # In-memory fallback
        try:
            score, job_id = await asyncio.wait_for(self._memory_queue.get(), timeout=timeout)
            job = self._memory_jobs.get(job_id)
            if job:
                job.status = CameraJobStatus.INFERENCING.value
            return job
        except (asyncio.TimeoutError, asyncio.QueueEmpty):
            return None

    async def ack_vision_completion(
        self,
        job: CameraJob,
        redis: Optional[Redis] = None,
    ) -> None:
        """
        Marks job as COMPLETED, clears pending key, and records idempotency key.
        """
        now = datetime.now(timezone.utc).isoformat()
        job.status = CameraJobStatus.COMPLETED.value
        job.completed_at = now

        if job.frame_sha256:
            await self.mark_idempotency(job.cam_id, job.frame_sha256, job.model_version, redis=redis)

        pending_key = f"{self.pending_prefix}{job.cam_id}"
        job_key = f"{self.job_prefix}{job.job_id}"

        if redis is not None:
            try:
                pipe = redis.pipeline()
                pipe.set(job_key, json.dumps(job.to_dict()), ex=self.job_ttl_sec)
                pipe.delete(pending_key)
                await pipe.execute()
            except Exception as exc:
                logger.debug("Redis ack completion error: %s", exc)
        else:
            self._memory_pending.pop(job.cam_id, None)
            if job.job_id in self._memory_jobs:
                self._memory_jobs[job.job_id] = job

    async def fail_vision_job(
        self,
        job: CameraJob,
        error_code: str,
        redis: Optional[Redis] = None,
    ) -> None:
        """
        Handles job failure with retry backoff or sends to DLQ if max attempts exceeded.
        """
        job.attempt_count += 1
        job.error_code = error_code
        pending_key = f"{self.pending_prefix}{job.cam_id}"
        job_key = f"{self.job_prefix}{job.job_id}"

        if job.attempt_count < job.max_attempts:
            job.status = CameraJobStatus.FAILED_RETRYABLE.value
            # Backoff delay: 2s, 6s, 18s
            backoff_delay = float(2 * (3 ** (job.attempt_count - 1)))
            retry_score = self._compute_score(job.priority, timestamp=time.time() + backoff_delay)
            job_data = json.dumps(job.to_dict())

            if redis is not None:
                try:
                    pipe = redis.pipeline()
                    pipe.set(job_key, job_data, ex=self.job_ttl_sec)
                    pipe.zadd(self.queue_key, {job.job_id: retry_score})
                    await pipe.execute()
                except Exception as exc:
                    logger.debug("Redis retry job error: %s", exc)
            else:
                self._memory_jobs[job.job_id] = job
                await self._memory_queue.put((retry_score, job.job_id))
        else:
            # Permanent failure -> Dead Letter Queue
            job.status = CameraJobStatus.FAILED_PERMANENTLY.value
            job_data = json.dumps(job.to_dict())

            if redis is not None:
                try:
                    pipe = redis.pipeline()
                    pipe.set(job_key, job_data, ex=self.job_ttl_sec)
                    pipe.delete(pending_key)
                    pipe.rpush(self.dlq_key, job_data)
                    await pipe.execute()
                except Exception as exc:
                    logger.debug("Redis DLQ push error: %s", exc)
            else:
                self._memory_pending.pop(job.cam_id, None)
                if job.job_id in self._memory_jobs:
                    self._memory_jobs[job.job_id] = job

    async def get_queue_stats(self, redis: Optional[Redis] = None) -> Dict[str, Any]:
        """Returns operational metrics across all priority tiers and DLQ."""
        if redis is not None:
            try:
                total_pending = await redis.zcard(self.queue_key)
                dlq_count = await redis.llen(self.dlq_key)
                return {
                    "total_pending": total_pending,
                    "dlq_count": dlq_count,
                    "backend": "redis",
                }
            except Exception as exc:
                logger.debug("Redis get_queue_stats error: %s", exc)

        return {
            "total_pending": self._memory_queue.qsize(),
            "dlq_count": sum(1 for j in self._memory_jobs.values() if j.status == CameraJobStatus.FAILED_PERMANENTLY.value),
            "backend": "memory",
        }


# Singleton Queue Manager Instance
camera_queue_manager = CameraQueueManager()
