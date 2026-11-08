"""
Tuổi Trẻ RSS Source Adapter for SafePathAI Traffic News.
Fetches real-world municipal news and traffic notices from Tuổi Trẻ Online RSS.
"""

from datetime import datetime, timezone
import logging
import re
from typing import List, Optional
import xml.etree.ElementTree as ET
import httpx

from backend.app.services.news_sources.base import (
    NewsItemData,
    classify_traffic_article,
    compute_news_id,
    parse_news_date,
    resolve_hcm_geocoding,
)

logger = logging.getLogger("safepath.news.tuoitre")

TUOITRE_RSS_URL = "https://tuoitre.vn/rss/thoi-su.rss"

HCMC_LOCAL_KEYWORDS = [
    "tp.hcm", "tp hcm", "sài gòn", "tphcm", "quận 1", "quận 3", "quận 7",
    "bình thạnh", "thủ đức", "gò vấp", "tân bình", "bình chánh", "hóc môn",
]

TRAFFIC_RELEVANCE_KEYWORDS = [
    "giao thông", "ùn tắc", "kẹt xe", "ngập", "triều cường", "cầu",
    "tai nạn", "tuyến đường", "thi công", "hầm chui", "vành đai",
]


async def fetch_tuoitre_news(client: Optional[httpx.AsyncClient] = None) -> List[NewsItemData]:
    """
    Fetches real RSS feed from Tuổi Trẻ Online, extracts HCMC traffic news,
    and returns parsed, verified NewsItemData objects.
    """
    items: List[NewsItemData] = []
    close_client = False
    if client is None:
        client = httpx.AsyncClient(timeout=8.0, follow_redirects=True)
        close_client = True

    try:
        resp = await client.get(TUOITRE_RSS_URL)
        if resp.status_code != 200:
            logger.warning("Tuổi Trẻ RSS responded with HTTP %d", resp.status_code)
            return items

        fetched_at = datetime.now(timezone.utc)
        root = ET.fromstring(resp.content)

        for item_elem in root.findall(".//item"):
            title = (item_elem.findtext("title") or "").strip()
            raw_desc = (item_elem.findtext("description") or "").strip()
            link = (item_elem.findtext("link") or "").strip()
            pub_date_str = item_elem.findtext("pubDate")

            if not title or not link:
                continue

            clean_desc = raw_desc.split("</br>")[-1].replace("]]>", "").strip()
            if "<" in clean_desc:
                clean_desc = re.sub(r"<[^>]+>", "", clean_desc).strip()

            text_lower = (title + " " + clean_desc).lower()

            is_hcm = any(k in text_lower for k in HCMC_LOCAL_KEYWORDS)
            is_traffic = any(k in text_lower for k in TRAFFIC_RELEVANCE_KEYWORDS)

            if not (is_hcm and is_traffic):
                continue

            published_at = parse_news_date(pub_date_str)
            item_id = compute_news_id("tuoitre", link)

            # Extract image url if provided by source
            image_url = None
            enclosure = item_elem.find("enclosure")
            if enclosure is not None and enclosure.get("url"):
                image_url = enclosure.get("url")
            elif "<img" in raw_desc:
                img_match = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', raw_desc)
                if img_match:
                    image_url = img_match.group(1)

            lat, lng, geo_status = resolve_hcm_geocoding(title + " " + clean_desc)
            category, severity, event_status = classify_traffic_article(title, clean_desc)

            items.append(
                NewsItemData(
                    id=item_id,
                    canonical_url=link,
                    source_name="Tuổi Trẻ Online / Thời sự",
                    title=title,
                    summary=clean_desc[:300],
                    category=category,
                    severity=severity,
                    event_status=event_status,
                    published_at=published_at,
                    fetched_at=fetched_at,
                    latitude=lat,
                    longitude=lng,
                    location_confidence=geo_status,
                    geocoding_status=geo_status,
                    verification_status="VERIFIED_SOURCE",
                    image_url=image_url,
                )
            )
    except Exception as exc:
        logger.warning("Tuổi Trẻ RSS fetch error: %s", exc)
    finally:
        if close_client:
            await client.aclose()

    return items

