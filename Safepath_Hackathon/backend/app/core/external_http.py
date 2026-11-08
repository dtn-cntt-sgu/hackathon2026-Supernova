"""Bounded retries for idempotent JSON GETs; failures never become synthetic data."""
import asyncio
from collections import OrderedDict
import random
import time
import httpx
from backend.app.core.observability import observe_operation

# Per-process negative cache is bounded and contains hashes, never credential URLs.
from hashlib import sha256
_COOLDOWNS = OrderedDict()


async def get_json_response(client, url, *, operation, budget_seconds=6.0):
    key = sha256(url.encode()).hexdigest()
    now = time.monotonic()
    if _COOLDOWNS.get(key, 0) > now:
        raise httpx.ConnectError('Source request is in outage cooldown')
    try:
        with observe_operation(operation) as metric:
            async with asyncio.timeout(budget_seconds):
                for attempt in range(2):
                    try:
                        response = await client.get(url)
                        # Authentication, permissions and quota failures are not retried.
                        if response.status_code in (401, 403, 429):
                            metric["outcome"] = "error"
                            _cooldown(key, 60)
                            return response
                        if response.status_code >= 500:
                            response.raise_for_status()
                        if response.status_code == 200:
                            payload = response.json()
                            if not isinstance(payload, dict):
                                raise ValueError('Source JSON must be an object')
                        if response.status_code >= 400:
                            metric["outcome"] = "error"
                        _COOLDOWNS.pop(key, None)
                        return response
                    except (httpx.TransportError, httpx.HTTPStatusError):
                        if attempt == 1:
                            raise
                        await asyncio.sleep(random.uniform(0.05, 0.2))
    except (httpx.HTTPError, TimeoutError, ValueError):
        _cooldown(key, 20)
        raise


def _cooldown(key, seconds):
    _COOLDOWNS[key] = time.monotonic() + seconds
    _COOLDOWNS.move_to_end(key)
    while len(_COOLDOWNS) > 128:
        _COOLDOWNS.popitem(last=False)
