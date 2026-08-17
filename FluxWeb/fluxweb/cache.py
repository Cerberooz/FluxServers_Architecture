"""Best-effort Redis cache for latency-sensitive, read-only data.

Redis is only an optimisation: a cache outage must never stop a page loading.
Database writes and Panel writes never go through this layer.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from flask import Flask
from redis import Redis
from redis.exceptions import RedisError

log = logging.getLogger(__name__)


class RuntimeCache:
    def __init__(self, url: str | None) -> None:
        self._client: Redis | None = Redis.from_url(url, decode_responses=True) if url else None

    def get_json(self, key: str) -> Any | None:
        if self._client is None:
            return None
        try:
            raw = self._client.get(key)
            return json.loads(raw) if raw else None
        except (RedisError, ValueError, TypeError):
            log.debug("Runtime cache read failed", exc_info=True)
            return None

    def set_json(self, key: str, value: Any, ttl: int) -> None:
        if self._client is None or ttl <= 0:
            return
        try:
            self._client.setex(key, ttl, json.dumps(value, separators=(",", ":")))
        except (RedisError, TypeError, ValueError):
            log.debug("Runtime cache write failed", exc_info=True)


def init_runtime_cache(app: Flask) -> None:
    config = app.extensions["flux_config"]
    app.extensions["runtime_cache"] = RuntimeCache(config.redis_url)
