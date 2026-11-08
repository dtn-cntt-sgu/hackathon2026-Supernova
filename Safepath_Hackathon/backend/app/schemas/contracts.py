"""
Data Contracts and Schema Definitions (Single Source of Truth).
Defines all domain models, enums, and API transfer schemas for SafePathAI.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, ConfigDict, Field


class RiskLevel(str, Enum):
    """
    Standard risk level classification used across all risk calculations.
    """
    SAFE = "SAFE"
    MODERATE = "MODERATE"
    CRITICAL = "CRITICAL"
    UNKNOWN = "UNKNOWN"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


class DataSourceStatus(str, Enum):
    """
    Status of the underlying data source to ensure transparency in UI.
    - LIVE: Fresh real camera/sensor data verified within expected interval (< 180s).
    - RECENT: Real data retrieved recently (< 600s) or with unverified capture watermark.
    - STALE: Data source is delayed or served from local fallback cache (> 600s).
    - SIMULATED: Data generated from mock fixtures for demonstration or test fallback.
    - UNAVAILABLE: Data source is unreachable, offline, or returned placeholder/error.
    """
    LIVE = "LIVE"
    RECENT = "RECENT"
    STALE = "STALE"
    SIMULATED = "SIMULATED"
    UNAVAILABLE = "UNAVAILABLE"


class TrafficDensityLevel(str, Enum):
    """
    Standardized 6-level traffic density classification from multi-factor analysis.
    """
    FREE_FLOW = "FREE_FLOW"    # Thông thoáng
    LIGHT = "LIGHT"            # Đông nhẹ / Lưu thông ổn định
    MODERATE = "MODERATE"      # Đông xe
    HEAVY = "HEAVY"            # Ùn ứ / Di chuyển chậm
    CONGESTED = "CONGESTED"    # Tắc nghẽn nghiêm trọng
    UNKNOWN = "UNKNOWN"        # Không đủ dữ liệu / Chất lượng ảnh kém


class TransportMode(str, Enum):
    """
    Supported transport modes for HCMC urban routing and ETA calculation.
    """
    MOTORCYCLE = "MOTORCYCLE"
    CAR = "CAR"
    WALKING = "WALKING"


class ConfidenceSummaryDTO(BaseModel):
    """
    Summary statistics of detection and traffic analysis confidence.
    """
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    mean_confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    min_confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    max_confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    high_confidence_ratio: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    analysis_confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)


class ETABreakdownDTO(BaseModel):
    """
    ETA support: measured speed replaces covered OSRM time; uncovered time is estimated.
    Legacy additional-delay fields remain zero; hazard ranking is separate.
    """
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    osrm_raw_duration_seconds: float = Field(default=0.0, ge=0.0, description="Unmodified raw OSRM duration")
    base_travel_time_seconds: float = Field(default=0.0, ge=0.0, description="Free-flow time for admitted measured speed plus OSRM time on uncovered road")
    traffic_delay_seconds: float = Field(default=0.0, ge=0.0, description="Observed slowdown plus a time-of-day estimate only on uncovered road")
    additional_delay_seconds: float = Field(default=0.0, ge=0.0, description="Legacy additional delay field; no guessed intersection/weather/risk penalties are added")
    intersection_delay_seconds: float = Field(default=0.0, ge=0.0, description="Legacy field, zero: synthetic intersection and turn waits are not added")
    environmental_delay_seconds: float = Field(default=0.0, ge=0.0, description="Legacy field, zero: rain/flood warnings do not supply measured transit delay")
    intersection_turn_delay_seconds: float = Field(default=0.0, ge=0.0, description="Legacy field, zero: synthetic intersection and turn waits are not added")
    weather_flood_delay_seconds: float = Field(default=0.0, ge=0.0, description="Legacy field, zero: rain/flood warnings do not supply measured transit delay")
    total_additional_delay_seconds: float = Field(default=0.0, ge=0.0, description="Legacy field, zero: risk penalties belong to ranking, not ETA")
    estimated_duration_seconds: float = Field(default=0.0, ge=0.0, description="Total realistic ETA in seconds")
    time_of_day_multiplier: float = Field(default=1.0, ge=0.5, le=3.0, description="Time-of-day estimate applied only to road without admitted speed data")
    rush_hour_multiplier: float = Field(default=1.0, ge=0.5, le=3.0, description="Time-of-day estimate applied only to road without admitted speed data")
    time_of_day_period: str = Field(default="NORMAL", description="MORNING_PEAK, EVENING_PEAK, NORMAL, or NIGHT_OFF_PEAK")
    effective_speed_kmh: float = Field(default=0.0, ge=0.0, description="Resulting average speed in km/h across the route")
    transport_mode: str = Field(default="MOTORCYCLE", description="MOTORCYCLE, CAR, or WALKING")
    eta_source: str = Field(default="OSRM_URBAN_CALIBRATED", description="Source of ETA calculation")
    is_live_traffic: bool = Field(default=False, description="True only if fresh matched measured speed contributed to ETA")
    traffic_status: str = Field(default="UNKNOWN", description="Aggregate traffic condition along corridor")
    data_freshness: str = Field(default="UNAVAILABLE", description="LIVE_VERIFIED indicates recently retrieved admitted speed data; ESTIMATED has no live speed support")
    confidence: float = Field(default=0.0, ge=0.0, le=1.0, description="Distance-weighted admitted speed observation confidence; not calibrated ETA accuracy")


class TrafficStatus(str, Enum):
    """
    Traffic flow condition for a specific road segment.
    Zero-Mock Principles:
    - Never defaults to FREE_FLOW without verified observation evidence.
    - If unobserved or camera lacks verified line-of-sight: UNKNOWN.
    """
    FREE_FLOW = "FREE_FLOW"    # Green (#16A34A): Verified smooth traffic flow
    SLOW = "SLOW"              # Yellow (#F59E0B): Verified heavy volume / reduced speed
    CONGESTED = "CONGESTED"    # Red (#EF4444): Verified severe bottleneck or stoppage
    CLOSED = "CLOSED"          # Dark Crimson (#7F1D1D): Verified road closure / impassable (B06)
    UNKNOWN = "UNKNOWN"        # Slate/Gray (#94A3B8): No reliable real-time traffic evidence


class ImageAccessStatus(str, Enum):
    """
    Reflects the actual accessibility and viewing status of a camera image snapshot.
    """
    VIEWABLE_PUBLIC = "VIEWABLE_PUBLIC"
    VIEWABLE_AUTHORIZED = "VIEWABLE_AUTHORIZED"
    EXTERNAL_ACCESS_RESTRICTED = "EXTERNAL_ACCESS_RESTRICTED"
    UNAVAILABLE = "UNAVAILABLE"


class EvidenceEligibility(str, Enum):
    """
    Verification gate for camera evidence in route risk scoring:
    - ROUTING_ELIGIBLE: ONLY when source permission, verified capture timestamp,
      camera positioning/FOV/LOS, and verified CV model results are all confirmed.
    - NOT_VERIFIED_FOR_ROUTING: Default for unverified, view-only, or candidate cameras.
    """
    ROUTING_ELIGIBLE = "ROUTING_ELIGIBLE"
    NOT_VERIFIED_FOR_ROUTING = "NOT_VERIFIED_FOR_ROUTING"


class CameraFreshnessStatus(str, Enum):
    """
    Explicit provenance and freshness lifecycle of a camera snapshot:
    - FRESH_VERIFIED / LIVE_VERIFIED: Physical frame capture timestamp is verified (watermark/OCR) and within TTL.
    - RECENTLY_FETCHED_UNVERIFIED / RECENTLY_RETRIEVED_CAPTURE_UNKNOWN: Freshly retrieved from portal within TTL, but capture timestamp is unverified.
    - STALE: Snapshot aged beyond TTL (> 600s) or served from local fallback cache.
    - FETCH_FAILED / OFFLINE: Camera endpoint unreachable or failing without cached fallback.
    - RESTRICTED: External portal returning HTTP 403 Forbidden or 429 Rate Limited.
    - PLACEHOLDER: Server returned 'IMAGE NOT AVAILABLE' error frame.
    - UNKNOWN: Insufficient data to determine freshness.
    """
    FRESH_VERIFIED = "FRESH_VERIFIED"
    LIVE_VERIFIED = "LIVE_VERIFIED"
    RECENTLY_FETCHED_UNVERIFIED = "RECENTLY_FETCHED_UNVERIFIED"
    RECENTLY_RETRIEVED_CAPTURE_UNKNOWN = "RECENTLY_RETRIEVED_CAPTURE_UNKNOWN"
    STALE = "STALE"
    FETCH_FAILED = "FETCH_FAILED"
    OFFLINE = "OFFLINE"
    RESTRICTED = "RESTRICTED"
    PLACEHOLDER = "PLACEHOLDER"
    UNKNOWN = "UNKNOWN"


class ImageQualityMetrics(BaseModel):
    """
    Granular image quality metrics evaluated on camera snapshots.
    """
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    brightness_score: float = Field(..., description="Mean luminance [0.0, 255.0]")
    blur_score: float = Field(..., description="Laplacian variance sharpness score")
    noise_estimate: float = Field(..., description="High-frequency noise estimate")
    resolution_score: float = Field(..., description="Normalized resolution factor against 640x480")
    contrast_score: float = Field(..., description="Standard deviation of grayscale intensities")
    is_low_light: bool = Field(..., description="True if scene luminance is below dark threshold")
    is_blurry: bool = Field(..., description="True if blur_score is below sharpness threshold")
    is_low_quality: bool = Field(..., description="True if dark, blurry, noisy, or low-resolution")


class ImageQualityAssessment(BaseModel):
    """
    Comprehensive quality status metadata for a camera frame.
    """
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    quality_status: str = Field(..., description="HIGH_QUALITY, ACCEPTABLE, POOR, or DEGRADED")
    quality_flags: list[str] = Field(
        default_factory=list,
        description="Quality flags: LOW_LIGHT, LOW_RESOLUTION, BLURRY, NOISY, PARTIAL_OCCLUSION",
    )
    quality_metrics: ImageQualityMetrics


class CameraEvidence(BaseModel):
    """
    Detailed evidence payload collected from a single traffic camera.
    Zero-Mock: All metric fields (vehicle_count, traffic_density_score, flood_ratio)
    are None when unobserved or unanalyzed. None != 0.
    """
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    cam_id: str = Field(..., description="Unique camera identifier in VDMS / database")
    code: Optional[str] = Field(default=None, description="Camera code label (e.g. 'TTH 35.4')")
    name: str = Field(..., description="Descriptive camera location name")
    district: Optional[str] = Field(default=None, description="Administrative district of the camera")
    lat: float = Field(..., ge=-90.0, le=90.0, description="WGS84 Latitude")
    lng: float = Field(..., ge=-180.0, le=180.0, description="WGS84 Longitude")
    osm_way_id: Optional[int] = Field(default=None, description="Associated nearest OSM Way ID")
    coordinate_source_url: Optional[str] = Field(default=None, description="Independent source of camera GPS")
    spatial_match_status: str = Field(default="UNVERIFIED", description="SPATIALLY_NEAR or OBSERVED_SEGMENT_VERIFIED")
    observed_osm_way_id: Optional[int] = Field(default=None, description="Manually verified road Way in camera view")
    observed_edge_index: Optional[int] = Field(default=None, description="Verified local edge index within the OSM Way")
    view_verification_source_url: Optional[str] = Field(default=None, description="Evidence for view direction and observed road")
    line_of_sight_verified: bool = Field(default=False, description="Whether obstacles were checked")
    permitted_use: Optional[str] = Field(default=None, description="Registry permission; ROUTING_EVIDENCE_PERMITTED explicitly allows route evidence")
    route_ai_model_version: Optional[str] = Field(default=None, description="Combined manifest fingerprint binding route inference to vehicle and flood model versions")
    snapshot_id: Optional[str] = Field(default=None, description="Immutable unified snapshot identifier")
    image_url: str = Field(default="", description="URL or static path to camera image snapshot")
    overlay_url: Optional[str] = Field(default=None, description="URL to AI detection overlay frame generated from this exact snapshot")
    overlay_path: Optional[str] = Field(default=None, description="Local disk path to overlay file")
    inference_input_sha256: Optional[str] = Field(default=None, description="SHA-256 of snapshot bytes fed into AI models")
    has_image: bool = Field(default=False, description="Whether a valid snapshot is currently cached and viewable")
    image_access_status: ImageAccessStatus = Field(
        default=ImageAccessStatus.UNAVAILABLE, description="Real accessibility of image snapshot"
    )
    evidence_eligibility: EvidenceEligibility = Field(
        default=EvidenceEligibility.NOT_VERIFIED_FOR_ROUTING,
        description="Verification gate for route risk scoring",
    )
    freshness_status: CameraFreshnessStatus = Field(
        default=CameraFreshnessStatus.RECENTLY_RETRIEVED_CAPTURE_UNKNOWN,
        description="Explicit provenance and freshness lifecycle status",
    )
    capture_time_status: str = Field(
        default="CAPTURE_TIME_UNKNOWN",
        description="'VERIFIED_TIMESTAMP' or 'CAPTURE_TIME_UNKNOWN'",
    )
    captured_at: Optional[datetime] = Field(default=None, description="Physical frame capture timestamp")
    retrieved_at: Optional[datetime] = Field(default=None, description="System fetch timestamp")
    fetched_at: Optional[datetime] = Field(default=None, description="System fetch timestamp (alias for retrieved_at)")
    last_attempt_at: Optional[datetime] = Field(default=None, description="Last poll attempt timestamp")
    last_success_at: Optional[datetime] = Field(default=None, description="Last successful new frame timestamp")
    last_content_changed_at: Optional[datetime] = Field(default=None, description="Timestamp when image content sha256 actually changed")
    last_source_captured_at: Optional[datetime] = Field(default=None, description="Source capture timestamp verified from feed")
    frame_sha256: Optional[str] = Field(default=None, description="SHA-256 fingerprint of the exact snapshot bytes")
    analyzed_at: Optional[datetime] = Field(default=None, description="ML inference completion timestamp")
    source_updated_at: Optional[datetime] = Field(default=None, description="Portal origin update timestamp")
    source_url: Optional[str] = Field(default=None, description="External origin URL for public view reference")
    image_status: Optional[str] = Field(default=None, description="Technical status of image frame")
    image_status_reason: Optional[str] = Field(default=None, description="Reason code explaining image status")
    model_status: Optional[str] = Field(default=None, description="Status of vision models")
    vehicle_model_name: Optional[str] = None
    vehicle_model_version: Optional[str] = None
    vehicle_model_sha256: Optional[str] = None
    vehicle_model_provenance: Optional[str] = None
    vehicle_model_validation: Optional[str] = None
    flood_model_status: Optional[str] = None
    vehicle_count: Optional[int] = Field(
        default=None, ge=0, description="Number of vehicles detected; None when unobserved or unanalyzed"
    )
    total_vehicles: Optional[int] = Field(
        default=None, ge=0, description="Total number of vehicles detected (equals sum of vehicle_counts)"
    )
    vehicle_counts: Optional[Dict[str, int]] = Field(
        default=None, description="6-class vehicle breakdown: motorcycle, car, bus, truck, bicycle, other"
    )
    detections: Optional[List[Dict[str, Any]]] = Field(
        default=None, description="List of detected vehicle objects with class, confidence, and bbox"
    )
    confidence_summary: Optional[ConfidenceSummaryDTO] = Field(
        default=None, description="Detection and analysis confidence summary statistics"
    )
    traffic_density_score: Optional[float] = Field(
        default=None, ge=0.0, le=1.0, description="Normalized traffic congestion score; None when unanalyzed"
    )
    traffic_density_level: Optional[TrafficDensityLevel] = Field(
        default=None, description="Standardized traffic density classification (FREE_FLOW..CONGESTED, UNKNOWN)"
    )
    roi_occupancy_ratio: Optional[float] = Field(
        default=None, ge=0.0, le=1.0, description="Perspective-weighted road ROI bounding-box area occupancy ratio"
    )
    analysis_confidence: Optional[float] = Field(
        default=None, ge=0.0, le=1.0, description="Confidence of multi-factor traffic density analysis"
    )
    analysis_timestamp: Optional[datetime] = Field(
        default=None, description="ISO timestamp when CV analysis was executed"
    )
    model_version: Optional[str] = Field(
        default=None, description="Version identifier of the active vehicle detection model"
    )
    flood_ratio: Optional[float] = Field(
        default=None, ge=0.0, le=1.0, description="Water segmentation ratio; None when unanalyzed"
    )
    image_quality: Optional[ImageQualityAssessment] = Field(
        default=None, description="Detailed image quality assessment"
    )
    model_pipeline: Optional[str] = Field(
        default=None, description="Name of the vision pipeline used"
    )
    risk_level: RiskLevel = Field(..., description="Computed risk level for this camera feed")
    source_status: DataSourceStatus = Field(..., description="Current status of the camera feed")
    updated_at: datetime = Field(..., description="Timestamp when evidence was processed")


class CameraImageMetadata(BaseModel):
    """
    Dedicated metadata response describing snapshot availability, provenance, ETag,
    access control, and eligibility reasons without serving large image bytes.
    """
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    cam_id: str
    snapshot_id: Optional[str] = None
    code: Optional[str] = None
    name: str
    district: Optional[str] = None
    lat: float
    lng: float
    has_image: bool
    image_url: Optional[str] = None
    overlay_url: Optional[str] = None
    source_url: Optional[str] = None
    image_access_status: ImageAccessStatus
    evidence_eligibility: EvidenceEligibility
    image_status_reason: str
    freshness_status: Optional[CameraFreshnessStatus] = None
    capture_time_status: Optional[str] = None
    captured_at: Optional[datetime] = None
    retrieved_at: Optional[datetime] = None
    fetched_at: Optional[datetime] = None
    last_attempt_at: Optional[datetime] = None
    last_success_at: Optional[datetime] = None
    last_content_changed_at: Optional[datetime] = None
    last_source_captured_at: Optional[datetime] = None
    frame_sha256: Optional[str] = None
    inference_input_sha256: Optional[str] = None
    analyzed_at: Optional[datetime] = None
    source_updated_at: Optional[datetime] = None
    model_status: Optional[str] = None
    vehicle_count: Optional[int] = None
    total_vehicles: Optional[int] = None
    vehicle_counts: Optional[Dict[str, int]] = None
    detections: Optional[List[Dict[str, Any]]] = None
    confidence_summary: Optional[ConfidenceSummaryDTO] = None
    traffic_density_score: Optional[float] = None
    traffic_density_level: Optional[TrafficDensityLevel] = None
    roi_occupancy_ratio: Optional[float] = None
    analysis_confidence: Optional[float] = None
    analysis_timestamp: Optional[datetime] = None
    model_version: Optional[str] = None
    flood_ratio: Optional[float] = None
    image_quality: Optional[ImageQualityAssessment] = None
    model_pipeline: Optional[str] = None
    etag: Optional[str] = None
    image_hash: Optional[str] = None
    content_length: Optional[int] = None
    mime_type: Optional[str] = None


class CameraSummary(BaseModel):
    """
    Summary operational statistics of registered cameras and ingestion status.
    Directly reflects real PostGIS and scheduler database counts (Zero-Mock).
    """
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    total_registered: int = Field(..., description="Total cameras registered in database")
    valid_gps_count: int = Field(..., description="Number of cameras with valid WGS84 GPS coordinates")
    checked_count: int = Field(..., description="Number of cameras checked by ingestion scheduler")
    valid_images_count: int = Field(..., description="Number of cameras with live valid images (within 15m)")
    stale_images_count: int = Field(..., description="Number of cameras with stale images (>15m)")
    unavailable_count: int = Field(..., description="Number of cameras currently unreachable or offline")
    analyzed_count: int = Field(..., description="Number of cameras processed by vision models")
    last_scheduler_cycle: Optional[datetime] = Field(default=None, description="Timestamp of latest scheduler fetch attempt")
    circuit_breaker_open: bool = Field(default=False, description="Whether HCMC traffic portal circuit breaker is open")
    cycle_target_sec: int = Field(default=600, description="Target full cycle duration in seconds (10m)")
    cycle_checked_count: Optional[int] = Field(default=None, description="Number of cameras checked in current cycle")
    cycle_pending_count: Optional[int] = Field(default=None, description="Number of cameras pending check in current cycle")
    actual_sweep_duration_min: Optional[float] = Field(default=None, description="Estimated minutes to sweep full camera registry at current rate")
    cycle_target_met: bool = Field(default=True, description="Whether current ingestion pace meets 600s cycle target")
    cycle_lag_seconds: Optional[float] = Field(default=0.0, description="Lag beyond target cycle duration")
    registered_count: Optional[int] = Field(default=None, description="Total registered cameras (Section F)")
    reachable_count: Optional[int] = Field(default=None, description="Reachable cameras responding with valid snapshot or 200/304")
    fetched_recently_count: Optional[int] = Field(default=None, description="Cameras fetched within target 600s cycle")
    fresh_verified_count: Optional[int] = Field(default=None, description="Cameras with verified physical capture timestamps")
    stale_count: Optional[int] = Field(default=None, description="Cameras with snapshots older than 600s")
    fetch_failed_count: Optional[int] = Field(default=None, description="Cameras whose latest fetch failed (403/429/timeout/placeholder)")
    capture_time_unknown_count: Optional[int] = Field(default=None, description="Valid frames whose capture timestamp is unverified")


class ActiveCameraRegisterRequest(BaseModel):
    """Request to register cameras as actively viewed in viewport or modal for 60s priority refresh."""
    model_config = ConfigDict(populate_by_name=True)
    cam_ids: List[str] = Field(..., min_length=1, max_length=50, description="List of camera IDs")
    ttl_seconds: int = Field(default=90, ge=10, le=3600, description="Priority lease duration in seconds")


class ActiveRouteRegisterRequest(BaseModel):
    """Request to register cameras along an active navigation route corridor for priority refresh."""
    model_config = ConfigDict(populate_by_name=True)
    cam_ids: List[str] = Field(..., min_length=1, max_length=100, description="List of camera IDs")
    ttl_seconds: int = Field(default=900, ge=60, le=7200, description="Corridor lease duration in seconds")


class ActiveCameraResponse(BaseModel):
    """Status response for active camera priority registration."""
    status: str = "ok"
    registered_count: int
    active_viewed_count: int
    active_route_count: int


class WeatherTideSignal(BaseModel):
    """
    Hydrometeorological signal combining rain intensity and tidal level.
    Zero-Mock: All metric fields are nullable when unobserved; never defaults to 0 mm/h or fake tide.
    """
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    rain_mm_per_hour: Optional[float] = Field(default=None, ge=0.0, description="Hourly rainfall in millimeters; None if unobserved")
    rain_status: str = Field(default="WEATHER_UNAVAILABLE", description="LIVE, STALE, or WEATHER_UNAVAILABLE")
    rain_observed_at: Optional[datetime] = Field(default=None, description="Observation timestamp from meteorological service")
    weather_code: Optional[int] = Field(default=None, description="WMO weather code (e.g. 51-65 rain)")
    tide_level_meters: Optional[float] = Field(default=None, description="Tidal water level in meters relative to datum; None if unobserved")
    tide_status: str = Field(default="TIDE_UNAVAILABLE", description="LIVE, STALE, or TIDE_UNAVAILABLE")
    tide_unavailable_reason: Optional[str] = Field(default=None, description="Reason no verified current tide reading can be displayed")
    tide_observed_at: Optional[datetime] = Field(default=None, description="Independent tidal observation timestamp")
    tide_source_url: Optional[str] = Field(default=None, description="Original source of the tidal bulletin")
    tide_station: Optional[str] = Field(default=None, description="Observing tidal station name (e.g. Phú An, Nhà Bè)")
    tide_datum: Optional[str] = Field(default=None, description="Vertical datum (e.g. Hòn Dấu VN-2000)")
    is_high_tide_alert: Optional[bool] = Field(default=None, description="True if tide exceeds warning threshold; None if unobserved")
    timestamp: Optional[datetime] = Field(default=None, description="Source observation timestamp; None when neither signal was observed")
    source_url: Optional[str] = Field(default=None, description="Source URL of environmental data")


class RouteSegmentRisk(BaseModel):
    """
    Risk assessment for a specific OpenStreetMap road segment.
    """
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    osm_way_id: Optional[int] = Field(default=None, description="Verified OpenStreetMap Way ID, if available")
    osm_edge_index: Optional[int] = Field(default=None, description="Verified local edge index within the OSM Way")
    candidate_osm_way_ids: List[int] = Field(default_factory=list, description="Nearby real OSM Ways; candidate only")
    candidate_road_edges: List[Dict[str, int]] = Field(default_factory=list, description="Nearby OSM Way/edge_index pairs; candidate only")
    road_match_status: str = Field(default="UNKNOWN", description="CANDIDATE_ONLY or NO_ROAD_EDGE_MATCH")
    geojson_path: Optional[Dict[str, Any]] = Field(default=None, description="Actual OSRM step LineString")
    street_name: Optional[str] = Field(default=None, description="Human-readable street name")
    length_meters: float = Field(..., ge=0.0, description="Segment length in meters")
    osrm_duration_seconds: Optional[float] = Field(default=None, ge=0.0, description="Raw OSRM duration for this step, before traffic adjustment")
    maneuver_type: Optional[str] = Field(default=None, description="Raw OSRM step maneuver type")
    maneuver_modifier: Optional[str] = Field(default=None, description="Raw OSRM turn direction modifier")
    maneuver_location: Optional[List[float]] = Field(default=None, description="Raw OSRM maneuver point [longitude, latitude]")
    maneuver_exit: Optional[int] = Field(default=None, description="Raw OSRM roundabout exit number")
    risk_score: Optional[float] = Field(
        default=None, ge=0.0, le=100.0, description="Verified risk score, absent when evidence is insufficient"
    )
    risk_level: RiskLevel = Field(..., description="Risk category for this segment")
    historical_flood_prone: Optional[bool] = Field(default=None, description="True if documented in municipal flood reports, None if unverified")
    historical_flood_cause: Optional[str] = Field(default=None, description="TIDAL, HEAVY_RAIN, or TIDAL_AND_HEAVY_RAIN")
    historical_typical_depth_cm: Optional[int] = Field(default=None, description="Typical flood depth from municipal reports")
    weather_risk: Optional[str] = Field(default=None, description="CLEAR, MODERATE_RAIN, HEAVY_RAIN, or UNKNOWN")
    evidence_coverage: str = Field(default="UNAVAILABLE", description="Verified observation coverage in the segment corridor")
    evidence_cameras: List[CameraEvidence] = Field(
        default_factory=list, description="List of cameras mapped or buffered to this road segment"
    )
    freshness_seconds: Optional[float] = Field(default=None, description="Seconds since most recent verified observation")
    traffic_status: TrafficStatus = Field(default=TrafficStatus.UNKNOWN, description="Traffic congestion status (FREE_FLOW, SLOW, CONGESTED, CLOSED, UNKNOWN)")
    traffic_observed_length_meters: Optional[float] = Field(default=None, ge=0.0, description="Verified traffic observation length within this step")
    is_closed: bool = Field(default=False, description="True if road segment is physically closed/blocked (B06)")
    observed_speed_kmh: Optional[float] = Field(default=None, description="Directly measured traffic velocity in km/h if available from speed sensor or provider")
    free_flow_speed_kmh: Optional[float] = Field(default=None, description="Free flow baseline velocity in km/h if provided by traffic provider")
    traffic_density_score: Optional[float] = Field(default=None, ge=0.0, le=1.0, description="Observed camera vehicle density / area saturation ratio")
    traffic_density_level: Optional[TrafficDensityLevel] = Field(default=None, description="Standardized 6-level traffic density classification")
    traffic_confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0, description="Confidence in traffic assessment")
    traffic_freshness_seconds: Optional[float] = Field(default=None, description="Age of traffic observation in seconds")
    traffic_source: Optional[str] = Field(default=None, description="Evidence source, e.g. tomtom_flow, here_flow, camera_vision:yolo26n, traffic_news:verified")
    traffic_estimation_method: Optional[str] = Field(default=None, description="Method: COMMERCIAL_FLOW_API, CAMERA_VIEW_OCCUPANCY, NLP_EVENT_GEOCODED, UNREPRESENTED")
    traffic_segment_match_status: Optional[str] = Field(default=None, description="CORRIDOR_MATCHED, OBSERVED_SEGMENT_VERIFIED, SPATIALLY_NEAR, UNMATCHED")
    traffic_delay_seconds: Optional[float] = Field(default=None, description="Congestion-induced transit delay in seconds relative to baseline")
    observed_at: Optional[datetime] = Field(default=None, description="Timestamp of the traffic measurement")


class SafeRouteResponse(BaseModel):
    """
    Complete response returned by the safe route finding API.
    """
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    route_id: str = Field(..., description="Unique route query identification UUID")
    total_distance_km: float = Field(..., ge=0.0, description="Total distance of the route in km")
    estimated_time_mins: float = Field(..., ge=0.0, description="Estimated travel time in minutes (calibrated for HCMC urban conditions and transport mode)")
    osrm_duration_seconds: float = Field(default=0.0, ge=0.0, description="Baseline duration in seconds from OSRM graph (unaltered)")
    baseline_duration_seconds: float = Field(default=0.0, ge=0.0, description="Mixed measured free-flow and uncovered OSRM baseline in seconds")
    duration_seconds: float = Field(default=0.0, ge=0.0, description="Base travel time in seconds before traffic congestion delay")
    duration_in_traffic_seconds: Optional[float] = Field(default=None, description="Travel time in live traffic when real-time provider or verified live camera is active")
    estimated_duration_seconds: float = Field(default=0.0, ge=0.0, description="Realistic estimated duration in seconds (Base + Traffic Delay + Additional Delay)")
    transport_mode: str = Field(default="CAR", description="Transport mode: MOTORCYCLE, CAR, or WALKING")
    eta_source: str = Field(default="OSRM_URBAN_CALIBRATED", description="Source of ETA calculation")
    is_live_traffic: bool = Field(default=False, description="True only if fresh matched measured speed contributed to ETA")
    traffic_status: TrafficStatus = Field(default=TrafficStatus.UNKNOWN, description="Aggregate traffic condition along route")
    data_freshness: Optional[str] = Field(default=None, description="Freshness state of traffic data: LIVE, RECENT, STALE, UNAVAILABLE")
    eta_breakdown: Optional[ETABreakdownDTO] = Field(default=None, description="Detailed breakdown of ETA components")
    traffic_adjusted_eta_seconds: Optional[float] = Field(default=None, description="Travel time adjusted for verified traffic congestion delays")
    traffic_eta_status: str = Field(default="BASE_OSRM_NO_TRAFFIC", description="BASE_OSRM_NO_TRAFFIC, TRAFFIC_CALIBRATED_ESTIMATE, or TRAFFIC_CONGESTION_DELAYED")
    traffic_eta_source: Optional[str] = Field(default=None, description="Source of traffic adjustment (e.g. 'commercial_traffic_provider', 'camera_corridor_analysis')")
    traffic_delay_seconds: Optional[float] = Field(default=None, description="Total seconds of congestion delay added across verified segments")
    traffic_coverage_ratio: float = Field(default=0.0, ge=0.0, le=1.0, description="Ratio of total route distance with verified real-time traffic data (0.0 to 1.0)")
    traffic_confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0, description="Overall confidence of traffic assessment across the corridor")
    observed_at: Optional[datetime] = Field(default=None, description="Timestamp of the latest traffic observation")
    is_recommended: bool = Field(default=False, description="True if selected by backend multi-criteria ranking policy")
    is_fastest: bool = Field(default=False, description="True if route has the lowest baseline or calibrated transit duration")
    route_type: str = Field(default="RECOMMENDED", description="Route categorization: RECOMMENDED, FASTEST, LEAST_RISK, ALTERNATIVE")
    ranking_cost: Optional[float] = Field(default=None, description="Objective multi-criteria cost used strictly for candidate route ranking")
    overall_risk: RiskLevel = Field(..., description="Overall aggregate risk level for the entire route")
    route_ai_status: str = Field(default="BLOCKED_BY_EVIDENCE", description="EVIDENCE_AVAILABLE or BLOCKED_BY_EVIDENCE; no inference claim without admitted observations")
    route_status: str = Field(default="ROUTE_FOUND_RISK_UNKNOWN", description="Route and evidence coverage status")
    evidence_coverage: str = Field(default="UNAVAILABLE", description="Coverage of verified risk observations")
    critical_segments_count: int = Field(default=0, description="Count of verified critical risk road segments")
    moderate_segments_count: int = Field(default=0, description="Count of verified moderate risk road segments")
    unknown_segments_count: int = Field(default=0, description="Count of unobserved or unknown risk road segments")
    geojson_path: Dict[str, Any] = Field(
        ..., description="GeoJSON Feature/Geometry representing the full navigation line"
    )
    segments: List[RouteSegmentRisk] = Field(
        ..., description="Sequential list of road segments and their associated risk assessments"
    )
    ai_explanation: str = Field(
        ..., description="AI-generated plain-language rationale explaining route choice and warnings"
    )
    alternative_routes: List["SafeRouteResponse"] = Field(
        default_factory=list, description="Alternative candidate routes evaluated"
    )


class Coordinates(BaseModel):
    """Geographic point coordinates."""
    model_config = ConfigDict(from_attributes=True)

    lat: float = Field(..., ge=-90.0, le=90.0, description="WGS84 Latitude")
    lng: float = Field(..., ge=-180.0, le=180.0, description="WGS84 Longitude")


class RouteSearchRequest(BaseModel):
    """Payload for finding a safe route between two points."""
    model_config = ConfigDict(from_attributes=True)

    origin: Coordinates = Field(..., description="Starting point coordinates")
    destination: Coordinates = Field(..., description="Destination point coordinates")
    transport_mode: str = Field(
        default="car",
        pattern=r"^(?i)(car|motorcycle|walking|walk)$",
        description="Vehicle profile: 'car', 'motorcycle', or 'walking' (C07)",
    )


class WebSocketAlertMessage(BaseModel):
    """Real-time structured alert message broadcast over WebSocket."""
    model_config = ConfigDict(from_attributes=True)

    event_id: str = Field(..., description="Unique UUID for this alert event to enable client deduplication")
    type: str = Field(..., description="Alert event type, e.g. CRITICAL_FLOOD_ALERT, CONNECTION_ESTABLISHED")
    severity: str = Field(default="INFO", description="CRITICAL, WARNING, or INFO")
    source: str = Field(..., description="Evidence source, e.g. 'camera_vision:ONNX', 'hydrology:open_meteo'")
    cam_id: Optional[str] = Field(default=None, description="Camera ID if triggered by surveillance feed")
    code: Optional[str] = Field(default=None, description="Camera code label")
    location: Optional[str] = Field(default=None, description="Street or district location")
    flood_ratio: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    risk_level: Optional[RiskLevel] = Field(default=None)
    message: str = Field(..., description="Human-readable alert message")
    observed_at: datetime = Field(..., description="Observation timestamp")
    expiry: Optional[datetime] = Field(default=None, description="Expiration time after which alert is stale")


def build_camera_alert(
    ev: CameraEvidence,
    now: Optional[datetime] = None,
    ttl_seconds: int = 120,
) -> WebSocketAlertMessage:
    """
    Constructs a schema-validated WebSocketAlertMessage from a CameraEvidence instance (B01).
    Ensures frontend `isVerifiedRouteAlert` contract fields (`event_id`, `type`, `severity`,
    `source`, `cam_id`, `risk_level`, `observed_at`, `expiry`) are populated consistently.
    """
    from datetime import timedelta
    import uuid

    observed = now or ev.updated_at or datetime.now(timezone.utc)
    if observed.tzinfo is None:
        observed = observed.replace(tzinfo=timezone.utc)
    expiry_dt = observed + timedelta(seconds=ttl_seconds)

    is_critical = ev.risk_level == RiskLevel.CRITICAL
    alert_type = "CRITICAL_FLOOD_ALERT" if is_critical else "MODERATE_CORRIDOR_ALERT"
    severity = "CRITICAL" if is_critical else "WARNING"
    model_tag = ev.vehicle_model_name or "ONNX"
    loc_label = f"{ev.name} ({ev.district})" if ev.district else ev.name

    return WebSocketAlertMessage(
        event_id=str(uuid.uuid4()),
        type=alert_type,
        severity=severity,
        source=f"camera_vision:{model_tag}",
        cam_id=ev.cam_id,
        code=ev.code,
        location=loc_label,
        flood_ratio=ev.flood_ratio,
        risk_level=ev.risk_level,
        message=(
            f"Cảnh báo tuyến đường: Camera {ev.code or ev.cam_id} tại {loc_label} "
            f"ghi nhận mức rủi ro {ev.risk_level.value}."
        ),
        observed_at=observed,
        expiry=expiry_dt,
    )


class PlaceResult(BaseModel):
    """Geocoded place, address, or POI candidate."""
    model_config = ConfigDict(from_attributes=True)

    id: str = Field(..., description="Unique identifier for the place")
    name: str = Field(..., description="Short place or street name")
    display_name: str = Field(..., description="Full formatted address or landmark name")
    lat: float = Field(..., ge=-90.0, le=90.0, description="WGS84 Latitude")
    lng: float = Field(..., ge=-180.0, le=180.0, description="WGS84 Longitude")
    osm_type: Optional[str] = Field(default=None, description="OSM node/way/relation type")
    osm_id: Optional[int] = Field(default=None, description="OSM entity ID")
    type: Optional[str] = Field(default=None, description="Feature type (e.g. street, poi, amenity)")
    district: Optional[str] = Field(default=None, description="District or county name")
    city: Optional[str] = Field(default=None, description="City or province name")
    provenance: str = Field(default="photon.komoot.io", description="Data provenance of this geocoded location")


class PlaceSearchResponse(BaseModel):
    """Response containing place search results and provenance metadata."""
    model_config = ConfigDict(from_attributes=True)

    query: str = Field(..., description="Normalized search query string")
    results: List[PlaceResult] = Field(default_factory=list, description="List of matched locations")
    provider: str = Field(..., description="Geocoding provider used (photon, postgis, or fallback)")
    count: int = Field(..., description="Number of results returned")


class UserSyncRequest(BaseModel):
    """Payload to synchronize Google OAuth identity to backend database."""
    model_config = ConfigDict(from_attributes=True)

    provider: Literal["google"] = Field(default="google", description="OAuth provider name")
    provider_account_id: str = Field(..., min_length=1, max_length=255, description="Provider stable unique account ID (Google sub)")
    email: str = Field(..., min_length=3, max_length=255, pattern=r"^[^\s@]+@[^\s@]+\.[^\s@]+$", description="User verified email address")
    display_name: str = Field(..., min_length=1, max_length=255, description="User display name")
    avatar_url: Optional[str] = Field(default=None, max_length=2048, pattern=r"^https://", description="Avatar image URL")


class UserPreferenceDTO(BaseModel):
    """User preferences schema."""
    model_config = ConfigDict(from_attributes=True)

    transport_mode: str = Field(default="motorcycle", description="motorcycle, car, bicycle, walk")
    avoid_flood_level: str = Field(default="MEDIUM", description="LOW, MEDIUM, HIGH")
    avoid_high_density: bool = Field(default=False)
    alert_notifications: bool = Field(default=True)
    voice_guidance_enabled: bool = Field(default=True)


class UserSavedPlaceDTO(BaseModel):
    """Saved place schema."""
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    address: str
    lat: float
    lng: float
    category: str = "favorite"
    created_at: Optional[datetime] = None


class UserRouteHistoryDTO(BaseModel):
    """Route history schema."""
    model_config = ConfigDict(from_attributes=True)

    id: str
    origin_name: str
    dest_name: str
    origin_lat: Optional[float] = None
    origin_lng: Optional[float] = None
    dest_lat: Optional[float] = None
    dest_lng: Optional[float] = None
    distance_km: float
    duration_mins: int
    travel_mode: str = "motorcycle"
    created_at: Optional[datetime] = None


class UserProfileResponse(BaseModel):
    """Full user profile response."""
    model_config = ConfigDict(from_attributes=True)

    id: str
    email: str
    display_name: str
    avatar_url: Optional[str] = None
    is_active: bool = True
    session_token: Optional[str] = Field(
        default=None,
        description="HMAC-SHA256 signed session token bound to this user (B02)",
    )
    preferences: UserPreferenceDTO
    saved_places: List[UserSavedPlaceDTO] = Field(default_factory=list)
    route_history: List[UserRouteHistoryDTO] = Field(default_factory=list)


class CreateSavedPlaceRequest(BaseModel):
    """Request to create a saved place."""
    model_config = ConfigDict(from_attributes=True)

    name: str = Field(..., min_length=1, max_length=255)
    address: str = Field(..., min_length=1, max_length=512)
    lat: float = Field(..., ge=-90.0, le=90.0)
    lng: float = Field(..., ge=-180.0, le=180.0)
    category: str = Field(default="favorite")


class CreateRouteHistoryRequest(BaseModel):
    """Request to store a completed route in user history."""
    model_config = ConfigDict(from_attributes=True)

    origin_name: str = Field(..., min_length=1, max_length=255)
    dest_name: str = Field(..., min_length=1, max_length=255)
    origin_lat: Optional[float] = None
    origin_lng: Optional[float] = None
    dest_lat: Optional[float] = None
    dest_lng: Optional[float] = None
    distance_km: float = Field(..., ge=0.0)
    duration_mins: int = Field(..., ge=0)
    travel_mode: str = Field(default="motorcycle")

