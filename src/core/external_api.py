from __future__ import annotations

from redis.asyncio import Redis

from core.config import settings
from core.governance import extract_domain

_EXTERNAL_BUDGET_LUA = """
local calls_key = KEYS[1]
local cost_key = KEYS[2]
local max_calls = tonumber(ARGV[1])
local max_cost = tonumber(ARGV[2])
local cost = tonumber(ARGV[3])
local ttl = tonumber(ARGV[4])

if max_calls <= 0 and max_cost <= 0 then
  return {1, 0, 0}
end

local calls = tonumber(redis.call('GET', calls_key) or '0')
local total_cost = tonumber(redis.call('GET', cost_key) or '0')
local allow = 1

if max_calls > 0 and (calls + 1) > max_calls then
  allow = 0
end
if max_cost > 0 and (total_cost + cost) > max_cost then
  allow = 0
end

if allow == 1 then
  calls = calls + 1
  total_cost = total_cost + cost
  redis.call('SET', calls_key, calls, 'EX', ttl)
  if max_cost > 0 then
    redis.call('SET', cost_key, total_cost, 'EX', ttl)
  end
end

return {allow, calls, total_cost}
"""


def is_external_allowed(url: str | None) -> bool:
    if not settings.external_enabled:
        return False
    allowlist = _parse_allowlist(settings.external_allowlist_domains)
    if not allowlist:
        return False
    domain = extract_domain(url or "")
    if not domain:
        return False
    return any(_domain_matches(domain, entry) for entry in allowlist)


async def allow_external_call_async(
    redis: Redis,
    tenant: str | None,
    estimated_cost: float,
) -> bool:
    max_calls = settings.external_max_calls_per_tenant
    max_cost = settings.external_max_cost_per_tenant
    window_sec = settings.external_window_sec
    if max_calls <= 0 and max_cost <= 0:
        return True
    if window_sec <= 0:
        return False
    tenant_key = tenant or "default"
    calls_key = _external_tenant_calls_key(tenant_key)
    cost_key = _external_tenant_cost_key(tenant_key)
    result = await redis.eval(
        _EXTERNAL_BUDGET_LUA,
        2,
        calls_key,
        cost_key,
        max_calls,
        max_cost,
        max(estimated_cost, 0.0),
        window_sec,
    )
    return bool(int(result[0]))


async def is_external_circuit_open_async(redis: Redis, url: str | None) -> bool:
    domain = extract_domain(url or "")
    if not domain:
        return False
    return bool(await redis.exists(_breaker_open_key(domain)))


async def record_external_failure_async(redis: Redis, url: str | None) -> None:
    domain = extract_domain(url or "")
    if not domain:
        return
    if settings.external_breaker_threshold <= 0:
        return
    key = _breaker_key(domain)
    count = await redis.incr(key)
    if count == 1:
        await redis.expire(key, settings.external_breaker_window_sec)
    if count >= settings.external_breaker_threshold:
        await redis.set(
            _breaker_open_key(domain),
            "1",
            ex=settings.external_breaker_cooldown_sec,
        )


def _external_tenant_calls_key(tenant: str) -> str:
    return f"external:tenant:{tenant}:calls"


def _external_tenant_cost_key(tenant: str) -> str:
    return f"external:tenant:{tenant}:cost"


def _breaker_key(domain: str) -> str:
    return f"external:breaker:{domain}:failures"


def _breaker_open_key(domain: str) -> str:
    return f"external:breaker:{domain}:open"


def _parse_allowlist(value: str | None) -> list[str]:
    if not value:
        return []
    items = [item.strip().lower() for item in value.split(",")]
    return [item for item in items if item]


def _domain_matches(domain: str, entry: str) -> bool:
    if entry == "*":
        return True
    if domain == entry:
        return True
    return domain.endswith(f".{entry}")
