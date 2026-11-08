"""
Traffic Provider Base Architecture for SafePathAI.
Defines abstract provider interfaces and standardized traffic flow structures.
Strict Zero-Mock: missing or unconfigured providers return UNKNOWN; never synthesize speeds.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional
from backend.app.schemas.contracts import TrafficStatus


@dataclass
class SegmentTrafficFlow:
    """
    Standardized traffic flow reading for a single road segment.
    """
    traffic_status: TrafficStatus = TrafficStatus.UNKNOWN
    is_closed: bool = False
    current_speed_kmh: Optional[float] = None
    free_flow_speed_kmh: Optional[float] = None
    traffic_delay_seconds: float = 0.0
    observed_length_meters: Optional[float] = None
    confidence: Optional[float] = None
    source: str = "NONE"
    freshness_seconds: Optional[float] = None
    observed_at: Optional[datetime] = None
    match_status: str = "UNMATCHED"
    raw_payload: Optional[Dict[str, Any]] = None


class BaseTrafficProvider(ABC):
    """
    Abstract interface for external and local traffic flow providers.
    Allows hot-swapping providers (TomTom, HERE, etc.) without altering routing or frontend logic.
    """
    name: str = "base"

    @abstractmethod
    def is_configured(self) -> bool:
        """Return True if credentials and network configuration are available."""
        pass

    @abstractmethod
    async def get_corridor_traffic(
        self,
        route_coordinates: List[List[float]],
        segments: List[Dict[str, Any]],
        redis_client: Optional[Any] = None,
    ) -> Dict[int, SegmentTrafficFlow]:
        """
        Query traffic flow only along the given route corridor segments.
        Does NOT scan the entire city.
        Returns a map of segment_index -> SegmentTrafficFlow.
        """
        pass

