from __future__ import annotations

import hashlib
import hmac
import os
import secrets
from datetime import timedelta
from email.utils import parseaddr

import httpx

SESSION_COOKIE = "meridian_session"
SESSION_TTL_SECONDS = 60 * 60 * 24 * 7
LOGIN_CODE_TTL_MINUTES = 10


def auth_secret() -> bytes:
    secret = os.getenv("MERIDIAN_AUTH_SECRET", "")
    if len(secret) < 32:
        raise RuntimeError("MERIDIAN_AUTH_SECRET must contain at least 32 characters.")
    return secret.encode("utf-8")


def code_digest(email: str, code: str, salt: str) -> str:
    message = f"{email.lower()}:{salt}:{code}".encode("utf-8")
    return hmac.new(auth_secret(), message, hashlib.sha256).hexdigest()


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def is_admin_email(email: str) -> bool:
    configured = os.getenv("MERIDIAN_ADMIN_EMAILS", "")
    admins = {item.strip().lower() for item in configured.replace(";", ",").split(",") if item.strip()}
    return email.strip().lower() in admins


def secure_cookie() -> bool:
    return (
        os.getenv("APP_ENV", "").lower() == "production"
        or os.getenv("RAILWAY_ENVIRONMENT_NAME", "").lower() == "production"
        or bool(os.getenv("RAILWAY_PRIVATE_DOMAIN"))
    )


async def deliver_login_code(email: str, code: str) -> None:
    api_key = os.getenv("RESEND_API_KEY", "").strip()
    sender = os.getenv("MERIDIAN_FROM_EMAIL", "").strip()
    if not api_key or not sender:
        raise RuntimeError("Email delivery is not configured.")

    _, sender_address = parseaddr(sender)
    if not sender_address or "@" not in sender_address:
        raise RuntimeError("MERIDIAN_FROM_EMAIL must be a valid verified sender address.")

    text_body = (
        f"Your MERIDIAN sign-in code is {code}.\n\n"
        f"It expires in {LOGIN_CODE_TTL_MINUTES} minutes. "
        "Do not share this code. MERIDIAN will never ask you to sign a transaction to log in."
    )
    html_body = (
        "<div style='font-family:Arial,sans-serif;max-width:480px;margin:auto;color:#1d2a38'>"
        "<h2>Sign in to MERIDIAN</h2>"
        "<p>Use this one-time code to access your private research workspace:</p>"
        f"<p style='font-size:32px;font-weight:700;letter-spacing:8px'>{code}</p>"
        f"<p>This code expires in {LOGIN_CODE_TTL_MINUTES} minutes.</p>"
        "<p>Do not share this code. Signing in never requires a wallet connection or transaction.</p>"
        "</div>"
    )
    timeout = httpx.Timeout(15.0, connect=5.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "from": sender,
                "to": [email],
                "subject": "Your MERIDIAN sign-in code",
                "text": text_body,
                "html": html_body,
            },
        )
        response.raise_for_status()
