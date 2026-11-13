from datetime import datetime, timezone, timedelta

from backend.app.research_sources import (
    analyse_tvl_history,
    filter_chain_protocols,
    historical_change,
    parse_intents_home,
    parse_official_hub_metrics,
    parse_stablecoin_chain_assets,
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



def test_chain_selector_does_not_match_stable_inside_stablecoin():
    names = ["Stable", "Near", "Ethereum"]

    selected = select_chain_from_topic(
        "Evaluate the NEAR ecosystem, including stablecoin supply and liquidity.",
        names,
        "Near",
    )

    assert selected == "Near"
    assert select_chain_from_topic(
        "Analyse the NEAR ecosystem and confirm it is NEAR, not Stable.",
        names,
        "Near",
    ) == "Near"
    assert select_chain_from_topic("Analyse Stable chain TVL", names, "Near") == "Stable"
