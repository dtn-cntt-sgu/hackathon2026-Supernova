"""CLI packaging/path checks and clearly mocked unit checks; no runtime datasets changed."""

import json
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from scripts import assign_camera_districts_postgis as districts
from scripts import import_historical_floods as floods
from scripts import import_vdms_cameras as cameras


@pytest.mark.parametrize("module", [
    "scripts.import_historical_floods",
    "scripts.import_vdms_cameras",
    "scripts.assign_camera_districts_postgis",
])
def test_installed_cli_imports_from_another_directory(module, tmp_path):
    result = subprocess.run([sys.executable, "-m", module, "--help"], cwd=tmp_path,
                            capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
    assert "usage:" in result.stdout


def test_default_dataset_paths_do_not_depend_on_cwd(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    assert floods.DATA_PATH.is_absolute() and floods.DATA_PATH.is_file()
    assert cameras.DEFAULT_DATA_PATH.is_absolute() and cameras.DEFAULT_DATA_PATH.is_file()
    assert (districts.ROOT / "data/boundaries/hcmc_district_boundaries.geojson").is_file()


def test_historical_import_upserts_without_clearing_other_records(monkeypatch):
    # Unit-only mock: the real importer must use one rollback-capable transaction.
    session = MagicMock(spec=["merge", "flush", "execute"])
    session.execute.return_value = SimpleNamespace(rowcount=0, fetchone=lambda: (0, 0, 0))
    transaction = MagicMock()
    transaction.__enter__.return_value = session
    factory = MagicMock()
    factory.begin.return_value = transaction
    monkeypatch.setattr(floods, "SessionLocal", factory)
    floods.run_import()
    expected = json.loads(floods.DATA_PATH.read_text())
    assert session.merge.call_count == len(expected)
    assert {call.args[0].id for call in session.merge.call_args_list} == {
        record["flood_point_id"] for record in expected
    }
    assert factory.begin.call_count == 1


def test_camera_reimport_preserves_existing_permissions(monkeypatch):
    # Unit-only mock: snapshot imports are not authorization records.
    report = cameras.parse_vdms_snapshot_file(str(cameras.DEFAULT_DATA_PATH))
    monkeypatch.setattr(cameras, "parse_vdms_snapshot_file", lambda path: report)
    session = MagicMock()
    factory = MagicMock()
    factory.return_value.__enter__.return_value = session
    monkeypatch.setattr(cameras, "SessionLocal", factory)
    cameras.import_vdms_cameras()
    statement, params = session.execute.call_args_list[0].args
    sql = str(statement)
    assert "permitted_use" in sql.split("ON CONFLICT")[0]
    assert params["permitted_use"] == "PERMISSION_UNVERIFIED"
    assert "permitted_use =" not in sql.split("ON CONFLICT")[1]
