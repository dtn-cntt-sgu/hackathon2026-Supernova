"""Unit/config checks only: never start services or write to a database."""
import hashlib
import json
import os
from pathlib import Path
import secrets
import stat
import subprocess
import sys
from types import SimpleNamespace
import pytest

from scripts.production import backup, preflight


def deployment_env():
    return {
        "BACKEND_IMAGE": "ghcr.io/unit/safepath/backend@sha256:" + "a" * 64,
        "FRONTEND_IMAGE": "ghcr.io/unit/safepath/frontend@sha256:" + "b" * 64,
        "PUBLIC_HOST": "safepath.example.org",
        "APP_DATABASE_URL": "postgresql+asyncpg://safepath_app:" + secrets.token_hex(32) + "@postgis:5432/safepath",
        "AUTH_SECRET": secrets.token_hex(32),
        "SERVICE_AUTH_TOKEN": secrets.token_hex(32),
        "POSTGRES_PASSWORD": secrets.token_hex(32),
        "AUTH_GOOGLE_ID": "unit-only-google-id",
        "AUTH_GOOGLE_SECRET": "unit-only-google-secret",
        "OSRM_GRAPH_VERSION": "unit-config-only",
        "OSRM_DATA_DIR": "/tmp/safepath-unit-only-graph",
    }


def test_environment_rejects_missing_and_shared_secrets_without_echoing_them():
    assert any("AUTH_SECRET" in error for error in preflight.validate_environment({}))
    env = deployment_env()
    env["SERVICE_AUTH_TOKEN"] = env["AUTH_SECRET"]
    errors = preflight.validate_environment(env)
    assert "AUTH_SECRET and SERVICE_AUTH_TOKEN must differ" in errors
    assert all(env["AUTH_SECRET"] not in error for error in errors)


def test_camera_access_requires_documented_permissions():
    env = deployment_env()
    assert preflight.validate_environment(env) == []
    env["CAMERA_ALLOW_VIEW_ONLY"] = "true"
    assert any("CAMERA_SOURCE_PERMISSION_REFERENCE" in error for error in preflight.validate_environment(env))


def test_preflight_detects_model_tampering_and_missing_graph(monkeypatch, tmp_path):
    # Explicit unit-only artifact fixtures; production never reads this directory.
    directory = tmp_path / "data/models"
    directory.mkdir(parents=True)
    weights = directory / "unit.onnx"
    weights.write_bytes(b"unit-only-artifact")
    record = {"file_path": "data/models/unit.onnx", "sha256": hashlib.sha256(weights.read_bytes()).hexdigest()}
    (directory / "model_manifest.json").write_text(json.dumps({"models": {"vehicle_detector": record, "flood_segmenter": record}}))
    monkeypatch.setattr(preflight, "ROOT", tmp_path)
    env = deployment_env()
    graph = tmp_path / "graph"
    graph.mkdir()
    env["OSRM_DATA_DIR"] = str(graph)
    assert any("Missing or empty MLD" in error for error in preflight.validate_artifacts(env))
    weights.write_bytes(b"tampered-unit-artifact")
    assert any("checksum mismatch" in error for error in preflight.validate_artifacts(env))


def test_production_compose_keeps_private_services_unpublished():
    command = ["docker", "compose", "--env-file", "/dev/null", "-f", str(preflight.ROOT / "docker-compose.prod.yml"), "config", "--format", "json"]
    result = subprocess.run(command, env={**os.environ, **deployment_env()}, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, "Production Compose validation failed (configuration withheld)"
    config = json.loads(result.stdout)
    for name in ("postgis", "redis", "osrm", "backend", "frontend"):
        assert not config["services"][name].get("ports"), f"Unexpected published port: {name}"
    assert {port["target"] for port in config["services"]["proxy"]["ports"]} == {80, 443}
    assert config["networks"]["internal"]["internal"] is True
    backend = config["services"]["backend"]
    assert backend["read_only"] is True
    assert backend["environment"]["CAMERA_VIEW_AI_ENABLED"] == "true"
    assert backend["environment"]["CAMERA_AI_MODE"] == "route_only"
    assert backend["environment"]["APP_ENV"] == "production"
    assert any(volume["target"] == "/app/storage" and volume["type"] == "volume" for volume in backend["volumes"])
    assert any(volume["target"] == "/app/data/osrm" and volume["read_only"] for volume in backend["volumes"])
    assert config["services"]["frontend"]["environment"]["NEXTAUTH_URL"].startswith("https://")


def test_backup_creates_private_archive_checksum_and_refuses_overwrite(monkeypatch, tmp_path):
    # Explicit unit-only subprocess mock: no database is contacted.
    env_file = tmp_path / "unit.env"
    env_file.write_text("")
    output = tmp_path / "backup.dump"
    monkeypatch.setattr(sys, "argv", ["backup", "--env-file", str(env_file), "--output", str(output)])
    calls = []

    def fake_run(command, **kwargs):
        calls.append(command)
        if "pg_dump" in command[-1]:
            kwargs["stdout"].write(b"unit-only-custom-archive")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(backup.subprocess, "run", fake_run)
    assert backup.main() == 0
    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    assert output.with_suffix(".dump.sha256").read_text().startswith(hashlib.sha256(output.read_bytes()).hexdigest())
    assert len(calls) == 2 and "pg_restore" in calls[1]
    with pytest.raises(SystemExit):
        backup.main()
    assert output.read_bytes() == b"unit-only-custom-archive"


@pytest.mark.parametrize("response,code,expected", [
    ({"ready": True, "osrm": "available"}, 0, 0),
    ({"ready": True, "osrm": "unavailable"}, 0, 1),
    ({}, 1, 1),
])
def test_optional_readiness_probe_fails_for_503_or_degraded_routing(monkeypatch, tmp_path, response, code, expected):
    # Explicit unit-only subprocess responses; no live services are contacted.
    env_file = tmp_path / "unit.env"
    env_file.write_text("\n".join(f"{key}={value}" for key, value in deployment_env().items()))
    monkeypatch.setattr(sys, "argv", ["preflight", "--env-file", str(env_file), "--check-running"])
    monkeypatch.setattr(preflight, "validate_artifacts", lambda env: [])
    def fake_run(command, **kwargs):
        if "exec" in command:
            return SimpleNamespace(returncode=code, stdout=json.dumps(response))
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(preflight.subprocess, "run", fake_run)
    assert preflight.main() == expected
