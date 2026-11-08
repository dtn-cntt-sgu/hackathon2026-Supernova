"""Restore a scratch database backup into a new scratch DB, compare counts, then drop it.

Requires SAFEPATH_REHEARSAL_DATABASE_URL, a local Docker Postgres container and a
source DB beginning safepath_readiness_qa_ or safepath_qa_. Never accepts production.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
from uuid import uuid4

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--container", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    url = make_url(os.environ["SAFEPATH_REHEARSAL_DATABASE_URL"].replace("postgresql+asyncpg", "postgresql+psycopg2"))
    source = url.database or ""
    if not re.fullmatch(r"safepath_(?:readiness_)?qa_[a-zA-Z0-9_]+", source):
        parser.error("Only explicitly named scratch QA databases can be backed up/restored")
    args.output_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor, filename = tempfile.mkstemp(prefix="rehearsal-", suffix=".dump", dir=args.output_dir)
    archive = Path(filename)
    command = ["docker", "exec", "-i", args.container]
    with os.fdopen(descriptor, "wb") as output:
        subprocess.run(command + ["pg_dump", "-U", url.username, "-d", source, "-Fc"], stdout=output, stderr=subprocess.PIPE, check=True, timeout=120)
    restore = "safepath_qa_restore_" + uuid4().hex[:12]
    admin = create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    created = False
    try:
        with admin.connect() as db:
            db.execute(text(f'CREATE DATABASE "{restore}"'))
            created = True
        with archive.open("rb") as data:
            subprocess.run(command + ["pg_restore", "-U", url.username, "-d", restore, "--no-owner", "--exit-on-error"], stdin=data, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=True, timeout=120)
        summaries = []
        for name in (source, restore):
            engine = create_engine(url.set(database=name))
            with engine.connect() as db:
                quote = db.dialect.identifier_preparer.quote
                tables = sorted(inspect(db).get_table_names(schema="public"))
                counts = {table: db.scalar(text(f"SELECT count(*) FROM {quote(table)}")) for table in tables}
                revision = db.scalar(text("SELECT version_num FROM alembic_version"))
                permissions = db.scalar(text("SELECT md5(string_agg(cam_id || ':' || coalesce(permitted_use,''),',' ORDER BY cam_id)) FROM traffic_cameras"))
                summaries.append({"counts": counts, "revision": revision, "camera_permission_hash": permissions})
            engine.dispose()
        if summaries[0] != summaries[1]:
            raise RuntimeError("Restored database differs from source")
        with archive.open("rb") as data:
            digest = hashlib.file_digest(data, "sha256").hexdigest()
        result = {"status": "PASS", "scope": "scratch databases only", "source": source, "restore_dropped": True,
                  "archive": str(archive), "sha256": digest, "validated": summaries[0]}
        print(json.dumps(result, indent=2))
    finally:
        if created:
            with admin.connect() as db:
                db.execute(text(f'DROP DATABASE "{restore}" WITH (FORCE)'))
        admin.dispose()


if __name__ == "__main__":
    main()
