"""Only fresh, independently verified reports with explicit road attribution enter risk."""
from datetime import datetime, timezone
from inspect import isawaitable
from sqlalchemy import select, tuple_
from backend.app.db.community_models import CommunityIncident
from backend.app.db.models import RoadEdge, RoadSegment


async def load_verified_incidents(session, edge_ids):
    if not edge_ids:
        return {}
    now = datetime.now(timezone.utc)
    statement = select(CommunityIncident).join(RoadEdge, (RoadEdge.osm_way_id == CommunityIncident.osm_way_id) &
        (RoadEdge.edge_index == CommunityIncident.edge_index)).join(RoadSegment, RoadSegment.osm_way_id == RoadEdge.osm_way_id).where(
        CommunityIncident.road_source_pbf_md5 == RoadSegment.source_pbf_md5,
        CommunityIncident.source_node_id == RoadEdge.source_node_id,
        CommunityIncident.target_node_id == RoadEdge.target_node_id,
        CommunityIncident.status == "VERIFIED", CommunityIncident.expires_at > now,
        CommunityIncident.observed_at <= now, CommunityIncident.evidence_url.is_not(None),
        tuple_(CommunityIncident.osm_way_id, CommunityIncident.edge_index).in_(sorted(set(edge_ids))),
    )
    result = session.execute(statement)
    if isawaitable(result):
        result = await result
    grouped = {}
    for row in result.scalars():
        grouped.setdefault((row.osm_way_id, row.edge_index), []).append({
            "id": row.id, "incident_id": row.id, "osm_way_id": row.osm_way_id, "edge_index": row.edge_index,
            "category": row.incident_type, "status": "VERIFIED", "observed_at": row.observed_at,
            "expires_at": row.expires_at, "evidence_url": row.evidence_url, "confidence": 0.8,
        })
    return grouped
