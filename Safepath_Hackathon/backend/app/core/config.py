"""
Application Configuration Module using Pydantic Settings.
Single Source of Truth for environment configurations and runtime parameters.
"""

from typing import Literal, Optional
import secrets
from pathlib import Path
from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Core application settings loaded from environment variables or .env file.
    """

    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parents[3] / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    APP_ENV: Literal["development", "test", "staging", "production"] = "development"
    SERVICE_AUTH_TOKEN: str = ""
    MAX_REQUEST_BODY_BYTES: int = Field(default=262144, ge=1024, le=10485760)
    TRUSTED_PROXY_IPS: list[str] = []

    # Database Configuration (PostgreSQL with PostGIS)
    DATABASE_URL: str = (
        "postgresql+asyncpg://safepath_user:safepath_password@localhost:5432/safepath_db"
    )

    # Redis Configuration (Streams and Real-time State Cache)
    REDIS_URL: str = "redis://localhost:6379/0"

    # Routing Engine (OSRM Backend)
    OSRM_BASE_URL: str = "http://localhost:5000"
    OSRM_GRAPH_VERSION: str = ""
    OSRM_GRAPH_MANIFEST_PATH: str = "data/osrm/graph-manifest.json"

    # Commercial Real-Time Traffic Providers (TomTom / HERE)
    TOMTOM_API_KEY: Optional[str] = None
    HERE_API_KEY: Optional[str] = None
    TRAFFIC_PROVIDER: str = "auto"
    TRAFFIC_CACHE_TTL_SECONDS: int = 180
    TRAFFIC_REQUEST_TIMEOUT_SECONDS: float = 3.0

    # Weather & Meteorological Service
    OPEN_METEO_URL: str = "https://api.open-meteo.com/v1/forecast"

    # HCMC VDMS Traffic Portal & Camera Scraper Settings
    HCMC_CAMERA_BASE_URL: str = (
        "https://giaothong.hochiminhcity.gov.vn:8007/Render/CameraHandler.ashx"
    )
    HCMC_CAMERA_REFERER: str = "https://giaothong.hochiminhcity.gov.vn/"
    HCMC_CAMERA_COOKIE: str = ""

    # Camera Ingestion Permissions & Security Settings
    # Default False: requires explicit authorization to scrape/ingest external cameras
    CAMERA_INGESTION_PERMITTED: bool = False

    # Granular Provider Capability Configuration
    # Allows viewing permitted/public snapshots without elevating them to routing evidence
    CAMERA_ALLOW_VIEW_ONLY: bool = True
    # Only allow altering route risk scores if explicit verified permission and calibration exist
    CAMERA_ROUTING_EVIDENCE_PERMITTED: bool = False
    # Freshness threshold: snapshots within 10-minute target cycle (600s) are fresh
    CAMERA_IMAGE_TTL_SECONDS: int = 600
    # Maximum allowable frame age: frames older than 1 hour (3600s) are strictly expired and purged
    CAMERA_MAX_IMAGE_AGE_SECONDS: int = 3600
    # Storage retention threshold: clean up cached frames older than 24h
    CAMERA_DISK_EVICTION_MAX_HOURS: int = 24

    # 10-minute background sweep target across full 796-node camera registry
    CAMERA_REFRESH_TARGET_SEC: int = 600
    CAMERA_PRIORITY_INTERVAL_SEC: int = 60
    CAMERA_REQUEST_TIMEOUT_SEC: float = 5.0
    CAMERA_FETCH_TIMEOUT_SEC: float = 5.0
    CAMERA_MAX_CONCURRENCY: int = 8
    CAMERA_BATCH_SIZE: int = 16
    CAMERA_SCRAPE_INTERVAL_SEC: int = 4
    CAMERA_INGESTION_ENABLED: bool = True
    ENABLE_BACKGROUND_WORKERS: bool = True
    ENABLE_EXTERNAL_AI_EXPLANATION: bool = False
    AUTH_SECRET: str = Field(default_factory=lambda: secrets.token_urlsafe(48))
    RATE_LIMIT_ROUTES_PER_MINUTE: int = 60
    RATE_LIMIT_PLACES_PER_MINUTE: int = 120

    # Viewing never authorizes routing inference. Budgets are per application process.
    CAMERA_PROXY_ENABLED: bool = True
    CAMERA_PROXY_PROVIDER: Literal["vietmap", "hcmc"] = "vietmap"
    CAMERA_PROXY_CACHE_TTL_SECONDS: int = Field(default=20, ge=10, le=30)
    CAMERA_PROXY_STALE_MAX_SECONDS: int = Field(default=120, ge=30, le=3600)
    CAMERA_PROXY_MAX_CACHED_FRAMES: int = Field(default=32, ge=1, le=256)
    CAMERA_PROXY_MAX_PENDING: int = Field(default=64, ge=1, le=256)
    CAMERA_PROXY_MAX_PIXELS: int = Field(default=4_194_304, ge=10000, le=16_777_216)
    CAMERA_PROXY_MAX_BYTES: int = Field(default=3_000_000, ge=4096, le=10000000)
    CAMERA_PROXY_MAX_CONCURRENCY: int = Field(default=4, ge=1, le=16)
    CAMERA_PROXY_TIMEOUT_SECONDS: float = Field(default=8.0, ge=0.1, le=30)
    CAMERA_PROXY_FAILURE_BACKOFF_SECONDS: int = Field(default=60, ge=1, le=3600)
    CAMERA_PROXY_MIN_REQUEST_INTERVAL_SECONDS: float = Field(default=0.25, ge=0, le=10)
    CAMERA_VIEW_AI_ENABLED: bool = True
    CAMERA_VIEW_AI_TIMEOUT_SECONDS: float = Field(default=20.0, ge=1, le=60)
    CAMERA_AI_MODE: str = "route_only"
    ROUTE_CAMERA_AI_ENABLED: bool = True
    ROUTE_AI_MAX_CAMERAS: int = Field(default=4, ge=1, le=16)
    ROUTE_AI_MAX_CONCURRENCY: int = Field(default=2, ge=1, le=4)
    ROUTE_AI_TIMEOUT_SECONDS: float = Field(default=8.0, ge=0.1, le=30)
    ROUTE_AI_CACHE_TTL_SECONDS: int = Field(default=300, ge=1, le=3600)
    ROUTE_AI_MAX_FRAME_AGE_SECONDS: int = Field(default=120, ge=1, le=120)

    # Official daily hydrology bulletin; independent of camera/routing evidence.
    HYDROLOGY_BULLETIN_ENABLED: bool = True
    HYDROLOGY_BULLETIN_POLL_SECONDS: int = Field(default=1800, ge=300, le=86400)
    HYDROLOGY_BULLETIN_TIMEOUT_SECONDS: float = Field(default=10.0, ge=1, le=30)
    HYDROLOGY_BULLETIN_MAX_BYTES: int = Field(default=3_000_000, ge=10000, le=10_000_000)
    HYDROLOGY_BULLETIN_MAX_AGE_HOURS: int = Field(default=36, ge=1, le=168)

    # Deprecated fallback flag kept False for strict Zero-Mock compliance
    USE_MOCK_CAMERA_FALLBACK: bool = False

    # Computer Vision & Vehicle Detection Settings (VGG16-SSD HCMC Finetuned)
    VEHICLE_MODEL_PATH: str = "data/models/vgg16_ssd_hcmc.onnx"
    YOLO_MODEL_PATH: str = "data/models/vgg16_ssd_hcmc.onnx"
    YOLO_CONFIDENCE_THRESHOLD: float = 0.25
    YOLO_MOTORCYCLE_CONF_THRESHOLD: float = 0.20
    YOLO_NMS_IOU_THRESHOLD: float = 0.45

    # Large Language Model API Key (Gemini / OpenAI)
    LLM_API_KEY: str = ""

    # CORS Allowed Origins (Restricted list)
    CORS_ALLOWED_ORIGINS: list[str] = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:3100",
        "http://127.0.0.1:3100",
        "http://localhost:3102",
        "http://127.0.0.1:3102",
    ]

    @model_validator(mode="after")
    def validate_deployment(self):
        if self.APP_ENV in {"development", "test"} and not self.AUTH_SECRET:
            self.AUTH_SECRET = secrets.token_urlsafe(48)
        if self.APP_ENV in {"staging", "production"}:
            for name in ("AUTH_SECRET", "SERVICE_AUTH_TOKEN"):
                value = getattr(self, name)
                if name not in self.model_fields_set or len(value) < 32 or any(word in value.lower() for word in ("placeholder", "replace", "safepath_dev", "example")):
                    raise ValueError(f"{name} must be an explicitly configured deployment secret of at least 32 characters")
            if self.AUTH_SECRET == self.SERVICE_AUTH_TOKEN:
                raise ValueError("Service and user signing secrets must be distinct")
            if any(not origin.startswith("https://") or "*" in origin for origin in self.CORS_ALLOWED_ORIGINS):
                raise ValueError("Deployment CORS origins must be explicit HTTPS origins")
            if self.CAMERA_AI_MODE != "route_only":
                raise ValueError("Deployment requires route-only ranking inference")
        return self

    @property
    def sync_database_url(self) -> str:
        """
        Derives a synchronous connection URL for synchronous drivers (psycopg2).
        Useful for synchronous database operations, testing, or migrations.
        """
        url = self.DATABASE_URL
        if url.startswith("postgresql+asyncpg://"):
            return url.replace("postgresql+asyncpg://", "postgresql+psycopg2://", 1)
        return url


# Global settings singleton
settings = Settings()
