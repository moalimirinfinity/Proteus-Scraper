from __future__ import annotations

from redis.asyncio import Redis

PRIORITY_ORDER = ("high", "standard", "low")
ENGINE_TYPES = ("fast", "browser", "stealth")


def priority_key(priority: str) -> str:
    return f"priority:{priority}"


def engine_queue(engine: str) -> str:
    return f"engine:{engine}"


async def enqueue_priority(redis: Redis, priority: str, job_id: str) -> None:
    await redis.rpush(priority_key(priority), job_id)
