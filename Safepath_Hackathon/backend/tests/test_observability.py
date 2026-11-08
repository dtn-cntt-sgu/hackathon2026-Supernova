import json
import logging
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend.app.core.observability import (
    install_observability, metrics_response, observe_operation, RedactedJSONFormatter,
)


def test_metrics_use_route_template_and_count_errors():
    app = FastAPI()
    install_observability(app)

    @app.get('/camera/{camera_id}')
    def camera(camera_id: str):
        return {'ok': True}

    client = TestClient(app)
    client.get('/camera/private-camera-id?token=private-token')
    client.get('/random-private-path')
    with pytest.raises(RuntimeError), observe_operation('ai'):
        raise RuntimeError('model unavailable')
    body = metrics_response().body.decode()
    assert 'route="/camera/{camera_id}"' in body
    assert 'route="unmatched"' in body
    assert 'name="ai",outcome="error"' in body
    assert 'private-camera-id' not in body
    assert 'private-token' not in body
    assert 'random-private-path' not in body
    with pytest.raises(ValueError):
        with observe_operation('arbitrary-private-key'):
            pass


def test_json_logging_redacts_credentials():
    record = logging.LogRecord('test', logging.ERROR, '', 1,
        'URL https://user:password@example.org/a?apikey=supersecret bearer abc.def token=secret', (), None)
    output = RedactedJSONFormatter().format(record)
    data = json.loads(output)
    assert data['level'] == 'ERROR'
    for value in ('user:password', 'supersecret', 'abc.def', 'token=secret'):
        assert value not in output


def test_health_gauges_are_bounded_and_unknown_is_not_zero():
    from backend.app.core.observability import set_gauge
    set_gauge('postgres_up', True)
    set_gauge('camera_observation_age_seconds', float('nan'))
    body = metrics_response().body.decode()
    assert 'safepath_postgres_up 1.0' in body
    assert 'safepath_camera_observation_age_seconds NaN' in body
    with pytest.raises(ValueError):
        set_gauge('private-user-identity', 1)
