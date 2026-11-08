"""Unit security regressions; fake cache and bodies exist only in tests."""
import asyncio
import hashlib
import hmac
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import HTTPException
from starlette.requests import Request

from backend.app import main
from backend.app.core.config import Settings, settings
from backend.app.core.auth import verify_user_session_token, verify_proxy_identity_signature
from backend.app.core.http_limits import RequestBodyLimit


@pytest.mark.asyncio
async def test_unauthorized_writes_and_identity_spoofing_fail_before_mutation():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url='http://test') as client:
        for path in ('/api/v1/hydrology/ingest',):
            result = await client.post(path, json={})
            assert result.status_code == 401
        for path in ('/api/v1/admin/camera-ingestion/status', '/api/v1/admin/cameras/metrics'):
            assert (await client.get(path)).status_code == 401
        sync = {'provider':'google', 'provider_account_id':'fake-google-sub', 'email':'fake@example.com', 'display_name':'Fake'}
        assert (await client.post('/api/v1/user/sync', json=sync)).status_code == 401
        assert (await client.get('/api/v1/user/profile', headers={'X-User-Id':'someone-else'})).status_code == 401
        assert (await client.put('/api/v1/user/preferences', headers={'X-User-Id':'someone-else'}, json={})).status_code in (401,422)


@pytest.mark.asyncio
async def test_hydrology_service_token_enforced_and_audited(monkeypatch, caplog):
    monkeypatch.setattr(settings, 'SERVICE_AUTH_TOKEN', 'unit-test-only-worker-token')
    ingest = AsyncMock(return_value=[])
    monkeypatch.setattr(main.hydrology_service, 'run_ingestion_cycle', ingest)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url='http://test') as client:
        assert (await client.post('/api/v1/hydrology/ingest', headers={'Authorization':'Bearer wrong'}, json={})).status_code == 401
        ingest.assert_not_called()
        assert (await client.post('/api/v1/hydrology/ingest', headers={'Authorization':'Bearer unit-test-only-worker-token'}, json={})).status_code == 200
        assert (await client.post('/api/v1/hydrology/ingest', headers={'Authorization':'Bearer unit-test-only-worker-token'}, json={'bulletin_text':'x'*100001})).status_code == 422
    assert 'unit-test-only-worker-token' not in caplog.text


@pytest.mark.asyncio
async def test_sync_rejects_signed_identity_body_mismatch():
    ts = str(int(time.time()))
    signature = hmac.new(settings.AUTH_SECRET.encode(), f'owner@example.com:owner:{ts}'.encode(), hashlib.sha256).hexdigest()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url='http://test') as client:
        result = await client.post('/api/v1/user/sync', headers={'X-Auth-User-Email':'owner@example.com','X-Auth-Provider-Id':'owner', 'X-Auth-Timestamp':ts, 'X-Auth-Signature':signature}, json={'provider':'google','provider_account_id':'victim','email':'victim@example.com','display_name':'spoof'})
    assert result.status_code in (401,403)


@pytest.mark.asyncio
async def test_request_body_limit_checks_content_length_and_chunked_body():
    async def target(scope, receive, send):
        raise AssertionError('Oversized body reached application')
    app = RequestBodyLimit(target, max_bytes=10)
    for headers, body in (([(b'content-length',b'11')], [b'x']), ([], [b'123456',b'78901'])):
        messages = iter([{'type':'http.request','body':chunk,'more_body':index<len(body)-1} for index,chunk in enumerate(body)])
        outputs=[]
        async def receive(): return next(messages)
        async def send(message): outputs.append(message)
        await app({'type':'http','headers':headers},receive,send)
        assert outputs[0]['status'] == 413


@pytest.mark.asyncio
async def test_shared_rate_limit_ignores_forged_forwarded_ip_and_fails_closed(monkeypatch):
    keys=[]
    async def evaluate(script, count, key):
        keys.append(key)
        return len(keys)
    cache=SimpleNamespace(eval=evaluate,aclose=AsyncMock())
    monkeypatch.setattr(main,'get_redis_client',lambda:cache)
    for forwarded in ('1.1.1.1','2.2.2.2'):
        request=Request({'type':'http','headers':[(b'x-forwarded-for',forwarded.encode()),(b'x-test-enforce-rate-limit',b'1')], 'client':('192.0.2.1',1000)})
        if not keys: await main.enforce_rate_limit(request,'test-spoof',1)
        else:
            with pytest.raises(HTTPException) as error: await main.enforce_rate_limit(request,'test-spoof',1)
            assert error.value.status_code == 429
    assert keys[0] == keys[1]
    monkeypatch.setattr(settings,'APP_ENV','production')
    cache.eval=AsyncMock(side_effect=OSError('cache unavailable'))
    with pytest.raises(HTTPException) as error: await main.enforce_rate_limit(request,'test-failure',1)
    assert error.value.status_code == 503


def test_production_rejects_unconfigured_or_fixed_secrets():
    with pytest.raises(ValueError): Settings(_env_file=None, APP_ENV='production')
    with pytest.raises(ValueError): Settings(_env_file=None, APP_ENV='production', AUTH_SECRET='safepath_dev_hmac_secret_replace_in_production_32chars', SERVICE_AUTH_TOKEN='x'*48, CORS_ALLOWED_ORIGINS=['https://test.invalid'])
    configuration=Settings(_env_file=None, APP_ENV='production', AUTH_SECRET='a'*48, SERVICE_AUTH_TOKEN='b'*48, CORS_ALLOWED_ORIGINS=['https://test.invalid'])
    assert configuration.CAMERA_VIEW_AI_ENABLED is True
    with pytest.raises(ValueError): Settings(_env_file=None, APP_ENV='production', AUTH_SECRET='a'*48, SERVICE_AUTH_TOKEN='b'*48, CORS_ALLOWED_ORIGINS=['*'])


def test_malformed_auth_inputs_fail_closed():
    assert verify_user_session_token('☃.invalid') is None
    assert not verify_proxy_identity_signature('e@example.com','sub',str(int(time.time())),'☃')


@pytest.mark.asyncio
async def test_local_osrm_failure_never_uses_public_graph(monkeypatch):
    from backend.app.services import routing
    monkeypatch.setattr(settings,'OSRM_BASE_URL','http://localhost:5001')
    monkeypatch.setattr(routing,'_osrm_circuit_open_until',0)
    hosts=[]
    async def source(request):
        hosts.append(request.url.host)
        raise httpx.ConnectError('offline',request=request)
    async with httpx.AsyncClient(transport=httpx.MockTransport(source)) as client:
        with pytest.raises(routing.RoutingError) as error:
            await routing._get_osrm_raw_routes(10.7725,106.698,10.795,106.7218,client)
    assert error.value.status_code == 503
    assert hosts == ['localhost']


@pytest.mark.asyncio
async def test_readiness_returns_503_when_core_unavailable(monkeypatch):
    monkeypatch.setattr(main, 'get_health', AsyncMock(return_value={'status':'degraded','database':'unhealthy','redis':'healthy','osrm':'unavailable'}))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url='http://test') as client:
        response = await client.get('/api/v1/ready')
    assert response.status_code == 503
    assert response.json()['ready'] is False and response.json()['routing_ready'] is False


def test_model_hash_cache_invalidates_on_weight_change(tmp_path, monkeypatch):
    import json
    from backend.app.services import vision
    path=tmp_path/'weights.onnx'
    path.write_bytes(b'original-weights')
    manifest=tmp_path/'manifest.json'
    manifest.write_text(json.dumps({'models':{'vehicle_detector':{'file_path':str(path),'size_bytes':len(b'original-weights'),'sha256':hashlib.sha256(b'original-weights').hexdigest()}}}))
    monkeypatch.setattr(vision,'DEFAULT_MANIFEST_PATH',str(manifest))
    vision._model_file_digest.cache_clear()
    assert vision.verified_model_manifest_entry('vehicle_detector',str(path))
    assert vision.verified_model_manifest_entry('vehicle_detector',str(path))
    assert vision._model_file_digest.cache_info().hits == 1
    path.write_bytes(b'tampered-weights')
    assert vision.verified_model_manifest_entry('vehicle_detector',str(path)) is None


@pytest.mark.asyncio
async def test_candidate_edge_cannot_trigger_model_or_become_route_evidence(monkeypatch):
    from backend.app.services import route_camera_ai as ai
    from backend.tests.test_route_camera_ai_only import camera
    monkeypatch.setattr(settings,'CAMERA_INGESTION_PERMITTED',True)
    monkeypatch.setattr(settings,'CAMERA_ROUTING_EVIDENCE_PERMITTED',True)
    snapshot=AsyncMock()
    monkeypatch.setattr(ai,'_snapshot',snapshot)
    observed=camera(evidence_eligibility='ROUTING_ELIGIBLE',route_ai_model_version=ai.model_version())
    candidate={'osm_way_id':1001,'edge_index':0}
    assert not ai.belongs_to_step(observed,[candidate])
    result=await ai.enrich_route_cameras({(0,0):[observed]}, {(0,0):[candidate]},None,None)
    snapshot.assert_not_called()
    assert result[(0,0)][0].evidence_eligibility == 'NOT_VERIFIED_FOR_ROUTING'


def test_proxy_identity_binds_stable_provider_id_even_if_email_matches():
    user = SimpleNamespace(is_active=True, email='shared@example.com',provider_account_id='historical-google-sub')
    with pytest.raises(HTTPException) as error:
        main.verify_proxy_row_owner(user,'shared@example.com','different-google-sub','verified-signature')
    assert error.value.status_code == 403
    main.verify_proxy_row_owner(user,'shared@example.com','historical-google-sub','verified-signature')


@pytest.mark.asyncio
async def test_revoked_image_rights_fail_before_database_or_files(monkeypatch):
    monkeypatch.setattr(settings,'CAMERA_ALLOW_VIEW_ONLY',False)
    monkeypatch.setattr(settings,'CAMERA_INGESTION_PERMITTED',False)
    database=AsyncMock()
    async def get_db(): yield database
    main.app.dependency_overrides[main.get_db]=get_db
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app),base_url='http://test') as client:
            for suffix in ('','?snapshot_id=old-frame','?type=analyzed&snapshot_id=old-frame'):
                response=await client.get('/api/v1/cameras/5deb576d1dc17d7c5515ad1a/image'+suffix)
                assert response.status_code == 403
                assert response.headers['cache-control'] == 'no-store'
        database.execute.assert_not_called()
    finally: main.app.dependency_overrides.pop(main.get_db,None)


@pytest.mark.asyncio
async def test_unknown_priority_ids_never_mutate_redis_or_allocate_locks(monkeypatch):
    database=AsyncMock()
    database.execute.return_value=SimpleNamespace(scalars=lambda:SimpleNamespace(all=lambda:[]))
    async def get_db(): yield database
    main.app.dependency_overrides[main.get_db]=get_db
    cache=AsyncMock()
    monkeypatch.setattr(main,'get_redis_client',lambda:cache)
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app),base_url='http://test') as client:
            unknown='aaaaaaaaaaaaaaaaaaaaaaaa'
            for path in ('active-view','active-route'):
                response=await client.post('/api/v1/cameras/'+path,json={'cam_ids':[unknown]})
                assert response.status_code == 404
            assert (await client.post('/api/v1/cameras/'+unknown+'/refresh')).status_code == 404
            assert unknown not in main._camera_refresh_locks
        cache.set.assert_not_called()
        cache.zadd.assert_not_called()
    finally: main.app.dependency_overrides.pop(main.get_db,None)
