from __future__ import annotations

import json
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

from core.config import settings

_fernet: Fernet | None = None


class IdentityCryptoError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _get_fernet() -> Fernet:
    global _fernet
    if _fernet is None:
        if not settings.identity_encryption_key:
            raise IdentityCryptoError("identity_key_missing")
        _fernet = Fernet(settings.identity_encryption_key.encode("utf-8"))
    return _fernet


def encrypt_payload(payload: Any) -> str:
    fernet = _get_fernet()
    data = json.dumps(payload, ensure_ascii=True, separators=(",", ":")).encode("utf-8")
    return fernet.encrypt(data).decode("utf-8")


def decrypt_payload(token: str) -> Any:
    fernet = _get_fernet()
    try:
        data = fernet.decrypt(token.encode("utf-8"))
    except InvalidToken as exc:
        raise IdentityCryptoError("identity_key_invalid") from exc
    return json.loads(data.decode("utf-8"))
