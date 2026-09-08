#!/usr/bin/env python3
"""שכבת התצורה (סעיף 3 באפיון) - טעינת rates.json / rules.json / fees.json.

עקרון־העל (סעיף 0): המנוע לא ממציא מספרים. כל מספר שמוצג למשתמש חייב
להיות ניתן להתחקות למקור בתצורה ולתאריך העדכון שלו. הקובץ הזה אחראי על:
- טעינת שלושת קבצי התצורה
- בדיקת "רעננות" (שדה שלא עודכן מעל 45 יום מסומן כישן)
- מיזוג כללי מחזור (פנימי/חיצוני) מעל newLoan לפי סעיף 3.4
- MissingConfigError - כשמבקשים שדה שלא קיים, לא ממציאים ברירת מחדל שקטה
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Optional

STALE_AFTER_DAYS = 45

DEFAULT_DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "mortgage"


class MissingConfigError(Exception):
    """נזרקת כשמבקשים ערך תצורה שלא קיים - המנוע לעולם לא משלים בשקט."""


@dataclass
class Freshness:
    updated_at: Optional[str]
    days_old: Optional[int]
    is_stale: bool
    label: str


def _parse_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def check_freshness(data: dict, as_of: Optional[date] = None) -> Freshness:
    as_of = as_of or date.today()
    updated_at = data.get("updatedAt")
    if not updated_at:
        return Freshness(None, None, True, "אין תאריך עדכון בתצורה - לא ניתן לאמת רעננות")
    d = _parse_date(updated_at)
    days_old = (as_of - d).days
    is_stale = days_old > STALE_AFTER_DAYS
    label = f"מחושב לפי תצורה מתאריך {updated_at}"
    if is_stale:
        label += f" (ישן - {days_old} ימים, מעל הסף של {STALE_AFTER_DAYS} ימים)"
    return Freshness(updated_at, days_old, is_stale, label)


def _load_json(path: Path) -> dict:
    if not path.exists():
        raise MissingConfigError(f"חסר קובץ תצורה: {path.name}")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


@dataclass
class ConfigBundle:
    rates: dict
    rules: dict
    fees: dict
    rates_freshness: Freshness
    rules_freshness: Freshness
    fees_freshness: Freshness

    def get_bank(self, bank_id: str) -> dict:
        for bank in self.rates.get("banks", []):
            if bank.get("id") == bank_id:
                return bank
        raise MissingConfigError(f"חסר נתון: בנק לא מוגדר בתצורה: {bank_id}")

    def banks(self) -> list:
        return self.rates.get("banks", [])


def load_config(data_dir: Optional[Path] = None) -> ConfigBundle:
    data_dir = data_dir or DEFAULT_DATA_DIR
    rates = _load_json(data_dir / "rates.json")
    rules = _load_json(data_dir / "rules.json")
    fees = _load_json(data_dir / "fees.json")
    return ConfigBundle(
        rates=rates, rules=rules, fees=fees,
        rates_freshness=check_freshness(rates),
        rules_freshness=check_freshness(rules),
        fees_freshness=check_freshness(fees),
    )


def _deep_merge(base: dict, override: dict) -> dict:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def effective_rules(rules_cfg: dict, mode: str) -> dict:
    """מיזוג כללים לפי סעיף 3.4: refinanceInternal/refinanceExternal יורשים
    מ-newLoan אלא אם נדרסים במפורש בתצורה."""
    base = rules_cfg.get("newLoan")
    if base is None:
        raise MissingConfigError("חסר נתון: אין כללי 'newLoan' בתצורת rules.json")
    if mode == "newLoan":
        return dict(base)
    if mode not in ("refinanceInternal", "refinanceExternal"):
        raise ValueError(f"מצב לא מוכר: {mode}")
    override = rules_cfg.get(mode) or {}
    return _deep_merge(base, override)


def require(data: dict, *path, error_context: str = "") -> object:
    """שליפה בטוחה מתוך dict מקונן; זורקת MissingConfigError עם הסבר אם
    חסר, במקום להחזיר None/ברירת מחדל בשקט."""
    cur = data
    for key in path:
        if not isinstance(cur, dict) or key not in cur:
            where = " -> ".join(str(p) for p in path)
            suffix = f" ({error_context})" if error_context else ""
            raise MissingConfigError(f"חסר נתון בתצורה: {where}{suffix}")
        cur = cur[key]
    return cur
