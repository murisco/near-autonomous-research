from __future__ import annotations

import os
from pathlib import Path

import yaml

ROOT_DIR = Path(__file__).resolve().parents[2]
DEFAULT_RULES_PATH = ROOT_DIR / "config" / "business-rules.yaml"


def database_url() -> str:
    return os.getenv("DATABASE_URL", "sqlite:///./data.db")


def load_business_rules() -> dict:
    rules_path = Path(os.getenv("BUSINESS_RULES_PATH", str(DEFAULT_RULES_PATH)))
    if not rules_path.is_absolute():
        rules_path = ROOT_DIR / rules_path
    if not rules_path.exists():
        raise RuntimeError(f"Business rules file not found: {rules_path}")
    with rules_path.open("r", encoding="utf-8") as file:
        rules = yaml.safe_load(file) or {}
    required_sections = ("limits", "revenue_split", "safety")
    missing = [section for section in required_sections if section not in rules]
    if missing:
        raise RuntimeError(f"Business rules missing sections: {', '.join(missing)}")
    return rules
