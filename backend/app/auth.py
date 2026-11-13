from __future__ import annotations

import hashlib
import os

SESSION_COOKIE = "meridian_session"
SESSION_TTL_SECONDS = 60 * 60 * 24 * 7


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def secure_cookie() -> bool:
    return (
        os.getenv("APP_ENV", "").lower() == "production"
        or os.getenv("RAILWAY_ENVIRONMENT_NAME", "").lower() == "production"
        or bool(os.getenv("RAILWAY_PRIVATE_DOMAIN"))
    )
