"""Authenticated reports and service-authorized moderation; no public reporter data."""
from datetime import datetime, timedelta, timezone
import hashlib
from typing import Literal, Optional
from urllib.parse import urlsplit
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.community_models import CommunityIncident
from backend.app.db.models import User
from backend.app.db.session import get_db


class IncidentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    incident_type: Literal["FLOOD", "ACCIDENT", "BLOCKED", "OTHER"]
    description: str = Field(min_length=10, max_length=2000)
    lat: float = Field(ge=10.3, le=11.3)
    lng: float = Field(ge=106.2, le=107.1)
    observed_at: datetime

    @field_validator("description")
    @classmethod
    def description_not_blank(cls, value):
        value = value.strip()
        if len(value) < 10:
            raise ValueError("Description must contain at least 10 characters")
        return value

    @field_validator("observed_at")
    @classmethod
    def recent_observation(cls, value):
        now = datetime.now(timezone.utc)
        if value.tzinfo is None or not now - timedelta(hours=6) <= value <= now + timedelta(minutes=2):
            raise ValueError("Observation must have a timezone and be within the last six hours")
        return value.astimezone(timezone.utc)


class IncidentModeration(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["VERIFIED", "REJECTED", "EXPIRED"]
    note: str = Field(min_length=10, max_length=2000)
    evidence_url: Optional[str] = Field(default=None, max_length=1024)
    osm_way_id: Optional[int] = Field(default=None, gt=0)
    edge_index: Optional[int] = Field(default=None, ge=0)

    @model_validator(mode="after")
    def verification_evidence(self):
        if self.status == "VERIFIED":
            url = urlsplit(self.evidence_url or "")
            if url.scheme != "https" or not url.hostname or url.username or url.password:
                raise ValueError("Verification requires an independent HTTPS evidence reference")
        if (self.osm_way_id is None) != (self.edge_index is None):
            raise ValueError("Both road identifiers are required together")
        return self


def incident_response(row):
    now = datetime.now(timezone.utc)
    status = "EXPIRED" if row.expires_at <= now and row.status in {"PENDING", "VERIFIED"} else row.status
    return {key: getattr(row, key) for key in (
        "id", "incident_type", "description", "lat", "lng", "observed_at", "created_at", "expires_at",
        "moderated_at", "moderation_note", "evidence_url", "osm_way_id", "edge_index",
    )} | {"status": status}


def build_community_router(authenticate_user, authorize_service, rate_limit):
    router = APIRouter(tags=["Community incidents"])

    @router.post("/api/v1/user/incidents", status_code=201)
    async def create_incident(body: IncidentCreate, request: Request, user: User = Depends(authenticate_user), db: AsyncSession = Depends(get_db)):
        await rate_limit(request, "community_submit:" + user.id, 5)
        now = datetime.now(timezone.utc)
        # Serialize submissions per account across workers, keeping dedupe and quotas atomic.
        lock = int.from_bytes(hashlib.sha256(user.id.encode()).digest()[:8], "big", signed=True)
        await db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": lock})
        recent = (await db.execute(select(CommunityIncident).where(
            CommunityIncident.user_id == user.id,
            CommunityIncident.created_at >= now - timedelta(hours=1),
        ))).scalars().all()
        for row in recent:
            if row.incident_type == body.incident_type and abs(row.lat - body.lat) < 0.0005 and abs(row.lng - body.lng) < 0.0005 and row.status != "REJECTED":
                raise HTTPException(409, detail={"code": "DUPLICATE_INCIDENT", "incident_id": row.id})
        if len(recent) >= 10:
            raise HTTPException(429, detail={"code": "INCIDENT_HOURLY_LIMIT"})
        row = CommunityIncident(id=str(uuid4()), user_id=user.id, **body.model_dump(), status="PENDING", created_at=now,
                                expires_at=body.observed_at + timedelta(hours=6))
        db.add(row)
        await db.commit()
        return incident_response(row)

    @router.get("/api/v1/user/incidents")
    async def own_incidents(user: User = Depends(authenticate_user), db: AsyncSession = Depends(get_db)):
        rows = (await db.execute(select(CommunityIncident).where(CommunityIncident.user_id == user.id)
                                .order_by(CommunityIncident.created_at.desc()).limit(100))).scalars().all()
        return [incident_response(row) for row in rows]

    @router.get("/api/v1/admin/incidents", dependencies=[Depends(authorize_service)])
    async def moderation_queue(db: AsyncSession = Depends(get_db)):
        rows = (await db.execute(select(CommunityIncident).where(CommunityIncident.status == "PENDING", CommunityIncident.expires_at > datetime.now(timezone.utc))
                                .order_by(CommunityIncident.created_at).limit(100))).scalars().all()
        return [incident_response(row) for row in rows]

    @router.patch("/api/v1/admin/incidents/{incident_id}", dependencies=[Depends(authorize_service)])
    async def moderate_incident(incident_id: str, body: IncidentModeration, db: AsyncSession = Depends(get_db)):
        row = (await db.execute(select(CommunityIncident).where(CommunityIncident.id == incident_id).with_for_update())).scalar_one_or_none()
        if row is None:
            raise HTTPException(404, detail={"code": "INCIDENT_NOT_FOUND"})
        now = datetime.now(timezone.utc)
        if body.status == "VERIFIED" and row.expires_at <= now:
            raise HTTPException(409, detail={"code": "INCIDENT_EXPIRED"})
        if body.osm_way_id is not None:
            edge = (await db.execute(text("SELECT r.source_pbf_md5, e.source_node_id, e.target_node_id FROM road_edges e JOIN road_segments r ON r.osm_way_id=e.osm_way_id WHERE e.osm_way_id=:way AND e.edge_index=:edge AND ST_DWithin(e.geom::geography, ST_SetSRID(ST_MakePoint(:lng,:lat),4326)::geography, 100)"),
                                    {"way": body.osm_way_id, "edge": body.edge_index, "lat": row.lat, "lng": row.lng})).mappings().one_or_none()
            if not edge or not edge["source_pbf_md5"] or not edge["source_node_id"] or not edge["target_node_id"]:
                raise HTTPException(422, detail={"code": "INCIDENT_EDGE_MISMATCH"})
            row.road_source_pbf_md5 = edge["source_pbf_md5"]
            row.source_node_id, row.target_node_id = edge["source_node_id"], edge["target_node_id"]
        else:
            row.road_source_pbf_md5 = row.source_node_id = row.target_node_id = None
        row.status, row.moderation_note = body.status, body.note.strip()
        row.evidence_url, row.osm_way_id, row.edge_index = body.evidence_url, body.osm_way_id, body.edge_index
        row.moderated_at = now
        await db.commit()
        # Risk is recomputed per request; raw OSRM geometry cache contains no incidents.
        return incident_response(row)

    return router
