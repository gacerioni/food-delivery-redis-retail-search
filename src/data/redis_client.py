"""Single shared Redis client (binary-safe for VECTOR bytes)."""

from __future__ import annotations

import redis

from core.config import get_settings

_client: redis.Redis | None = None


def get_redis() -> redis.Redis:
    global _client
    if _client is None:
        _client = redis.from_url(
            get_settings().redis_url,
            decode_responses=False,
        )
    return _client


def reset_redis() -> None:
    global _client
    if _client is not None:
        _client.close()
    _client = None
