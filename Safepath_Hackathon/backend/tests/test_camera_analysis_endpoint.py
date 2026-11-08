"""Unit HTTP fixtures for explicit camera inspection; model responses are mocked only here."""
from types import SimpleNamespace
from unittest.mock import AsyncMock
import httpx
import pytest
from backend.app.main import app, get_db
from backend.app.core.config import settings
from backend.app.services import camera_overlay

CAM='5deb576d1dc17d7c5515ad1a'

@pytest.fixture
def inspection(monkeypatch):
    for key in ('CAMERA_VIEW_AI_ENABLED','CAMERA_PROXY_ENABLED','CAMERA_ALLOW_VIEW_ONLY'):
        monkeypatch.setattr(settings,key,True)
    db=AsyncMock()
    db.execute.return_value=SimpleNamespace(mappings=lambda:SimpleNamespace(one_or_none=lambda:{'cam_id':CAM,'name':'Unit camera','lat':10.7,'lng':106.7}))
    async def dependency():yield db
    app.dependency_overrides[get_db]=dependency
    monkeypatch.setattr(app.state,'camera_proxy',object(),raising=False)
    analyze=AsyncMock(return_value={'status':'READY','snapshot_id':'immutable-unit','content_sha256':'a'*64})
    monkeypatch.setattr(camera_overlay,'prepare_camera_overlay',analyze)
    yield db,analyze
    app.dependency_overrides.pop(get_db,None)

@pytest.mark.asyncio
async def test_selected_frame_is_forwarded_and_permission_is_not_elevated(inspection):
    _,analyze=inspection
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
        response=await client.post(f'/api/v1/cameras/{CAM}/analysis',json={'snapshot_id':'a'*64})
    assert response.status_code==200
    assert analyze.await_args.kwargs['expected_snapshot_id']=='a'*64
    assert 'permitted_use' not in analyze.await_args.args[0]

@pytest.mark.asyncio
async def test_disabled_inspection_and_invalid_source_never_infer(inspection,monkeypatch):
    db,analyze=inspection
    monkeypatch.setattr(settings,'CAMERA_VIEW_AI_ENABLED',False)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
        assert (await client.post(f'/api/v1/cameras/{CAM}/analysis')).status_code==403
    db.execute.assert_not_called();analyze.assert_not_called()

@pytest.mark.asyncio
async def test_unknown_camera_and_invalid_frame_hash_are_rejected(inspection):
    db,analyze=inspection
    db.execute.return_value=SimpleNamespace(mappings=lambda:SimpleNamespace(one_or_none=lambda:None))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
        assert (await client.post(f'/api/v1/cameras/{CAM}/analysis')).status_code==404
        assert (await client.post(f'/api/v1/cameras/{CAM}/analysis',json={'snapshot_id':'../other-frame'})).status_code==422
        assert (await client.get(f'/api/v1/cameras/{CAM}/image?type=enhanced')).status_code==422
        assert (await client.get(f'/api/v1/cameras/{CAM}/image?type=analyzed')).status_code==400
    analyze.assert_not_called()
