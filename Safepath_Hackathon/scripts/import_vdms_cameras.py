"""
Ingests 796 verified VDMS camera nodes from list_camera_coordinate.txt into PostGIS.
Extracts official WGS84 coordinates from VDMS GIS POINT geometries.
Maintains provenance, orientation, and strict zero-mock spatial trust boundaries.
"""

from datetime import datetime, timezone
import argparse
import logging
from pathlib import Path

from sqlalchemy import text
from backend.app.db.session import SessionLocal
from backend.app.services.vdms_parser import parse_vdms_snapshot_file

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("import_vdms_cameras")
DEFAULT_DATA_PATH = Path(__file__).resolve().parents[1] / "list_camera_coordinate.txt"


def import_vdms_cameras(filepath: str | Path = DEFAULT_DATA_PATH) -> None:
    logger.info("Parsing VDMS camera snapshot from %s...", filepath)
    report = parse_vdms_snapshot_file(filepath)
    logger.info(
        "Parsed %d camera nodes. Status breakdown: %s. Coordinates count: %d",
        report.total_nodes,
        report.status_breakdown,
        report.valid_coordinates_count,
    )

    now = datetime.now(timezone.utc)
    inserted = 0
    updated = 0

    with SessionLocal() as session:
        for cam in report.cameras:
            # Upsert camera record
            upsert_query = text("""
                INSERT INTO traffic_cameras (
                    cam_id,
                    code,
                    name,
                    district,
                    stream_url,
                    snapshot_cam_status,
                    source_uri,
                    location_confidence,
                    orientation,
                    permitted_use,
                    coordinate_source_url,
                    coordinate_verified_at,
                    metadata_created_at,
                    metadata_modified_at,
                    bearing_degrees,
                    line_of_sight_verified,
                    geom
                ) VALUES (
                    :cam_id,
                    :code,
                    :name,
                    :district,
                    :stream_url,
                    :snapshot_cam_status,
                    :source_uri,
                    :location_confidence,
                    :orientation,
                    :permitted_use,
                    :coordinate_source_url,
                    :coordinate_verified_at,
                    :metadata_created_at,
                    :metadata_modified_at,
                    :bearing_degrees,
                    FALSE,
                    ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)
                )
                ON CONFLICT (cam_id) DO UPDATE SET
                    code = EXCLUDED.code,
                    name = EXCLUDED.name,
                    district = CASE
                        WHEN traffic_cameras.district IS NOT NULL AND traffic_cameras.district != '' THEN traffic_cameras.district
                        ELSE COALESCE(EXCLUDED.district, 'UNKNOWN_DISTRICT')
                    END,
                    stream_url = EXCLUDED.stream_url,
                    snapshot_cam_status = EXCLUDED.snapshot_cam_status,
                    source_uri = EXCLUDED.source_uri,
                    location_confidence = EXCLUDED.location_confidence,
                    orientation = EXCLUDED.orientation,
                    coordinate_source_url = EXCLUDED.coordinate_source_url,
                    coordinate_verified_at = EXCLUDED.coordinate_verified_at,
                    metadata_created_at = EXCLUDED.metadata_created_at,
                    metadata_modified_at = EXCLUDED.metadata_modified_at,
                    bearing_degrees = EXCLUDED.bearing_degrees,
                    geom = EXCLUDED.geom
            """)

            session.execute(
                upsert_query,
                {
                    "cam_id": cam.cam_id,
                    "code": cam.code,
                    "name": cam.name,
                    "district": cam.district,
                    "stream_url": cam.snapshot_url,
                    "snapshot_cam_status": cam.snapshot_status,
                    "source_uri": f"file://{cam.source_file}",
                    "location_confidence": cam.location_confidence,
                    "orientation": cam.angle,
                    "permitted_use": "PERMISSION_UNVERIFIED",
                    "coordinate_source_url": f"file://{cam.source_file}#DataTable.Shape",
                    "coordinate_verified_at": now,
                    "metadata_created_at": cam.created_at,
                    "metadata_modified_at": cam.modified_at,
                    "bearing_degrees": float(cam.angle) if cam.angle is not None else None,
                    "lng": cam.lng,
                    "lat": cam.lat,
                },
            )
            inserted += 1

        # Match nearest road segment within 80 meters (SPATIALLY_NEAR only)
        logger.info("Computing nearest OSM road segment within 80m for cameras...")
        match_query = text("""
            WITH nearest_matches AS (
                SELECT 
                    c.cam_id,
                    r.osm_way_id,
                    ROW_NUMBER() OVER (
                        PARTITION BY c.cam_id 
                        ORDER BY ST_Distance(c.geom::geography, r.geom::geography) ASC
                    ) AS rank
                FROM traffic_cameras c
                JOIN road_segments r 
                  ON ST_DWithin(c.geom::geography, r.geom::geography, 80)
                WHERE c.geom IS NOT NULL
            )
            UPDATE traffic_cameras tc
            SET nearest_osm_way_id = nm.osm_way_id
            FROM nearest_matches nm
            WHERE tc.cam_id = nm.cam_id AND nm.rank = 1;
        """)
        session.execute(match_query)
        session.commit()

    logger.info("Successfully imported and indexed %d cameras in PostGIS.", inserted)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("filepath", nargs="?", type=Path, default=DEFAULT_DATA_PATH)
    import_vdms_cameras(parser.parse_args().filepath)


if __name__ == "__main__":
    main()

