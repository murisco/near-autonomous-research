from __future__ import annotations

import asyncio
import base64
import html
import os
import re
from datetime import datetime, timedelta, timezone
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


def analyse_tvl_history(current_tvl: float, history: list[dict], days: int = 30) -> dict:
    """Flag rapid TVL moves and disagreement between current and historical endpoints."""
    valid = []
    for row in history:
        stamp = timestamp_seconds(row.get("date"))
        value = as_float(row.get("tvl"))
        if stamp is not None and value is not None:
            valid.append((stamp, value))
    valid.sort(key=lambda item: item[0])
    if not valid:
        return {"status": "unavailable", "warnings": ["No historical observations available for TVL anomaly checks."]}

    latest_stamp, latest_value = valid[-1]
    delta = ((current_tvl / latest_value) - 1) * 100 if latest_value > 0 else None
    cutoff = latest_stamp - days * 86400
    recent = [item for item in valid if item[0] >= cutoff]
    daily_moves = []
    for previous, current in zip(recent, recent[1:]):
        elapsed = current[0] - previous[0]
        if 20 * 3600 <= elapsed <= 52 * 3600 and previous[1] > 0:
            daily_moves.append({
                "date": datetime.fromtimestamp(current[0], timezone.utc).date().isoformat(),
                "change_percent": round((current[1] / previous[1] - 1) * 100, 2),
            })
    largest_move = max(daily_moves, key=lambda item: abs(item["change_percent"]), default=None)
    max_increase = max((item["change_percent"] for item in daily_moves), default=None)
    max_decrease = min((item["change_percent"] for item in daily_moves), default=None)
    warnings = []
    if delta is not None and abs(delta) > 10:
        warnings.append(
            "Current chain TVL differs from the latest historical observation by more than 10%; check endpoint timing and data consistency."
        )
    if largest_move and abs(largest_move["change_percent"]) > 25:
        warnings.append(
            "A single approximately daily TVL move exceeded 25%; inspect constituent assets and source snapshots before interpreting it as organic growth."
        )
    return {
        "status": "available",
        "latest_history_at": datetime.fromtimestamp(latest_stamp, timezone.utc).isoformat(),
        "latest_history_tvl_usd": round(latest_value, 2),
        "current_vs_latest_history_percent": round(delta, 2) if delta is not None else None,
        "largest_daily_move": largest_move,
        "max_daily_increase_percent": max_increase,
        "max_daily_decrease_percent": max_decrease,
        "daily_observations_checked": len(daily_moves),
        "warnings": warnings,
    }


def select_chain_from_topic(topic: str, chain_names: list[str], default_chain: str = "Near") -> str | None:
    """Choose a positively requested chain; ignore names explicitly negated by the prompt."""
    topic_text = topic or ""
    default_match = next(
        (name for name in chain_names if name.casefold() == default_chain.casefold()),
        None,
    )
    negation_before = re.compile(
        r"(?:not|never|exclude(?:d)?|except|rather than|instead of|other than|but not)"
        r"\s+(?:(?:the|chain)\s+)?$",
        re.IGNORECASE,
    )
    positive = []
    for name in chain_names:
        pattern = r"(?<![A-Za-z0-9])" + re.escape(name) + r"(?![A-Za-z0-9])"
        for match in re.finditer(pattern, topic_text, flags=re.IGNORECASE):
            prefix = topic_text[max(0, match.start() - 48):match.start()]
            if negation_before.search(prefix):
                continue
            positive.append(name)
            break
    if positive:
        return sorted(positive, key=len, reverse=True)[0]
    return default_match


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
    selected = select_chain_from_topic(topic, names, default_chain)
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
    tvl_anomalies = analyse_tvl_history(current_tvl, clean_history)
    warnings = list(tvl_anomalies.get("warnings") or [])
    seven_day_change = historical_change(clean_history, 7)
    thirty_day_change = historical_change(clean_history, 30)
    if seven_day_change is not None and seven_day_change > 50:
        warnings.append("Chain TVL increased by more than 50% over 7 days; verify the underlying assets and daily observations before calling this organic growth.")
    if thirty_day_change is not None and thirty_day_change > 100:
        warnings.append("Chain TVL more than doubled over 30 days; treat the trend as an anomaly requiring constituent-level validation.")
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
        "change_7d_percent": seven_day_change,
        "change_30d_percent": thirty_day_change,
        "tvl_anomaly_checks": tvl_anomalies,
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


STABLECOINS_BASE = DEFILLAMA_BASE


def _stablecoin_usd_value(value: Any) -> float | None:
    if isinstance(value, dict):
        for key in ("peggedUSD", "peggedUsd", "totalCirculatingUSD", "usd", "value"):
            parsed = as_float(value.get(key))
            if parsed is not None:
                return parsed
        return None
    return as_float(value)


def parse_stablecoin_chain_assets(raw_assets: list[dict], chain: str) -> list[dict]:
    """Extract per-asset circulating amounts for one chain from DefiLlama's catalogue."""
    asset_rows = []
    target = chain.casefold()
    for asset in raw_assets:
        if not isinstance(asset, dict):
            continue
        circulating = asset.get("chainCirculating") or {}
        matching = next(
            (value for key, value in circulating.items() if str(key).casefold() == target),
            None,
        ) if isinstance(circulating, dict) else None
        if not isinstance(matching, dict):
            continue
        current_value = _stablecoin_usd_value(matching.get("circulating", matching.get("current")))
        if current_value is None or current_value <= 0:
            continue
        previous = {
            "day": _stablecoin_usd_value(matching.get("circulatingPrevDay")),
            "week": _stablecoin_usd_value(matching.get("circulatingPrevWeek")),
            "month": _stablecoin_usd_value(matching.get("circulatingPrevMonth")),
        }
        def change_from(value):
            return round((current_value / value - 1) * 100, 2) if value and value > 0 else None
        asset_rows.append({
            "name": asset.get("name") or asset.get("symbol") or "Unknown stablecoin",
            "symbol": asset.get("symbol"),
            "peg_type": asset.get("pegType"),
            "current_supply_usd": round(current_value, 2),
            "change_1d_percent": change_from(previous["day"]),
            "change_7d_percent": change_from(previous["week"]),
            "change_30d_percent": change_from(previous["month"]),
        })
    return sorted(asset_rows, key=lambda item: item["current_supply_usd"], reverse=True)


def parse_stablecoin_chain_aggregate(rows: list[dict], chain: str) -> float | None:
    """Read the provider's current chain aggregate without summing token rows."""
    target = chain.casefold()
    for row in rows:
        if not isinstance(row, dict) or str(row.get("name") or "").casefold() != target:
            continue
        value = _stablecoin_usd_value(
            row.get("totalCirculatingUSD", row.get("totalCirculatingUsd", row.get("totalCirculating")))
        )
        if value is not None:
            return value
    return None


async def collect_stablecoin_context(chain: str = "Near") -> dict:
    """Collect stablecoin supply with independent endpoint fallbacks and partial-result handling."""
    headers = {"User-Agent": "MERIDIAN-Autonomous-Research/0.6"}
    timeout = httpx.Timeout(20.0, connect=8.0)
    chart_url = STABLECOINS_BASE + "/stablecoincharts/" + quote(chain, safe="")
    assets_url = STABLECOINS_BASE + "/stablecoins?includePrices=true"
    chains_url = STABLECOINS_BASE + "/stablecoinchains"
    errors: list[str] = []

    async def fetch_json(client: httpx.AsyncClient, url: str, label: str):
        try:
            response = await client.get(url)
            if response.status_code >= 400:
                errors.append(f"{label}_http_{response.status_code}")
                return None
            return response.json()
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            errors.append(f"{label}_{type(exc).__name__}")
            return None

    async with httpx.AsyncClient(
        timeout=timeout, headers=headers, follow_redirects=True
    ) as client:
        chart, assets_payload, chain_rows = await asyncio.gather(
            fetch_json(client, chart_url, "chain_history"),
            fetch_json(client, assets_url, "stablecoin_catalogue"),
            fetch_json(client, chains_url, "chain_aggregate"),
        )

    history = []
    if isinstance(chart, list):
        for row in chart:
            if not isinstance(row, dict):
                continue
            stamp = timestamp_seconds(row.get("date"))
            value = _stablecoin_usd_value(
                row.get("totalCirculatingUSD", row.get("totalCirculatingUsd", row.get("totalCirculating")))
            )
            if stamp is not None and value is not None:
                history.append({"date": stamp, "tvl": value})
    history.sort(key=lambda row: row["date"])
    latest = history[-1] if history else None

    if isinstance(assets_payload, dict):
        raw_assets = assets_payload.get("peggedAssets") or assets_payload.get("stablecoins") or []
    elif isinstance(assets_payload, list):
        raw_assets = assets_payload
    else:
        raw_assets = []
    asset_rows = parse_stablecoin_chain_assets(raw_assets, chain)
    chain_aggregate = parse_stablecoin_chain_aggregate(
        chain_rows if isinstance(chain_rows, list) else [], chain
    )
    reconstructed_total = sum(item["current_supply_usd"] for item in asset_rows) if asset_rows else None
    chart_total = latest["tvl"] if latest else None

    if chart_total is not None:
        total = chart_total
        total_method = "DefiLlama chain-level stablecoin history"
    elif chain_aggregate is not None:
        total = chain_aggregate
        total_method = "DefiLlama current chain aggregate"
    elif reconstructed_total is not None:
        total = reconstructed_total
        total_method = "sum of returned per-asset chainCirculating values; catalogue coverage may be incomplete"
    else:
        total = None
        total_method = "unavailable"

    retrieved = datetime.now(timezone.utc)
    history_for_change = [{"date": row["date"], "tvl": row["tvl"]} for row in history]
    warnings = []
    if not asset_rows:
        warnings.append("Per-stablecoin chain breakdown was unavailable; do not treat the aggregate as a token-level liquidity map.")
    if chart_total is None:
        warnings.append("Chain-level historical stablecoin data was unavailable; current supply uses a fallback source.")
    if chart_total is None and chain_aggregate is None and reconstructed_total is None:
        warnings.append("No independent stablecoin supply endpoint returned a usable NEAR value.")
    if chart_total is not None and reconstructed_total is not None and reconstructed_total > 0:
        divergence = (reconstructed_total / chart_total - 1) * 100
        if abs(divergence) > 15:
            warnings.append("Per-asset supply sum differs from chain aggregate by more than 15%; catalogue coverage, aliases, or endpoint timing may differ.")
    warnings.extend(errors)

    return {
        "status": "available" if total is not None or asset_rows else "unavailable",
        "chain": chain,
        "total_supply_usd": round(total, 2) if total is not None else None,
        "total_method": total_method,
        "history_points": len(history),
        "as_of": (
            datetime.fromtimestamp(latest["date"], timezone.utc).isoformat()
            if latest else retrieved.isoformat() if total is not None else None
        ),
        "change_7d_percent": historical_change(history_for_change, 7),
        "change_30d_percent": historical_change(history_for_change, 30),
        "assets": asset_rows[:15],
        "asset_count": len(asset_rows),
        "asset_sum_usd": round(reconstructed_total, 2) if reconstructed_total is not None else None,
        "chain_aggregate_usd": round(chain_aggregate, 2) if chain_aggregate is not None else None,
        "quality_warnings": warnings,
        "retrieved_at": retrieved.isoformat(),
        "sources": [chart_url, assets_url, chains_url],
        "limitations": "Stablecoin supply is not equivalent to available DEX liquidity, trading volume, or user adoption; coverage and classification depend on DefiLlama's stablecoin catalogue.",
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
    """Summarise only completed UTC days; do not compare a partial current day."""
    today_utc = datetime.now(timezone.utc).date()
    by_day: dict[str, dict] = {}
    for row in rows:
        date_label, stamp = _row_date(row)
        metric_key, value = _first_numeric(row, metric_keys)
        if stamp is None or value is None or not date_label:
            continue
        try:
            day = datetime.fromtimestamp(stamp, timezone.utc).date()
        except (OverflowError, OSError, ValueError):
            continue
        if day >= today_utc:
            continue
        entry = {"date": day.isoformat(), "timestamp": stamp, "value": value, "field": metric_key}
        by_day[day.isoformat()] = entry
    usable = sorted(by_day.values(), key=lambda item: item["timestamp"])
    if not usable:
        return {
            "status": "unavailable", "metric": label,
            "reason": "No completed UTC daily observations were returned; the current day is excluded as potentially partial.",
        }

    latest_day = datetime.fromisoformat(usable[-1]["date"]).date()
    recent_start = latest_day - timedelta(days=6)
    previous_start = latest_day - timedelta(days=13)
    previous_end = latest_day - timedelta(days=7)
    month_start = latest_day - timedelta(days=29)
    last_7 = [row for row in usable if recent_start <= datetime.fromisoformat(row["date"]).date() <= latest_day]
    previous_7 = [row for row in usable if previous_start <= datetime.fromisoformat(row["date"]).date() <= previous_end]
    last_30 = [row for row in usable if month_start <= datetime.fromisoformat(row["date"]).date() <= latest_day]
    prior_total = sum(row["value"] for row in previous_7)
    latest_total = sum(row["value"] for row in last_7)
    change = (
        round((latest_total / prior_total - 1) * 100, 2)
        if prior_total > 0 and len(last_7) >= 5 and len(previous_7) >= 5 else None
    )
    return {
        "status": "available",
        "metric": label,
        "source_field": usable[-1]["field"],
        "latest_day": usable[-1]["date"],
        "latest_day_value": round(usable[-1]["value"], 2),
        "latest_day_is_complete_utc": True,
        "last_7d_total": round(latest_total, 2),
        "last_7d_days": len(last_7),
        "last_7d_expected_days": 7,
        "last_7d_window_complete": len(last_7) == 7,
        "previous_7d_total": round(prior_total, 2),
        "previous_7d_days": len(previous_7),
        "previous_7d_window_complete": len(previous_7) == 7,
        "last_30d_total": round(sum(row["value"] for row in last_30), 2),
        "last_30d_days": len(last_30),
        "last_30d_expected_days": 30,
        "last_7d_vs_previous_7d_percent": change,
        "history_points": len(usable),
        "excluded_current_utc_day": True,
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
        ("transactions", "txns", "txn_count", "total_txns", "total_transactions", "transaction_count"),
        "daily transactions",
    )
    addresses = summarise_daily_rows(
        _find_rows(address_payload) if address_payload is not None else [],
        ("active_addresses", "active_accounts", "unique_accounts", "unique_addresses"),
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
                "classification": "publisher-reported NEAR headline; methodology and underlying query not independently verified.",
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


async def collect_near_agent_projects(limit: int = 8) -> dict:
    """Inspect GitHub README and recent commits; classify only README-supported candidates."""
    query_url = "https://api.github.com/search/repositories"
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "MERIDIAN-Autonomous-Research/0.5",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    queries = [
        '"NEAR Protocol" agent in:readme',
        '"NEAR testnet" agent in:readme',
        '"near-sdk" agent in:readme',
        'NEAR hackathon agent 2026 in:readme',
    ]
    timeout = httpx.Timeout(18.0, connect=7.0)
    try:
        async with httpx.AsyncClient(timeout=timeout, headers=headers, follow_redirects=True) as client:
            searches = await asyncio.gather(
                *(client.get(query_url, params={"q": query, "sort": "updated", "order": "desc", "per_page": 12}) for query in queries),
                return_exceptions=True,
            )
            candidates = {}
            total_count = 0
            search_errors = 0
            for response in searches:
                if isinstance(response, Exception):
                    search_errors += 1
                    continue
                if response.status_code >= 400:
                    search_errors += 1
                    continue
                try:
                    payload = response.json()
                except ValueError:
                    search_errors += 1
                    continue
                total_count += int(payload.get("total_count", 0) or 0)
                for item in payload.get("items", []):
                    if isinstance(item, dict) and item.get("full_name"):
                        candidates[item["full_name"].casefold()] = item

            def candidate_priority(item):
                identity = " ".join([
                    str(item.get("full_name") or ""),
                    str(item.get("name") or ""),
                    str(item.get("description") or ""),
                ]).lower()
                score = 0
                if re.search(r"\bnear\b", identity):
                    score += 2
                if re.search(r"\b(agent|agents|agentic|swarm)\b", identity):
                    score += 3
                if re.search(r"\b(autonomous|hackathon|marketplace|onchain)\b", identity):
                    score += 1
                return (score, item.get("pushed_at") or item.get("updated_at") or "")

            selected = sorted(
                candidates.values(),
                key=candidate_priority,
                reverse=True,
            )[:max(1, min(limit, 10))]

            async def inspect(item):
                full_name = item["full_name"]
                readme_task = client.get(
                    "https://api.github.com/repos/" + full_name + "/readme",
                    headers={"Accept": "application/vnd.github+json"},
                )
                commits_task = client.get(
                    "https://api.github.com/repos/" + full_name + "/commits",
                    params={"per_page": 3},
                )
                readme_response, commits_response = await asyncio.gather(
                    readme_task, commits_task, return_exceptions=True
                )
                readme_text = ""
                readme_status = "unavailable"
                if not isinstance(readme_response, Exception) and readme_response.status_code < 400:
                    try:
                        readme_payload = readme_response.json()
                        encoded = readme_payload.get("content", "")
                        readme_text = base64.b64decode(encoded).decode("utf-8", errors="replace")
                        readme_status = "inspected"
                    except (ValueError, TypeError, KeyError):
                        readme_status = "unreadable"
                commits = []
                if not isinstance(commits_response, Exception) and commits_response.status_code < 400:
                    try:
                        for commit_row in commits_response.json()[:3]:
                            commit = (commit_row.get("commit") or {}) if isinstance(commit_row, dict) else {}
                            author = commit.get("author") or {}
                            message = (commit.get("message") or "").splitlines()[0][:180]
                            commits.append({
                                "date": author.get("date"),
                                "message": message,
                                "url": commit_row.get("html_url"),
                            })
                    except (ValueError, TypeError, AttributeError):
                        commits = []
                combined = " ".join([
                    str(item.get("name") or ""), str(item.get("description") or ""), readme_text[:30000]
                ]).lower()
                near_patterns = (
                    r"near protocol", r"near blockchain", r"near-sdk", r"nearcore",
                    r"near testnet", r"near mainnet", r"near account", r"near intents",
                    r"near ai", r"\bnep-\d+\b",
                )
                agent_patterns = (
                    r"\bai agent\b", r"\bautonomous agent\b", r"\bagentic\b",
                    r"\bmulti-agent\b", r"\bmulti agent\b", r"\bllm agent\b",
                    r"\bagent swarm\b", r"\bagent runtime\b", r"\bagent framework\b",
                )
                infrastructure_patterns = (
                    r"agent framework", r"agent runtime", r"agent orchestration",
                    r"agent infrastructure", r"sdk for agents", r"agent toolkit",
                )
                near_hits = [pattern for pattern in near_patterns if re.search(pattern, combined)]
                agent_hits = [pattern for pattern in agent_patterns if re.search(pattern, combined)]
                infra_hits = [pattern for pattern in infrastructure_patterns if re.search(pattern, combined)]
                explicit_near_integration = any(
                    re.search(pattern, combined)
                    for pattern in (
                        r"near protocol", r"near blockchain", r"near[-_]sdk",
                        r"near-api-js", r"@near-js", r"near testnet", r"near mainnet",
                        r"\bnep[- ]\d+\b", r"market\.near\.ai", r"near intents",
                    )
                )
                strong_agent_evidence = any(
                    re.search(pattern, combined)
                    for pattern in (
                        r"\bautonomous ai agent\b", r"\bautonomous agent\b",
                        r"\bai agent\b", r"\bagent swarm\b",
                        r"\bagent marketplace\b", r"\bagent market\b",
                    )
                )
                if readme_status == "inspected" and explicit_near_integration and strong_agent_evidence:
                    classification = "autonomous_ai_agent_candidate"
                elif readme_status == "inspected" and near_hits and infra_hits:
                    classification = "agent_infrastructure"
                elif readme_status == "inspected" and explicit_near_integration:
                    classification = "related_near_ecosystem_project_not_verified_as_agent"
                else:
                    classification = "unverified_candidate"
                clean_description = str(item.get("description") or "")[:300]
                return {
                    "name": full_name,
                    "description": clean_description,
                    "url": item.get("html_url"),
                    "language": item.get("language"),
                    "stars": item.get("stargazers_count"),
                    "forks": item.get("forks_count"),
                    "open_issues": item.get("open_issues_count"),
                    "last_pushed_at": item.get("pushed_at"),
                    "created_at": item.get("created_at"),
                    "archived": item.get("archived", False),
                    "classification": classification,
                    "readme_status": readme_status,
                    "readme_evidence": re.sub(r"\s+", " ", readme_text[:420]).strip() if readme_text else None,
                    "near_evidence_patterns": near_hits,
                    "agent_evidence_patterns": agent_hits,
                    "recent_commits": commits,
                    "latest_commit_at": commits[0].get("date") if commits else None,
                    "source": "GitHub repository metadata, README API and recent commit API",
                    "evidence_limit": "README and commit metadata are public repository evidence, not independent proof of a deployed agent, production users, or revenue.",
                }

            inspected = await asyncio.gather(*(inspect(item) for item in selected), return_exceptions=True)
        projects = [item for item in inspected if isinstance(item, dict)]
        projects.sort(key=lambda item: (
            item["classification"] != "autonomous_ai_agent_candidate",
            item["classification"] != "agent_infrastructure",
            item.get("latest_commit_at") or item.get("last_pushed_at") or "",
        ), reverse=False)
        categories = {
            "autonomous_ai_agent_candidates": [item for item in projects if item["classification"] == "autonomous_ai_agent_candidate"],
            "agent_infrastructure": [item for item in projects if item["classification"] == "agent_infrastructure"],
            "related_ecosystem_projects": [item for item in projects if item["classification"] == "related_near_ecosystem_project_not_verified_as_agent"],
            "unverified_candidates": [item for item in projects if item["classification"] == "unverified_candidate"],
        }
        return {
            "status": "available" if projects else "no_results",
            "queries": queries,
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
            "total_search_matches": total_count,
            "search_errors": search_errors,
            "projects": projects,
            **categories,
            "source": "https://api.github.com/search/repositories",
            "limitations": "GitHub search is incomplete. README classification is a screening signal, not a code audit. Stars, forks, pushes, and README claims do not prove deployment, active use, users, or revenue.",
        }
    except (httpx.HTTPError, ValueError, TypeError) as exc:
        return {
            "status": "unavailable",
            "projects": [],
            "autonomous_ai_agent_candidates": [],
            "agent_infrastructure": [],
            "related_ecosystem_projects": [],
            "unverified_candidates": [],
            "reason": "GitHub repository discovery failed: " + type(exc).__name__,
            "source": "https://api.github.com/search/repositories",
        }
