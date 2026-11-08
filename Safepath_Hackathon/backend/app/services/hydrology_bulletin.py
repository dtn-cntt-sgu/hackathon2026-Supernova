"""Bounded ingestion of official daily tidal extrema; never feeds live risk caches."""
from __future__ import annotations

from backend.app.core.observability import observe_operation
import random
import asyncio
import hashlib
import io
import json
import logging
import re
import time
import uuid
from datetime import date, datetime, timedelta, timezone
from html.parser import HTMLParser
from urllib.parse import unquote, urljoin, urlsplit
from zoneinfo import ZoneInfo

import httpx
from pypdf import PdfReader
from sqlalchemy import select

from backend.app.core.config import settings
from backend.app.db.models import HydrologyBulletin, HydrologyBulletinEvent

LIST_URL = "https://www.phongchonglutbaotphcm.gov.vn/index.php/da-ba-o-tha-y-v-n"
PORTAL_HOST = "www.phongchonglutbaotphcm.gov.vn"
ICT = ZoneInfo("Asia/Ho_Chi_Minh")
SOURCE_NAME = "Đài Khí tượng Thủy văn Nam Bộ / Cổng Phòng chống thiên tai TP.HCM"
DATUM = "UNSPECIFIED_IN_BULLETIN"
STATIONS = {"Phú An": "tram_phu_an", "Nhà Bè": "tram_nha_be"}
_STATE_KEY = "hydrology:daily_bulletin:poll"
_LOCK_KEY = "hydrology:daily_bulletin:lock"
_poll_lock = asyncio.Lock()
_local_state: dict = {}
_parse_task: asyncio.Task | None = None
logger = logging.getLogger(__name__)


def safe_portal_url(value: str, base: str = LIST_URL) -> str:
    url = urljoin(base, value)
    part = urlsplit(url)
    decoded = unquote(part.path)
    if (part.scheme != "https" or part.hostname != PORTAL_HOST or part.port not in (None, 443)
            or part.username or part.password or part.fragment or "\\" in decoded
            or any(piece in (".", "..") for piece in decoded.split("/"))
            or not decoded.startswith(("/index.php/", "/phocadownload/"))):
        raise ValueError("URL outside the official hydrology portal")
    return url


class _Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.urls: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in {"a", "iframe", "embed"}:
            for key, value in attrs:
                if key in {"href", "src"} and value:
                    try:
                        self.urls.append(safe_portal_url(value))
                    except ValueError:
                        pass


def discover_links(html: str) -> tuple[list[str], list[str]]:
    parser = _Links()
    parser.feed(html)
    pdfs, months = [], []
    for url in set(parser.urls):
        path = urlsplit(url).path
        match = re.fullmatch(r"/phocadownload/(\d{4})/\d{2}-\d{4}/HCMC_TVHN_(\d{8})\.pdf", path, re.I)
        if match:
            try:
                date.fromisoformat(f"{match[2][:4]}-{match[2][4:6]}-{match[2][6:]}")
                pdfs.append(url)
            except ValueError:
                pass
        if re.fullmatch(r"/index.php/\d{4}/\d{2}-\d{4}", path):
            months.append(url)
    return sorted(pdfs, key=lambda u: re.search(r"(\d{8})\.pdf", u, re.I)[1], reverse=True), sorted(months, reverse=True)


def _stamp(day: date, token: str) -> datetime | None:
    if token in {"ct", "-", "*"}:
        return None
    match = re.fullmatch(r"(\d{1,2})[.:](\d{2})", token)
    if not match:
        raise ValueError(f"Unsupported tide time: {token}")
    hour, minute = map(int, match.groups())
    if hour == 24 and minute == 0:
        return datetime.combine(day + timedelta(days=1), datetime.min.time(), ICT)
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=ICT)


def _events(name: str, day: date, cells: list[str], data_type: str) -> list[dict]:
    if len(cells) != 8:
        raise ValueError("Expected four level/time pairs")
    events = []
    for index in range(4):
        value, raw_time = cells[index * 2:index * 2 + 2]
        level = None if value in {"ct", "-", "*"} else float(value.replace(",", "."))
        if level is not None and not -5 <= level <= 5:
            raise ValueError("Unexpected tidal level")
        event_time = _stamp(day, raw_time)
        reason = f"SOURCE_MARKER_{value}" if level is None else (f"SOURCE_TIME_MARKER_{raw_time}" if event_time is None else None)
        events.append(dict(station_id=STATIONS[name], station_name=name, event_date=day.isoformat(),
                           data_type=data_type, event_kind="HIGH_TIDE" if index < 2 else "LOW_TIDE",
                           event_slot=index % 2 + 1, water_level_m=level, source_value=value,
                           source_time=raw_time, event_time=event_time, missing_reason=reason))
    return events


def parse_bulletin_text(text: str) -> dict:
    number = re.search(r"Bản tin số\s*:\s*(\d+/\d{4})", text)
    issued = re.search(r"Tin phát lúc:\s*(\d{1,2}):(\d{2})\s*giờ ngày\s*(\d{1,2})\s*tháng\s*(\d{1,2})\s*năm\s*(\d{4})", text)
    observed = re.search(r"MỰC NƯỚC THỰC ĐO NGÀY\s+(\d{2}/\d{2}/\d{4})\s*\(m\)", text)
    if not number or not issued or not observed or "MỰC NƯỚC DỰ BÁO (m)" not in text:
        raise ValueError("Unsupported official bulletin layout")
    hour, minute, day, month, year = map(int, issued.groups())
    issued_at = datetime(year, month, day, hour, minute, tzinfo=ICT)
    if number[1].split("/")[1] != str(year):
        raise ValueError("Bulletin year does not match issuance")
    observation_day = datetime.strptime(observed[1], "%d/%m/%Y").date()
    if not 0 <= (issued_at.date() - observation_day).days <= 7:
        raise ValueError("Observation date outside daily bulletin")
    measured, forecast = text[observed.end():].split("MỰC NƯỚC DỰ BÁO (m)", 1)
    events = []
    for name in STATIONS:
        rows = [line for line in measured.splitlines() if re.match(rf"\s*{re.escape(name)}\s+", line)]
        if len(rows) != 1:
            raise ValueError(f"Missing or duplicate measured station: {name}")
        events.extend(_events(name, observation_day, rows[0].split()[-8:], "OBSERVED"))
    # Merged station cells are centered: identify the station across each date-reset group.
    groups: list[list[tuple[str, date, list[str]]]] = []
    previous_day = None
    for line in forecast.split("Cảnh báo", 1)[0].splitlines():
        match = re.match(r"\s*(.*?)\s*(\d{2}/\d{2})\s+(.+?)\s*$", line)
        if not match:
            continue
        dm = datetime.strptime(f"{match[2]}/{year}", "%d/%m/%Y").date()
        # Forecasts may cross New Year; select the occurrence near issuance.
        alternatives = []
        for candidate_year in (year - 1, year, year + 1):
            try:
                alternatives.append(dm.replace(year=candidate_year))
            except ValueError:  # February 29 has no occurrence in neighboring non-leap years.
                continue
        forecast_day = min(alternatives, key=lambda d: abs((d - issued_at.date()).days))
        if previous_day is None or forecast_day <= previous_day:
            groups.append([])
        groups[-1].append((match[1].strip(), forecast_day, match[3].split()))
        previous_day = forecast_day
    seen = set()
    for group in groups:
        labels = {name for name, _, _ in group if name}
        target = labels.intersection(STATIONS)
        if not target:
            continue
        if len(labels) != 1 or len(target) != 1:
            raise ValueError("Ambiguous forecast station group")
        name = target.pop()
        if name in seen or len(group) != 5:
            raise ValueError("Expected one five-day forecast per station")
        seen.add(name)
        if [row[1] for row in group] != [issued_at.date() + timedelta(days=offset) for offset in range(5)]:
            raise ValueError("Expected five consecutive forecast dates")
        for _, forecast_day, cells in group:
            if not 0 <= (forecast_day - issued_at.date()).days <= 5:
                raise ValueError("Forecast outside daily bulletin window")
            events.extend(_events(name, forecast_day, cells, "FORECAST"))
    if seen != set(STATIONS):
        raise ValueError("Missing forecast station group")
    return dict(bulletin_number=number[1], bulletin_date=issued_at.date().isoformat(),
                issued_at=issued_at, source_unit="m", vertical_datum=DATUM, source_name=SOURCE_NAME, events=events)


def parse_bulletin_pdf(content: bytes) -> dict:
    if not content.startswith(b"%PDF-"):
        raise ValueError("Response is not a PDF")
    reader = PdfReader(io.BytesIO(content), strict=True)
    if reader.is_encrypted or not 1 <= len(reader.pages) <= 4:
        raise ValueError("Unsupported PDF size/encryption")
    text = "\n".join(page.extract_text(extraction_mode="layout") or "" for page in reader.pages)
    if len(text) > 100_000:
        raise ValueError("Oversized extracted bulletin")
    return parse_bulletin_text(text)


async def _download(client: httpx.AsyncClient, url: str, *, pdf: bool = False) -> bytes:
    url = safe_portal_url(url)
    maximum = getattr(settings, "HYDROLOGY_BULLETIN_MAX_BYTES", 3_000_000) if pdf else 1_000_000
    with observe_operation("hydrology"):
        async with client.stream("GET", url, follow_redirects=False) as response:
            response.raise_for_status()
            if response.is_redirect:
                raise ValueError("Portal redirects are not followed")
            kind = response.headers.get("content-type", "").split(";", 1)[0].lower()
            if pdf and kind not in {"application/pdf", "application/octet-stream"}:
                raise ValueError("Unexpected PDF content type")
            if int(response.headers.get("content-length", "0")) > maximum:
                raise ValueError("Response exceeds bulletin byte limit")
            content = bytearray()
            async for chunk in response.aiter_bytes():
                content.extend(chunk)
                if len(content) > maximum:
                    raise ValueError("Response exceeds bulletin byte limit")
            return bytes(content)


async def discover_latest_pdf(client: httpx.AsyncClient) -> str:
    html = (await _download(client, LIST_URL)).decode("utf-8", errors="replace")
    pdfs, months = discover_links(html)
    if months:
        more, _ = discover_links((await _download(client, months[0])).decode("utf-8", errors="replace"))
        pdfs.extend(more)
    if not pdfs:
        raise ValueError("No supported official daily PDF link found")
    return max(pdfs, key=lambda url: re.search(r"(\d{8})\.pdf", url, re.I)[1])


async def _state(redis) -> dict:
    if redis is not None:
        try:
            raw = await redis.get(_STATE_KEY)
            if raw:
                return json.loads(raw)
        except Exception:
            logger.warning("Bulletin Redis state unavailable")
    return _local_state.copy()


async def _save_state(redis, state: dict):
    _local_state.clear()
    _local_state.update(state)
    if redis is not None:
        try:
            await redis.set(_STATE_KEY, json.dumps(state), ex=172800)
        except Exception:
            logger.warning("Could not persist bulletin polling state")


async def ingest_latest_bulletin(session, redis=None) -> dict:
    """One bounded polling attempt. Errors retain the previous valid database bulletin."""
    global _parse_task
    if not getattr(settings, "HYDROLOGY_BULLETIN_ENABLED", True):
        return {"status": "DISABLED"}
    if _parse_task is not None and not _parse_task.done():
        return {"status": "SKIPPED", "reason": "PARSER_IN_PROGRESS"}
    if _poll_lock.locked():
        return {"status": "SKIPPED", "reason": "POLL_IN_PROGRESS"}
    async with _poll_lock:
        state = await _state(redis)
        if time.time() < state.get("next_attempt", 0):
            return {"status": "SKIPPED", "reason": "POLL_COOLDOWN"}
        token, acquired = uuid.uuid4().hex, False
        timeout = getattr(settings, "HYDROLOGY_BULLETIN_TIMEOUT_SECONDS", 10)
        if redis is not None:
            try:
                acquired = bool(await redis.set(_LOCK_KEY, token, nx=True, ex=max(120, int(timeout * 5))))
                if not acquired:
                    return {"status": "SKIPPED", "reason": "POLL_IN_PROGRESS"}
            except Exception:
                # Without distributed exclusion, do not multiply upstream fetches across workers.
                return {"status": "UNAVAILABLE", "reason": "POLL_LOCK_UNAVAILABLE"}
        try:
            async with asyncio.timeout(timeout * 4):
                async with httpx.AsyncClient(timeout=timeout, verify=True, follow_redirects=False) as client:
                    source_url = await discover_latest_pdf(client)
                    content = await _download(client, source_url, pdf=True)
                # Shield the one retained task: a timed-out thread must finish before another starts.
                _parse_task = asyncio.create_task(asyncio.to_thread(parse_bulletin_pdf, content))
                _parse_task.add_done_callback(lambda task: task.exception() if not task.cancelled() else None)
                parsed = await asyncio.wait_for(asyncio.shield(_parse_task), timeout=timeout)
            now = datetime.now(timezone.utc)
            if parsed["issued_at"] > now + timedelta(minutes=10):
                raise ValueError("Bulletin issuance is in the future")
            digest = hashlib.sha256(content).hexdigest()
            if await session.get(HydrologyBulletin, digest) is None:
                events = parsed.pop("events")
                async with session.begin_nested():
                    session.add(HydrologyBulletin(content_sha256=digest, source_url=source_url, fetched_at=now, **parsed))
                    await session.flush()
                    session.add_all([HydrologyBulletinEvent(bulletin_sha256=digest, **event) for event in events])
                    await session.flush()
                await session.commit()
            await _save_state(redis, {"next_attempt": time.time() + max(1800, getattr(settings, "HYDROLOGY_BULLETIN_POLL_SECONDS", 1800)),
                                      "last_success": now.isoformat(), "last_error": None, "failures": 0})
            return {"status": "INGESTED", "content_sha256": digest, "source_url": source_url}
        except Exception as exc:
            await session.rollback()
            failures = min(int(state.get("failures", 0)) + 1, 5)
            await _save_state(redis, {**state, "next_attempt": time.time() + min(21600, 1800 * 2 ** (failures - 1)) * random.uniform(1.0, 1.1),
                                      "last_error": type(exc).__name__, "last_attempt": datetime.now(timezone.utc).isoformat(), "failures": failures})
            logger.warning("Daily hydrology bulletin unavailable: %s", type(exc).__name__)
            return {"status": "UNAVAILABLE", "reason": "BULLETIN_FETCH_OR_PARSE_FAILED"}
        finally:
            if acquired:
                try:
                    await redis.eval("if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('del', KEYS[1]) else return 0 end", 1, _LOCK_KEY, token)
                except Exception:
                    logger.warning("Bulletin poll lock will expire")


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


async def get_latest_bulletin(session, redis=None) -> dict:
    unavailable = {"status": "UNAVAILABLE", "events": [], "unavailable_reason": "NO_VALID_BULLETIN", "vertical_datum": DATUM}
    try:
        # A missing additive table must not abort a caller's existing transaction.
        async with session.begin_nested():
            bulletin = (await session.execute(select(HydrologyBulletin).order_by(HydrologyBulletin.issued_at.desc(), HydrologyBulletin.fetched_at.desc()).limit(1))).scalar_one_or_none()
            if bulletin is None:
                return unavailable
            rows = (await session.execute(select(HydrologyBulletinEvent).where(HydrologyBulletinEvent.bulletin_sha256 == bulletin.content_sha256)
                                           .order_by(HydrologyBulletinEvent.station_id, HydrologyBulletinEvent.event_date, HydrologyBulletinEvent.data_type, HydrologyBulletinEvent.event_kind, HydrologyBulletinEvent.event_slot))).scalars().all()
        now = datetime.now(timezone.utc)
        state = await _state(redis)
        stale = (now - _aware(bulletin.issued_at)).total_seconds() > getattr(settings, "HYDROLOGY_BULLETIN_MAX_AGE_HOURS", 36) * 3600
        stale = stale or bool(state.get("last_error")) or not getattr(settings, "HYDROLOGY_BULLETIN_ENABLED", True)
        events = []
        for row in rows:
            timestamp = _aware(row.event_time) if row.event_time else None
            quality = "UNAVAILABLE" if row.water_level_m is None or timestamp is None else (
                "OBSERVED_HISTORICAL" if row.data_type == "OBSERVED" else
                "FORECAST_PAST" if timestamp < now else "FORECAST_VALID")
            events.append({key: getattr(row, key) for key in ("station_id", "station_name", "event_date", "data_type", "event_kind", "event_slot", "water_level_m", "source_value", "source_time", "missing_reason")}
                          | {"event_time": timestamp.astimezone(ICT).isoformat() if timestamp else None, "quality_status": quality})
        return {"status": "STALE" if stale else "DAILY_BULLETIN", "bulletin_number": bulletin.bulletin_number,
                "bulletin_date": bulletin.bulletin_date, "issued_at": _aware(bulletin.issued_at).astimezone(ICT).isoformat(),
                "fetched_at": _aware(bulletin.fetched_at).isoformat(), "source_url": bulletin.source_url, "source_name": bulletin.source_name,
                "content_sha256": bulletin.content_sha256, "source_unit": bulletin.source_unit, "vertical_datum": bulletin.vertical_datum,
                "timezone": "Asia/Ho_Chi_Minh", "events": events,
                "unavailable_reason": "LATEST_POLL_FAILED" if state.get("last_error") else ("BULLETIN_TOO_OLD_OR_DISABLED" if stale else None)}
    except Exception as exc:
        logger.warning("Could not read daily hydrology bulletin: %s", type(exc).__name__)
        return {**unavailable, "unavailable_reason": "BULLETIN_STORAGE_UNAVAILABLE"}
