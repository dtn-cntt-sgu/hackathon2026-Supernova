"""Deployment guardrails; never start Docker or modify databases."""
import importlib.util
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('deploy_staging', ROOT / 'scripts/production/deploy_staging.py')
deploy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(deploy)


def environment():
    return {'IMAGE_REPOSITORY': 'owner/safepath', 'EXPECTED_SHA': 'a' * 40,
            'BACKEND_IMAGE': 'ghcr.io/owner/safepath/backend@sha256:' + 'b' * 64,
            'FRONTEND_IMAGE': 'ghcr.io/owner/safepath/frontend@sha256:' + 'c' * 64}


def test_only_immutable_approved_repository_images():
    deploy.validate_images(environment())
    for key, value in [('BACKEND_IMAGE', 'ghcr.io/owner/safepath/backend:latest'),
                       ('FRONTEND_IMAGE', 'ghcr.io/attacker/safepath/frontend@sha256:' + 'c' * 64),
                       ('EXPECTED_SHA', 'main'), ('IMAGE_REPOSITORY', 'owner/repo; command')]:
        env = environment()
        env[key] = value
        with pytest.raises(ValueError):
            deploy.validate_images(env)


def test_publication_has_no_independent_bypass_and_scans_before_push():
    ci = (ROOT / '.github/workflows/ci.yml').read_text()
    assert 'needs: [security-audit, backend-test, frontend-check]' in ci
    assert ci.index('Scan backend image') < ci.index('Publish the exact scanned images')
    assert ci.index('Scan frontend image') < ci.index('Publish the exact scanned images')
    assert 'continue-on-error: true' not in ci
    assert 'pip-audit -r requirements.txt --strict' in ci
    assert not (ROOT / '.github/workflows/docker-image.yml').exists()
    cd = (ROOT / '.github/workflows/cd.yml').read_text()
    assert 'environment: staging' in cd and 'workflow_dispatch:' in cd
    assert 'push: true' not in cd and 'production' not in cd.split('jobs:')[1].split('steps:')[0].replace('# Dedicated runner; never use a production host.', '')


def test_development_api_mounts_same_graph_directory_readonly():
    from pathlib import Path
    compose = Path('docker-compose.yml').read_text()
    backend = compose.split('  backend:', 1)[1].split('  frontend:', 1)[0]
    osrm = compose.split('  osrm:', 1)[1].split('  osm2pgsql:', 1)[0]
    assert '- ./data/osrm:/app/data/osrm:ro' in backend
    assert '- ./data/osrm:/data:ro' in osrm
