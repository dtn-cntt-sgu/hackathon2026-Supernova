"""Real disposable-PostGIS regressions for complete status tokens and atomic snapshots."""
from dataclasses import replace
from datetime import datetime, timezone

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession

from backend.tests.test_database_migrations import migration_db, upgrade
from backend.app.services.scraper import ScrapedCameraResult, DataSourceStatus
from backend.app.services.camera_scheduler import camera_scheduler
from backend.app.services.routing import calculate_hcmc_route_eta


@pytest.mark.asyncio
async def test_full_freshness_token_persists_and_failed_snapshot_keeps_previous_latest(migration_db):
    upgrade(migration_db)
    engine = create_async_engine(migration_db.url.set(drivername="postgresql+asyncpg"))
    try:
        async with AsyncSession(engine) as session:
            await session.execute(text("INSERT INTO traffic_cameras(cam_id,name) VALUES('snapshot-regression','Fixture')"))
            await session.commit()
            now = datetime.now(timezone.utc)
            result = ScrapedCameraResult(cam_id="snapshot-regression", code=None, name="Fixture", district=None,
                lat=None,lng=None,image_path="storage/fixture-only.jpg",image_bytes=b"synthetic fixture",
                source_status=DataSourceStatus.LIVE,retrieved_at=now,captured_at=None,
                capture_time_status="CAPTURE_TIME_UNKNOWN",file_size=17,is_valid_image=True,
                snapshot_id="fixture-first",freshness_status="RECENTLY_RETRIEVED_CAPTURE_UNKNOWN")
            await camera_scheduler.record_result(session,result)
            assert await session.scalar(text("SELECT freshness_status FROM camera_snapshots WHERE snapshot_id='fixture-first'")) == result.freshness_status
            assert await session.scalar(text("SELECT character_maximum_length FROM information_schema.columns WHERE table_name='camera_snapshots' AND column_name='freshness_status'")) == 64
            # A real DB length violation must roll back both insertion and the previous-latest update.
            with pytest.raises(DBAPIError,match="value too long"):
                await camera_scheduler.record_result(session,replace(result,snapshot_id="fixture-rejected",freshness_status="X"*65))
            # The savepoint leaves this transaction usable without a caller rollback.
            assert await session.scalar(text("SELECT is_latest FROM camera_snapshots WHERE snapshot_id='fixture-first'")) is True
            assert await session.scalar(text("SELECT count(*) FROM camera_snapshots WHERE snapshot_id='fixture-rejected'")) == 0
            assert await session.scalar(text("SELECT latest_snapshot_id FROM camera_ingestion_state WHERE cam_id='snapshot-regression'")) == "fixture-first"
    finally:
        await engine.dispose()


@pytest.mark.parametrize("raw_seconds", [1790.999,1791.001])
def test_eta_minutes_derive_from_serialized_seconds_at_rounding_boundary(raw_seconds):
    # Walking time is distance / speed, with no invented traffic-light wait.
    distance = raw_seconds * (4.8 / 3.6)
    result = calculate_hcmc_route_eta([],distance,raw_seconds,transport_mode="WALKING")
    assert result["estimated_duration_seconds"] == 1791.0
    assert result["estimated_time_mins"] == round(result["estimated_duration_seconds"] / 60,1)
    assert result["estimated_time_mins"] == 29.9
