from __future__ import annotations

from redis import Redis

from core.config import settings

_redis: Redis | None = None


def get_sync_redis() -> Redis:
    global _redis
    if _redis is None:
        _redis = Redis.from_url(settings.redis_url, decode_responses=True)
    return _redis
