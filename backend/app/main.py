from __future__ import annotations

import json
import os
from datetime import datetime, time, timedelta
from uuid import uuid4
import secrets
import httpx

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import func, inspect, select, text
from sqlalchemy.orm import Session, joinedload

from .config import load_business_rules
from .database import Base, engine, get_db
from .models import AuditEvent, AuthSession, NearLoginChallenge, Order, Report
from .payments import create_tidepool_dry_quote
from .policy import PolicyViolation, enforce_order_policy
from .research import ResearchSourceError, generate_report
from .schemas import DemoRunRequest, NearAuthVerifyRequest, OrderCreate
from .auth import SESSION_COOKIE, SESSION_TTL_SECONDS, secure_cookie, token_digest
from .near_auth import (
    account_has_full_access_key, auth_recipient,
    is_admin_account, valid_account_id, verify_nep413_signature,
)

app = FastAPI(
    title="MERIDIAN Autonomous Intelligence Business API",
    description=(
        "API for MERIDIAN report orders, source-backed research, business policy, projected accounting, "
        "and an off-chain audit ledger. Payment settlement and payouts are not enabled."
    ),
    version="0.1.0",
)

origins = [
    item.strip()
    for item in os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",")
    if item.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "X-Meridian-Requested"],
)


@app.on_event("startup")
def startup() -> None:
    Base.metadata.create_all(bind=engine)
    # Additive migration for existing Railway databases; no customer data is removed.
    with engine.begin() as connection:
        order_columns = {column["name"] for column in inspect(connection).get_columns("orders")}
        if "buyer_account_id" not in order_columns:
            connection.execute(text("ALTER TABLE orders ADD COLUMN buyer_account_id VARCHAR(128)"))
        session_columns = {column["name"] for column in inspect(connection).get_columns("auth_sessions")}
        if "account_id" not in session_columns:
            connection.execute(text("ALTER TABLE auth_sessions ADD COLUMN account_id VARCHAR(128)"))


def require_browser_request(request: Request) -> None:
    if request.headers.get("x-meridian-requested") != "1":
        raise HTTPException(status_code=403, detail="Request origin could not be verified.")


def get_current_user(request: Request, db: Session = Depends(get_db)) -> dict:
    raw_token = request.cookies.get(SESSION_COOKIE)
    if not raw_token:
        raise HTTPException(status_code=401, detail="Please sign in to continue.")
    session = db.scalar(
        select(AuthSession).where(
            AuthSession.token_hash == token_digest(raw_token),
            AuthSession.expires_at > datetime.utcnow(),
        )
    )
    if not session:
        raise HTTPException(status_code=401, detail="Your session has expired. Please sign in again.")
    if not session.account_id:
        raise HTTPException(status_code=401, detail="This legacy email session is no longer valid. Sign in with your NEAR wallet.")
    role = "admin" if is_admin_account(session.account_id) else "customer"
    return {"account_id": session.account_id, "role": role}


def require_admin(user: dict = Depends(get_current_user)) -> dict:
    if user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Administrator access is required.")
    return user


@app.post("/api/auth/nonce", dependencies=[Depends(require_browser_request)])
def create_near_login_nonce(db: Session = Depends(get_db)) -> dict:
    now = datetime.utcnow()
    challenge_id = str(uuid4())
    nonce_b64 = __import__("base64").b64encode(secrets.token_bytes(32)).decode("ascii")
    recipient = auth_recipient()
    expires_at = now + timedelta(minutes=5)
    issued = now.replace(microsecond=0).isoformat() + "Z"
    expires = expires_at.replace(microsecond=0).isoformat() + "Z"
    message = (
        "Sign in to MERIDIAN (identity only).\\n"
        f"Website: https://{recipient}\\n"
        "Purpose: Prove control of the NEAR account selected in your wallet.\\n"
        f"Challenge: {challenge_id}\\n"
        f"Issued: {issued}\\n"
        f"Expires: {expires}\\n\\n"
        "This is an off-chain message signature only. It does not approve a transaction, "
        "transfer tokens, grant an allowance, or authorize a payment."
    )
    db.add(
        NearLoginChallenge(
            id=challenge_id,
            nonce_b64=nonce_b64,
            message=message,
            recipient=recipient,
            expires_at=expires_at,
        )
    )
    db.commit()
    return {
        "challenge_id": challenge_id,
        "nonce": nonce_b64,
        "message": message,
        "recipient": recipient,
        "expires_at": expires,
        "network": "mainnet",
    }


@app.post("/api/auth/verify", dependencies=[Depends(require_browser_request)])
async def verify_near_login(
    payload: NearAuthVerifyRequest,
    response: Response,
    db: Session = Depends(get_db),
) -> dict:
    challenge = db.scalar(
        select(NearLoginChallenge).where(
            NearLoginChallenge.id == payload.challenge_id,
            NearLoginChallenge.consumed_at.is_(None),
        )
    )
    now = datetime.utcnow()
    if not challenge or challenge.expires_at <= now:
        raise HTTPException(status_code=400, detail="That login request has expired. Please try again.")
    if not valid_account_id(payload.account_id):
        raise HTTPException(status_code=400, detail="The wallet returned an invalid NEAR account ID.")

    valid_signature = verify_nep413_signature(
        challenge.message,
        challenge.nonce_b64,
        challenge.recipient,
        payload.public_key,
        payload.signature,
    )
    if not valid_signature:
        raise HTTPException(status_code=401, detail="NEAR message signature could not be verified.")

    try:
        full_access = await account_has_full_access_key(payload.account_id, payload.public_key)
    except (httpx.HTTPError, RuntimeError, ValueError) as exc:
        raise HTTPException(
            status_code=503,
            detail="NEAR RPC is temporarily unavailable. No session was created; please try again.",
        ) from exc
    if not full_access:
        raise HTTPException(
            status_code=401,
            detail="The signing key is not a current full-access key for this NEAR account.",
        )

    # Consume the challenge before creating a session so the same signature cannot be replayed.
    challenge.consumed_at = now
    raw_token = secrets.token_urlsafe(32)
    db.add(
        AuthSession(
            id=str(uuid4()),
            email="",  # Legacy non-null column retained for an additive database migration.
            account_id=payload.account_id,
            token_hash=token_digest(raw_token),
            expires_at=now + timedelta(seconds=SESSION_TTL_SECONDS),
        )
    )
    db.commit()
    response.set_cookie(
        key=SESSION_COOKIE,
        value=raw_token,
        max_age=SESSION_TTL_SECONDS,
        httponly=True,
        secure=secure_cookie(),
        samesite="lax",
        path="/",
    )
    return {
        "ok": True,
        "account_id": payload.account_id,
        "role": "admin" if is_admin_account(payload.account_id) else "customer",
    }


@app.get("/api/auth/me")
def auth_me(user: dict = Depends(get_current_user)) -> dict:
    return user


@app.post("/api/auth/logout", dependencies=[Depends(require_browser_request)])
def logout(request: Request, response: Response, db: Session = Depends(get_db)) -> dict:
    raw_token = request.cookies.get(SESSION_COOKIE)
    if raw_token:
        session = db.scalar(select(AuthSession).where(AuthSession.token_hash == token_digest(raw_token)))
        if session:
            db.delete(session)
            db.commit()
    response.delete_cookie(
        key=SESSION_COOKIE,
        path="/",
        httponly=True,
        secure=secure_cookie(),
        samesite="lax",
    )
    return {"ok": True}


def add_event(db: Session, order_id: str, event_type: str, details: dict) -> None:
    db.add(
        AuditEvent(
            order_id=order_id,
            event_type=event_type,
            details_json=json.dumps(details, sort_keys=True),
        )
    )


def serialize_order(order: Order, include_report: bool = False, admin: bool = False) -> dict:
    payload = {
        "id": order.id,
        "topic": order.topic,
        "price_usd": round(order.price_usd, 2),
        "status": order.status,
        "data_mode": order.data_mode,
        "created_at": order.created_at.isoformat() + "Z",
    }
    if admin:
        payload.update({
            "buyer_account_id": order.buyer_account_id,
            "inference_cost_usd": round(order.inference_cost_usd, 2),
            "projected_profit_usd": round(order.projected_profit_usd, 2),
            "operator_share_usd": round(order.operator_share_usd, 2),
            "contributor_share_usd": round(order.contributor_share_usd, 2),
        })
    if include_report and order.report:
        payload["report"] = {
            "id": order.report.id,
            "title": order.report.title,
            "markdown": order.report.markdown,
            "data_mode": order.report.data_mode,
            "created_at": order.report.created_at.isoformat() + "Z",
        }
    return payload


async def process_order(db: Session, request: OrderCreate, force_demo: bool = False) -> dict:
    try:
        rules, inference_cost = enforce_order_policy(
            db, request.price_usd, research_mode_override="demo" if force_demo else None
        )
    except PolicyViolation as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    order_id = str(uuid4())
    report_id = str(uuid4())
    split = rules["revenue_split"]

    order = Order(
        id=order_id,
        topic=request.topic,
        buyer_email=None,
        buyer_account_id=request.buyer_account_id,
        price_usd=request.price_usd,
        inference_cost_usd=inference_cost,
        status="researching",
        data_mode="synthetic_demo",
    )
    db.add(order)
    db.flush()  # Ensure the order exists before its audit events are inserted.
    add_event(
        db,
        order_id,
        "order_received",
        {"quoted_price_usd": round(request.price_usd, 2), "topic": request.topic},
    )
    add_event(
        db,
        order_id,
        "policy_approved",
        {
            "kill_switch": rules["safety"]["kill_switch"],
            "estimated_inference_cost_usd": inference_cost,
            "daily_inference_limit_usd": float(rules["limits"]["max_inference_spend_per_day"]),
        },
    )
    add_event(db, order_id, "research_started", {"mode": (rules.get("research") or {}).get("mode", "demo")})
    try:
        title, markdown, data_mode, research_meta = await generate_report(request.topic, rules)
    except ResearchSourceError as exc:
        order.status = "research_failed"
        order.data_mode = "research_failed"
        add_event(
            db,
            order_id,
            "research_failed",
            {
                "mode": (rules.get("research") or {}).get("mode", "demo"),
                "reason": str(exc),
            },
        )
        db.commit()
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    order.data_mode = data_mode
    add_event(
        db,
        order_id,
        "research_completed",
        {"provider": research_meta.get("provider"), "data_mode": data_mode},
    )
    profit = max(0.0, request.price_usd - inference_cost)
    operator_share = round(profit * int(split["operator_percent"]) / 100, 2)
    contributor_share = round(profit - operator_share, 2)

    report = Report(
        id=report_id,
        order_id=order_id,
        title=title,
        markdown=markdown,
        data_mode=data_mode,
    )
    order.projected_profit_usd = profit
    order.operator_share_usd = operator_share
    order.contributor_share_usd = contributor_share
    order.status = "report_ready_unpaid"
    db.add(report)

    add_event(
        db,
        order_id,
        "report_generated",
        {"report_id": report_id, "data_mode": data_mode},
    )
    add_event(db, order_id, "research_sources_recorded", research_meta)
    payment_settings = rules.get("payments") or {}
    if force_demo:
        payment_quote = {
            "status": "simulation_only",
            "provider": "none",
            "reason": "Deterministic CI/demo path does not make external quote requests.",
            "no_deposit_address": True,
            "settlement": False,
        }
    else:
        payment_quote = await create_tidepool_dry_quote(request.price_usd, payment_settings)

    quote_event_type = (
        "tidepool_sandbox_dry_quote_created"
        if payment_quote.get("status") == "dry_quote_returned"
        else "simulated_payment_quote_created"
    )
    add_event(
        db,
        order_id,
        quote_event_type,
        {
            "invoice_quote_usd": round(request.price_usd, 2),
            "payment_quote": payment_quote,
            "near_intents_production_called": False,
            "deposit_address_created": False,
            "customer_payment_received": False,
        },
    )
    add_event(
        db,
        order_id,
        "projected_accounting_recorded",
        {
            "inference_cost_usd": round(inference_cost, 2),
            "projected_profit_usd": round(profit, 2),
            "operator_share_usd": operator_share,
            "contributor_share_usd": contributor_share,
            "revenue_received_usd": 0,
        },
    )
    add_event(
        db,
        order_id,
        "report_preview_available",
        {"status": order.status, "customer_payment_received": False},
    )

    db.commit()
    db.refresh(order)
    db.refresh(report)
    order.report = report
    response_payload = serialize_order(order, include_report=True)
    response_payload["payment_quote"] = payment_quote
    return response_payload


@app.get("/health")
def health() -> dict:
    return {"ok": True, "service": "meridian-api", "version": "0.1.0"}


@app.get("/api/rules")
def get_rules() -> dict:
    try:
        return load_business_rules()
    except (OSError, RuntimeError) as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/api/dashboard")
def dashboard(db: Session = Depends(get_db), user: dict = Depends(require_admin)) -> dict:
    orders_count = db.scalar(select(func.count(Order.id))) or 0
    reports_count = db.scalar(select(func.count(Report.id))) or 0
    quoted_sales = db.scalar(select(func.coalesce(func.sum(Order.price_usd), 0.0))) or 0.0
    inference_spend = db.scalar(
        select(func.coalesce(func.sum(Order.inference_cost_usd), 0.0))
    ) or 0.0
    projected_profit = db.scalar(
        select(func.coalesce(func.sum(Order.projected_profit_usd), 0.0))
    ) or 0.0
    today_start = datetime.combine(datetime.utcnow().date(), time.min)
    today_spend = db.scalar(
        select(func.coalesce(func.sum(Order.inference_cost_usd), 0.0))
        .where(Order.created_at >= today_start)
    ) or 0.0
    rules = load_business_rules()
    latest_order = db.scalar(select(Order).order_by(Order.created_at.desc()).limit(1))
    return {
        "orders": orders_count,
        "reports_generated": reports_count,
        "quoted_sales_usd": round(float(quoted_sales), 2),
        "revenue_received_usd": 0.0,
        "estimated_inference_spend_usd": round(float(inference_spend), 2),
        "projected_profit_usd": round(float(projected_profit), 2),
        "today_inference_budget_usd": float(rules["limits"]["max_inference_spend_per_day"]),
        "today_estimated_inference_spend_usd": round(float(today_spend), 2),
        "payments_enabled": bool(rules["safety"]["payments_enabled"]),
        "mainnet_execution_enabled": bool(rules["safety"]["mainnet_execution_enabled"]),
        "data_mode": latest_order.data_mode if latest_order else "no_orders",
        "research_mode": (rules.get("research") or {}).get("mode", "demo"),
        "near_ai_cloud_configured": bool(os.getenv("NEAR_AI_API_KEY", "").strip()),
    }


@app.post("/api/orders", dependencies=[Depends(require_browser_request)])
async def create_order(request: OrderCreate, db: Session = Depends(get_db), user: dict = Depends(get_current_user)) -> dict:
    owned_request = request.model_copy(update={"buyer_email": None, "buyer_account_id": user["account_id"]})
    result = await process_order(db, owned_request)
    if user["role"] == "admin":
        order = db.scalar(select(Order).where(Order.id == result["id"]))
        if order:
            result = serialize_order(order, include_report=True, admin=True) | {"payment_quote": result.get("payment_quote")}
    return result


@app.post("/api/demo/run", dependencies=[Depends(require_browser_request)])
async def run_demo(request: DemoRunRequest, db: Session = Depends(get_db), user: dict = Depends(require_admin)) -> dict:
    demo_request = OrderCreate(topic=request.topic, price_usd=10.0)
    return await process_order(db, demo_request, force_demo=True)


@app.get("/api/orders")
def list_orders(limit: int = 50, db: Session = Depends(get_db), user: dict = Depends(get_current_user)) -> dict:
    limit = max(1, min(limit, 100))
    query = select(Order).options(joinedload(Order.report)).order_by(Order.created_at.desc())
    if user["role"] != "admin":
        query = query.where(Order.buyer_account_id == user["account_id"])
    orders = db.scalars(query.limit(limit)).unique().all()
    return {"items": [serialize_order(order, admin=user["role"] == "admin") for order in orders], "count": len(orders)}


@app.get("/api/orders/{order_id}")
def get_order(order_id: str, db: Session = Depends(get_db), user: dict = Depends(get_current_user)) -> dict:
    order = db.scalar(
        select(Order).options(joinedload(Order.report)).where(Order.id == order_id)
    )
    if not order or (user["role"] != "admin" and order.buyer_account_id != user["account_id"]):
        raise HTTPException(status_code=404, detail="Order not found.")
    payload = serialize_order(order, include_report=True, admin=user["role"] == "admin")
    quote_event = db.scalar(
        select(AuditEvent)
        .where(
            AuditEvent.order_id == order_id,
            AuditEvent.event_type.in_(
                ["tidepool_sandbox_dry_quote_created", "simulated_payment_quote_created"]
            ),
        )
        .order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc())
        .limit(1)
    )
    if quote_event:
        try:
            quote_details = json.loads(quote_event.details_json)
            payload["payment_quote"] = quote_details.get("payment_quote")
        except (json.JSONDecodeError, AttributeError):
            payload["payment_quote"] = None
    return payload


@app.get("/api/ledger")
def ledger(limit: int = 100, db: Session = Depends(get_db), user: dict = Depends(get_current_user)) -> dict:
    limit = max(1, min(limit, 250))
    query = select(AuditEvent).order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc())
    if user["role"] != "admin":
        query = query.join(Order, AuditEvent.order_id == Order.id).where(Order.buyer_account_id == user["account_id"])
    events = db.scalars(query.limit(limit)).all()
    items = []
    for event in events:
        try:
            details = json.loads(event.details_json)
        except json.JSONDecodeError:
            details = {"raw": event.details_json}
        items.append(
            {
                "id": event.id,
                "order_id": event.order_id,
                "event_type": event.event_type,
                "details": details,
                "created_at": event.created_at.isoformat() + "Z",
                "record_type": "offchain_audit_event",
            }
        )
    return {"items": items, "count": len(items)}
