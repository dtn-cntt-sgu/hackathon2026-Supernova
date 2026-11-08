"""Read-only production checks. Does not start services, migrate or contact providers."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from urllib.parse import urlsplit

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[2]


def validate_environment(env: dict) -> list[str]:
    errors = []
    for name in ("BACKEND_IMAGE", "FRONTEND_IMAGE"):
        if not re.fullmatch(r"ghcr\.io/[a-z0-9_./-]+@sha256:[0-9a-f]{64}", env.get(name, "")):
            errors.append(f"{name}: require an approved immutable GHCR image digest")
    for name in ("AUTH_SECRET", "SERVICE_AUTH_TOKEN", "POSTGRES_PASSWORD"):
        value = env.get(name, "")
        if len(value) < 32 or any(word in value.lower() for word in ("example", "placeholder", "replace", "safepath_dev")):
            errors.append(f"{name}: provide an independent randomly generated secret of at least 32 characters")
    if env.get("AUTH_SECRET") == env.get("SERVICE_AUTH_TOKEN"):
        errors.append("AUTH_SECRET and SERVICE_AUTH_TOKEN must differ")
    if not re.fullmatch(r"[A-Za-z0-9_-]{32,}", env.get("POSTGRES_PASSWORD", "")):
        errors.append("POSTGRES_PASSWORD must use URI-safe letters, digits, underscore or hyphen")
    try:
        database = urlsplit(env.get("APP_DATABASE_URL", ""))
        if (database.scheme != "postgresql+asyncpg" or database.hostname != "postgis"
                or database.username in (None, env.get("POSTGRES_USER", "safepath"), "postgres")
                or len(database.password or "") < 32
                or database.password == env.get("POSTGRES_PASSWORD")
                or database.path != "/" + env.get("POSTGRES_DB", "safepath")):
            errors.append("APP_DATABASE_URL must use the independently provisioned runtime role on internal postgis and the configured database")
    except ValueError:
        errors.append("APP_DATABASE_URL is invalid (value withheld)")
    host = env.get("PUBLIC_HOST", "")
    if not re.fullmatch(r"(?=.{1,253}$)(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,63}", host):
        errors.append("PUBLIC_HOST must be a public DNS hostname, without scheme, path or port")
    for name in ("AUTH_GOOGLE_ID", "AUTH_GOOGLE_SECRET", "OSRM_GRAPH_VERSION"):
        if not env.get(name):
            errors.append(f"{name}: required; do not assume external configuration is verified")
    for name in ("POSTGRES_USER", "POSTGRES_DB"):
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", env.get(name, "safepath")):
            errors.append(f"{name}: use a simple PostgreSQL identifier")
    permission_flags = ("CAMERA_PROXY_ENABLED", "CAMERA_ALLOW_VIEW_ONLY", "CAMERA_INGESTION_PERMITTED", "CAMERA_ROUTING_EVIDENCE_PERMITTED")
    if any(env.get(flag, "false").lower() == "true" for flag in permission_flags) and not env.get("CAMERA_SOURCE_PERMISSION_REFERENCE"):
        errors.append("Camera access requires documented CAMERA_SOURCE_PERMISSION_REFERENCE; this does not itself authorize station evidence")
    return errors


def validate_artifacts(env: dict) -> list[str]:
    errors = []
    graph = Path(env.get("OSRM_DATA_DIR", ""))
    if not graph.is_absolute():
        errors.append("OSRM_DATA_DIR must be an absolute path")
    for suffix in ("", ".partition", ".cells", ".cell_metrics", ".mldgr", ".geometry", ".edges"):
        path = graph / f"vietnam-latest.osrm{suffix}"
        if not path.is_file() or path.stat().st_size == 0:
            errors.append(f"Missing or empty MLD graph component: vietnam-latest.osrm{suffix}")
    from backend.app.services.route_matching import graph_proof
    if graph_proof(graph / "graph-manifest.json") is None:
        errors.append("OSRM graph build manifest/hash proof is missing or invalid")
    try:
        manifest = json.loads((ROOT / "data/models/model_manifest.json").read_text())
        for name in ("vehicle_detector", "flood_segmenter"):
            record = manifest["models"][name]
            path = (ROOT / record["file_path"]).resolve()
            if not path.is_relative_to(ROOT / "data/models") or not path.is_file():
                raise ValueError("Missing or invalid model path")
            with path.open("rb") as stream:
                digest = hashlib.file_digest(stream, "sha256").hexdigest()
            if digest != record["sha256"]:
                errors.append(f"Model checksum mismatch: {name}")
    except (OSError, KeyError, ValueError):
        errors.append("Model manifest/assets are missing or invalid")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--check-running", action="store_true", help="Read readiness inside an already approved/running stack; never starts it")
    parser.add_argument("--project", default="safepath-production")
    args = parser.parse_args()
    if not args.env_file.is_file():
        parser.error("Supply an existing protected production environment file")
    env_file = args.env_file.resolve()
    env = {**{key: value for key, value in dotenv_values(env_file).items() if value is not None}, **os.environ}
    errors = validate_environment(env) + validate_artifacts(env)
    command = ["docker", "compose", "--env-file", str(env_file), "-f", str(ROOT / "docker-compose.prod.yml"), "config", "--quiet"]
    try:
        if subprocess.run(command, cwd=ROOT, env=env, capture_output=True, timeout=30).returncode:
            errors.append("Production Compose configuration failed validation (values withheld)")
    except (OSError, subprocess.TimeoutExpired):
        errors.append("Docker Compose unavailable or timed out")
    if args.check_running and not errors:
        probe = (
            "import json,urllib.request; "
            "r=urllib.request.urlopen('http://127.0.0.1:8000/api/v1/ready',timeout=10); "
            "d=json.load(r); "
            "print(json.dumps({k:d.get(k) for k in ('ready','osrm')}))"
        )
        command = command[:-2] + ["-p", args.project, "exec", "-T", "backend", "python", "-c", probe]
        try:
            result = subprocess.run(command, cwd=ROOT, env=env, capture_output=True, text=True, timeout=20)
            status = json.loads(result.stdout) if result.returncode == 0 else {}
            if status.get("ready") is not True:
                errors.append("Running backend readiness failed or returned HTTP 503")
            elif status.get("osrm") != "available":
                errors.append("DEGRADED: core dependencies available but OSRM is unavailable")
        except (OSError, ValueError, subprocess.TimeoutExpired):
            errors.append("Running-service readiness could not be verified")
    for error in errors:
        print(f"BLOCKED: {error}")
    if errors:
        return 1
    print("PASS: local configuration, model checksums and graph artifacts. DNS/TLS/OAuth, source rights, migration and running-service acceptance remain NOT VERIFIED.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
