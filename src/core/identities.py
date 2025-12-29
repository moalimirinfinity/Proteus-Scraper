from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import select

from core.config import settings
from core.db import async_session
from core.db_sync import get_sync_session
from core.governance import extract_domain
from core.identity_crypto import IdentityCryptoError, decrypt_payload, encrypt_payload
from core.models import Identity
from core.proxy import resolve_proxy_async
from core.redis import get_redis

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class IdentityContext:
    id: UUID
    tenant: str
    fingerprint: dict[str, Any]
    cookies: list[dict[str, Any]]
    storage_state: dict[str, Any] | None


@dataclass(frozen=True)
class IdentityAssignment:
    identity: IdentityContext | None
    proxy_url: str | None
    domain: str | None


@dataclass(frozen=True)
class IdentityBindingRecord:
    identity_id: UUID
    proxy_url: str | None


def _tenant_key(tenant: str | None) -> str:
    return tenant or "default"


_BINDING_PREFIX = "identity:binding"
_IDENTITY_CANDIDATE_LIMIT = 50


def _binding_key(tenant: str, domain: str) -> str:
    return f"{_BINDING_PREFIX}:{tenant}:{domain}"


def _binding_payload(identity_id: UUID, proxy_url: str | None) -> str:
    payload = {"identity_id": str(identity_id), "proxy_url": proxy_url}
    return json.dumps(payload, ensure_ascii=True, separators=(",", ":"))


async def _load_binding_async(redis, tenant: str, domain: str) -> IdentityBindingRecord | None:
    raw = await redis.get(_binding_key(tenant, domain))
    if not raw:
        return None
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        await redis.delete(_binding_key(tenant, domain))
        return None
    identity_raw = payload.get("identity_id")
    if not identity_raw:
        await redis.delete(_binding_key(tenant, domain))
        return None
    try:
        identity_id = UUID(identity_raw)
    except (TypeError, ValueError):
        await redis.delete(_binding_key(tenant, domain))
        return None
    proxy_url = payload.get("proxy_url")
    return IdentityBindingRecord(identity_id=identity_id, proxy_url=proxy_url or None)


async def _store_binding_async(
    redis,
    tenant: str,
    domain: str,
    identity_id: UUID,
    proxy_url: str | None,
) -> None:
    ttl = settings.identity_binding_ttl_sec
    if ttl <= 0:
        return
    await redis.set(
        _binding_key(tenant, domain),
        _binding_payload(identity_id, proxy_url),
        ex=ttl,
    )


async def _refresh_binding_ttl_async(redis, tenant: str, domain: str) -> None:
    ttl = settings.identity_binding_ttl_sec
    if ttl <= 0:
        return
    await redis.expire(_binding_key(tenant, domain), ttl)


async def _clear_binding_async(
    redis,
    tenant: str,
    domain: str,
    identity_id: UUID | None,
) -> None:
    key = _binding_key(tenant, domain)
    if identity_id is None:
        await redis.delete(key)
        return
    raw = await redis.get(key)
    if not raw:
        return
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        await redis.delete(key)
        return
    if payload.get("identity_id") == str(identity_id):
        await redis.delete(key)


def _load_cookies(identity: Identity) -> list[dict[str, Any]]:
    if not identity.cookies_encrypted:
        return []
    try:
        payload = decrypt_payload(identity.cookies_encrypted)
        if isinstance(payload, list):
            return payload
        return []
    except IdentityCryptoError as exc:
        logger.warning("identity_cookie_decrypt_failed: %s", exc.code)
        return []


def _load_storage_state(identity: Identity) -> dict[str, Any] | None:
    if not identity.storage_state_encrypted:
        return None
    try:
        payload = decrypt_payload(identity.storage_state_encrypted)
        return payload if isinstance(payload, dict) else None
    except IdentityCryptoError as exc:
        logger.warning("identity_storage_state_decrypt_failed: %s", exc.code)
        return None


def _fingerprint_payload(identity: Identity) -> dict[str, Any]:
    payload = identity.fingerprint or {}
    return payload if isinstance(payload, dict) else {}


def _context_from_identity(identity: Identity) -> IdentityContext:
    return IdentityContext(
        id=identity.id,
        tenant=identity.tenant,
        fingerprint=_fingerprint_payload(identity),
        cookies=_load_cookies(identity),
        storage_state=_load_storage_state(identity),
    )


def _decayed_failure_count(identity: Identity, now: datetime) -> float:
    failures = float(identity.failure_count or 0)
    if failures <= 0:
        return 0.0
    last_failed = identity.last_failed_at
    decay_per_hour = settings.identity_failure_decay_per_hour
    if not last_failed or decay_per_hour <= 0:
        return failures
    elapsed = (now - last_failed).total_seconds()
    hours = max(elapsed / 3600, 0.0)
    return max(0.0, failures - (decay_per_hour * hours))


def _identity_sort_key(identity: Identity, now: datetime) -> tuple:
    min_dt = datetime.min.replace(tzinfo=timezone.utc)
    last_used = identity.last_used_at or min_dt
    created_at = identity.created_at or min_dt
    return (
        _decayed_failure_count(identity, now),
        last_used,
        identity.use_count,
        created_at,
        str(identity.id),
    )


async def acquire_identity_async(tenant: str | None) -> IdentityContext | None:
    tenant_key = _tenant_key(tenant)
    async with async_session() as session:
        result = await session.execute(
            select(Identity)
            .where(Identity.tenant == tenant_key)
            .where(Identity.active.is_(True))
            .order_by(
                Identity.failure_count.asc(),
                Identity.last_used_at.asc().nullsfirst(),
                Identity.use_count.asc(),
            )
            .limit(_IDENTITY_CANDIDATE_LIMIT)
        )
        identities = result.scalars().all()
        if not identities:
            return None
        now = datetime.now(timezone.utc)
        identity = min(identities, key=lambda item: _identity_sort_key(item, now))
        identity.use_count += 1
        identity.last_used_at = now
        await session.commit()
        return _context_from_identity(identity)


def acquire_identity_sync(tenant: str | None) -> IdentityContext | None:
    tenant_key = _tenant_key(tenant)
    with get_sync_session() as session:
        result = session.execute(
            select(Identity)
            .where(Identity.tenant == tenant_key)
            .where(Identity.active.is_(True))
            .order_by(
                Identity.failure_count.asc(),
                Identity.last_used_at.asc().nullsfirst(),
                Identity.use_count.asc(),
            )
            .limit(_IDENTITY_CANDIDATE_LIMIT)
        )
        identities = result.scalars().all()
        if not identities:
            return None
        now = datetime.now(timezone.utc)
        identity = min(identities, key=lambda item: _identity_sort_key(item, now))
        identity.use_count += 1
        identity.last_used_at = now
        return _context_from_identity(identity)


async def _acquire_identity_by_id_async(identity_id: UUID) -> IdentityContext | None:
    async with async_session() as session:
        result = await session.execute(select(Identity).where(Identity.id == identity_id))
        identity = result.scalar_one_or_none()
        if identity is None or not identity.active:
            return None
        now = datetime.now(timezone.utc)
        identity.use_count += 1
        identity.last_used_at = now
        await session.commit()
        return _context_from_identity(identity)


async def acquire_identity_for_url_async(url: str, tenant: str | None) -> IdentityAssignment:
    tenant_key = _tenant_key(tenant)
    domain = extract_domain(url)
    proxy_decision = await resolve_proxy_async(url)
    proxy_url = proxy_decision.proxy_url
    if not domain or settings.identity_binding_ttl_sec <= 0:
        identity = await acquire_identity_async(tenant_key)
        return IdentityAssignment(identity=identity, proxy_url=proxy_url, domain=domain)

    redis = get_redis()
    binding = await _load_binding_async(redis, tenant_key, domain)
    if binding:
        identity = await _acquire_identity_by_id_async(binding.identity_id)
        if identity:
            if binding.proxy_url:
                proxy_url = binding.proxy_url
            elif proxy_url:
                await _store_binding_async(redis, tenant_key, domain, binding.identity_id, proxy_url)
            await _refresh_binding_ttl_async(redis, tenant_key, domain)
            return IdentityAssignment(identity=identity, proxy_url=proxy_url, domain=domain)
        await _clear_binding_async(redis, tenant_key, domain, binding.identity_id)

    identity = await acquire_identity_async(tenant_key)
    if identity:
        await _store_binding_async(redis, tenant_key, domain, identity.id, proxy_url)
    return IdentityAssignment(identity=identity, proxy_url=proxy_url, domain=domain)


async def release_identity_binding_async(
    url: str | None,
    tenant: str | None,
    identity_id: UUID | None = None,
) -> None:
    domain = extract_domain(url) if url else None
    if not domain or settings.identity_binding_ttl_sec <= 0:
        return
    redis = get_redis()
    tenant_key = _tenant_key(tenant)
    await _clear_binding_async(redis, tenant_key, domain, identity_id)


async def store_identity_cookies_async(identity_id: UUID, cookies: list[dict[str, Any]]) -> None:
    try:
        encrypted = encrypt_payload(cookies)
    except IdentityCryptoError as exc:
        logger.warning("identity_cookie_encrypt_failed: %s", exc.code)
        return
    async with async_session() as session:
        result = await session.execute(select(Identity).where(Identity.id == identity_id))
        identity = result.scalar_one_or_none()
        if identity is None:
            return
        identity.cookies_encrypted = encrypted
        identity.updated_at = datetime.now(timezone.utc)
        await session.commit()


def store_identity_cookies_sync(identity_id: UUID, cookies: list[dict[str, Any]]) -> None:
    try:
        encrypted = encrypt_payload(cookies)
    except IdentityCryptoError as exc:
        logger.warning("identity_cookie_encrypt_failed: %s", exc.code)
        return
    with get_sync_session() as session:
        identity = session.execute(select(Identity).where(Identity.id == identity_id)).scalar_one_or_none()
        if identity is None:
            return
        identity.cookies_encrypted = encrypted
        identity.updated_at = datetime.now(timezone.utc)


async def store_identity_storage_state_async(
    identity_id: UUID,
    storage_state: dict[str, Any],
) -> None:
    try:
        encrypted = encrypt_payload(storage_state)
    except IdentityCryptoError as exc:
        logger.warning("identity_storage_state_encrypt_failed: %s", exc.code)
        return
    async with async_session() as session:
        result = await session.execute(select(Identity).where(Identity.id == identity_id))
        identity = result.scalar_one_or_none()
        if identity is None:
            return
        identity.storage_state_encrypted = encrypted
        identity.updated_at = datetime.now(timezone.utc)
        await session.commit()


def store_identity_storage_state_sync(
    identity_id: UUID,
    storage_state: dict[str, Any],
) -> None:
    try:
        encrypted = encrypt_payload(storage_state)
    except IdentityCryptoError as exc:
        logger.warning("identity_storage_state_encrypt_failed: %s", exc.code)
        return
    with get_sync_session() as session:
        identity = session.execute(select(Identity).where(Identity.id == identity_id)).scalar_one_or_none()
        if identity is None:
            return
        identity.storage_state_encrypted = encrypted
        identity.updated_at = datetime.now(timezone.utc)


async def record_identity_failure_async(
    identity_id: UUID,
    reason: str | None,
    *,
    url: str | None = None,
) -> None:
    if not _is_ban_reason(reason):
        return
    tenant_key: str | None = None
    async with async_session() as session:
        result = await session.execute(select(Identity).where(Identity.id == identity_id))
        identity = result.scalar_one_or_none()
        if identity is None:
            return
        tenant_key = identity.tenant
        identity.failure_count += 1
        identity.last_failed_at = datetime.now(timezone.utc)
        if identity.failure_count >= settings.identity_failure_threshold > 0:
            identity.active = False
        await session.commit()
    await release_identity_binding_async(url, tenant_key, identity_id)


def record_identity_failure_sync(
    identity_id: UUID,
    reason: str | None,
    *,
    url: str | None = None,
) -> None:
    if not _is_ban_reason(reason):
        return
    tenant_key: str | None = None
    with get_sync_session() as session:
        identity = session.execute(select(Identity).where(Identity.id == identity_id)).scalar_one_or_none()
        if identity is None:
            return
        tenant_key = identity.tenant
        identity.failure_count += 1
        identity.last_failed_at = datetime.now(timezone.utc)
        if identity.failure_count >= settings.identity_failure_threshold > 0:
            identity.active = False
    if url:
        try:
            from core.redis_sync import get_sync_redis
        except ImportError:
            return
        domain = extract_domain(url)
        if not domain or settings.identity_binding_ttl_sec <= 0:
            return
        redis = get_sync_redis()
        key = _binding_key(_tenant_key(tenant_key), domain)
        if identity_id is None:
            redis.delete(key)
            return
        raw = redis.get(key)
        if not raw:
            return
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            redis.delete(key)
            return
        if payload.get("identity_id") == str(identity_id):
            redis.delete(key)


def _is_ban_reason(reason: str | None) -> bool:
    if not reason:
        return False
    if reason in {"http_403", "http_429"}:
        return True
    if reason.startswith("blocked_"):
        return True
    return reason in {"captcha_detected", "challenge_script"}
