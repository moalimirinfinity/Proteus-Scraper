from __future__ import annotations

import base64
import hmac
import json
import time
from dataclasses import dataclass
from hashlib import sha256
from typing import Any

from fastapi import HTTPException, Request, status

from core.config import settings


@dataclass(frozen=True)
class AuthContext:
    token: str
    token_type: str
    source: str
    tenant: str | None
    subject: str | None
    claims: dict[str, Any]


class AuthError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def auth_required() -> bool:
    if settings.auth_enabled:
        return True
    return bool(settings.auth_jwt_secret or settings.auth_api_tokens)


def authenticate_request(request: Request) -> AuthContext:
    token, source = _extract_token(request)
    if not token:
        raise AuthError("missing_token")

    api_tokens = _parse_api_tokens(settings.auth_api_tokens)
    if token in api_tokens:
        tenant = api_tokens[token]
        return AuthContext(
            token=token,
            token_type="api_token",
            source=source,
            tenant=tenant,
            subject=None,
            claims={},
        )

    if settings.auth_jwt_secret:
        claims = _decode_jwt(token, settings.auth_jwt_secret)
        tenant = claims.get("tenant")
        subject = claims.get("sub")
        return AuthContext(
            token=token,
            token_type="jwt",
            source=source,
            tenant=tenant if isinstance(tenant, str) else None,
            subject=subject if isinstance(subject, str) else None,
            claims=claims,
        )

    raise AuthError("invalid_token")


def get_auth_context(request: Request) -> AuthContext | None:
    return getattr(request.state, "auth", None)


def resolve_tenant(request: Request, requested: str | None) -> str | None:
    ctx = get_auth_context(request)
    if ctx and ctx.tenant:
        if requested and requested != ctx.tenant:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="tenant_mismatch")
        return ctx.tenant
    return requested


def assert_tenant_access(request: Request, resource_tenant: str | None) -> None:
    ctx = get_auth_context(request)
    if ctx and ctx.tenant and resource_tenant != ctx.tenant:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="tenant_mismatch")


def require_auth(request: Request) -> AuthContext:
    ctx = get_auth_context(request)
    if ctx is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="unauthorized")
    return ctx


def _extract_token(request: Request) -> tuple[str | None, str]:
    auth_header = request.headers.get("authorization")
    if auth_header:
        parts = auth_header.split()
        if len(parts) == 2 and parts[0].lower() == "bearer":
            return parts[1], "bearer"
    api_key = request.headers.get("x-api-key")
    if api_key:
        return api_key, "api_key"
    cookie = request.cookies.get("proteus_token")
    if cookie:
        return cookie, "cookie"
    return None, "unknown"


def csrf_valid(request: Request) -> bool:
    header = request.headers.get("x-proteus-csrf")
    cookie = request.cookies.get("proteus_csrf")
    if not header or not cookie:
        return False
    return hmac.compare_digest(header, cookie)


def _parse_api_tokens(value: str | None) -> dict[str, str | None]:
    if not value:
        return {}
    tokens: dict[str, str | None] = {}
    for entry in value.split(","):
        entry = entry.strip()
        if not entry:
            continue
        if ":" in entry:
            token, tenant = entry.split(":", 1)
            tokens[token] = tenant or None
        else:
            tokens[entry] = None
    return tokens


def _decode_jwt(token: str, secret: str) -> dict[str, Any]:
    parts = token.split(".")
    if len(parts) != 3:
        raise AuthError("invalid_token")
    header = _b64url_json(parts[0])
    payload = _b64url_json(parts[1])
    signature = _b64url_decode(parts[2])

    if header.get("alg") != "HS256":
        raise AuthError("invalid_token")
    signing_input = f"{parts[0]}.{parts[1]}".encode("utf-8")
    expected = hmac.new(secret.encode("utf-8"), signing_input, sha256).digest()
    if not hmac.compare_digest(signature, expected):
        raise AuthError("invalid_token")

    now = int(time.time())
    leeway = max(settings.auth_jwt_leeway_sec, 0)
    exp = payload.get("exp")
    if isinstance(exp, (int, float)) and now > int(exp) + leeway:
        raise AuthError("token_expired")
    nbf = payload.get("nbf")
    if isinstance(nbf, (int, float)) and now + leeway < int(nbf):
        raise AuthError("token_not_yet_valid")

    issuer = settings.auth_jwt_issuer
    if issuer and payload.get("iss") != issuer:
        raise AuthError("invalid_token")
    audience = settings.auth_jwt_audience
    if audience and not _audience_matches(payload.get("aud"), audience):
        raise AuthError("invalid_token")
    return payload


def _audience_matches(value: object, audience: str) -> bool:
    if isinstance(value, str):
        return value == audience
    if isinstance(value, list):
        return any(entry == audience for entry in value)
    return False


def _b64url_json(segment: str) -> dict[str, Any]:
    raw = _b64url_decode(segment)
    try:
        payload = json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise AuthError("invalid_token") from exc
    if not isinstance(payload, dict):
        raise AuthError("invalid_token")
    return payload


def _b64url_decode(segment: str) -> bytes:
    padding = "=" * (-len(segment) % 4)
    try:
        return base64.urlsafe_b64decode(segment + padding)
    except (ValueError, TypeError) as exc:
        raise AuthError("invalid_token") from exc
