import os
from datetime import datetime, time

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .config import load_business_rules
from .models import Order

DEMO_INFERENCE_COST_USD = 0.65


class PolicyViolation(Exception):
    pass


def current_rules() -> dict:
    rules = load_business_rules()
    limits = rules["limits"]
    split = rules["revenue_split"]
    safety = rules["safety"]
    if int(split.get("operator_percent", -1)) + int(split.get("contributors_percent", -1)) != 100:
        raise RuntimeError("Revenue split must total exactly 100 percent.")
    if float(limits.get("max_inference_spend_per_day", 0)) <= 0:
        raise RuntimeError("Daily inference budget must be greater than zero.")
    if float(limits.get("minimum_report_price", 0)) <= 0:
        raise RuntimeError("Minimum report price must be greater than zero.")
    if not isinstance(safety.get("kill_switch"), bool):
        raise RuntimeError("safety.kill_switch must be a boolean.")
    return rules


def estimated_inference_cost(rules: dict) -> float:
    research_mode = (rules.get("research") or {}).get("mode", "demo")
    if research_mode == "live":
        if os.getenv("NEAR_AI_API_KEY", "").strip():
            return max(0.0, float(os.getenv("LIVE_INFERENCE_RESERVE_USD", "0.05")))
        return 0.0
    return DEMO_INFERENCE_COST_USD


def enforce_order_policy(db: Session, price_usd: float) -> tuple[dict, float]:
    rules = current_rules()
    limits = rules["limits"]
    safety = rules["safety"]
    if safety.get("kill_switch", True):
        raise PolicyViolation("The business kill switch is enabled. New orders are paused.")

    minimum_price = float(limits["minimum_report_price"])
    if price_usd < minimum_price:
        raise PolicyViolation("Report price must be at least $" + f"{minimum_price:.2f}.")

    now = datetime.utcnow()
    day_start = datetime.combine(now.date(), time.min)
    spent_today = db.scalar(
        select(func.coalesce(func.sum(Order.inference_cost_usd), 0.0))
        .where(Order.created_at >= day_start)
        .where(Order.status != "rejected")
    ) or 0.0

    estimated_cost = estimated_inference_cost(rules)
    daily_limit = float(limits["max_inference_spend_per_day"])
    if float(spent_today) + estimated_cost > daily_limit:
        raise PolicyViolation(
            "Daily inference budget reached ($"
            + f"{float(spent_today):.2f} of $"
            + f"{daily_limit:.2f} used)."
        )
    return rules, estimated_cost
