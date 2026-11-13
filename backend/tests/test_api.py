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
