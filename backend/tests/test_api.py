from fastapi.testclient import TestClient

from backend.app.main import app


POST_HEADERS = {"X-Meridian-Requested": "1"}


def configure_near_auth(monkeypatch):
    from backend.app import main as main_module

    monkeypatch.setenv("MERIDIAN_ADMIN_ACCOUNT_IDS", "owner.near")

    def valid_signature(*args):
        return True

    async def has_full_access(account_id, public_key):
        return True

    monkeypatch.setattr(main_module, "verify_nep413_signature", valid_signature)
    monkeypatch.setattr(main_module, "account_has_full_access_key", has_full_access)


def sign_in(client, account_id):
    requested = client.post("/api/auth/nonce", json={}, headers=POST_HEADERS)
    assert requested.status_code == 200, requested.text
    challenge = requested.json()
    verified = client.post(
        "/api/auth/verify",
        json={
            "challenge_id": challenge["challenge_id"],
            "account_id": account_id,
            "public_key": "ed25519:" + "1" * 44,
            "signature": "A" * 88,
        },
        headers=POST_HEADERS,
    )
    assert verified.status_code == 200, verified.text
    return verified.json()


def test_demo_order_generates_report_and_audit_events(monkeypatch):
    configure_near_auth(monkeypatch)
    with TestClient(app, base_url="https://testserver") as client:
        sign_in(client, "owner.near")
        response = client.post(
            "/api/demo/run",
            json={"topic": "Assess NEAR autonomous business infrastructure"},
            headers=POST_HEADERS,
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


def test_business_rejects_price_below_minimum(monkeypatch):
    configure_near_auth(monkeypatch)
    with TestClient(app, base_url="https://testserver") as client:
        sign_in(client, "owner.near")
        response = client.post(
            "/api/orders",
            json={"topic": "Assess NEAR application activity", "price_usd": 2},
            headers=POST_HEADERS,
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
        assert client.get("/api/dashboard").status_code == 401


def test_live_research_failure_is_preserved_in_audit_ledger(monkeypatch):
    from backend.app import main as main_module

    configure_near_auth(monkeypatch)

    async def fail_research(topic, rules):
        raise main_module.ResearchSourceError("Public data provider unavailable.")

    monkeypatch.setattr(main_module, "generate_report", fail_research)

    with TestClient(app, base_url="https://testserver") as client:
        sign_in(client, "owner.near")
        response = client.post(
            "/api/orders",
            json={"topic": "Assess NEAR ecosystem activity", "price_usd": 10},
            headers=POST_HEADERS,
        )
        assert response.status_code == 503
        ledger = client.get("/api/ledger").json()
        failed = [event for event in ledger["items"] if event["event_type"] == "research_failed"]
        assert failed
        assert failed[0]["details"]["reason"] == "Public data provider unavailable."


def test_live_order_returns_only_a_tidepool_dry_quote(monkeypatch):
    from backend.app import main as main_module

    configure_near_auth(monkeypatch)

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

    with TestClient(app, base_url="https://testserver") as client:
        sign_in(client, "owner.near")
        response = client.post(
            "/api/orders",
            json={"topic": "Assess NEAR ecosystem activity", "price_usd": 10},
            headers=POST_HEADERS,
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


def test_customers_cannot_read_other_customers_orders_or_admin_data(monkeypatch):
    from backend.app import main as main_module

    configure_near_auth(monkeypatch)

    async def demo_report(topic, rules):
        return (
            "Private customer report",
            "# Private report\\nThis report belongs to one customer.",
            "multi_source_live",
            {"provider": "test", "source_urls": []},
        )

    async def no_payment_quote(amount_usd, settings):
        return {
            "status": "fallback",
            "reason": "Payment preview disabled in this test.",
            "no_deposit_address": True,
            "settlement": False,
        }

    monkeypatch.setattr(main_module, "generate_report", demo_report)
    monkeypatch.setattr(main_module, "create_tidepool_dry_quote", no_payment_quote)

    with TestClient(app, base_url="https://testserver") as client:
        sign_in(client, "customer-one.near")
        created = client.post(
            "/api/orders",
            json={"topic": "Research for customer one on NEAR", "price_usd": 10},
            headers=POST_HEADERS,
        )
        assert created.status_code == 200, created.text
        private_order_id = created.json()["id"]
        assert "buyer_account_id" not in created.json()
        assert "projected_profit_usd" not in created.json()

        client.post("/api/auth/logout", headers=POST_HEADERS)
        sign_in(client, "customer-two.near")
        assert client.get("/api/orders").json()["items"] == []
        assert client.get(f"/api/orders/{private_order_id}").status_code == 404
        assert client.get("/api/dashboard").status_code == 403
        assert client.get("/api/ledger").json()["items"] == []

        client.post("/api/auth/logout", headers=POST_HEADERS)
        sign_in(client, "owner.near")
        assert client.get("/api/orders").json()["count"] >= 1
        assert client.get("/api/dashboard").status_code == 200


def test_near_wallet_sign_in_requires_browser_request_header(monkeypatch):
    configure_near_auth(monkeypatch)
    with TestClient(app) as client:
        response = client.post("/api/auth/nonce", json={})
        assert response.status_code == 403


def test_near_challenge_is_single_use(monkeypatch):
    configure_near_auth(monkeypatch)
    with TestClient(app) as client:
        requested = client.post("/api/auth/nonce", json={}, headers=POST_HEADERS)
        challenge = requested.json()
        payload = {
            "challenge_id": challenge["challenge_id"],
            "account_id": "customer.near",
            "public_key": "ed25519:" + "1" * 44,
            "signature": "A" * 88,
        }
        first = client.post("/api/auth/verify", json=payload, headers=POST_HEADERS)
        assert first.status_code == 200, first.text
        replay = client.post("/api/auth/verify", json=payload, headers=POST_HEADERS)
        assert replay.status_code == 400


def test_near_wallet_login_rejects_non_full_access_key(monkeypatch):
    from backend.app import main as main_module

    configure_near_auth(monkeypatch)

    async def no_full_access(account_id, public_key):
        return False

    monkeypatch.setattr(main_module, "account_has_full_access_key", no_full_access)
    with TestClient(app) as client:
        challenge = client.post("/api/auth/nonce", json={}, headers=POST_HEADERS).json()
        response = client.post(
            "/api/auth/verify",
            json={
                "challenge_id": challenge["challenge_id"],
                "account_id": "customer.near",
                "public_key": "ed25519:" + "1" * 44,
                "signature": "A" * 88,
            },
            headers=POST_HEADERS,
        )
        assert response.status_code == 401
        assert "full-access key" in response.json()["detail"]
