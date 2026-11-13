from datetime import datetime, timezone, timedelta

from backend.app.research_sources import (
    filter_chain_protocols,
    historical_change,
    parse_intents_home,
    parse_official_hub_metrics,
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

    assert historical_change(history, 7) == 66.67
    assert historical_change(history, 30) is None


def test_daily_activity_parser_recognises_metrics_and_does_not_guess():
    rows = [
        {"date": "2026-11-10", "txns": "100"},
        {"date": "2026-11-11", "txns": "110"},
        {"date": "2026-11-12", "txns": "120"},
    ]
    result = summarise_daily_rows(rows, ("transactions", "txns"), "daily transactions")
    assert result["status"] == "available"
    assert result["last_7d_total"] == 330
    assert result["source_field"] == "txns"

    unavailable = summarise_daily_rows(
        [{"date": "2026-11-12", "foo": 12}],
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
