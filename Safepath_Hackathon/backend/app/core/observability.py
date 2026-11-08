"""Bounded, process-local Prometheus metrics without request identifiers or URL labels.

Run one ASGI worker per container and scrape each replica separately. Counters reset
on restart; use Prometheus rate()/histogram_quantile() over the exported buckets.
"""
from collections import defaultdict
from contextlib import contextmanager
import json
import logging
import math
import re
from threading import Lock
from time import perf_counter

from starlette.responses import Response

_LOCK = Lock()
_REQUESTS = defaultdict(int)
_GAUGES = {}
_GAUGE_NAMES = frozenset({"postgres_up", "redis_up", "osrm_up", "camera_observation_age_seconds", "route_last_traffic_coverage_ratio"})
_DURATIONS = defaultdict(lambda: [0, 0.0, [0] * 8])
_BUCKETS = (0.01, 0.05, 0.1, 0.5, 1, 5, 10, float("inf"))
_OPERATIONS = frozenset({"osrm", "weather", "hydrology", "camera", "ai", "traffic"})


def _observe(key, elapsed):
    with _LOCK:
        value = _DURATIONS[key]
        value[0] += 1
        value[1] += elapsed
        for index, bound in enumerate(_BUCKETS):
            if elapsed <= bound:
                value[2][index] += 1


@contextmanager
def observe_operation(operation):
    """Time a fixed operation name; exceptions are counted and re-raised."""
    if operation not in _OPERATIONS:
        raise ValueError("Unsupported operation metric")
    start = perf_counter()
    result = {"outcome": "success"}
    try:
        yield result
    except BaseException:
        result["outcome"] = "error"
        raise
    finally:
        _observe(("operation", operation, result["outcome"]), perf_counter() - start)


class RequestMetrics:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        start, status = perf_counter(), 500

        async def tracked_send(message):
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, tracked_send)
        finally:
            # Route templates prevent camera IDs, email addresses and arbitrary paths
            # from creating unbounded series or disclosing personal data.
            route = getattr(scope.get("route"), "path", "unmatched")
            method = scope.get("method", "OTHER")
            if method not in {"GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"}:
                method = "OTHER"
            with _LOCK:
                _REQUESTS[(route, method, str(status))] += 1
            elapsed = perf_counter() - start
            _observe(("request", route, method), elapsed)
            logging.getLogger("safepath.request").info("request completed", extra={
                "request_id": scope.get("state", {}).get("request_id"),
                "route": route, "method": method, "status": status,
                "duration_ms": round(elapsed * 1000, 2),
            })


def install_observability(app):
    app.add_middleware(RequestMetrics)


def set_gauge(name, value):
    if name not in _GAUGE_NAMES:
        raise ValueError("Unsupported gauge")
    with _LOCK:
        _GAUGES[name] = float(value)


def metrics_response():
    lines = ["# TYPE safepath_http_requests_total counter", "# TYPE safepath_duration_seconds histogram"]
    with _LOCK:
        for name, value in sorted(_GAUGES.items()):
            lines.extend([f"# TYPE safepath_{name} gauge", f"safepath_{name} {'NaN' if math.isnan(value) else value}"])
        for (route, method, status), count in sorted(_REQUESTS.items()):
            labels = f'route={json.dumps(route)},method={json.dumps(method)},status="{status}"'
            lines.append(f"safepath_http_requests_total{{{labels}}} {count}")
        for (kind, name, outcome), (count, total, buckets) in sorted(_DURATIONS.items()):
            labels = f'kind="{kind}",name={json.dumps(name)},outcome={json.dumps(outcome)}'
            for bound, value in zip(_BUCKETS, buckets):
                label = "+Inf" if bound == float("inf") else str(bound)
                lines.append(f'safepath_duration_seconds_bucket{{{labels},le="{label}"}} {value}')
            lines.extend([f"safepath_duration_seconds_count{{{labels}}} {count}", f"safepath_duration_seconds_sum{{{labels}}} {total}"])
    return Response("\n".join(lines) + "\n", media_type="text/plain; version=0.0.4", headers={"Cache-Control": "no-store"})


class RedactedJSONFormatter(logging.Formatter):
    """Keep messages useful while removing URLs' credentials/query and token fields."""
    def format(self, record):
        message = record.getMessage()
        message = re.sub(r"(https?://)[^\s/@]+:[^\s/@]+@", r"\1[redacted]@", message)
        message = re.sub(r"(https?://[^\s?#]+)[?#][^\s]*", r"\1?[redacted]", message)
        message = re.sub(r"(?i)(bearer\s+)[\w.\-]+", r"\1[redacted]", message)
        message = re.sub(r"(?i)((?:password|secret|token|api_key|apikey)\s*[=:]\s*)[^\s,;]+", r"\1[redacted]", message)
        data = {"timestamp": self.formatTime(record), "level": record.levelname, "logger": record.name, "message": message}
        for key in ("request_id", "route", "method", "status", "duration_ms"):
            if hasattr(record, key):
                data[key] = getattr(record, key)
        return json.dumps(data, ensure_ascii=False)


def configure_json_logging():
    formatter = RedactedJSONFormatter()
    for handler in logging.getLogger().handlers:
        handler.setFormatter(formatter)
