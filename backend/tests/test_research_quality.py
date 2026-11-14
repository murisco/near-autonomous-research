import asyncio
from datetime import datetime, timezone, timedelta

from backend.app import research_sources as sources
from backend.app import research as research_module
from backend.app.research import _customer_summary, _is_defi_protocol_question
from backend.app.research_sources import (
    analyse_tvl_history,
    filter_chain_protocols,
    historical_change,
    parse_intents_home,
    parse_official_hub_metrics,
    parse_stablecoin_chain_assets,
    parse_stablecoin_chain_aggregate,
    select_chain_from_topic,
    summarise_daily_rows,
)


def test_defillama_protocol_rows_exclude_non_chain_tvl_categories_and_outliers():
    protocols = [
        {
            "name": "Rhea Lend",
            "category": "Lending",
            "chains": ["Near"],
            "chainTvls": {"Near": 120_000_000},
        },
        {
            "name": "NEAR Intents",
            "category": "Bridge",
            "chains": ["Near"],
            "chainTvls": {"Near": 90_000_000},
        },
        {
            "name": "Meta Pool Near",
            "category": "Liquid Staking",
            "chains": ["Near"],
            "chainTvls": {"Near": 80_000_000},
        },
        {
            "name": "Binance CEX",
            "category": "CEX",
            "chains": ["Near"],
            "chainTvls": {"Near": 550_000_000},
        },
        {
            "name": "Impossible Protocol",
            "category": "Lending",
            "chains": ["Near"],
            "chainTvls": {"Near": 180_000_000},
        },
        {
            "name": "Other Chain",
            "category": "Lending",
            "chains": ["Ethereum"],
            "chainTvls": {"Ethereum": 1_000_000_000},
        },
    ]

    eligible, excluded = filter_chain_protocols(protocols, "Near", 165_000_000)

    assert [row["name"] for row in eligible] == ["Rhea Lend"]
    assert {row["name"] for row in excluded} == {
        "NEAR Intents",
        "Meta Pool Near",
        "Binance CEX",
        "Impossible Protocol",
    }
    reasons = {row["name"]: row["reason"] for row in excluded}
    assert "methodology" in reasons["NEAR Intents"]
    assert "methodology" in reasons["Meta Pool Near"]
    assert "methodology" in reasons["Binance CEX"]
    assert "exceeds" in reasons["Impossible Protocol"]


def test_historical_change_uses_calendar_time_not_row_offsets():
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    history = [
        {"date": int((base + timedelta(days=day)).timestamp()), "tvl": value}
        for day, value in [(0, 100), (2, 110), (7, 120), (10, 130), (14, 150), (30, 200)]
    ]

    assert historical_change(history, 7) == 33.33
    assert historical_change(history, 30) == 100.0


def test_daily_activity_parser_recognises_metrics_and_does_not_guess():
    today = datetime.now(timezone.utc).date()
    rows = [
        {"date": (today - timedelta(days=3)).isoformat(), "txns": "100"},
        {"date": (today - timedelta(days=2)).isoformat(), "txns": "110"},
        {"date": (today - timedelta(days=1)).isoformat(), "txns": "120"},
    ]
    result = summarise_daily_rows(rows, ("transactions", "txns"), "daily transactions")
    assert result["status"] == "available"
    assert result["last_7d_total"] == 330
    assert result["source_field"] == "txns"

    unavailable = summarise_daily_rows(
        [{"date": (today - timedelta(days=1)).isoformat(), "foo": 12}],
        ("transactions", "txns"),
        "daily transactions",
    )
    assert unavailable["status"] == "unavailable"

def test_official_publisher_metrics_are_marked_as_publisher_claims():
    metrics = parse_official_hub_metrics(
        "5M+ Daily Transactions 48M+ Monthly Active Users 100K Transactions per second"
    )
    values = {item["metric"]: item["publisher_displayed_value"] for item in metrics}
    assert values["daily_transactions"] == "5M+"
    assert values["monthly_active_users"] == "48M+"
    assert values["tps_headline"] == "100K"
    assert all("publisher" in item["classification"] for item in metrics)


def test_intents_home_headline_is_not_mislabelled_as_verified_api_volume():
    metric = parse_intents_home("$33B+ all-time volume across 38 chains")
    assert metric["all_time_volume_displayed"] == "$33B+"
    assert metric["chains_displayed"] == 38
    assert "not independently reconstructed" in metric["classification"]



def test_activity_summary_excludes_partial_current_utc_day_and_compares_full_windows():
    today = datetime.now(timezone.utc).date()
    rows = []
    for offset in range(14, 0, -1):
        day = today - timedelta(days=offset)
        rows.append({"date": day.isoformat(), "txns": 100 + (14 - offset)})
    rows.append({"date": today.isoformat(), "txns": 999_999})

    result = summarise_daily_rows(rows, ("txns",), "daily transactions")

    assert result["status"] == "available"
    assert result["latest_day"] == (today - timedelta(days=1)).isoformat()
    assert result["latest_day_is_complete_utc"] is True
    assert result["excluded_current_utc_day"] is True
    assert result["last_7d_days"] == 7
    assert result["previous_7d_days"] == 7
    assert result["last_7d_window_complete"] is True
    assert result["previous_7d_window_complete"] is True
    assert result["latest_day_value"] != 999_999


def test_tvl_anomaly_check_flags_large_daily_move_and_current_history_divergence():
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    history = []
    for day in range(10):
        value = 100 if day < 8 else (200 if day == 8 else 210)
        history.append({"date": int((base + timedelta(days=day)).timestamp()), "tvl": value})

    result = analyse_tvl_history(240, history)

    assert result["status"] == "available"
    assert result["largest_daily_move"]["change_percent"] == 100.0
    assert result["current_vs_latest_history_percent"] > 10
    assert any("single approximately daily TVL move exceeded 25%" in item for item in result["warnings"])
    assert any("differs from the latest historical observation" in item for item in result["warnings"])



def test_stablecoin_parser_reads_chain_circulating_and_historical_comparisons():
    assets = [
        {
            "name": "Example USD",
            "symbol": "EUSD",
            "pegType": "peggedUSD",
            "chainCirculating": {
                "Near": {
                    "circulating": {"peggedUSD": 1_000_000},
                    "circulatingPrevDay": {"peggedUSD": 900_000},
                    "circulatingPrevWeek": {"peggedUSD": 800_000},
                    "circulatingPrevMonth": {"peggedUSD": 500_000},
                }
            },
        },
        {
            "name": "Ethereum only",
            "symbol": "ETHUSD",
            "chainCirculating": {
                "Ethereum": {
                    "circulating": {"peggedUSD": 9_000_000},
                }
            },
        },
    ]

    rows = parse_stablecoin_chain_assets(assets, "Near")

    assert len(rows) == 1
    assert rows[0]["symbol"] == "EUSD"
    assert rows[0]["current_supply_usd"] == 1_000_000
    assert rows[0]["change_1d_percent"] == 11.11
    assert rows[0]["change_7d_percent"] == 25.0
    assert rows[0]["change_30d_percent"] == 100.0




def test_stablecoin_collector_falls_back_and_rejects_empty_primary_responses(monkeypatch):
    class FakeResponse:
        def __init__(self, status_code, payload):
            self.status_code = status_code
            self._payload = payload

        def json(self):
            return self._payload

    class FakeClient:
        def __init__(self, *args, **kwargs):
            self.requests = []

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return False

        async def get(self, url):
            self.requests.append(url)
            if url.startswith("https://api.llama.fi/"):
                return FakeResponse(404, {"error": "not found"})
            if "/stablecoincharts/" in url:
                return FakeResponse(200, [{
                    "date": int(datetime.now(timezone.utc).timestamp()),
                    "totalCirculating": 123_456_789,
                }])
            if "/stablecoins?" in url:
                return FakeResponse(200, {
                    "peggedAssets": [{
                        "name": "USD Coin",
                        "symbol": "USDC",
                        "chainCirculating": {
                            "Near": {"circulating": {"peggedUSD": 123_456_789}}
                        },
                    }]
                })
            if url.endswith("/stablecoinchains"):
                return FakeResponse(200, [
                    {"name": "Near", "totalCirculating": 123_456_789}
                ])
            raise AssertionError("Unexpected URL: " + url)

    monkeypatch.setattr(sources.httpx, "AsyncClient", FakeClient)
    result = asyncio.run(sources.collect_stablecoin_context("Near"))

    assert result["status"] == "available"
    assert result["total_supply_usd"] == 123_456_789
    assert result["asset_count"] == 1
    assert all(check["status"] == "available" for check in result["endpoint_checks"].values())
    assert all(check["url"].startswith("https://stablecoins.llama.fi/") for check in result["endpoint_checks"].values())
    assert all(check["attempts"][0]["http_status"] == 404 for check in result["endpoint_checks"].values())


def test_stablecoin_payload_validation_rejects_wrong_chain_and_empty_shapes():
    assert not sources._stablecoin_payload_has_chain_data("chain_history", [], "Near")
    assert not sources._stablecoin_payload_has_chain_data("chain_aggregate", [{"name": "Ethereum", "totalCirculating": 1}], "Near")
    assert not sources._stablecoin_payload_has_chain_data("stablecoin_catalogue", {"peggedAssets": []}, "Near")

def test_chain_selector_ignores_negated_chain_and_prefers_positive_chain():
    names = ["Stable", "Near", "Ethereum"]

    assert select_chain_from_topic(
        "Evaluate the NEAR ecosystem, including stablecoin supply and liquidity.",
        names,
        "Near",
    ) == "Near"
    assert select_chain_from_topic(
        "Analyse the NEAR ecosystem and confirm it is NEAR, not Stable.",
        names,
        "Near",
    ) == "Near"
    assert select_chain_from_topic(
        "Analyse the Stable chain, not NEAR.",
        names,
        "Near",
    ) == "Stable"
    assert select_chain_from_topic("Analyse Stable chain TVL", names, "Near") == "Stable"


def test_stablecoin_chain_aggregate_parser_matches_exact_chain_name():
    rows = [
        {"name": "Stable", "totalCirculating": 99_000_000},
        {"name": "Near", "totalCirculating": 123_456_789},
    ]
    assert parse_stablecoin_chain_aggregate(rows, "Near") == 123_456_789
    assert parse_stablecoin_chain_aggregate(rows, "Ethereum") is None



def test_near_protocol_name_does_not_trigger_defi_tvl_fallback():
    assert not _is_defi_protocol_question(
        "What are the biggest challenges currently facing NEAR Protocol, including scalability and competition?"
    )
    assert _is_defi_protocol_question(
        "Identify the top 5 DeFi protocols by TVL on NEAR."
    )
    assert _is_defi_protocol_question(
        "Compare the largest lending protocols on NEAR by TVL."
    )


def test_ecosystem_challenge_fallback_answers_requested_dimensions():
    answer = _customer_summary(
        "Assess NEAR Protocol challenges: scalability, adoption, developer activity, token economics and competition.",
        {"current_tvl_usd": 100_000_000, "change_30d_percent": -3.5},
        {
            "transaction_stats": {"status": "available", "latest_day_value": 5000, "last_7d_vs_previous_7d_percent": 4.0},
            "address_stats": {"status": "unavailable"},
        },
        {"status": "unavailable"},
        {"near_ai_documented_facts": ["NEAR AI supports confidential inference."]},
        {"projects": [], "autonomous_ai_agent_candidates": [], "agent_infrastructure": []},
    )
    assert "Scalability, token economics and L1 competition" in answer
    assert "Three critical risks" in answer
    assert "Practical growth opportunities" in answer
    assert "largest protocols" not in answer


def test_near_ai_default_model_uses_current_documented_model_id():
    assert sources.NEAR_AI_DEFAULT_MODEL == "z-ai/glm-5.3-flash"


def test_gemini_free_model_is_default():
    assert sources.GEMINI_DEFAULT_MODEL == "gemini-3.8-flash"


def test_near_ai_cloud_primary_uses_official_chat_completions_endpoint(monkeypatch):
    monkeypatch.setenv("NEAR_AI_API_KEY", "unit-test-key")
    monkeypatch.delenv("NEAR_AI_BASE_URL", raising=False)
    monkeypatch.delenv("NEAR_AI_MODEL", raising=False)

    class FakeResponse:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {
                "id": "chatcmpl-test",
                "choices": [{"message": {"content": "A question-specific NEAR AI answer."}}],
                "usage": {"prompt_tokens": 50, "completion_tokens": 20},
            }

    class FakeClient:
        request = None

        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return False

        async def post(self, url, headers=None, json=None):
            FakeClient.request = {"url": url, "headers": headers, "json": json}
            return FakeResponse()

    monkeypatch.setattr(research_module.httpx, "AsyncClient", FakeClient)
    content, metadata = asyncio.run(
        research_module._generate_near_ai_cloud_analysis(
            "How has NEAR developer activity changed?", {"nearblocks": {"active_accounts": 123}}
        )
    )

    assert content == "A question-specific NEAR AI answer."
    assert metadata["status"] == "completed"
    assert metadata["provider"] == "near_ai_cloud"
    assert FakeClient.request["url"] == "https://cloud-api.near.ai/v1/chat/completions"
    assert FakeClient.request["headers"]["Authorization"] == "Bearer unit-test-key"
    assert FakeClient.request["json"]["model"] == sources.NEAR_AI_DEFAULT_MODEL
    assert "How has NEAR developer activity changed?" in FakeClient.request["json"]["messages"][1]["content"]
    assert "active_accounts" in FakeClient.request["json"]["messages"][1]["content"]


def test_near_ai_analysis_uses_gemini_only_when_near_ai_cloud_fails(monkeypatch):
    async def near_failure(topic, context):
        return None, {
            "status": "unavailable",
            "provider": "near_ai_cloud",
            "model": "z-ai/glm-5.3-flash",
            "error": "NEAR AI Cloud API returned HTTP 401: unauthorized",
        }

    async def gemini_success(topic, context):
        return "Gemini's report for: " + topic, {
            "status": "completed",
            "provider": "google_gemini",
            "model": "gemini-3.8-flash",
        }

    monkeypatch.setattr(research_module, "_generate_near_ai_cloud_analysis", near_failure)
    monkeypatch.setattr(research_module, "_generate_gemini_analysis", gemini_success)

    content, metadata = asyncio.run(
        research_module.generate_near_ai_analysis("Compare NEAR stablecoins", {"stablecoins": {}})
    )

    assert content == "Gemini's report for: Compare NEAR stablecoins"
    assert metadata["provider"] == "google_gemini"
    assert metadata["fallback_from"] == "near_ai_cloud"
    assert "HTTP 401" in metadata["near_ai_cloud_error"]


def test_near_ai_analysis_retains_both_provider_errors_when_all_ai_fails(monkeypatch):
    async def near_failure(topic, context):
        return None, {"error": "NEAR AI Cloud returned HTTP 503: busy", "model": "model-a"}

    async def gemini_failure(topic, context):
        return None, {"error": "Gemini returned HTTP 429: quota", "model": "model-b"}

    monkeypatch.setattr(research_module, "_generate_near_ai_cloud_analysis", near_failure)
    monkeypatch.setattr(research_module, "_generate_gemini_analysis", gemini_failure)

    content, metadata = asyncio.run(
        research_module.generate_near_ai_analysis("What is NEAR?", {})
    )

    assert content is None
    assert metadata["provider"] == "near_ai_cloud+google_gemini"
    assert "HTTP 503" in metadata["near_ai_cloud_error"]
    assert "HTTP 429" in metadata["gemini_error"]
