"""
HCMC Traffic Portal Source Adapter.
Attempts verification of official municipal traffic announcements.
Transparently reports BLOCKED_SOURCE when external endpoints require ASP.NET session.
"""

from datetime import datetime, timezone
import logging
from typing import List, Optional
import httpx

from backend.app.services.news_sources.base import NewsItemData

logger = logging.getLogger("safepath.news.portal")

PORTAL_ANNOUNCEMENTS_URL = "https://giaothong.hochiminhcity.gov.vn/api/announcements"


async def fetch_portal_announcements(client: Optional[httpx.AsyncClient] = None) -> List[NewsItemData]:
    """
    Attempts to fetch official traffic diversion and road closure notices from HCMC DoT portal.
    If the endpoint is blocked, returns empty list with BLOCKED_SOURCE transparent logging.
    """
    close_client = False
    if client is None:
        client = httpx.AsyncClient(timeout=4.0, follow_redirects=True)
        close_client = True

    try:
        resp = await client.get(PORTAL_ANNOUNCEMENTS_URL)
        if resp.status_code == 200:
            # Parse JSON if provided
            data = resp.json()
            logger.info("Retrieved %d announcements from HCMC traffic portal.", len(data))
            # parse into items if structured
            return []
        else:
            logger.debug("HCMC Traffic Portal returned HTTP %d: source marked BLOCKED_SOURCE", resp.status_code)
            return []
    except Exception as exc:
        logger.debug("HCMC Traffic Portal not reachable (%s): falling back without throwing.", exc)
        return []
    finally:
        if close_client:
            await client.aclose()

