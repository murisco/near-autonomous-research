from __future__ import annotations

import json
import os
from datetime import datetime, time
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from .config import load_business_rules
from .database import Base, engine, get_db
from .models import AuditEvent, Order, Report
from .policy import PolicyViolation, enforce_order_policy
from .research import ResearchSourceError, generate_report
from .schemas import DemoRunRequest, OrderCreate

app = FastAPI(
    title="Autonomous Onchain Intelligence Business API",
    description=(
        "Hackathon MVP API for report orders, business policy, projected accounting, "
        "and a transparent off-chain audit ledger. The current research provider is demo-only."
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
    allow_headers=["Content-Type"],
)


@app.on_event("startup")
def startup() -> None:
    Base.metadata.create_all(bind=engine)


def add_event(db: Session, order_id: str, event_type: str, details: dict) -> None:
    db.add(
        AuditEvent(
            order_id=order_id,
            event_type=event_type,
            details_json=json.dumps(details, sort_keys=True),
        )
    )


def serialize_order(order: Order, include_report: bool = False) -> dict:
    payload = {
        "id": order.id,
        "topic": order.topic,
        "buyer_email": order.buyer_email,
        "price_usd": round(order.price_usd, 2),
        "inference_cost_usd": round(order.inference_cost_usd, 2),
        "projected_profit_usd": round(order.projected_profit_usd, 2),
        "operator_share_usd": round(order.operator_share_usd, 2),
        "contributor_share_usd": round(order.contributor_share_usd, 2),
        "status": order.status,
        "data_mode": order.data_mode,
        "created_at": order.created_at.isoformat() + "Z",
    }
    if include_report and order.report:
        payload["report"] = {
            "id": order.report.id,
            "title": order.report.title,
            "markdown": order.report.markdown,
            "data_mode": order.report.data_mode,
            "created_at": order.report.created_at.isoformat() + "Z",
        }
    return payload


async def process_order(db: Session, request: OrderCreate) -> dict:
    try:
        rules, inference_cost = enforce_order_policy(db, request.price_usd)
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
    try:
        title, markdown, data_mode, research_meta = await generate_report(request.topic, rules)
    except ResearchSourceError as exc:
        db.rollback()
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    order.data_mode = data_mode
    add_event(
        db,
        order_id,
        "research_started",
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
    add_event(
        db,
        order_id,
        "simulated_payment_quote_created",
        {
            "amount_usd": round(request.price_usd, 2),
            "status": "simulation_only",
            "near_intents_called": False,
            "reason": "Payment integration is not enabled in this build.",
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
    return serialize_order(order, include_report=True)


@app.get("/health")
def health() -> dict:
    return {"ok": True, "service": "autonomous-onchain-intelligence-api", "version": "0.1.0"}


@app.get("/api/rules")
def get_rules() -> dict:
    try:
        return load_business_rules()
    except (OSError, RuntimeError) as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/api/dashboard")
def dashboard(db: Session = Depends(get_db)) -> dict:
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
    return {
        "orders": orders_count,
        "reports_generated": reports_count,
        "quoted_sales_usd": round(float(quoted_sales), 2),
        "revenue_received_usd": 0.0,
        "simulated_inference_spend_usd": round(float(inference_spend), 2),
        "projected_profit_usd": round(float(projected_profit), 2),
        "today_inference_budget_usd": float(rules["limits"]["max_inference_spend_per_day"]),
        "today_inference_spend_usd": round(float(today_spend), 2),
        "payments_enabled": bool(rules["safety"]["payments_enabled"]),
        "mainnet_execution_enabled": bool(rules["safety"]["mainnet_execution_enabled"]),
        "data_mode": "synthetic_demo",
    }


@app.post("/api/orders")
async def create_order(request: OrderCreate, db: Session = Depends(get_db)) -> dict:
    return await process_order(db, request)


@app.post("/api/demo/run")
async def run_demo(request: DemoRunRequest, db: Session = Depends(get_db)) -> dict:
    demo_request = OrderCreate(topic=request.topic, price_usd=10.0)
    return await process_order(db, demo_request)


@app.get("/api/orders")
def list_orders(limit: int = 50, db: Session = Depends(get_db)) -> dict:
    limit = max(1, min(limit, 100))
    orders = db.scalars(
        select(Order).options(joinedload(Order.report)).order_by(Order.created_at.desc()).limit(limit)
    ).unique().all()
    return {"items": [serialize_order(order) for order in orders], "count": len(orders)}


@app.get("/api/orders/{order_id}")
def get_order(order_id: str, db: Session = Depends(get_db)) -> dict:
    order = db.scalar(
        select(Order).options(joinedload(Order.report)).where(Order.id == order_id)
    )
    if not order:
        raise HTTPException(status_code=404, detail="Order not found.")
    return serialize_order(order, include_report=True)


@app.get("/api/ledger")
def ledger(limit: int = 100, db: Session = Depends(get_db)) -> dict:
    limit = max(1, min(limit, 250))
    events = db.scalars(
        select(AuditEvent).order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc()).limit(limit)
    ).all()
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
