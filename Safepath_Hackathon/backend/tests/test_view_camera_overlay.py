"""Unit-only viewing inference fixtures; no fabricated images are served in production."""
import asyncio
from datetime import datetime, timezone
import hashlib
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.app.core.config import settings
from backend.app.schemas.contracts import CameraEvidence, EvidenceEligibility, RiskLevel
from backend.app.services import camera_overlay as overlay
from backend.app.services import route_camera_ai as ai

CAM = "5deb576d1dc17d7c5515ad1a"


def evidence(**updates):
    now = datetime.now(timezone.utc)
    values = dict(cam_id=CAM, name="Unit camera", lat=10.7, lng=106.7, captured_at=None,
                  retrieved_at=now, updated_at=now, source_status="STALE", risk_level=RiskLevel.UNKNOWN)
    values.update(updates)
    return CameraEvidence(**values)


@pytest.mark.asyncio
async def test_explicit_view_dedupes_without_capture_time_but_never_routes(monkeypatch):
    monkeypatch.setattr(settings, "CAMERA_VIEW_AI_ENABLED", True)
    service = ai.RouteCameraAI()
    monkeypatch.setattr(ai, "model_version", lambda: "unit-version")
    calls=[]
    def analyze(path, metadata, version):
        calls.append(metadata)
        return evidence(snapshot_id=metadata["snapshot_id"], inference_input_sha256="abc",
                        risk_level=RiskLevel.CRITICAL, evidence_eligibility=EvidenceEligibility.ROUTING_ELIGIBLE)
    monkeypatch.setattr(service, "_analyze", analyze)
    metadata=dict(cam_id=CAM, content_sha256="abc", snapshot_id="view-unit", captured_at=None,
                  retrieved_at=datetime.now(timezone.utc), permitted_use="VIEW_ONLY")
    first,second=await asyncio.gather(*(service.analyze("unit.jpg",metadata,None,view_only=True) for _ in range(2)))
    assert len(calls)==1 and first==second
    assert first.risk_level==RiskLevel.UNKNOWN and first.evidence_eligibility==EvidenceEligibility.NOT_VERIFIED_FOR_ROUTING
    assert await service.analyze("unit.jpg",metadata,None) is None
    assert all(key.startswith("camera:view_ai:") for key in service._cache)
    await service.close()


@pytest.mark.asyncio
async def test_immutable_pair_and_frame_changed_gate(tmp_path,monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(settings,"CAMERA_VIEW_AI_ENABLED",True)
    monkeypatch.setattr(overlay,"model_version",lambda:"f"*64)
    content=b"unit-only-source"
    digest=hashlib.sha256(content).hexdigest()
    proxy=SimpleNamespace(get_frame=AsyncMock(return_value=SimpleNamespace(data=content,content_hash=digest,
        retrieved_at=datetime.now(timezone.utc),source_status="RECENTLY_RETRIEVED_CAPTURE_UNKNOWN",provider="vietmap")))
    model=AsyncMock()
    monkeypatch.setattr(overlay.route_camera_ai,"analyze",model)
    changed=await overlay.prepare_camera_overlay({"cam_id":CAM},proxy,"0"*64)
    assert changed["status"]=="FRAME_CHANGED" and changed["content_sha256"]==digest
    model.assert_not_called()
    async def analyze(path,metadata,redis,**kwargs):
        assert kwargs["view_only"] is True and Path(path).read_bytes()==content
        target=Path(path).with_name(Path(path).stem+"_overlay.jpg")
        target.write_bytes(b"unit-overlay")
        return evidence(snapshot_id=metadata["snapshot_id"],inference_input_sha256=digest,
                        vehicle_count=3,vehicle_counts={"car":3},overlay_path=str(target),model_status="INFERENCE_COMPLETED")
    model.side_effect=analyze
    result=await overlay.prepare_camera_overlay({"cam_id":CAM},proxy,digest)
    assert result["status"]=="READY"
    assert result["snapshot_id"]==f"view_{digest}_{'f'*12}"
    assert result["snapshot_id"] in result["image_url"] and result["snapshot_id"] in result["overlay_url"]
    assert "enhanced_url" not in result


@pytest.mark.asyncio
async def test_disabled_or_stale_does_not_run_model(monkeypatch):
    monkeypatch.setattr(settings,"CAMERA_VIEW_AI_ENABLED",False)
    proxy=SimpleNamespace(get_frame=AsyncMock())
    assert (await overlay.prepare_camera_overlay({"cam_id":CAM},proxy))["status"]=="DISABLED"
    proxy.get_frame.assert_not_called()
    monkeypatch.setattr(settings,"CAMERA_VIEW_AI_ENABLED",True)
    proxy.get_frame.return_value=SimpleNamespace(source_status="STALE")
    model=AsyncMock()
    monkeypatch.setattr(overlay.route_camera_ai,"analyze",model)
    assert (await overlay.prepare_camera_overlay({"cam_id":CAM},proxy))["status"]=="UNAVAILABLE"
    model.assert_not_called()


def test_view_does_not_overwrite_legacy_route_files(tmp_path,monkeypatch):
    from PIL import Image
    monkeypatch.chdir(tmp_path)
    path=Path("storage/snapshots")/CAM/"unit-frame.jpg"
    path.parent.mkdir(parents=True)
    Image.effect_noise((300,230),80).convert("RGB").save(path)
    digest=hashlib.sha256(path.read_bytes()).hexdigest()
    legacy=Path("storage/cams")/f"{CAM}_analyzed.jpg"
    legacy.parent.mkdir(parents=True)
    legacy.write_bytes(b"unit-existing-route-overlay")
    def analyze(path,metadata,storage_dir):
        (Path(storage_dir)/f"{CAM}_analyzed.jpg").write_bytes(b"unit-view-overlay")
        return evidence(inference_input_sha256=digest)
    service=ai.RouteCameraAI()
    service._pipeline=SimpleNamespace(analyze_camera_image=analyze)
    service._pipeline_version="unit"
    service._analyze(str(path),{"content_sha256":digest,"permitted_use":"VIEW_ONLY","retrieved_at":datetime.now(timezone.utc)},"unit")
    assert legacy.read_bytes()==b"unit-existing-route-overlay"


def test_reused_original_keeps_truthful_new_retrieval_time(tmp_path):
    import os
    path=tmp_path/'unchanged.jpg'
    path.write_bytes(b'unit-unchanged-frame')
    os.utime(path,(1,1))
    retrieved=datetime.now(timezone.utc)
    overlay._store_original(path,b'unit-unchanged-frame',retrieved)
    assert path.read_bytes()==b'unit-unchanged-frame'
    assert abs(path.stat().st_mtime-retrieved.timestamp())<0.01
