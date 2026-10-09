"""Password hashing and session tokens (standard library only)."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

ITERATIONS = 240_000
SESSION_DAYS = 30


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, ITERATIONS)
    return f"pbkdf2_sha256${ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, iterations, salt_hex, digest_hex = stored.split("$")
        digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), bytes.fromhex(salt_hex), int(iterations)
        )
    except ValueError:
        return False
    return hmac.compare_digest(digest.hex(), digest_hex)


# Checked against when an email has no account, so login takes the same time either way.
_DUMMY_HASH = hash_password("timing-equalizer")


def verify_password_or_dummy(password: str, stored: str | None) -> bool:
    if stored is None:
        verify_password(password, _DUMMY_HASH)
        return False
    return verify_password(password, stored)


def new_session() -> tuple[str, str]:
    """Return (token, expires_at ISO timestamp)."""
    expires = datetime.now(timezone.utc) + timedelta(days=SESSION_DAYS)
    return secrets.token_urlsafe(32), expires.isoformat(timespec="seconds")
