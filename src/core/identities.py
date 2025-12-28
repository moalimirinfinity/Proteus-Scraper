from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import select
from core.config import settings
from core.db import async_session
from core.db_sync import get_sync_session
from core.identity_crypto import IdentityCryptoError, decrypt_payload, encrypt_payload
from core.models import Identity

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class IdentityContext:
    id: UUID
    tenant: str
    fingerprint: dict[str, Any]
    cookies: list[dict[str, Any]]


def _tenant_key(tenant: str | None) -> str:
    return tenant or "default"


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


def _fingerprint_payload(identity: Identity) -> dict[str, Any]:
    payload = identity.fingerprint or {}
    return payload if isinstance(payload, dict) else {}


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
            .limit(1)
        )
        identity = result.scalar_one_or_none()
        if identity is None:
            return None
        identity.use_count += 1
        identity.last_used_at = datetime.now(timezone.utc)
        await session.commit()
        return IdentityContext(
            id=identity.id,
            tenant=identity.tenant,
            fingerprint=_fingerprint_payload(identity),
            cookies=_load_cookies(identity),
        )


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
            .limit(1)
        )
        identity = result.scalar_one_or_none()
        if identity is None:
            return None
        identity.use_count += 1
        identity.last_used_at = datetime.now(timezone.utc)
        return IdentityContext(
            id=identity.id,
            tenant=identity.tenant,
            fingerprint=_fingerprint_payload(identity),
            cookies=_load_cookies(identity),
        )


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


async def record_identity_failure_async(identity_id: UUID, reason: str | None) -> None:
    if not _is_ban_reason(reason):
        return
    async with async_session() as session:
        result = await session.execute(select(Identity).where(Identity.id == identity_id))
        identity = result.scalar_one_or_none()
        if identity is None:
            return
        identity.failure_count += 1
        identity.last_failed_at = datetime.now(timezone.utc)
        if identity.failure_count >= settings.identity_failure_threshold > 0:
            identity.active = False
        await session.commit()


def record_identity_failure_sync(identity_id: UUID, reason: str | None) -> None:
    if not _is_ban_reason(reason):
        return
    with get_sync_session() as session:
        identity = session.execute(select(Identity).where(Identity.id == identity_id)).scalar_one_or_none()
        if identity is None:
            return
        identity.failure_count += 1
        identity.last_failed_at = datetime.now(timezone.utc)
        if identity.failure_count >= settings.identity_failure_threshold > 0:
            identity.active = False


def _is_ban_reason(reason: str | None) -> bool:
    if not reason:
        return False
    return reason in {"http_403", "http_429"}
