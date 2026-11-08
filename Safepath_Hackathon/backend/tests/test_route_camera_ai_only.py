"""Isolated fixtures verify route admission, bounded inference and actual ranking."""
import asyncio
from datetime import datetime, timedelta, timezone
import hashlib
import threading
import time
from unittest.mock import AsyncMock

import pytest

from backend.app.core.config import settings
from backend.app.schemas.contracts import CameraEvidence, DataSourceStatus, EvidenceEligibility, RiskLevel
from backend.app.services import route_camera_ai as ai


def camera(**updates):
    now = datetime.now(timezone.utc)
    values = dict(cam_id="56de42f611f398ec0c48127d", name="Test camera", lat=10.8, lng=106.7,
                  permitted_use="ROUTING_EVIDENCE_PERMITTED", coordinate_source_url="https://source.test/gps",
                  view_verification_source_url="https://source.test/view", line_of_sight_verified=True,
                  observed_osm_way_id=1001, observed_edge_index=0, spatial_match_status="OBSERVED_SEGMENT_VERIFIED",
                  risk_level=RiskLevel.UNKNOWN, source_status=DataSourceStatus.LIVE, updated_at=now,
                  retrieved_at=now, captured_at=now, snapshot_id="snapshot-1")
    values.update(updates)
    return CameraEvidence(**values)


@pytest.fixture
def enabled(monkeypatch):
    for field, value in dict(CAMERA_AI_MODE="route_only", ROUTE_CAMERA_AI_ENABLED=True,
                             CAMERA_INGESTION_PERMITTED=True, CAMERA_ROUTING_EVIDENCE_PERMITTED=True,
                             ROUTE_AI_TIMEOUT_SECONDS=0.5, ROUTE_AI_MAX_CONCURRENCY=2,
                             ROUTE_AI_MAX_CAMERAS=4).items():
        monkeypatch.setattr(settings, field, value)


@pytest.mark.parametrize("changes", [dict(line_of_sight_verified=False), dict(observed_osm_way_id=99),
                                    dict(observed_edge_index=None), dict(observed_edge_index=2),
                                    dict(coordinate_source_url=None), dict(view_verification_source_url=None),
                                    dict(permitted_use="VIEW_ONLY"), dict(permitted_use="PERMISSION_UNVERIFIED")])
def test_camera_must_observe_verified_step(changes):
    assert not ai.belongs_to_step(camera(**changes), [dict(osm_way_id=1001, edge_index=0, route_match_verified=True)])


@pytest.mark.parametrize("age", [None, -100, 121, 3600])
def test_unverified_or_old_capture_rejected(age):
    value = None if age is None else datetime.now(timezone.utc) - timedelta(seconds=age)
    assert not ai.fresh(value)


@pytest.mark.asyncio
@pytest.mark.parametrize("flag", ["ROUTE_CAMERA_AI_ENABLED", "CAMERA_INGESTION_PERMITTED", "CAMERA_ROUTING_EVIDENCE_PERMITTED"])
async def test_permissions_disable_all_snapshot_and_model_work(enabled, monkeypatch, flag):
    monkeypatch.setattr(settings, flag, False)
    snapshot = AsyncMock()
    monkeypatch.setattr(ai, "_snapshot", snapshot)
    await ai.enrich_route_cameras({(0, 0): [camera()]}, {(0, 0): [dict(osm_way_id=1001, edge_index=0, route_match_verified=True)]}, None, None)
    snapshot.assert_not_called()


@pytest.mark.asyncio
async def test_no_related_cameras_never_fetch(enabled, monkeypatch):
    snapshot = AsyncMock()
    monkeypatch.setattr(ai, "_snapshot", snapshot)
    await ai.enrich_route_cameras({(0, 0): [camera()]}, {}, None, None)
    snapshot.assert_not_called()


def metadata(hash_value="abc"):
    return {**camera().model_dump(), "content_sha256": hash_value, "image_path": "immutable.jpg"}


@pytest.mark.asyncio
async def test_singleflight_cache_snapshot_change_and_expiry(enabled, monkeypatch):
    service = ai.RouteCameraAI()
    calls = []
    def analyze(path, meta, version):
        calls.append(meta["content_sha256"])
        time.sleep(0.02)
        return camera(inference_input_sha256=meta["content_sha256"])
    monkeypatch.setattr(service, "_analyze", analyze)
    monkeypatch.setattr(ai, "model_version", lambda: "v1")
    first, second = await asyncio.gather(service.analyze("immutable.jpg", metadata(), None), service.analyze("immutable.jpg", metadata(), None))
    assert first == second
    assert len(calls) == 1
    await service.analyze("immutable.jpg", metadata(), None)
    assert len(calls) == 1
    await service.analyze("immutable.jpg", metadata("changed"), None)
    assert len(calls) == 2
    monkeypatch.setattr(ai, "model_version", lambda: "v2")
    await service.analyze("immutable.jpg", metadata(), None)
    assert len(calls) == 3
    for key, (_, evidence) in list(service._cache.items()):
        service._cache[key] = (time.monotonic() - 1, evidence)
    await service.analyze("immutable.jpg", metadata(), None)
    assert len(calls) == 4
    service._executor.shutdown()


@pytest.mark.asyncio
async def test_timeout_keeps_running_thread_in_concurrency_budget(enabled, monkeypatch):
    monkeypatch.setattr(settings, "ROUTE_AI_MAX_CONCURRENCY", 1)
    service = ai.RouteCameraAI()
    released = threading.Event()
    started = []
    def analyze(path, meta, version):
        started.append(meta["content_sha256"])
        released.wait(1)
        return camera(inference_input_sha256=meta["content_sha256"])
    monkeypatch.setattr(service, "_analyze", analyze)
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(service.analyze("immutable.jpg", metadata(), None), 0.03)
    second = asyncio.create_task(service.analyze("immutable.jpg", metadata("second"), None))
    await asyncio.sleep(0.03)
    assert started == ["abc"]
    released.set()
    await second
    assert started == ["abc", "second"]
    service._executor.shutdown()


@pytest.mark.asyncio
async def test_model_unavailable_does_not_fail_route(enabled, monkeypatch):
    service = ai.RouteCameraAI()
    def unavailable(*args):
        raise RuntimeError("MODEL_UNAVAILABLE")
    monkeypatch.setattr(service, "_analyze", unavailable)
    assert await service.analyze("immutable.jpg", metadata(), None) is None
    service._executor.shutdown()


def test_hash_mismatch_rejected_before_model(tmp_path):
    path = tmp_path / "snapshot.jpg"
    path.write_bytes(b"actual source bytes")
    service = ai.RouteCameraAI()
    with pytest.raises(ValueError, match="SNAPSHOT_HASH_MISMATCH"):
        service._analyze(str(path), metadata("wrong-sha"), "v1")
    assert service._pipeline is None


@pytest.mark.asyncio
async def test_route_camera_limit_and_provenance(enabled, monkeypatch):
    monkeypatch.setattr(settings, "ROUTE_AI_MAX_CAMERAS", 1)
    snapshot = AsyncMock(return_value={"snapshot_id": "snapshot-1", "content_sha256": "abc",
                                      "image_path": "immutable.jpg", "captured_at": camera().captured_at,
                                      "retrieved_at": camera().retrieved_at})
    monkeypatch.setattr(ai, "_snapshot", snapshot)
    analyze = AsyncMock(return_value=camera(line_of_sight_verified=False, observed_osm_way_id=999))
    monkeypatch.setattr(ai.route_camera_ai, "analyze", analyze)
    result = await ai.enrich_route_cameras({(0, 0): [camera(), camera(cam_id="other")]},
                                         {(0, 0): [dict(osm_way_id=1001, edge_index=0, route_match_verified=True)]}, None, None)
    assert snapshot.call_count == analyze.call_count == 1
    assert result[(0, 0)][0].observed_osm_way_id == 1001
    assert result[(0, 0)][0].line_of_sight_verified


@pytest.mark.asyncio
async def test_route_timeout_returns_unknown(enabled, monkeypatch):
    monkeypatch.setattr(settings, "ROUTE_AI_TIMEOUT_SECONDS", 0.01)
    async def slow_snapshot(*args):
        await asyncio.sleep(1)
    monkeypatch.setattr(ai, "_snapshot", slow_snapshot)
    result = await ai.enrich_route_cameras({(0, 0): [camera()]}, {(0, 0): [dict(osm_way_id=1001, edge_index=0, route_match_verified=True)]}, None, None)
    assert result[(0, 0)][0].risk_level == RiskLevel.UNKNOWN


@pytest.mark.asyncio
async def test_route_ranking_uses_new_camera_evidence_before_scoring(enabled, monkeypatch):
    from backend.app.services import routing
    geometry = {"type": "LineString", "coordinates": [[106.7, 10.8], [106.701, 10.801]]}
    def route(distance):
        return dict(distance=distance, duration=60, geometry=geometry,
                    legs=[dict(steps=[dict(distance=distance, duration=60, geometry=geometry, name="Test road")])])
    monkeypatch.setattr(routing, "_get_osrm_raw_routes", AsyncMock(return_value=[route(150), route(180)]))
    monkeypatch.setattr(routing, "_batched_spatial_context", AsyncMock(return_value=(
        {(0, 0): [dict(osm_way_id=1001, edge_index=0, route_match_verified=True)], (1, 0): [dict(osm_way_id=2002, edge_index=0, route_match_verified=True)]},
        {(0, 0): [camera()]}, True, True)))
    monkeypatch.setattr(routing, "_get_flood_prone_way_ids", AsyncMock(return_value=set()))
    async def enrich(cameras, edges, session, redis, **context):
        return {(0, 0): [camera(flood_ratio=0.8, evidence_eligibility=EvidenceEligibility.ROUTING_ELIGIBLE)]}
    monkeypatch.setattr(ai, "enrich_route_cameras", enrich)
    results = await routing.find_safe_route(10.8, 106.7, 10.801, 106.701, None)
    assert results[0].overall_risk == RiskLevel.UNKNOWN
    assert results[1].overall_risk == RiskLevel.CRITICAL
    assert results[0].ranking_cost < results[1].ranking_cost
    assert results[1].segments[0].evidence_cameras[0].flood_ratio == 0.8


@pytest.mark.asyncio
async def test_fresh_matching_current_model_evidence_avoids_inference(enabled, monkeypatch):
    import json
    from pathlib import Path
    model = json.loads(Path("data/models/model_manifest.json").read_text())["models"]["vehicle_detector"]
    evidence = camera(evidence_eligibility=EvidenceEligibility.ROUTING_ELIGIBLE,
                      vehicle_model_sha256=model["sha256"], model_version=model["version"],
                      inference_input_sha256="abc", route_ai_model_version=ai.model_version())
    snapshot = dict(snapshot_id=evidence.snapshot_id, content_sha256="abc", image_path="immutable.jpg",
                    captured_at=evidence.captured_at, retrieved_at=evidence.retrieved_at)
    monkeypatch.setattr(ai, "_snapshot", AsyncMock(return_value=snapshot))
    analyze = AsyncMock()
    monkeypatch.setattr(ai.route_camera_ai, "analyze", analyze)
    await ai.enrich_route_cameras({(0, 0): [evidence]}, {(0, 0): [dict(osm_way_id=1001, edge_index=0, route_match_verified=True)]}, None, None)
    analyze.assert_not_called()
    assert not ai.sufficient_existing_evidence(evidence, {**snapshot, "content_sha256": "different"})


@pytest.mark.asyncio
async def test_pending_work_is_globally_bounded(enabled, monkeypatch):
    monkeypatch.setattr(settings, "ROUTE_AI_MAX_CONCURRENCY", 1)
    service = ai.RouteCameraAI()
    release = threading.Event()
    def analyze(path, meta, version):
        release.wait(1)
        return camera(inference_input_sha256=meta["content_sha256"])
    monkeypatch.setattr(service, "_analyze", analyze)
    first = asyncio.create_task(service.analyze("immutable.jpg", metadata("one"), None))
    second = asyncio.create_task(service.analyze("immutable.jpg", metadata("two"), None))
    await asyncio.sleep(0.02)
    assert await service.analyze("immutable.jpg", metadata("three"), None) is None
    assert len(service._inflight) == 2
    release.set()
    await asyncio.gather(first, second)
    await service.close()
    assert await service.analyze("immutable.jpg", metadata("closed"), None) is None


@pytest.mark.asyncio
async def test_established_critical_context_avoids_extra_visual_work(enabled, monkeypatch):
    from types import SimpleNamespace
    from backend.app.services import risk_engine
    monkeypatch.setattr(risk_engine, "calculate_segment_risk", lambda **kwargs: SimpleNamespace(risk_level=RiskLevel.CRITICAL, is_closed=False))
    snapshot = AsyncMock()
    monkeypatch.setattr(ai, "_snapshot", snapshot)
    await ai.enrich_route_cameras({(0, 0): [camera()]}, {(0, 0): [dict(osm_way_id=1001, edge_index=0, route_match_verified=True)]},
                                  None, None, step_context={(0, 0): dict(distance=100)})
    snapshot.assert_not_called()


def test_old_flood_model_manifest_invalidates_existing_evidence():
    evidence = camera(evidence_eligibility=EvidenceEligibility.ROUTING_ELIGIBLE,
                      inference_input_sha256="abc", route_ai_model_version="old-combined-version")
    assert not ai.sufficient_existing_evidence(evidence, dict(snapshot_id=evidence.snapshot_id, content_sha256="abc"))


@pytest.mark.asyncio
async def test_equal_bytes_from_different_snapshot_never_reuses_wrong_snapshot(enabled, monkeypatch):
    service = ai.RouteCameraAI()
    calls = []
    def analyze(path, meta, version):
        calls.append(meta["snapshot_id"])
        return camera(snapshot_id=meta["snapshot_id"], inference_input_sha256=meta["content_sha256"])
    monkeypatch.setattr(service, "_analyze", analyze)
    await service.analyze("immutable.jpg", metadata(), None)
    result = await service.analyze("immutable.jpg", {**metadata(), "snapshot_id": "snapshot-2"}, None)
    assert result.snapshot_id == "snapshot-2"
    assert calls == ["snapshot-1", "snapshot-2"]
    await service.close()


@pytest.mark.asyncio
async def test_disabled_ai_does_not_retain_old_model_routing_eligibility(enabled, monkeypatch):
    monkeypatch.setattr(settings, "ROUTE_CAMERA_AI_ENABLED", False)
    old = camera(evidence_eligibility=EvidenceEligibility.ROUTING_ELIGIBLE,
                 route_ai_model_version="obsolete-manifest")
    result = await ai.enrich_route_cameras({(0, 0): [old]}, {}, None, None)
    assert result[(0, 0)][0].evidence_eligibility == EvidenceEligibility.NOT_VERIFIED_FOR_ROUTING


@pytest.mark.asyncio
async def test_repeated_lifespan_can_reopen_inference(enabled, monkeypatch):
    service = ai.RouteCameraAI()
    monkeypatch.setattr(service, "_analyze", lambda path, meta, version: camera(
        inference_input_sha256=meta["content_sha256"], snapshot_id=meta["snapshot_id"]))
    assert await service.analyze("immutable.jpg", metadata("first"), None) is not None
    await service.close()
    assert await service.analyze("immutable.jpg", metadata("second"), None) is None
    service.reopen()
    assert await service.analyze("immutable.jpg", metadata("second"), None) is not None
    await service.close()
