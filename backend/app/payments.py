from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import httpx


TIDEPOOL_QUOTE_URL = os.getenv(
    "TIDEPOOL_QUOTE_URL", "https://www.usetidepool.tech/v0/quote"
)


async def create_tidepool_dry_quote(amount_usd: float, settings: dict) -> dict:
    """Request a valueless 1Click-compatible quote from the community Tidepool sandbox."""
    if not settings.get("enable_sandbox_dry_quotes", False):
        return {
            "status": "simulation_only",
            "provider": "none",
            "reason": "Sandbox dry quotes are disabled in business rules.",
            "no_deposit_address": True,
            "settlement": False,
        }

    amount_usdc = max(1, round(float(amount_usd) * 1_000_000))
    deadline = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat().replace("+00:00", "Z")
    payload = {
        "dry": True,
        "swapType": "EXACT_OUTPUT",
        "slippageTolerance": 100,
        "originAsset": "nep141:wnear.tidepool-sandbox.testnet",
        "depositType": "INTENTS",
        "destinationAsset": "nep141:usdc.tidepool-sandbox.testnet",
        "amount": str(amount_usdc),
        "recipient": "user.testnet",
        "recipientType": "INTENTS",
        "refundTo": "user.testnet",
        "refundType": "INTENTS",
        "deadline": deadline,
        "depositMode": "SIMPLE",
        "referral": "meridian-hackathon",
        "quoteWaitingTimeMs": 1000,
        "sessionId": "meridian-" + uuid4().hex,
        "confidentiality": "public",
    }

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(15.0, connect=5.0)) as client:
            response = await client.post(
                TIDEPOOL_QUOTE_URL,
                json=payload,
                headers={"Content-Type": "application/json", "User-Agent": "MERIDIAN-Hackathon/0.1"},
            )
            response.raise_for_status()
            data = response.json()
        quote = data.get("quote") if isinstance(data, dict) else None
        if not isinstance(quote, dict):
            raise ValueError("Tidepool response did not include a quote object.")

        return {
            "status": "dry_quote_returned",
            "provider": "Tidepool",
            "network": "community-operated testnet sandbox",
            "correlation_id": data.get("correlationId"),
            "quote_timestamp": data.get("timestamp"),
            "quote": {
                "amount_in_formatted": quote.get("amountInFormatted"),
                "amount_in_usd": quote.get("amountInUsd"),
                "amount_out_formatted": quote.get("amountOutFormatted"),
                "amount_out_usd": quote.get("amountOutUsd"),
                "time_estimate_seconds": quote.get("timeEstimate"),
                "slippage_tolerance_bps": payload["slippageTolerance"],
            },
            "signature_verified": False,
            "no_deposit_address": True,
            "settlement": False,
            "note": (
                "Valueless dry quote only. Tidepool is a community sandbox, not an official NEAR/Defuse "
                "testnet. No deposit address is created and no funds are moved."
            ),
        }
    except (httpx.HTTPError, ValueError, TypeError) as exc:
        return {
            "status": "simulation_fallback",
            "provider": "Tidepool unavailable",
            "reason": str(exc)[:240],
            "no_deposit_address": True,
            "settlement": False,
            "note": "No payment was attempted. This order remains unpaid.",
        }
