from __future__ import annotations

import asyncio
import math
import time
from dataclasses import dataclass
from urllib.parse import urlparse

from redis import Redis
from redis.asyncio import Redis as AsyncRedis

from core.config import settings


class GovernanceError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class RateLimitDecision:
    allowed: bool
    retry_after_ms: int


RATE_LIMIT_LUA = """
local key = KEYS[1]
local capacity = tonumber(ARGV[1])
local refill_rate = tonumber(ARGV[2])
local now_ms = tonumber(ARGV[3])
local requested = tonumber(ARGV[4])
local ttl_sec = tonumber(ARGV[5])

local data = redis.call('HMGET', key, 'tokens', 'ts')
local tokens = tonumber(data[1])
local ts = tonumber(data[2])
if tokens == nil then
  tokens = capacity
  ts = now_ms
end

local delta = math.max(0, now_ms - ts)
local refill = delta * (refill_rate / 1000.0)
tokens = math.min(capacity, tokens + refill)

local allowed = tokens >= requested
local retry_after = 0
if allowed then
  tokens = tokens - requested
else
  local needed = requested - tokens
  if refill_rate > 0 then
    retry_after = math.ceil((needed / refill_rate) * 1000)
  end
end

redis.call('HMSET', key, 'tokens', tokens, 'ts', now_ms)
redis.call('EXPIRE', key, ttl_sec)

return {allowed and 1 or 0, retry_after}
"""


def extract_domain(url: str) -> str | None:
    parsed = urlparse(url)
    host = parsed.hostname
    if not host:
        return None
    return host.lower()


def _rate_limit_key(domain: str) -> str:
    return f"rate:{domain}"


def _breaker_key(domain: str) -> str:
    return f"breaker:{domain}:failures"


def _breaker_open_key(domain: str) -> str:
    return f"breaker:{domain}:open"


def _llm_job_key(job_id: str) -> str:
    return f"llm:job:{job_id}"


def _llm_tenant_key(tenant: str) -> str:
    return f"llm:tenant:{tenant}"


def _rate_limit_ttl_seconds(capacity: int, refill_rate: float) -> int:
    if refill_rate <= 0:
        return 60
    return max(60, int(math.ceil(capacity / refill_rate * 2)))


async def acquire_rate_limit_async(redis: AsyncRedis, domain: str) -> RateLimitDecision:
    capacity = settings.rate_limit_capacity
    refill_rate = settings.rate_limit_refill_per_sec
    if capacity <= 0 or refill_rate <= 0:
        return RateLimitDecision(allowed=True, retry_after_ms=0)

    now_ms = int(time.time() * 1000)
    ttl_sec = _rate_limit_ttl_seconds(capacity, refill_rate)
    result = await redis.eval(
        RATE_LIMIT_LUA,
        1,
        _rate_limit_key(domain),
        capacity,
        refill_rate,
        now_ms,
        1,
        ttl_sec,
    )
    allowed = bool(int(result[0]))
    retry_after = int(result[1])
    return RateLimitDecision(allowed=allowed, retry_after_ms=retry_after)


def acquire_rate_limit_sync(redis: Redis, domain: str) -> RateLimitDecision:
    capacity = settings.rate_limit_capacity
    refill_rate = settings.rate_limit_refill_per_sec
    if capacity <= 0 or refill_rate <= 0:
        return RateLimitDecision(allowed=True, retry_after_ms=0)

    now_ms = int(time.time() * 1000)
    ttl_sec = _rate_limit_ttl_seconds(capacity, refill_rate)
    result = redis.eval(
        RATE_LIMIT_LUA,
        1,
        _rate_limit_key(domain),
        capacity,
        refill_rate,
        now_ms,
        1,
        ttl_sec,
    )
    allowed = bool(int(result[0]))
    retry_after = int(result[1])
    return RateLimitDecision(allowed=allowed, retry_after_ms=retry_after)


async def wait_for_rate_limit_async(redis: AsyncRedis, domain: str) -> bool:
    max_wait_ms = settings.rate_limit_max_wait_ms
    deadline = time.monotonic() + max_wait_ms / 1000 if max_wait_ms > 0 else None
    while True:
        decision = await acquire_rate_limit_async(redis, domain)
        if decision.allowed:
            return True
        if max_wait_ms <= 0:
            return False
        now = time.monotonic()
        if deadline is not None and now >= deadline:
            return False
        sleep_for = decision.retry_after_ms / 1000 if decision.retry_after_ms else 0.1
        if deadline is not None:
            sleep_for = min(sleep_for, max(0.0, deadline - now))
        await asyncio.sleep(max(0.05, sleep_for))


def wait_for_rate_limit_sync(redis: Redis, domain: str) -> bool:
    max_wait_ms = settings.rate_limit_max_wait_ms
    deadline = time.monotonic() + max_wait_ms / 1000 if max_wait_ms > 0 else None
    while True:
        decision = acquire_rate_limit_sync(redis, domain)
        if decision.allowed:
            return True
        if max_wait_ms <= 0:
            return False
        now = time.monotonic()
        if deadline is not None and now >= deadline:
            return False
        sleep_for = decision.retry_after_ms / 1000 if decision.retry_after_ms else 0.1
        if deadline is not None:
            sleep_for = min(sleep_for, max(0.0, deadline - now))
        time.sleep(max(0.05, sleep_for))


async def is_circuit_open_async(redis: AsyncRedis, domain: str) -> bool:
    return bool(await redis.exists(_breaker_open_key(domain)))


def is_circuit_open_sync(redis: Redis, domain: str) -> bool:
    return bool(redis.exists(_breaker_open_key(domain)))


async def record_failure_async(redis: AsyncRedis, domain: str, status: int | None) -> None:
    if status not in {403, 429}:
        return
    if settings.circuit_breaker_threshold <= 0:
        return
    key = _breaker_key(domain)
    count = await redis.incr(key)
    if count == 1:
        await redis.expire(key, settings.circuit_breaker_window_sec)
    if count >= settings.circuit_breaker_threshold:
        await redis.set(_breaker_open_key(domain), "1", ex=settings.circuit_breaker_cooldown_sec)


def record_failure_sync(redis: Redis, domain: str, status: int | None) -> None:
    if status not in {403, 429}:
        return
    if settings.circuit_breaker_threshold <= 0:
        return
    key = _breaker_key(domain)
    count = redis.incr(key)
    if count == 1:
        redis.expire(key, settings.circuit_breaker_window_sec)
    if count >= settings.circuit_breaker_threshold:
        redis.set(_breaker_open_key(domain), "1", ex=settings.circuit_breaker_cooldown_sec)


async def guard_request_async(redis: AsyncRedis, url: str) -> str | None:
    domain = extract_domain(url)
    if not domain:
        return None
    if await is_circuit_open_async(redis, domain):
        return "circuit_open"
    allowed = await wait_for_rate_limit_async(redis, domain)
    if not allowed:
        return "rate_limited"
    return None


def guard_request_sync(redis: Redis, url: str) -> str | None:
    domain = extract_domain(url)
    if not domain:
        return None
    if is_circuit_open_sync(redis, domain):
        return "circuit_open"
    allowed = wait_for_rate_limit_sync(redis, domain)
    if not allowed:
        return "rate_limited"
    return None


async def allow_llm_call_async(redis: AsyncRedis, job_id: str | None, tenant: str | None) -> bool:
    if settings.llm_job_max_calls > 0 and job_id:
        count = await redis.incr(_llm_job_key(job_id))
        if count == 1:
            await redis.expire(_llm_job_key(job_id), settings.llm_job_window_sec)
        if count > settings.llm_job_max_calls:
            return False

    if settings.llm_tenant_max_calls > 0:
        tenant_key = tenant or "default"
        count = await redis.incr(_llm_tenant_key(tenant_key))
        if count == 1:
            await redis.expire(_llm_tenant_key(tenant_key), settings.llm_tenant_window_sec)
        if count > settings.llm_tenant_max_calls:
            return False

    return True


def allow_llm_call_sync(redis: Redis, job_id: str | None, tenant: str | None) -> bool:
    if settings.llm_job_max_calls > 0 and job_id:
        count = redis.incr(_llm_job_key(job_id))
        if count == 1:
            redis.expire(_llm_job_key(job_id), settings.llm_job_window_sec)
        if count > settings.llm_job_max_calls:
            return False

    if settings.llm_tenant_max_calls > 0:
        tenant_key = tenant or "default"
        count = redis.incr(_llm_tenant_key(tenant_key))
        if count == 1:
            redis.expire(_llm_tenant_key(tenant_key), settings.llm_tenant_window_sec)
        if count > settings.llm_tenant_max_calls:
            return False

    return True
