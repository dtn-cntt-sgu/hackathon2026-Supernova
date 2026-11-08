"""Explicit selected-camera analysis, bound to immutable source bytes."""
import asyncio
import hashlib
import os
from pathlib import Path
import tempfile

from backend.app.core.config import settings
from backend.app.services.route_camera_ai import route_camera_ai, model_version


def _store_original(path: Path, data: bytes, retrieved_at) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == hashlib.sha256(data).hexdigest():
        os.utime(path, (retrieved_at.timestamp(), retrieved_at.timestamp()))
        return
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as output:
            temporary = output.name
            output.write(data)
        os.replace(temporary, path)
        os.utime(path, (retrieved_at.timestamp(), retrieved_at.timestamp()))
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)


async def prepare_camera_overlay(camera: dict, proxy, expected_snapshot_id: str | None = None) -> dict:
    if not settings.CAMERA_VIEW_AI_ENABLED:
        return {"status": "DISABLED", "reason": "Phân tích ảnh chưa được bật."}
    frame = await proxy.get_frame(camera["cam_id"])
    if frame.source_status == "STALE":
        return {"status": "UNAVAILABLE", "reason": "Nguồn chưa trả được ảnh mới để phân tích. Hãy thử lại."}
    snapshot_id = f"view_{frame.content_hash}_{model_version()[:12]}"
    path = Path("storage/snapshots") / camera["cam_id"] / f"{snapshot_id}.jpg"
    await asyncio.to_thread(_store_original, path, frame.data, frame.retrieved_at)
    image_url = f"/api/v1/cameras/{camera['cam_id']}/image?snapshot_id={snapshot_id}"
    source = {"snapshot_id": snapshot_id, "content_sha256": frame.content_hash,
              "retrieved_at": frame.retrieved_at.isoformat(), "provider": frame.provider,
              "image_url": image_url}
    if expected_snapshot_id and expected_snapshot_id != frame.content_hash:
        return {**source, "status": "FRAME_CHANGED", "reason": "Nguồn đã cập nhật ảnh. Đang dùng ảnh mới để phân tích."}
    metadata = {**camera, "snapshot_id": snapshot_id, "content_sha256": frame.content_hash,
                "captured_at": None, "retrieved_at": frame.retrieved_at,
                "line_of_sight_verified": False, "observed_osm_way_id": None,
                "observed_edge_index": None, "permitted_use": "VIEW_ONLY"}
    try:
        result = await asyncio.wait_for(route_camera_ai.analyze(str(path), metadata, None, view_only=True),
                                        timeout=settings.CAMERA_VIEW_AI_TIMEOUT_SECONDS)
    except asyncio.TimeoutError:
        return {**source, "status": "PENDING", "reason": "Model đang xử lý ảnh. Kiểm tra lại để lấy kết quả."}
    if result is None:
        return {**source, "status": "UNAVAILABLE", "reason": "Model đang bận hoặc chưa xử lý được ảnh. Hãy thử lại."}
    if (result.vehicle_count is None or not result.overlay_path or not Path(result.overlay_path).is_file()
            or result.inference_input_sha256 != frame.content_hash or result.snapshot_id != snapshot_id):
        return {**source, "status": "MODEL_UNAVAILABLE", "reason": "Chưa tạo được nhận diện cho đúng ảnh này. Hãy thử lại."}
    return {**source, "status": "READY", "vehicle_count": result.vehicle_count,
            "vehicle_counts": result.vehicle_counts, "flood_ratio": result.flood_ratio,
            "model_status": result.model_status, "model_version": result.model_version,
            "analysis_confidence": result.analysis_confidence,
            "traffic_density_score": result.traffic_density_score,
            "traffic_density_level": result.traffic_density_level,
            "analyzed_at": result.analyzed_at.isoformat() if result.analyzed_at else None,
            "overlay_url": f"/api/v1/cameras/{camera['cam_id']}/image?type=analyzed&snapshot_id={snapshot_id}",
            "notice": "Kết quả nhận diện thuộc ảnh này; không tự xác nhận hiện trạng ngập hoặc mức an toàn tuyến đường."}
