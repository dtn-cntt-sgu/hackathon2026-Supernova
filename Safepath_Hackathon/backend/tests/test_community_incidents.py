"""Real PostgreSQL persistence/authorization; no production mock reports."""
from datetime import datetime, timedelta, timezone
from uuid import uuid4
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select

from backend.app.core.auth import create_user_session_token
from backend.app.core.config import settings
from backend.app.db.community_models import CommunityIncident
from backend.app.db.models import Base, User
from backend.app.db.session import AsyncSessionLocal, async_engine
from backend.app.main import app
from backend.app.api.community import IncidentCreate, IncidentModeration, incident_response
from backend.app.services.community_incidents import load_verified_incidents


@pytest_asyncio.fixture
async def account():
    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    uid = str(uuid4())
    async with AsyncSessionLocal() as db:
        db.add(User(id=uid, provider="google", provider_account_id=uid, email=uid+"@example.com", display_name="QA reporter", is_active=True))
        await db.commit()
    yield uid, {"Authorization": "Bearer " + create_user_session_token(uid, uid+"@example.com", uid), "X-User-Id": uid}
    async with AsyncSessionLocal() as db:
        await db.execute(delete(CommunityIncident).where(CommunityIncident.user_id == uid))
        await db.execute(delete(User).where(User.id == uid))
        await db.commit()


def payload():
    return {"incident_type": "FLOOD", "description": "Water visible across the roadway", "lat": 10.77, "lng": 106.7,
            "observed_at": datetime.now(timezone.utc).isoformat()}


@pytest.mark.asyncio
async def test_report_persists_pending_and_isolates_accounts(account):
    uid, headers = account
    async with AsyncClient(transport=ASGITransport(app), base_url="http://test", headers=headers) as client:
        result = await client.post("/api/v1/user/incidents", json=payload())
        assert result.status_code == 201, result.text
        report = result.json()
        assert report["status"] == "PENDING" and "user_id" not in report
        assert (await client.get("/api/v1/user/incidents")).json()[0]["id"] == report["id"]
        assert (await client.post("/api/v1/user/incidents", json=payload())).status_code == 409
        assert (await client.get("/api/v1/user/incidents", headers={"X-User-Id": "other-account"})).status_code == 403
    async with AsyncSessionLocal() as db:
        row = (await db.execute(select(CommunityIncident).where(CommunityIncident.id == report["id"]))).scalar_one()
        assert row.user_id == uid
        assert await load_verified_incidents(db, [(123, 1)]) == {}


@pytest.mark.asyncio
async def test_anonymous_and_user_cannot_moderate(account):
    _, headers = account
    async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
        assert (await client.post("/api/v1/user/incidents", json=payload())).status_code == 401
        result = await client.post("/api/v1/user/incidents", json=payload(), headers=headers)
        assert result.status_code == 201
        assert (await client.patch("/api/v1/admin/incidents/"+result.json()["id"], headers=headers,
                                  json={"status": "VERIFIED", "note": "Independently confirmed", "evidence_url": "https://example.org/bulletin"})).status_code == 401
        assert (await client.get("/api/v1/admin/incidents", headers=headers)).status_code == 401


@pytest.mark.asyncio
async def test_service_moderation_and_expiry(account, monkeypatch):
    _, headers = account
    monkeypatch.setattr(settings, "SERVICE_AUTH_TOKEN", "qa-only-community-service-token")
    service = {"Authorization": "Bearer qa-only-community-service-token"}
    async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
        result = await client.post("/api/v1/user/incidents", headers=headers, json=payload())
        identifier = result.json()["id"]
        endpoint = "/api/v1/admin/incidents/" + identifier
        assert (await client.patch(endpoint, headers=service, json={"status": "VERIFIED", "note": "Independently confirmed"})).status_code == 422
        result = await client.patch(endpoint, headers=service, json={"status": "VERIFIED", "note": "Independently confirmed", "evidence_url": "https://example.org/official-bulletin"})
        assert result.status_code == 200, result.text
        assert result.json()["status"] == "VERIFIED"
        async with AsyncSessionLocal() as db:
            row = await db.get(CommunityIncident, identifier)
            row.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
            await db.commit()
            assert incident_response(row)["status"] == "EXPIRED"
            assert await load_verified_incidents(db, [(123, 1)]) == {}
        result = await client.patch(endpoint, headers=service, json={"status": "VERIFIED", "note": "Independently confirmed", "evidence_url": "https://example.org/official-bulletin"})
        assert result.status_code == 409


@pytest.mark.parametrize("override", [{"lat": float("inf")}, {"lng": 0}, {"description": "          "},
    {"observed_at": "2020-01-01T00:00:00Z"}, {"observed_at": "2026-11-08T00:00:00"}, {"status": "VERIFIED"}])
def test_report_trust_boundaries(override):
    with pytest.raises(ValueError):
        IncidentCreate(**(payload() | override))


def test_moderation_requires_safe_reference_and_paired_edge_identity():
    for extra in ({"evidence_url": "http://example.org"}, {"evidence_url": "https://name:secret@example.org"},
                  {"evidence_url": "https://example.org", "osm_way_id": 123}):
        with pytest.raises(ValueError):
            IncidentModeration(status="VERIFIED", note="Independently confirmed", **extra)


@pytest.mark.asyncio
async def test_disabled_account_rejected_across_existing_user_apis(account):
    uid, headers = account
    async with AsyncSessionLocal() as db:
        row = await db.get(User, uid)
        row.is_active = False
        await db.commit()
    async with AsyncClient(transport=ASGITransport(app), base_url="http://test", headers=headers) as client:
        for method, endpoint, body in [
            ("GET", "/api/v1/user/profile", None),
            ("PUT", "/api/v1/user/preferences", {"transport_mode": "car"}),
            ("POST", "/api/v1/user/saved-places", {"name": "QA", "address": "QA", "lat": 10.77, "lng":106.7}),
        ]:
            response = await client.request(method, endpoint, json=body)
            assert response.status_code == 403, (endpoint, response.text)
        assert (await client.get("/api/v1/user/incidents")).status_code == 401


def test_session_rejects_signed_wrong_issuer_or_audience():
    import base64, hashlib, hmac, json
    from backend.app.core.auth import verify_user_session_token
    token = create_user_session_token("qa-user", "qa@example.com")
    assert verify_user_session_token(token)
    encoded, _ = token.split(".")
    claims = json.loads(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)))
    for overrides in ({"iss": "other-service"}, {"aud": "other-api"}, {"iss": None}, {"exp": 1}):
        raw = base64.urlsafe_b64encode(json.dumps(claims | overrides).encode()).decode().rstrip("=")
        signed = raw + "." + hmac.new(settings.AUTH_SECRET.encode(), raw.encode(), hashlib.sha256).hexdigest()
        assert verify_user_session_token(signed) is None


@pytest.mark.asyncio
async def test_verified_report_cannot_survive_edge_reassignment(account):
    from sqlalchemy import text
    uid, _ = account
    way = 800000000000 + int(uuid4().hex[:7], 16)
    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        try:
            await db.execute(text("INSERT INTO road_segments(osm_way_id, geom, source_pbf_md5) VALUES (:way, ST_GeomFromText('LINESTRING(106.7 10.77,106.701 10.77)',4326), :hash)"), {"way": way, "hash": "a"*32})
            await db.execute(text("INSERT INTO road_edges(osm_way_id,edge_index,length_meters,geom,source_node_id,target_node_id) VALUES (:way,1,110,ST_GeomFromText('LINESTRING(106.7 10.77,106.701 10.77)',4326),101,102)"), {"way":way})
            report = CommunityIncident(id=str(uuid4()), user_id=uid, incident_type="BLOCKED", description="Independently confirmed road closure", lat=10.77, lng=106.7,
                status="VERIFIED", observed_at=now, created_at=now, expires_at=now+timedelta(hours=1), evidence_url="https://example.org/official-closure",
                osm_way_id=way, edge_index=1, road_source_pbf_md5="a"*32, source_node_id=101, target_node_id=102)
            db.add(report)
            await db.flush()
            assert len((await load_verified_incidents(db, [(way,1)]))[(way,1)]) == 1
            await db.execute(text("UPDATE road_segments SET source_pbf_md5=:hash WHERE osm_way_id=:way"), {"way":way,"hash":"b"*32})
            assert await load_verified_incidents(db, [(way,1)]) == {}
            await db.execute(text("UPDATE road_segments SET source_pbf_md5=:hash WHERE osm_way_id=:way"), {"way":way,"hash":"a"*32})
            await db.execute(text("UPDATE road_edges SET target_node_id=103 WHERE osm_way_id=:way"), {"way":way})
            assert await load_verified_incidents(db, [(way,1)]) == {}
        finally:
            await db.rollback()
