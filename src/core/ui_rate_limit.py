from __future__ import annotations

from redis.asyncio import Redis


async def allow_ui_action_async(
    redis: Redis,
    scope: str,
    actor: str,
    limit: int,
    window_sec: int,
) -> bool:
    if limit <= 0 or window_sec <= 0:
        return True
    key = f"ui:rate:{scope}:{actor}"
    count = await redis.incr(key)
    if count == 1:
        await redis.expire(key, window_sec)
    return count <= limit
