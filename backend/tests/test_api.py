from fastapi.testclient import TestClient

from backend.app.main import app


def test_demo_order_generates_report_and_audit_events():
    with TestClient(app) as client:
        response = client.post(
            "/api/demo/run",
            json={"topic": "Assess NEAR autonomous business infrastructure"},
        )

        assert response.status_code == 200
        order = response.json()
        assert order["status"] == "report_ready_unpaid"
        assert order["data_mode"] == "synthetic_demo"
        assert order["report"]["data_mode"] == "synthetic_demo"
        assert "DEMO DATA NOTICE" in order["report"]["markdown"]

        dashboard = client.get("/api/dashboard").json()
        assert dashboard["revenue_received_usd"] == 0
        assert dashboard["payments_enabled"] is False
        assert dashboard["mainnet_execution_enabled"] is False

        ledger = client.get("/api/ledger").json()
        event_types = {event["event_type"] for event in ledger["items"]}
        assert "report_generated" in event_types
        assert "simulated_payment_quote_created" in event_types
        assert "projected_accounting_recorded" in event_types


def test_business_rejects_price_below_minimum():
    with TestClient(app) as client:
        response = client.post(
            "/api/orders",
            json={"topic": "Assess NEAR application activity", "price_usd": 2},
        )
        assert response.status_code == 409
        assert "at least" in response.json()["detail"]


def test_health_and_safety_rules():
    with TestClient(app) as client:
        assert client.get("/health").json()["ok"] is True
        rules = client.get("/api/rules").json()
        assert rules["safety"]["payments_enabled"] is False
        assert rules["safety"]["mainnet_execution_enabled"] is False
        assert rules["safety"]["kill_switch"] is False



def test_live_research_failure_is_preserved_in_audit_ledger(monkeypatch):
    from backend.app import main as main_module

    async def fail_research(topic, rules):
        raise main_module.ResearchSourceError("Public data provider unavailable.")

    monkeypatch.setattr(main_module, "generate_report", fail_research)

    with TestClient(app) as client:
        response = client.post(
            "/api/orders",
            json={"topic": "Assess NEAR ecosystem activity", "price_usd": 10},
        )
        assert response.status_code == 503
        ledger = client.get("/api/ledger").json()
        failed = [event for event in ledger["items"] if event["event_type"] == "research_failed"]
        assert failed
        assert failed[0]["details"]["reason"] == "Public data provider unavailable."


def test_live_order_returns_only_a_tidepool_dry_quote(monkeypatch):
    from backend.app import main as main_module

    async def live_report(topic, rules):
        return (
            "MERIDIAN live report",
            "# Live report\\nSource-backed test report.",
            "defillama_live",
            {"provider": "defillama", "source_urls": ["https://api.llama.fi/v2/chains"]},
        )

    async def sandbox_quote(amount_usd, settings):
        return {
            "status": "dry_quote_returned",
            "provider": "Tidepool",
            "network": "community-operated testnet sandbox",
            "quote": {
                "amount_in_formatted": "0.23",
                "amount_in_usd": "10.02",
                "amount_out_formatted": "10",
                "amount_out_usd": "10.00",
                "time_estimate_seconds": 10,
            },
            "signature_verified": False,
            "no_deposit_address": True,
            "settlement": False,
        }

    monkeypatch.setattr(main_module, "generate_report", live_report)
    monkeypatch.setattr(main_module, "create_tidepool_dry_quote", sandbox_quote)

    with TestClient(app) as client:
        response = client.post(
            "/api/orders",
            json={"topic": "Assess NEAR ecosystem activity", "price_usd": 10},
        )
        assert response.status_code == 200
        order = response.json()
        assert order["payment_quote"]["status"] == "dry_quote_returned"
        assert order["payment_quote"]["no_deposit_address"] is True
        assert order["payment_quote"]["settlement"] is False

        ledger = client.get("/api/ledger").json()
        quote_events = [
            event for event in ledger["items"]
            if event["event_type"] == "tidepool_sandbox_dry_quote_created"
        ]
        assert quote_events
        assert quote_events[0]["details"]["customer_payment_received"] is False
        assert quote_events[0]["details"]["deposit_address_created"] is False
