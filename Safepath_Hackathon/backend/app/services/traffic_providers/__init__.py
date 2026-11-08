"""
Traffic Provider Package initialization for SafePathAI.
Provides hot-swappable provider factory and interfaces.
"""

from typing import Optional
from backend.app.core.config import settings
from backend.app.services.traffic_providers.base import BaseTrafficProvider, SegmentTrafficFlow
from backend.app.services.traffic_providers.tomtom import TomTomTrafficProvider
from backend.app.services.traffic_providers.here import HereTrafficProvider


def get_traffic_provider(name: Optional[str] = None) -> BaseTrafficProvider:
    """
    Factory to retrieve active traffic flow provider based on configuration or explicit name.
    """
    provider_name = (name or getattr(settings, "TRAFFIC_PROVIDER", "auto")).lower()
    if provider_name == "tomtom":
        return TomTomTrafficProvider()
    elif provider_name == "here":
        return HereTrafficProvider()
    elif provider_name == "auto":
        if settings.TOMTOM_API_KEY and settings.TOMTOM_API_KEY.strip():
            return TomTomTrafficProvider()
        if settings.HERE_API_KEY and settings.HERE_API_KEY.strip():
            return HereTrafficProvider()
        return TomTomTrafficProvider()
    return TomTomTrafficProvider()


__all__ = [
    "BaseTrafficProvider",
    "SegmentTrafficFlow",
    "TomTomTrafficProvider",
    "HereTrafficProvider",
    "get_traffic_provider",
]

