from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

from app.core.config import settings

_hasher = PasswordHasher()

ALGORITHM = "HS256"
ACCESS = "access"
REFRESH = "refresh"


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, InvalidHashError, Exception):
        return False


def needs_rehash(password_hash: str) -> bool:
    try:
        return _hasher.check_needs_rehash(password_hash)
    except Exception:
        return False


def _encode(subject: str, token_type: str, expires: timedelta, token_version: int) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": str(subject),
        "type": token_type,
        "ver": token_version,
        "iat": int(now.timestamp()),
        "exp": int((now + expires).timestamp()),
        "jti": secrets.token_urlsafe(12),
    }
    return jwt.encode(payload, settings.secret_key, algorithm=ALGORITHM)


def create_access_token(user_id: int, token_version: int = 0) -> str:
    return _encode(user_id, ACCESS, timedelta(minutes=settings.access_token_minutes), token_version)


def create_refresh_token(user_id: int, token_version: int = 0) -> str:
    return _encode(user_id, REFRESH, timedelta(days=settings.refresh_token_days), token_version)


def decode_token(token: str, expected_type: str) -> dict:
    """Raises jwt exceptions on anything malformed, expired or of the wrong type."""
    payload = jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])
    if payload.get("type") != expected_type:
        raise jwt.InvalidTokenError(f"expected a {expected_type} token")
    return payload


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
