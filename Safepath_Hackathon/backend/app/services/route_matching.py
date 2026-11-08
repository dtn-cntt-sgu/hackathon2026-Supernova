"""Exact OSM topology matching; nearby geometry alone never authorizes road risk."""
import hashlib
import json
import re
from pathlib import Path
from functools import lru_cache

from backend.app.core.config import settings
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

MATCH_VERSION = "osm-node-pairs-v1"
SOURCE_URL = "https://download.geofabrik.de/asia/vietnam-latest.osm.pbf"


def graph_proof(manifest_path=None):
    """Require a build-produced manifest and unchanged graph artifacts, fail closed."""
    path = Path(manifest_path or settings.OSRM_GRAPH_MANIFEST_PATH)
    try:
        payload = path.read_bytes()
        manifest = json.loads(payload)
        if manifest.get("schema") != 1 or manifest.get("source_url") != SOURCE_URL:
            return None
        if not isinstance(manifest.get("pbf_md5"), str) or not re.fullmatch(r"[a-f0-9]{32}", manifest["pbf_md5"]):
            return None
        files = manifest["files"]
        if not isinstance(files, dict):
            return None
        required = {"vietnam-latest.osrm.mldgr", "vietnam-latest.osrm.geometry", "vietnam-latest.osrm.nbg_nodes", "vietnam-latest.osrm.properties"}
        if not required.issubset(files):
            return None
        signatures = []
        for name, digest in sorted(files.items()):
            if (not isinstance(name, str) or not isinstance(digest, str)
                    or not re.fullmatch(r"[a-f0-9]{64}", digest)
                    or Path(name).name != name or not name.startswith("vietnam-latest.osrm")):
                return None
            artifact = path.parent / name
            stat = artifact.stat()
            signatures.append((str(artifact), stat.st_size, stat.st_mtime_ns, digest))
        if not _validate_artifacts(tuple(signatures)):
            return None
        return {"pbf_md5": manifest["pbf_md5"], "identity": hashlib.sha256(payload).hexdigest()}
    except (OSError, ValueError, KeyError, TypeError):
        return None


@lru_cache(maxsize=2)
def _validate_artifacts(signatures):
    for name, _, _, expected in signatures:
        with open(name, "rb") as source:
            if hashlib.file_digest(source, "sha256").hexdigest() != expected:
                return False
    return True


MATCH_SQL = text("""
WITH steps AS (
    SELECT s.route_idx, s.step_idx, s.leg_idx,
           ST_SetSRID(ST_GeomFromGeoJSON(s.geometry::text),4326) AS geom
    FROM jsonb_to_recordset(CAST(:steps AS jsonb))
      AS s(route_idx int, step_idx int, leg_idx int, geometry jsonb)
), pairs AS (
    SELECT * FROM jsonb_to_recordset(CAST(:pairs AS jsonb))
      AS p(route_idx int, leg_idx int, pair_idx int, source_node bigint, target_node bigint)
), candidates AS (
    SELECT p.*, e.osm_way_id, e.edge_index, e.geom,
           CASE WHEN e.source_node_id=p.source_node THEN e.geom ELSE ST_Reverse(e.geom) END AS traversal_geom,
           count(*) OVER (PARTITION BY p.route_idx,p.leg_idx,p.pair_idx) AS alternatives
    FROM pairs p JOIN road_edges e ON
      LEAST(e.source_node_id,e.target_node_id)=LEAST(p.source_node,p.target_node)
      AND GREATEST(e.source_node_id,e.target_node_id)=GREATEST(p.source_node,p.target_node)
    JOIN road_segments r USING (osm_way_id)
    WHERE r.source_pbf_md5=:pbf_md5 AND r.source_url=:source_url
      AND ((e.source_node_id=p.source_node AND coalesce(r.oneway,'') != '-1')
        OR (e.target_node_id=p.source_node AND coalesce(r.oneway,'') NOT IN ('yes','1','true')))
      AND coalesce(r.access,'') NOT IN ('no','private')
), matched AS (
    SELECT s.route_idx,s.step_idx,s.geom AS step_geom,c.osm_way_id,c.edge_index,c.pair_idx,c.geom,
           CASE WHEN ST_CoveredBy(c.geom,ST_Buffer(s.geom::geography,0.75)::geometry)
                THEN ST_Length(c.geom::geography)
                ELSE ST_Length(c.geom::geography) * abs(
                    ST_LineLocatePoint(c.geom,ST_StartPoint(s.geom)) -
                    ST_LineLocatePoint(c.geom,ST_EndPoint(s.geom))) END AS overlap_m
    FROM steps s JOIN candidates c USING (route_idx,leg_idx)
    WHERE c.alternatives=1 AND ST_DWithin(c.geom::geography,s.geom::geography,0.75)
      AND ST_LineLocatePoint(s.geom,ST_StartPoint(c.traversal_geom))
          < ST_LineLocatePoint(s.geom,ST_EndPoint(c.traversal_geom))
), covered AS (
    SELECT route_idx,step_idx,
      ST_CoveredBy(step_geom,ST_Buffer(ST_Union(geom)::geography,0.75)::geometry)
      AND count(DISTINCT pair_idx)=max(pair_idx)-min(pair_idx)+1 AS complete
    FROM matched WHERE overlap_m > 0 GROUP BY route_idx,step_idx,step_geom
)
SELECT m.route_idx,m.step_idx,m.osm_way_id,m.edge_index,
       ST_AsGeoJSON(m.geom) AS geometry,m.overlap_m
FROM matched m JOIN covered c USING(route_idx,step_idx)
WHERE c.complete AND m.overlap_m > 0
ORDER BY m.route_idx,m.step_idx,m.pair_idx,m.osm_way_id,m.edge_index
""")


async def verified_step_edges(routes, db_session, proof):
    if not proof:
        return {}
    steps, pairs = [], []
    for ri, route in enumerate(routes):
        si = 0
        for li, leg in enumerate(route.get("legs", [])):
            nodes = leg.get("annotation", {}).get("nodes", [])
            if isinstance(nodes, list) and len(nodes) >= 2 and all(type(n) is int and n > 0 for n in nodes):
                pairs.extend({"route_idx": ri, "leg_idx": li, "pair_idx": pi,
                              "source_node": a, "target_node": b}
                             for pi, (a, b) in enumerate(zip(nodes, nodes[1:])) if a != b)
                steps.extend({"route_idx": ri, "leg_idx": li, "step_idx": si + offset,
                              "geometry": step["geometry"]}
                             for offset, step in enumerate(leg.get("steps", []))
                             if step.get("geometry", {}).get("type") == "LineString" and step.get("distance", 0) > 0)
            si += len(leg.get("steps", []))
    if not pairs or not steps:
        return {}
    params = {"steps": json.dumps(steps), "pairs": json.dumps(pairs),
              "pbf_md5": proof["pbf_md5"], "source_url": SOURCE_URL}
    result = await db_session.execute(MATCH_SQL, params) if isinstance(db_session, AsyncSession) else db_session.execute(MATCH_SQL, params)
    matches = {}
    for row in result.fetchall():
        edges = matches.setdefault((row.route_idx, row.step_idx), [])
        key = (int(row.osm_way_id), int(row.edge_index))
        if not any((e["osm_way_id"], e["edge_index"]) == key for e in edges):
            edges.append({"osm_way_id": key[0], "edge_index": key[1], "route_match_verified": True,
                          "geometry": json.loads(row.geometry), "length_meters": float(row.overlap_m)})
    return matches
