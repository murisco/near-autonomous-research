from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import struct
from datetime import datetime, timezone

import base58
import httpx
from nacl.exceptions import BadSignatureError
from nacl.signing import VerifyKey

NEP413_TAG = (1 << 31) + 413
ACCOUNT_ID_RE = re.compile(r"^[a-z0-9]+(?:[._-][a-z0-9]+)*$")


def auth_recipient() -> str:
    return os.getenv("MERIDIAN_NEAR_AUTH_RECIPIENT", "").strip() or "meridian-dashboard.up.railway.app"


def valid_account_id(account_id: str) -> bool:
    value = account_id.strip().lower()
    return bool(
        ACCOUNT_ID_RE.fullmatch(value)
        and not value.startswith((".", "-", "_"))
        and not value.endswith((".", "-", "_"))
        and ".." not in value
        and "__" not in value
        and "--" not in value
    )


def _u32(value: int) -> bytes:
    return struct.pack("<I", value)


def _borsh_string(value: str) -> bytes:
    raw = value.encode("utf-8")
    return _u32(len(raw)) + raw


def nep413_signing_hash(message: str, nonce: bytes, recipient: str) -> bytes:
    if len(nonce) != 32:
        raise ValueError("NEP-413 nonce must be exactly 32 bytes.")
    payload = b"".join(
        (
            _u32(NEP413_TAG),
            _borsh_string(message),
            nonce,
            _borsh_string(recipient),
            b"\x00",  # callbackUrl: None
        )
    )
    return hashlib.sha256(payload).digest()


def verify_nep413_signature(
    message: str,
    nonce_b64: str,
    recipient: str,
    public_key: str,
    signature_b64: str,
) -> bool:
    try:
        if len(message.encode("utf-8")) > 65_536:
            return False
        if not public_key.startswith("ed25519:"):
            return False
        key_bytes = base58.b58decode(public_key.split(":", 1)[1])
        nonce = base64.b64decode(nonce_b64, validate=True)
        signature = base64.b64decode(signature_b64, validate=True)
        if len(key_bytes) != 32 or len(signature) != 64 or len(nonce) != 32:
            return False
        digest = nep413_signing_hash(message, nonce, recipient)
        VerifyKey(key_bytes).verify(digest, signature)
        return True
    except (ValueError, BadSignatureError, TypeError):
        return False


async def account_has_full_access_key(account_id: str, public_key: str) -> bool:
    network = "testnet" if account_id.endswith(".testnet") else "mainnet"
    rpc_url = os.getenv(
        "NEAR_TESTNET_RPC_URL" if network == "testnet" else "NEAR_MAINNET_RPC_URL",
        "https://rpc.testnet.near.org" if network == "testnet" else "https://rpc.mainnet.near.org",
    )
    payload = {
        "jsonrpc": "2.0",
        "id": "meridian-near-login",
        "method": "query",
        "params": {
            "request_type": "view_access_key_list",
            "finality": "final",
            "account_id": account_id,
        },
    }
    timeout = httpx.Timeout(12.0, connect=5.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(rpc_url, json=payload)
        response.raise_for_status()
        body = response.json()
    if body.get("error"):
        error_text = json.dumps(body["error"]).lower()
        if "does not exist" in error_text or "unknown account" in error_text:
            return False
        raise RuntimeError("NEAR RPC could not verify the account's access keys.")
    keys = (body.get("result") or {}).get("keys") or []
    for item in keys:
        if item.get("public_key") != public_key:
            continue
        permission = (item.get("access_key") or {}).get("permission")
        return permission == "FullAccess"
    return False


def admin_account_ids() -> set[str]:
    raw = os.getenv("MERIDIAN_ADMIN_ACCOUNT_IDS", "")
    return {item.strip().lower() for item in raw.replace(";", ",").split(",") if item.strip()}


def is_admin_account(account_id: str) -> bool:
    return account_id.strip().lower() in admin_account_ids()
