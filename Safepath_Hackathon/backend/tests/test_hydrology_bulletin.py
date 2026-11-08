"""Real official fixture, parser boundaries, polling and normalized storage isolation."""
import asyncio
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path

import httpx
import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from backend.app.db.models import HydrologyBulletin, HydrologyBulletinEvent
from backend.app.services import hydrology_bulletin as bulletin

FIXTURES = Path(__file__).parent / "fixtures" / "hydrology"
PDF = (FIXTURES / "HCMC_TVHN_20261107.pdf").read_bytes()
TEXT = (FIXTURES / "HCMC_TVHN_20261107.txt").read_text()
URL = "https://www.phongchonglutbaotphcm.gov.vn/phocadownload/2026/11-2026/HCMC_TVHN_20261107.pdf"


@pytest.fixture(autouse=True)
def clean_poll_state():
    bulletin._local_state.clear()
    bulletin._parse_task = None
    yield
    bulletin._local_state.clear()


class AsyncSessionFacade:
    """SQLite exercises the real SQLAlchemy mappings without optional async drivers."""
    def __init__(self, session):
        self.sync = session

    async def get(self, *args): return self.sync.get(*args)
    async def execute(self, *args): return self.sync.execute(*args)
    async def flush(self): self.sync.flush()
    async def commit(self): self.sync.commit()
    async def rollback(self): self.sync.rollback()
    def add(self, item): self.sync.add(item)
    def add_all(self, items): self.sync.add_all(items)

    @asynccontextmanager
    async def begin_nested(self):
        with self.sync.begin_nested():
            yield


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    HydrologyBulletin.__table__.create(engine)
    HydrologyBulletinEvent.__table__.create(engine)
    with Session(engine) as session:
        yield AsyncSessionFacade(session)
    engine.dispose()


def test_provenance_and_actual_pdf():
    provenance = json.loads((FIXTURES / "HCMC_TVHN_20261107.provenance.json").read_text())
    assert provenance["sha256"] == hashlib.sha256(PDF).hexdigest()
    assert provenance["source_url"] == URL
    parsed = bulletin.parse_bulletin_pdf(PDF)
    assert parsed["bulletin_number"] == "311/2026"
    assert parsed["issued_at"].isoformat() == "2026-11-07T09:06:00+07:00"
    assert parsed["vertical_datum"] == "UNSPECIFIED_IN_BULLETIN"
    assert parsed["source_unit"] == "m"
    assert len(parsed["events"]) == 48


def test_observed_explicit_previous_day_not_rain_or_reservoir():
    events = [e for e in bulletin.parse_bulletin_text(TEXT)["events"] if e["data_type"] == "OBSERVED"]
    assert [e["water_level_m"] for e in events] == [1.25, 1.46, -.66, -.74, 1.24, 1.5, -.84, -.98]
    assert {e["event_date"] for e in events} == {"2026-11-06"}
    assert events[0]["event_time"].hour == 15
    assert events[5]["event_time"].hour == 1


@pytest.mark.parametrize("station,expected", [("tram_phu_an", [1.59, 1.57, -.35, -1.26]), ("tram_nha_be", [1.60, 1.60, -.51, -1.47])])
def test_merged_station_center_rows(station, expected):
    events = [e for e in bulletin.parse_bulletin_text(TEXT)["events"] if e["station_id"] == station and e["event_date"] == "2026-11-08"]
    assert [e["water_level_m"] for e in events] == expected
    assert {e["data_type"] for e in events} == {"FORECAST"}


def test_unknown_station_does_not_carry_previous_label():
    parsed = bulletin.parse_bulletin_text(TEXT)
    assert {e["station_id"] for e in parsed["events"]} == set(bulletin.STATIONS.values())
    assert len([e for e in parsed["events"] if e["station_id"] == "tram_nha_be"]) == 24


@pytest.mark.parametrize("marker", ["ct", "-", "*"])
def test_missing_markers_are_null_with_exact_reason(marker):
    events = bulletin._events("Phú An", date(2026, 11, 8), [marker, marker, "1.50", "03.00", "-0.98", "10.00", "1.20", "11.00"], "FORECAST")
    assert events[0]["water_level_m"] is None
    assert events[0]["event_time"] is None
    assert events[0]["source_value"] == marker
    assert events[0]["missing_reason"] == f"SOURCE_MARKER_{marker}"
    assert events[2]["water_level_m"] == -.98


def test_24_hour_next_day_only_explicit():
    assert bulletin._stamp(date(2026, 12, 31), "24.00").isoformat() == "2027-01-01T00:00:00+07:00"
    assert bulletin._stamp(date(2026, 12, 31), "0.00").date() == date(2026, 12, 31)


@pytest.mark.parametrize("token", ["24.30", "25.00", "11.60", "11", "noon"])
def test_malformed_time_rejected(token):
    with pytest.raises(ValueError): bulletin._stamp(date(2026, 11, 8), token)


@pytest.mark.parametrize("text", ["", TEXT.replace("MỰC NƯỚC THỰC ĐO NGÀY", "MỰC NƯỚC"), TEXT.replace("Tin phát lúc:", "Unknown:"), TEXT.replace("    Nhà Bè              09/11", "    Unknown              09/11")])
def test_unsupported_layout_rejected(text):
    with pytest.raises(ValueError): bulletin.parse_bulletin_text(text)


@pytest.mark.parametrize("url", ["http://www.phongchonglutbaotphcm.gov.vn/phocadownload/x.pdf", "https://evil.test/phocadownload/x.pdf", "https://www.phongchonglutbaotphcm.gov.vn.evil.test/phocadownload/x.pdf", "https://user:pass@www.phongchonglutbaotphcm.gov.vn/phocadownload/x.pdf", "https://www.phongchonglutbaotphcm.gov.vn:444/phocadownload/x.pdf", "/phocadownload/%2e%2e/private", "file:///tmp/x.pdf", "/private/x.pdf", "/phocadownload/x.pdf#frag"])
def test_url_allowlist(url):
    with pytest.raises(ValueError): bulletin.safe_portal_url(url)


def test_discovery_newest_valid_filename_and_not_unrelated_pdf():
    html = f'<a href="{URL}">new</a><a href="{URL.replace("20261107", "20261106")}">old</a><iframe src="/phocadownload/2026/11-2026/rain.pdf"></iframe><a href="https://evil.test/HCMC_TVHN_20990101.pdf">bad</a>'
    pdfs, _ = bulletin.discover_links(html)
    assert pdfs[0] == URL and len(pdfs) == 2


@pytest.mark.asyncio
async def test_discovery_follows_newest_month():
    newer = URL.replace("11-2026", "12-2026").replace("20261107", "20261201")
    def handler(request):
        return httpx.Response(200, text=(f'<a href="/index.php/2026/12-2026">Dec</a><a href="{URL}">old</a>' if str(request.url) == bulletin.LIST_URL else f'<iframe src="{newer}"></iframe>'))
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        assert await bulletin.discover_latest_pdf(client) == newer


@pytest.mark.asyncio
@pytest.mark.parametrize("response", [httpx.Response(302, headers={"location": "https://evil.test/x"}), httpx.Response(200, headers={"content-type": "text/html"}, content=b"x"), httpx.Response(200, headers={"content-type": "application/pdf", "content-length": "4000000"}, content=b"x")])
async def test_download_rejects_redirect_wrong_type_oversize(response):
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: response)) as client:
        with pytest.raises((ValueError, httpx.HTTPStatusError)):
            await bulletin._download(client, URL, pdf=True)


@pytest.mark.asyncio
async def test_stream_cap_without_content_length(monkeypatch):
    monkeypatch.setattr(bulletin.settings, "HYDROLOGY_BULLETIN_MAX_BYTES", 10)
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, headers={"content-type": "application/pdf"}, content=b"%PDF-" * 10))) as client:
        with pytest.raises(ValueError): await bulletin._download(client, URL, pdf=True)


def mock_source(monkeypatch, *, failure=False):
    constructor = httpx.AsyncClient
    def handler(request):
        if failure: raise httpx.ConnectError("offline")
        if str(request.url).endswith(".pdf"):
            return httpx.Response(200, headers={"content-type": "application/pdf"}, content=PDF)
        return httpx.Response(200, text=f'<a href="{URL}">PDF</a>')
    monkeypatch.setattr(bulletin.httpx, "AsyncClient", lambda **kwargs: constructor(transport=httpx.MockTransport(handler), **kwargs))


@pytest.mark.asyncio
async def test_ingest_db_dedupe_and_no_telemetry(db, monkeypatch):
    mock_source(monkeypatch)
    assert (await bulletin.ingest_latest_bulletin(db))["status"] == "INGESTED"
    assert (await db.execute(select(func.count()).select_from(HydrologyBulletin))).scalar() == 1
    assert (await db.execute(select(func.count()).select_from(HydrologyBulletinEvent))).scalar() == 48
    assert (await bulletin.ingest_latest_bulletin(db))["reason"] == "POLL_COOLDOWN"
    bulletin._local_state.clear()
    assert (await bulletin.ingest_latest_bulletin(db))["status"] == "INGESTED"
    assert (await db.execute(select(func.count()).select_from(HydrologyBulletinEvent))).scalar() == 48
    latest = await bulletin.get_latest_bulletin(db)
    assert latest["status"] in {"DAILY_BULLETIN", "STALE"}
    assert latest["vertical_datum"] == bulletin.DATUM
    assert len(latest["events"]) == 48
    assert {e["quality_status"] for e in latest["events"]}.issubset({"OBSERVED_HISTORICAL", "FORECAST_VALID", "FORECAST_PAST"})


@pytest.mark.asyncio
async def test_outage_preserves_last_good_marks_stale(db, monkeypatch):
    mock_source(monkeypatch)
    await bulletin.ingest_latest_bulletin(db)
    bulletin._local_state.clear()
    async def fail(client): raise httpx.ConnectError("offline")
    monkeypatch.setattr(bulletin, "discover_latest_pdf", fail)
    assert (await bulletin.ingest_latest_bulletin(db))["status"] == "UNAVAILABLE"
    latest = await bulletin.get_latest_bulletin(db)
    assert latest["status"] == "STALE"
    assert latest["unavailable_reason"] == "LATEST_POLL_FAILED"
    assert len(latest["events"]) == 48
    assert bulletin._local_state["failures"] == 1


@pytest.mark.asyncio
async def test_empty_storage_unavailable(db):
    assert (await bulletin.get_latest_bulletin(db))["status"] == "UNAVAILABLE"


@pytest.mark.asyncio
async def test_storage_failure_rolls_back_entire_bulletin(db, monkeypatch):
    mock_source(monkeypatch)
    original = bulletin.parse_bulletin_pdf
    def broken(content):
        parsed = original(content)
        parsed["events"][0]["station_name"] = None  # Database NOT NULL fails after header flush.
        return parsed
    monkeypatch.setattr(bulletin, "parse_bulletin_pdf", broken)
    assert (await bulletin.ingest_latest_bulletin(db))["status"] == "UNAVAILABLE"
    assert (await db.execute(select(func.count()).select_from(HydrologyBulletin))).scalar() == 0
    assert (await db.execute(select(func.count()).select_from(HydrologyBulletinEvent))).scalar() == 0


@pytest.mark.asyncio
async def test_redis_lock_failure_does_not_fetch(db, monkeypatch):
    class RedisOffline:
        async def get(self, key): raise ConnectionError()
        async def set(self, *args, **kwargs): raise ConnectionError()
    async def forbidden(client): raise AssertionError("network must not run")
    monkeypatch.setattr(bulletin, "discover_latest_pdf", forbidden)
    assert (await bulletin.ingest_latest_bulletin(db, RedisOffline()))["reason"] == "POLL_LOCK_UNAVAILABLE"


@pytest.mark.asyncio
async def test_retained_parser_prevents_unbounded_threads(db):
    bulletin._parse_task = asyncio.create_task(asyncio.sleep(60))
    try:
        assert (await bulletin.ingest_latest_bulletin(db))["reason"] == "PARSER_IN_PROGRESS"
    finally:
        bulletin._parse_task.cancel()
        try: await bulletin._parse_task
        except asyncio.CancelledError: pass


def test_leap_day_forecast_and_explicit_day_rollover():
    text = TEXT.replace("311/2026", "59/2028").replace("06/11/2026", "27/02/2028")
    text = text.replace("7 tháng 11 năm 2026", "28 tháng 02 năm 2028")
    for previous, current in [("07/11", "28/02"), ("08/11", "29/02"), ("09/11", "01/03"), ("10/11", "02/03"), ("11/11", "03/03")]:
        text = text.replace(previous, current)
    parsed = bulletin.parse_bulletin_text(text)
    assert any(event["event_date"] == "2028-02-29" for event in parsed["events"])
    midnight = bulletin._stamp(date(2026, 12, 31), "24.00")
    assert midnight.isoformat() == "2027-01-01T00:00:00+07:00"


@pytest.mark.asyncio
async def test_missing_event_is_unavailable_in_persisted_api(db, monkeypatch):
    mock_source(monkeypatch)
    original = bulletin.parse_bulletin_pdf
    def missing(content):
        parsed = original(content)
        parsed["events"][0].update(water_level_m=None, source_value="ct", event_time=None, missing_reason="SOURCE_MARKER_ct")
        return parsed
    monkeypatch.setattr(bulletin, "parse_bulletin_pdf", missing)
    assert (await bulletin.ingest_latest_bulletin(db))["status"] == "INGESTED"
    latest = await bulletin.get_latest_bulletin(db)
    item = next(event for event in latest["events"] if event["source_value"] == "ct")
    assert item["water_level_m"] is None and item["event_time"] is None
    assert item["quality_status"] == "UNAVAILABLE"
