from __future__ import annotations

import json
import os
from datetime import datetime, time, timedelta
from uuid import uuid4
import secrets
import hmac

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from .config import load_business_rules
from .database import Base, engine, get_db
from .models import AuditEvent, AuthSession, EmailLoginCode, Order, Report
from .payments import create_tidepool_dry_quote
from .policy import PolicyViolation, enforce_order_policy
from .research import ResearchSourceError, generate_report
from .schemas import DemoRunRequest, EmailCodeRequest, OrderCreate, VerifyEmailCodeRequest
from .auth import (
    LOGIN_CODE_TTL_MINUTES, SESSION_COOKIE, SESSION_TTL_SECONDS,
    code_digest, deliver_login_code, is_admin_email, secure_cookie, token_digest,
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
    role = "admin" if is_admin_email(session.email) else "customer"
    return {"email": session.email, "role": role}


def require_admin(user: dict = Depends(get_current_user)) -> dict:
    if user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Administrator access is required.")
    return user


@app.post("/api/auth/request-code", dependencies=[Depends(require_browser_request)])
async def request_email_code(payload: EmailCodeRequest, db: Session = Depends(get_db)) -> dict:
    now = datetime.utcnow()
    try:
        from .auth import auth_secret
        auth_secret()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail="Email sign-in is not configured yet.") from exc

    recent_count = db.scalar(
        select(func.count(EmailLoginCode.id)).where(
            EmailLoginCode.email == payload.email,
            EmailLoginCode.created_at >= now - timedelta(hours=1),
        )
    ) or 0
    latest = db.scalar(
        select(EmailLoginCode)
        .where(EmailLoginCode.email == payload.email)
        .order_by(EmailLoginCode.created_at.desc())
        .limit(1)
    )
    if latest and latest.created_at >= now - timedelta(seconds=60):
        raise HTTPException(status_code=429, detail="Please wait a minute before requesting another code.")
    if recent_count >= 5:
        raise HTTPException(status_code=429, detail="Too many sign-in codes requested. Try again in an hour.")

    active_codes = db.scalars(
        select(EmailLoginCode).where(
            EmailLoginCode.email == payload.email,
            EmailLoginCode.consumed_at.is_(None),
        )
    ).all()
    for existing in active_codes:
        existing.consumed_at = now

    code = f"{secrets.randbelow(1_000_000):06d}"
    salt = secrets.token_hex(16)
    db.add(
        EmailLoginCode(
            id=str(uuid4()),
            email=payload.email,
            code_hash=code_digest(payload.email, code, salt),
            salt=salt,
            attempts=0,
            expires_at=now + timedelta(minutes=LOGIN_CODE_TTL_MINUTES),
        )
    )
    try:
        await deliver_login_code(payload.email, code)
        db.commit()
    except Exception as exc:
        db.rollback()
        raise HTTPException(
            status_code=503,
            detail="We could not send the sign-in email. Please check the email service configuration and try again.",
        ) from exc
    return {"ok": True, "message": "A sign-in code has been sent to your email address."}


@app.post("/api/auth/verify-code", dependencies=[Depends(require_browser_request)])
def verify_email_code(
    payload: VerifyEmailCodeRequest,
    response: Response,
    db: Session = Depends(get_db),
) -> dict:
    try:
        from .auth import auth_secret
        auth_secret()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail="Email sign-in is not configured yet.") from exc

    now = datetime.utcnow()
    login_code = db.scalar(
        select(EmailLoginCode)
        .where(
            EmailLoginCode.email == payload.email,
            EmailLoginCode.consumed_at.is_(None),
        )
        .order_by(EmailLoginCode.created_at.desc())
        .limit(1)
    )
    if not login_code or login_code.expires_at <= now:
        raise HTTPException(status_code=400, detail="That code has expired. Request a new one.")
    if login_code.attempts >= 5:
        raise HTTPException(status_code=429, detail="Too many incorrect attempts. Request a new code.")

    login_code.attempts += 1
    expected = code_digest(payload.email, payload.code, login_code.salt)
    if not hmac.compare_digest(login_code.code_hash, expected):
        db.commit()
        raise HTTPException(status_code=400, detail="That code is incorrect.")

    login_code.consumed_at = now
    raw_token = secrets.token_urlsafe(32)
    db.add(
        AuthSession(
            id=str(uuid4()),
            email=payload.email,
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
    return {"ok": True, "email": payload.email, "role": "admin" if is_admin_email(payload.email) else "customer"}


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
            "buyer_email": order.buyer_email,
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
        buyer_email=request.buyer_email,
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
    owned_request = request.model_copy(update={"buyer_email": user["email"]})
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
        query = query.where(Order.buyer_email == user["email"])
    orders = db.scalars(query.limit(limit)).unique().all()
    return {"items": [serialize_order(order, admin=user["role"] == "admin") for order in orders], "count": len(orders)}


@app.get("/api/orders/{order_id}")
def get_order(order_id: str, db: Session = Depends(get_db), user: dict = Depends(get_current_user)) -> dict:
    order = db.scalar(
        select(Order).options(joinedload(Order.report)).where(Order.id == order_id)
    )
    if not order or (user["role"] != "admin" and order.buyer_email != user["email"]):
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
        query = query.join(Order, AuditEvent.order_id == Order.id).where(Order.buyer_email == user["email"])
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
