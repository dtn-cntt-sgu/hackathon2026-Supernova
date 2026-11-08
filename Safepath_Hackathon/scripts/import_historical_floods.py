"""
Imports verified municipal historical flood observation points into PostGIS
and links them to nearest road segments, marking is_flood_prone_history=True.
Zero-Mock Compliance:
- Sourced from official HCMC municipal reports.
- Leaves unverified roads as is_flood_prone_history=NULL (UNKNOWN), never False.
- Distinguishes historical flood records from current real-time observations.
"""

import json
import logging
import argparse
from pathlib import Path
from datetime import datetime, timezone

from geoalchemy2.elements import WKTElement
from sqlalchemy import text

from backend.app.db.models import HistoricalFloodPoint
from backend.app.db.session import SessionLocal

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("import_historical_floods")

DATA_PATH = Path(__file__).resolve().parents[1] / "data/floods/hcmc_historical_flood_points.json"


def run_import(data_path: str | Path = DATA_PATH):
    with open(data_path, "r", encoding="utf-8") as f:
        records = json.load(f)

    logger.info("Loaded %d historical flood points from %s", len(records), data_path)

    with SessionLocal.begin() as session:
        imported_count = 0
        now = datetime.now(timezone.utc)

        for rec in records:
            point_id = rec["flood_point_id"]
            lat = rec["lat"]
            lng = rec["lng"]
            wkt = f"POINT({lng} {lat})"

            fp = HistoricalFloodPoint(
                id=point_id,
                street_name=rec["street_name"],
                district=rec.get("district"),
                cause=rec["cause"],
                reported_years=rec.get("reported_years"),
                typical_depth_cm=rec.get("typical_depth_cm"),
                source_name=rec["source_name"],
                source_url=rec["source_url"],
                confidence=rec.get("confidence", "OFFICIAL_MUNICIPAL_REPORT"),
                geom=WKTElement(wkt, srid=4326),
                created_at=now,
            )
            # Upsert source IDs without deleting unrelated station/history records.
            session.merge(fp)
            imported_count += 1

        session.flush()
        logger.info("Inserted %d historical flood points into PostGIS.", imported_count)

        # 2. Match historical flood points to road_segments within 80 meters where street_name matches or nearby
        match_sql = text("""
            WITH matched_roads AS (
                SELECT 
                    fp.id as flood_id,
                    r.osm_way_id,
                    ROW_NUMBER() OVER (
                        PARTITION BY fp.id 
                        ORDER BY ST_Distance(cast(fp.geom as geography), cast(r.geom as geography)) ASC
                    ) as rn
                FROM historical_flood_points fp
                JOIN road_segments r 
                  ON ST_DWithin(cast(fp.geom as geography), cast(r.geom as geography), 80.0)
            )
            UPDATE historical_flood_points fp
            SET matched_osm_way_id = mr.osm_way_id
            FROM matched_roads mr
            WHERE fp.id = mr.flood_id AND mr.rn = 1;
        """)
        session.execute(match_sql)

        # 3. Update is_flood_prone_history = TRUE on road_segments matching flood points
        update_road_sql = text("""
            UPDATE road_segments r
            SET is_flood_prone_history = TRUE
            FROM historical_flood_points fp
            WHERE r.osm_way_id = fp.matched_osm_way_id;
        """)
        res = session.execute(update_road_sql)
        logger.info("Updated %d road segments with is_flood_prone_history = TRUE.", res.rowcount)

        # 4. Verify unverified roads remain NULL
        check_sql = text("""
            SELECT 
                count(*) FILTER (WHERE is_flood_prone_history IS TRUE) as true_count,
                count(*) FILTER (WHERE is_flood_prone_history IS FALSE) as false_count,
                count(*) FILTER (WHERE is_flood_prone_history IS NULL) as null_count
            FROM road_segments;
        """)
        counts = session.execute(check_sql).fetchone()
        logger.info(
            "Road segments status: TRUE (historical flood)=%d, FALSE (never fabricated)=%d, NULL (unknown)=%d",
            counts[0], counts[1], counts[2]
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=DATA_PATH)
    run_import(parser.parse_args().data)


if __name__ == "__main__":
    main()
