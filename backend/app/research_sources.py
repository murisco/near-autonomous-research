from __future__ import annotations

import asyncio
import html
import os
import re
from datetime import datetime, timezone
from html.parser import HTMLParser
from urllib.parse import quote
from typing import Any

import httpx

DEFILLAMA_BASE = "https://api.llama.fi"
NEARBLOCKS_BASE = "https://api.nearblocks.io"
NEAR_ANALYTICS_URL = "https://www.near.org/research-analytics"
NEAR_INTENTS_HOME_URL = "https://intents.near.org/"
NEAR_AI_QUICKSTART_URL = "https://docs.near.ai/cloud/quickstart.md"
NEAR_AI_MODELS_URL = "https://docs.near.ai/cloud/models.md"
NEAR_INTENTS_QUICKSTART_URL = (
    "https://docs.near-intents.org/integration/distribution-channels/"
    "1click-api/quickstart/introduction.md"
)
NEAR_INTENTS_EXPLORER_URL = "https://explorer.near-intents.org/api/v0/transactions"
NEAR_AI_DEFAULT_MODEL = "zai-org/GLM-5.1-FP8"

EXCLUDED_TVL_CATEGORIES = {
    "cex", "centralized exchange", "bridge", "liquid staking", "staking",
    "pool2", "borrow", "borrowing", "vesting", "treasury", "assets",
}
EXCLUDED_CATEGORY_TERMS = (
    "centralized exchange", "liquid staking", "bridge", "staking",
    "pool2", "vesting", "treasury",
)


class ResearchSourceError(Exception):
    pass


def as_float(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(str(value).replace(",", "").replace("$", "").strip())
    except (TypeError, ValueError):
        return None
    return number if number >= 0 else None


def timestamp_seconds(value: Any) -> float | None:
    numeric = as_float(value)
    if numeric is not None:
        return numeric / 1000 if numeric > 100_000_000_000 else numeric
    if isinstance(value, str):
        candidate = value.strip().replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(candidate)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.timestamp()
        except ValueError:
            return None
    return None


def is_excluded_category(category: str) -> bool:
    normalized = re.sub(r"[_-]+", " ", (category or "").strip().lower())
    return normalized in EXCLUDED_TVL_CATEGORIES or any(
        term in normalized for term in EXCLUDED_CATEGORY_TERMS
    )


def filter_chain_protocols(
    protocols: list[dict], chain: str, chain_tvl_usd: float
) -> tuple[list[dict], list[dict]]:
    """Filter protocols using chain-TVL methodology and sanity checks."""
    eligible: list[dict] = []
    excluded: list[dict] = []
    target = chain.casefold()

    for protocol in protocols:
        if not isinstance(protocol, dict):
            continue
        name = str(protocol.get("name") or "Unknown")
        category = str(protocol.get("category") or "Uncategorised")
        chains = protocol.get("chains") or []
        chain_tvls = protocol.get("chainTvls") or {}
        if not any(str(item).casefold() == target for item in chains):
            continue
        if is_excluded_category(category):
            excluded.append({
                "name": name, "category": category,
                "reason": "Excluded by DefiLlama chain-TVL methodology.",
            })
            continue
        if bool(protocol.get("doublecounted")):
            excluded.append({
                "name": name, "category": category,
                "reason": "Flagged as double-counted by DefiLlama.",
            })
            continue

        chain_value = None
        if isinstance(chain_tvls, dict):
            for key, value in chain_tvls.items():
                if str(key).casefold() == target:
                    chain_value = as_float(value)
                    break
        if chain_value is None:
            excluded.append({
                "name": name, "category": category,
                "reason": "No exact chain-specific TVL value was returned.",
            })
            continue
        if chain_tvl_usd > 0 and chain_value > chain_tvl_usd * 1.05:
            excluded.append({
                "name": name, "category": category,
                "reason": "Reported chain value exceeds chain-wide TVL by more than 5%; excluded as inconsistent.",
                "reported_chain_tvl_usd": round(chain_value, 2),
            })
            continue
        eligible.append({
            "name": name,
            "category": category,
            "chain_tvl_usd": chain_value,
            "change_1d_percent": protocol.get("change_1d"),
            "change_7d_percent": protocol.get("change_7d"),
            "source": DEFILLAMA_BASE + "/protocols",
        })

    eligible.sort(key=lambda row: row["chain_tvl_usd"], reverse=True)
    return eligible[:5], excluded


def historical_change(history: list[dict], days: int) -> float | None:
    valid = []
    for row in history:
        stamp = timestamp_seconds(row.get("date"))
        value = as_float(row.get("tvl"))
        if stamp is not None and value is not None:
            valid.append((stamp, value))
    if len(valid) < 2:
        return None
    valid.sort(key=lambda item: item[0])
    latest_time, latest_value = valid[-1]
    target_time = latest_time - days * 86400
    previous = [item for item in valid[:-1] if item[0] <= target_time]
    if not previous:
        return None
    previous_value = previous[-1][1]
    if previous_value <= 0:
        return None
    return round((latest_value / previous_value - 1) * 100, 2)


async def collect_defillama_context(topic: str, default_chain: str = "Near") -> dict:
    timeout = httpx.Timeout(20.0, connect=8.0)
    headers = {"User-Agent": "MERIDIAN-Autonomous-Research/0.3"}
    async with httpx.AsyncClient(timeout=timeout, headers=headers) as client:
        try:
            chain_response = await client.get(DEFILLAMA_BASE + "/v2/chains")
            chain_response.raise_for_status()
            chains = chain_response.json()
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            raise ResearchSourceError("DefiLlama could not provide a valid chain catalogue.") from exc

    if not isinstance(chains, list):
        raise ResearchSourceError("DefiLlama returned an unexpected chain catalogue format.")
    names = [
        str(item.get("name", "")) for item in chains
        if isinstance(item, dict) and item.get("name")
    ]
    mentioned = [name for name in names if name.casefold() in topic.casefold()]
    selected = (
        sorted(mentioned, key=len, reverse=True)[0]
        if mentioned else next((name for name in names if name.casefold() == default_chain.casefold()), None)
    )
    if not selected:
        raise ResearchSourceError("The requested chain was not found in DefiLlama's chain catalogue.")
    chain_row = next(
        item for item in chains
        if isinstance(item, dict) and str(item.get("name", "")).casefold() == selected.casefold()
    )
    current_tvl = as_float(chain_row.get("tvl"))
    if current_tvl is None:
        raise ResearchSourceError("DefiLlama did not return a valid chain TVL value.")

    history_url = DEFILLAMA_BASE + "/v2/historicalChainTvl/" + quote(selected, safe="")
    async with httpx.AsyncClient(timeout=timeout, headers=headers) as client:
        try:
            history_response, protocols_response = await asyncio.gather(
                client.get(history_url),
                client.get(DEFILLAMA_BASE + "/protocols"),
            )
            history_response.raise_for_status()
            protocols_response.raise_for_status()
            history = history_response.json()
            protocols = protocols_response.json()
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            raise ResearchSourceError("DefiLlama could not provide matching chain history and protocol rows.") from exc
    if not isinstance(history, list) or not isinstance(protocols, list):
        raise ResearchSourceError("DefiLlama returned an unexpected history or protocol response format.")

    clean_history = [
        row for row in history
        if isinstance(row, dict)
        and timestamp_seconds(row.get("date")) is not None
        and as_float(row.get("tvl")) is not None
    ]
    clean_history.sort(key=lambda row: timestamp_seconds(row["date"]) or 0)
    if not clean_history:
        raise ResearchSourceError("DefiLlama returned no usable historical chain TVL observations.")

    eligible, excluded = filter_chain_protocols(protocols, selected, current_tvl)
    retrieved = datetime.now(timezone.utc)
    latest_stamp = timestamp_seconds(clean_history[-1]["date"])
    age_hours = (
        max(0.0, (retrieved.timestamp() - latest_stamp) / 3600)
        if latest_stamp is not None else None
    )
    top_sum = sum(item["chain_tvl_usd"] for item in eligible)
    warnings = []
    if age_hours is not None and age_hours > 72:
        warnings.append("Historical chain TVL data is more than 72 hours old.")
    if top_sum > current_tvl * 1.05:
        warnings.append(
            "Top protocol rows sum to more than chain TVL. Protocol values may overlap and must not be added together."
        )
    if excluded:
        warnings.append(
            f"{len(excluded)} protocol rows were excluded for category, double-counting, or value-consistency reasons."
        )

    return {
        "chain": selected,
        "current_tvl_usd": current_tvl,
        "change_7d_percent": historical_change(clean_history, 7),
        "change_30d_percent": historical_change(clean_history, 30),
        "history_points": len(clean_history),
        "history_latest_at": datetime.fromtimestamp(latest_stamp, timezone.utc).isoformat() if latest_stamp else None,
        "history_age_hours": round(age_hours, 2) if age_hours is not None else None,
        "top_protocols": eligible,
        "excluded_protocols": excluded[:30],
        "excluded_protocol_count": len(excluded),
        "top_protocol_rows_sum_usd": round(top_sum, 2),
        "protocol_rows_are_additive": False,
        "quality_warnings": warnings,
        "retrieved_at": retrieved.isoformat(),
        "sources": [
            DEFILLAMA_BASE + "/v2/chains",
            history_url,
            DEFILLAMA_BASE + "/protocols",
            "https://docs.llama.fi/analysts/data-definitions",
        ],
    }


def _find_rows(payload: Any) -> list[dict]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        for key in ("stats", "data", "items", "rows", "results", "result", "txns", "addresses"):
            if key in payload:
                rows = _find_rows(payload[key])
                if rows:
                    return rows
        for value in payload.values():
            if isinstance(value, (dict, list)):
                rows = _find_rows(value)
                if rows:
                    return rows
    return []


def _row_date(row: dict) -> tuple[str | None, float | None]:
    for key in ("date", "day", "timestamp", "time", "created_at", "block_date"):
        if row.get(key) is not None:
            stamp = timestamp_seconds(row[key])
            label = (
                datetime.fromtimestamp(stamp, timezone.utc).date().isoformat()
                if stamp is not None else str(row[key])
            )
            return label, stamp
    return None, None


def _first_numeric(row: dict, keys: tuple[str, ...]) -> tuple[str | None, float | None]:
    for key in keys:
        if key in row:
            value = as_float(row[key])
            if value is not None:
                return key, value
    return None, None


def summarise_daily_rows(rows: list[dict], metric_keys: tuple[str, ...], label: str) -> dict:
    usable = []
    for row in rows:
        date_label, stamp = _row_date(row)
        metric_key, value = _first_numeric(row, metric_keys)
        if stamp is not None and value is not None:
            usable.append({"date": date_label, "timestamp": stamp, "value": value, "field": metric_key})
    usable.sort(key=lambda item: item["timestamp"])
    if not usable:
        return {"status": "unavailable", "metric": label, "reason": "No recognised daily metric field was returned."}

    latest = usable[-1]["timestamp"]
    last_7 = [row for row in usable if row["timestamp"] >= latest - 7 * 86400]
    last_30 = [row for row in usable if row["timestamp"] >= latest - 30 * 86400]
    previous_7 = [
        row for row in usable
        if latest - 14 * 86400 <= row["timestamp"] < latest - 7 * 86400
    ]
    prior_total = sum(row["value"] for row in previous_7)
    latest_total = sum(row["value"] for row in last_7)
    change = round((latest_total / prior_total - 1) * 100, 2) if prior_total > 0 and previous_7 else None
    return {
        "status": "available",
        "metric": label,
        "source_field": usable[-1]["field"],
        "latest_day": usable[-1]["date"],
        "latest_day_value": round(usable[-1]["value"], 2),
        "last_7d_total": round(latest_total, 2),
        "last_7d_days": len(last_7),
        "last_30d_total": round(sum(row["value"] for row in last_30), 2),
        "last_30d_days": len(last_30),
        "last_7d_vs_previous_7d_percent": change,
        "history_points": len(usable),
    }


async def collect_nearblocks_activity() -> dict:
    headers = {"User-Agent": "MERIDIAN-Autonomous-Research/0.3"}
    api_key = os.getenv("NEARBLOCKS_API_KEY", "").strip()
    if api_key:
        headers["Authorization"] = "Bearer " + api_key
    base = os.getenv("NEARBLOCKS_BASE_URL", NEARBLOCKS_BASE).rstrip("/")
    timeout = httpx.Timeout(18.0, connect=7.0)

    async def request(endpoint: str):
        async with httpx.AsyncClient(timeout=timeout, headers=headers) as client:
            response = await client.get(base + endpoint, params={"limit": 30})
            response.raise_for_status()
            return endpoint, response.json()

    results = await asyncio.gather(
        request("/v3/txn-stats"),
        request("/v3/address-stats"),
        return_exceptions=True,
    )
    txn_payload = address_payload = None
    errors = []
    for result in results:
        if isinstance(result, Exception):
            errors.append(type(result).__name__)
        else:
            endpoint, payload = result
            if endpoint == "/v3/txn-stats":
                txn_payload = payload
            elif endpoint == "/v3/address-stats":
                address_payload = payload

    txn = summarise_daily_rows(
        _find_rows(txn_payload) if txn_payload is not None else [],
        ("transactions", "txns", "txn_count", "total_txns", "total_transactions", "transaction_count", "count"),
        "daily transactions",
    )
    addresses = summarise_daily_rows(
        _find_rows(address_payload) if address_payload is not None else [],
        ("active_addresses", "active_accounts", "unique_accounts", "unique_addresses", "accounts", "addresses"),
        "daily active/unique addresses",
    )
    return {
        "provider": "NearBlocks",
        "transaction_stats": txn,
        "address_stats": addresses,
        "status": "available" if txn["status"] == "available" or addresses["status"] == "available" else "unavailable",
        "errors": errors,
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "sources": [
            base + "/v3/txn-stats?limit=30",
            base + "/v3/address-stats?limit=30",
            "https://api.nearblocks.io/api-docs/ui/",
        ],
        "attribution": "Powered by NearBlocks.io APIs.",
    }


class PlainTextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        text = data.strip()
        if text:
            self.parts.append(text)

    def extract(self, source: str) -> str:
        self.feed(source)
        return re.sub(r"\s+", " ", html.unescape(" ".join(self.parts))).strip()


def parse_official_hub_metrics(text: str) -> list[dict]:
    patterns = [
        ("daily_transactions", r"(\d+(?:\.\d+)?\s*[KMB]\+?)\s*Daily Transactions"),
        ("monthly_active_users", r"(\d+(?:\.\d+)?\s*[KMB]\+?)\s*Monthly Active Users"),
        ("tps_headline", r"(\d+(?:\.\d+)?\s*[KMB]\+?)\s*Transactions per second"),
        ("stablecoin_supply", r"(\$?\d+(?:\.\d+)?\s*[KMB]\+?)\s*Stablecoin Supply"),
        ("ecosystem_funding", r"(\$?\d+(?:\.\d+)?\s*[KMB]\+?)\s*Total Funding Raised"),
    ]
    metrics = []
    for label, pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            metrics.append({
                "metric": label,
                "publisher_displayed_value": re.sub(r"\s+", "", match.group(1)),
                "classification": "NEAR-published headline; methodology and underlying query not independently verified.",
            })
    return metrics


def parse_intents_home(text: str) -> dict | None:
    match = re.search(
        r"(\$?\d+(?:\.\d+)?\s*[KMB]\+?)\s*all-time volume across\s*(\d+)\s*chains",
        text,
        flags=re.IGNORECASE,
    )
    if not match:
        return None
    return {
        "all_time_volume_displayed": re.sub(r"\s+", "", match.group(1)),
        "chains_displayed": int(match.group(2)),
        "classification": "NEAR Intents publisher-displayed headline; not independently reconstructed from transaction records.",
    }


async def collect_official_near_context() -> dict:
    urls = [
        NEAR_ANALYTICS_URL,
        NEAR_INTENTS_HOME_URL,
        NEAR_AI_QUICKSTART_URL,
        NEAR_AI_MODELS_URL,
        NEAR_INTENTS_QUICKSTART_URL,
    ]
    timeout = httpx.Timeout(18.0, connect=7.0)
    async with httpx.AsyncClient(
        timeout=timeout,
        headers={"User-Agent": "MERIDIAN-Autonomous-Research/0.3"},
        follow_redirects=True,
    ) as client:
        responses = await asyncio.gather(
            *(client.get(url) for url in urls),
            return_exceptions=True,
        )

    fetched = {}
    for url, response in zip(urls, responses):
        if not isinstance(response, Exception) and response.status_code < 400:
            fetched[url] = response.text

    analytics_text = PlainTextExtractor().extract(fetched.get(NEAR_ANALYTICS_URL, ""))
    intents_text = PlainTextExtractor().extract(fetched.get(NEAR_INTENTS_HOME_URL, ""))
    ai_text = fetched.get(NEAR_AI_QUICKSTART_URL, "")
    ai_models_text = fetched.get(NEAR_AI_MODELS_URL, "")
    intents_docs_text = fetched.get(NEAR_INTENTS_QUICKSTART_URL, "")

    ai_facts = []
    if "OpenAI-compatible API" in ai_text:
        ai_facts.append("NEAR AI Cloud documents an OpenAI-compatible API at cloud-api.near.ai.")
    if "Trusted Execution Environments" in ai_text or "TEE" in ai_text:
        ai_facts.append(
            "The official quickstart describes inference routed to model Trusted Execution Environments; privacy guarantees depend on the selected model tier."
        )
    if "Confidential TEE" in ai_models_text and "Incognito" in ai_models_text:
        ai_facts.append(
            "The official model catalogue distinguishes Confidential TEE, third-party Confidential TEE, and Incognito models; these tiers do not provide identical model-level guarantees."
        )

    intents_facts = []
    if "There is no testnet version of NEAR Intents" in intents_docs_text:
        intents_facts.append("The official 1Click quickstart states that NEAR Intents has no testnet version.")
    if "quote" in intents_docs_text.lower() and "deposit" in intents_docs_text.lower():
        intents_facts.append(
            "The documented 1Click flow requests a quote, deposits the selected asset, and tracks execution; a dry quote is only a preview."
        )

    return {
        "publisher": "NEAR",
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "official_hub_metrics": parse_official_hub_metrics(analytics_text),
        "intents_home_metric": parse_intents_home(intents_text),
        "near_ai_documented_facts": ai_facts,
        "near_intents_documented_facts": intents_facts,
        "near_intents_explorer": {
            "status": "jwt_required" if not os.getenv("NEAR_INTENTS_EXPLORER_JWT", "").strip() else "jwt_configured_not_queried",
            "source": NEAR_INTENTS_EXPLORER_URL,
            "note": "The official Explorer API requires a partner JWT. MERIDIAN does not invent swap activity when credentials are unavailable.",
        },
        "sources": urls + [
            "https://docs.near.ai/llms.txt",
            "https://docs.near-intents.org/llms.txt",
        ],
    }
