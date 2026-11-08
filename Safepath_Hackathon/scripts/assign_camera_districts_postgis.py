"""
Assigns all 796 SafePathAI traffic cameras to official HCMC municipal districts
using PostGIS spatial joins (ST_Covers).

Data Provenance:
- Source: OCHA ROAP, Government of Viet Nam via geoBoundaries v5
- Dataset ID: VNM-ADM2-81297802
- Boundary Year: 2020 (covers all 24 HCMC districts matching system schema)
- License: Creative Commons Attribution 3.0 Intergovernmental Organisations (CC BY 3.0 IGO)
- Method: Exact geometric containment via PostGIS ST_Covers on WGS84 coordinates.
- Cameras outside HCMC boundary are assigned 'UNKNOWN_DISTRICT' (zero guessing, zero centroid snapping).
"""

from datetime import datetime, timezone
import json
import logging
import os
import argparse
from pathlib import Path

from sqlalchemy import text
from backend.app.db.session import SessionLocal
from backend.app.db.models import map_cameras_to_districts_sync

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("assign_camera_districts")
ROOT = Path(__file__).resolve().parents[1]


def populate_district_boundaries(geojson_path: str | Path = ROOT / "data/boundaries/hcmc_district_boundaries.geojson") -> int:
    """Loads and upserts the 24 HCMC district boundary polygons into PostGIS."""
    if not os.path.exists(geojson_path):
        raise FileNotFoundError(f"District boundaries GeoJSON not found at {geojson_path}")

    with open(geojson_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    features = data.get("features", [])
    logger.info("Loading %d district boundaries from %s...", len(features), geojson_path)

    upsert_sql = text("""
        INSERT INTO hcmc_district_boundaries (
            district_id,
            name,
            name_en,
            shape_name_raw,
            province,
            source,
            source_dataset_id,
            boundary_year,
            license,
            geom
        ) VALUES (
            :district_id,
            :name,
            :name_en,
            :shape_name_raw,
            :province,
            :source,
            :source_dataset_id,
            :boundary_year,
            :license,
            ST_Multi(ST_SetSRID(ST_GeomFromGeoJSON(:geom_geojson), 4326))
        )
        ON CONFLICT (district_id) DO UPDATE SET
            name = EXCLUDED.name,
            name_en = EXCLUDED.name_en,
            shape_name_raw = EXCLUDED.shape_name_raw,
            province = EXCLUDED.province,
            source = EXCLUDED.source,
            source_dataset_id = EXCLUDED.source_dataset_id,
            boundary_year = EXCLUDED.boundary_year,
            license = EXCLUDED.license,
            geom = EXCLUDED.geom;
    """)

    count = 0
    with SessionLocal() as session:
        for feat in features:
            props = feat.get("properties", {})
            geom_str = json.dumps(feat.get("geometry", {}))
            session.execute(
                upsert_sql,
                {
                    "district_id": props["district_id"],
                    "name": props["name"],
                    "name_en": props.get("name_en"),
                    "shape_name_raw": props.get("shape_name_raw"),
                    "province": props.get("province", "Thành phố Hồ Chí Minh"),
                    "source": props.get("source", "OCHA ROAP / Government of Viet Nam"),
                    "source_dataset_id": props.get("source_dataset_id", "VNM-ADM2-81297802"),
                    "boundary_year": props.get("boundary_year", 2020),
                    "license": props.get("license", "CC BY 3.0 IGO"),
                    "geom_geojson": geom_str,
                },
            )
            count += 1
        session.commit()

    logger.info("Successfully loaded and indexed %d district boundaries in PostGIS.", count)
    return count


def run_spatial_assignment(*, update_manifest: bool = True) -> dict:
    """Executes the PostGIS spatial join to map all cameras to official districts."""
    populate_district_boundaries()

    logger.info("Executing PostGIS spatial join (ST_Covers)...")
    with SessionLocal() as session:
        matched_count, unknown_count = map_cameras_to_districts_sync(session)
        logger.info("Spatial mapping complete. Matched: %d, Unknown: %d", matched_count, unknown_count)

        # Audit breakdown
        rows = session.execute(text("""
            SELECT 
                COALESCE(district, 'NULL') as district_name,
                COUNT(*) as count,
                district_method,
                district_source
            FROM traffic_cameras
            GROUP BY district, district_method, district_source
            ORDER BY count DESC, district_name ASC;
        """)).fetchall()

        total = session.execute(text("SELECT COUNT(*) FROM traffic_cameras;")).scalar()
        null_count = session.execute(text("SELECT COUNT(*) FROM traffic_cameras WHERE district IS NULL;")).scalar()
        q4_count = session.execute(text("SELECT COUNT(*) FROM traffic_cameras WHERE district = 'Quận 4';")).scalar()
        q10_count = session.execute(text("SELECT COUNT(*) FROM traffic_cameras WHERE district = 'Quận 10';")).scalar()
        q11_count = session.execute(text("SELECT COUNT(*) FROM traffic_cameras WHERE district = 'Quận 11';")).scalar()
        unknown_db = session.execute(text("SELECT COUNT(*) FROM traffic_cameras WHERE district = 'UNKNOWN_DISTRICT';")).scalar()

    breakdown = [{"district": r[0], "count": r[1], "method": r[2], "source": r[3]} for r in rows]

    audit_summary = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "total_cameras": total,
        "null_districts_count": null_count,
        "matched_hcmc_districts_count": total - unknown_db - null_count,
        "unknown_districts_count": unknown_db,
        "q4_count": q4_count,
        "q10_count": q10_count,
        "q11_count": q11_count,
        "breakdown": breakdown,
    }

    # Synchronize camera_url_manifest.json if it exists
    if update_manifest:
        sync_manifest(audit_summary)

    return audit_summary


def sync_manifest(audit_summary: dict, manifest_path: str | Path = ROOT / "data/cameras/camera_url_manifest.json") -> None:
    """Updates camera_url_manifest.json with verified districts and provenance."""
    if not os.path.exists(manifest_path):
        logger.warning("Manifest not found at %s. Skipping manifest sync.", manifest_path)
        return

    logger.info("Syncing verified districts to %s...", manifest_path)
    with SessionLocal() as session:
        cam_records = session.execute(text("""
            SELECT cam_id, district, district_source, district_method, district_verified_at
            FROM traffic_cameras;
        """)).fetchall()
        cam_lookup = {
            r[0]: {
                "district": r[1],
                "district_source": r[2],
                "district_method": r[3],
                "district_verified_at": r[4].isoformat() if r[4] else None,
            }
            for r in cam_records
        }

    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    cameras = manifest.get("cameras", [])
    updated = 0
    for c in cameras:
        cid = c.get("cam_id")
        if cid in cam_lookup:
            meta = cam_lookup[cid]
            c["district"] = meta["district"]
            c["district_source"] = meta["district_source"]
            c["district_method"] = meta["district_method"]
            c["district_verified_at"] = meta["district_verified_at"]
            updated += 1

    manifest["district_audit"] = {
        "verified_at": audit_summary["timestamp"],
        "source": "OCHA ROAP, Government of Viet Nam via geoBoundaries (VNM-ADM2-81297802)",
        "method": "PostGIS ST_Covers",
        "hcmc_districts_count": audit_summary["matched_hcmc_districts_count"],
        "unknown_districts_count": audit_summary["unknown_districts_count"],
        "q4_count": audit_summary["q4_count"],
        "q10_count": audit_summary["q10_count"],
        "q11_count": audit_summary["q11_count"],
    }

    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    logger.info("Updated %d cameras in %s with verified district provenance.", updated, manifest_path)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-manifest", action="store_true", help="Keep the bundled source manifest read-only")
    summary = run_spatial_assignment(update_manifest=not parser.parse_args().no_manifest)
    print("\n=======================================================")
    print("   SAFEPATH AI — CAMERA DISTRICT CLASSIFICATION AUDIT  ")
    print("=======================================================")
    print(f"Total Cameras in DB        : {summary['total_cameras']}")
    print(f"Cameras inside HCMC        : {summary['matched_hcmc_districts_count']}")
    print(f"Outside HCMC / UNKNOWN     : {summary['unknown_districts_count']}")
    print(f"Unassigned / NULL Districts: {summary['null_districts_count']}")
    print("-------------------------------------------------------")
    print(f"Quận 4 Camera Count        : {summary['q4_count']}")
    print(f"Quận 10 Camera Count       : {summary['q10_count']}")
    print(f"Quận 11 Camera Count       : {summary['q11_count']}")
    print("=======================================================\n")
    print("DISTRICT BREAKDOWN:")
    for b in summary["breakdown"]:
        print(f"  {b['district']:22s} | {b['count']:3d} cameras | {b['method']} | {b['source']}")


if __name__ == "__main__":
    main()

