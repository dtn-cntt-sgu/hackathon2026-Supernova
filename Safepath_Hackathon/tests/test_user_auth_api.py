import uuid
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from backend.app.main import app
from backend.app.db.session import async_engine
from backend.app.db.models import Base


@pytest_asyncio.fixture(autouse=True)
async def setup_db():
    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield


@pytest.mark.asyncio
async def test_auth_status_endpoint():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/v1/auth/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "status" in data
        assert data["provider"] == "google"
        assert "google_oauth_configured" in data


@pytest.mark.asyncio
async def test_user_sync_and_persistence_flow():
    unique_sub = f"google-sub-{uuid.uuid4().hex[:8]}"
    unique_email = f"user-{uuid.uuid4().hex[:8]}@example.com"
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        sync_payload = {
            "provider": "google",
            "provider_account_id": unique_sub,
            "email": unique_email,
            "display_name": "Test User",
            "avatar_url": "https://lh3.googleusercontent.com/test-avatar.jpg",
        }
        # 1. First sync -> creates user and default preferences
        sync_resp = await client.post("/api/v1/user/sync", json=sync_payload)
        assert sync_resp.status_code == 200
        user_data = sync_resp.json()
        assert user_data["email"] == unique_email
        assert user_data["display_name"] == "Test User"
        assert user_data["preferences"]["transport_mode"] == "motorcycle"
        user_id = user_data["id"]
        assert len(user_id) > 10

        # 2. Get profile by header
        profile_resp = await client.get("/api/v1/user/profile", headers={"X-User-Id": user_id})
        assert profile_resp.status_code == 200
        assert profile_resp.json()["id"] == user_id

        # 3. Update preferences
        pref_resp = await client.put(
            "/api/v1/user/preferences",
            headers={"X-User-Id": user_id},
            json={
                "transport_mode": "car",
                "avoid_flood_level": "HIGH",
                "avoid_high_density": True,
                "alert_notifications": True,
                "voice_guidance_enabled": False,
            },
        )
        assert pref_resp.status_code == 200
        assert pref_resp.json()["transport_mode"] == "car"
        assert pref_resp.json()["avoid_flood_level"] == "HIGH"

        # 4. Add saved place
        place_resp = await client.post(
            "/api/v1/user/saved-places",
            headers={"X-User-Id": user_id},
            json={
                "name": "Nhà riêng",
                "address": "123 Đường Nguyễn Huệ, Quận 1",
                "lat": 10.7745,
                "lng": 106.7025,
                "category": "home",
            },
        )
        assert place_resp.status_code == 200
        place_id = place_resp.json()["id"]

        # 5. Add route history
        history_resp = await client.post(
            "/api/v1/user/history",
            headers={"X-User-Id": user_id},
            json={
                "origin_name": "Chợ Bến Thành",
                "dest_name": "Nhà thờ Đức Bà",
                "origin_lat": 10.7725,
                "origin_lng": 106.6980,
                "dest_lat": 10.7798,
                "dest_lng": 106.6990,
                "distance_km": 1.2,
                "duration_mins": 5,
                "travel_mode": "motorcycle",
            },
        )
        assert history_resp.status_code == 200
        assert history_resp.json()["distance_km"] == 1.2

        # 6. Verify profile has saved place and history
        verify_profile = await client.get("/api/v1/user/profile", headers={"X-User-Id": user_id})
        v_data = verify_profile.json()
        assert len(v_data["saved_places"]) >= 1
        assert v_data["saved_places"][0]["name"] == "Nhà riêng"
        assert len(v_data["route_history"]) >= 1
        assert v_data["preferences"]["transport_mode"] == "car"

        # 7. Delete saved place
        del_resp = await client.delete(f"/api/v1/user/saved-places/{place_id}", headers={"X-User-Id": user_id})
        assert del_resp.status_code == 200

        # Verify deletion
        after_del = await client.get("/api/v1/user/profile", headers={"X-User-Id": user_id})
        assert len(after_del.json()["saved_places"]) == 0

        # 8. Unauthorized / Non-existent user access checks
        bad_req = await client.get("/api/v1/user/profile", headers={"X-User-Id": "non_existent_id_99999"})
        assert bad_req.status_code == 404


@pytest.mark.asyncio
async def test_user_token_enforcement_rejects_cross_user_impersonation_and_forged_tokens():
    """
    Regression test for B02 & R14:
    Verifies that `/api/v1/user/sync` issues a cryptographic HMAC session token,
    and that attempting to access or mutate another user's profile/preferences/places
    using a mismatched `X-User-Id` or forged token is rejected with 403/401.
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        user_a_resp = await client.post(
            "/api/v1/user/sync",
            json={
                "provider": "google",
                "provider_account_id": f"sub-a-{uuid.uuid4().hex[:8]}",
                "email": f"user-a-{uuid.uuid4().hex[:8]}@example.com",
                "display_name": "User A",
            },
        )
        assert user_a_resp.status_code == 200
        user_a = user_a_resp.json()
        user_a_id = user_a["id"]
        user_a_token = user_a.get("session_token")
        assert user_a_token and "." in user_a_token

        user_b_resp = await client.post(
            "/api/v1/user/sync",
            json={
                "provider": "google",
                "provider_account_id": f"sub-b-{uuid.uuid4().hex[:8]}",
                "email": f"user-b-{uuid.uuid4().hex[:8]}@example.com",
                "display_name": "User B",
            },
        )
        assert user_b_resp.status_code == 200
        user_b_id = user_b_resp.json()["id"]

        # 1. Valid token for User A succeeds on User A's profile
        ok_resp = await client.get(
            "/api/v1/user/profile",
            headers={"X-User-Id": user_a_id, "Authorization": f"Bearer {user_a_token}"},
        )
        assert ok_resp.status_code == 200
        assert ok_resp.json()["id"] == user_a_id

        # 2. User A's token attempting to read User B's profile via spoofed X-User-Id -> 403 Forbidden
        cross_read = await client.get(
            "/api/v1/user/profile",
            headers={"X-User-Id": user_b_id, "Authorization": f"Bearer {user_a_token}"},
        )
        assert cross_read.status_code == 403

        # 3. User A's token attempting to mutate User B's preferences -> 403 Forbidden
        cross_write = await client.put(
            "/api/v1/user/preferences",
            headers={"X-User-Id": user_b_id, "Authorization": f"Bearer {user_a_token}"},
            json={
                "transport_mode": "car",
                "avoid_flood_level": "HIGH",
                "avoid_high_density": True,
                "alert_notifications": True,
                "voice_guidance_enabled": False,
            },
        )
        assert cross_write.status_code == 403

        # 4. Forged / tampered Bearer token -> 401 Unauthorized
        forged_resp = await client.get(
            "/api/v1/user/profile",
            headers={"X-User-Id": user_a_id, "Authorization": "Bearer forged.invalid_signature"},
        )
        assert forged_resp.status_code == 401

