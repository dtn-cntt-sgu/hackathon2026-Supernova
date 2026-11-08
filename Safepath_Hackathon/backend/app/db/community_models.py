"""User reports are quarantined until a service-authorized moderation decision."""
from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, CheckConstraint, DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.db.models import Base


class CommunityIncident(Base):
    __tablename__ = "community_incidents"
    __table_args__ = (
        CheckConstraint("status IN ('PENDING','VERIFIED','REJECTED','EXPIRED')", name="ck_incident_status"),
        CheckConstraint("incident_type IN ('FLOOD','ACCIDENT','BLOCKED','OTHER')", name="ck_incident_type"),
        CheckConstraint("lat BETWEEN 10.3 AND 11.3 AND lng BETWEEN 106.2 AND 107.1", name="ck_incident_location"),
        Index("ix_incidents_user_created", "user_id", "created_at"),
        Index("ix_incidents_status_expiry", "status", "expires_at"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    incident_type: Mapped[str] = mapped_column(String(16), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    lat: Mapped[float] = mapped_column(Float, nullable=False)
    lng: Mapped[float] = mapped_column(Float, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="PENDING")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    moderated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    moderation_note: Mapped[Optional[str]] = mapped_column(Text)
    # A moderator must supply independent evidence; proximity cannot assign a road.
    evidence_url: Mapped[Optional[str]] = mapped_column(String(1024))
    osm_way_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    edge_index: Mapped[Optional[int]] = mapped_column(Integer)
    road_source_pbf_md5: Mapped[Optional[str]] = mapped_column(String(32))
    source_node_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    target_node_id: Mapped[Optional[int]] = mapped_column(BigInteger)
