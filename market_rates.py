#!/usr/bin/env python3
"""
ריביות השוק שמשמשות לחישוב עמלת ההיוון, ומוסכמות המסלולים המשתנים לפי בנק.

## למה זה קובץ נתונים ולא קבועים בקוד

עמלת ההיוון מחושבת מול **הריבית הממוצעת שמפרסם בנק ישראל** לאותו סוג
מסלול ולתקופה שנותרה. זה הקלט היחיד שקובע אם יש עמלה בכלל, והוא משתנה
מדי חודש. ריבית ממוצעת שגויה בעשירית אחוז מזיזה את העמלה בעשרות אלפי
שקלים ויכולה להפוך המלצת מיחזור.

לכן הנתונים יושבים בקובץ JSON עם תאריך ומקור, והקוד **מסרב להתייחס
אליהם כאמת** בלי שמישהו אימת אותם. עדיף כלי שאומר "הנתון לא מאומת"
מכלי שנותן מספר בטוח ושגוי.

## מה הכלי לא יכול לעשות

לשאוב את הנתונים לבד. הסביבה הזו חוסמת גישה לאתר בנק ישראל, ולכן
העדכון ידני: נכנסים לטבלת הריביות הממוצעות של בנק ישראל, מעתיקים,
ומסמנים verified=true עם התאריך.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

RATES_FILE = Path(__file__).with_name("market_rates.json")

# מעל זה הנתון נחשב ישן מדי כדי להסתמך עליו להחלטת מיחזור.
STALE_AFTER_DAYS = 45

# פריים = ריבית בנק ישראל + 1.5%. זו מוסכמה קבועה בשוק הישראלי ולא
# משתנה בין בנקים, ולכן היא כן ראויה להיות בקוד.
PRIME_SPREAD_OVER_BOI_PCT = 1.5


def prime_rate_from_boi(boi_rate_pct: float) -> float:
    """ריבית הפריים הנגזרת מריבית בנק ישראל."""
    return boi_rate_pct + PRIME_SPREAD_OVER_BOI_PCT


@dataclass
class RatesStatus:
    """מצב אמינות הנתונים - מה שהממשק צריך כדי להזהיר את היועץ."""
    as_of: str
    verified: bool
    source: str
    age_days: int | None
    is_stale: bool

    @property
    def is_trustworthy(self) -> bool:
        return self.verified and not self.is_stale

    @property
    def warning(self) -> str | None:
        if not self.verified:
            return (
                "ריביות השוק בקובץ **לא אומתו מול בנק ישראל**. הן נועדו רק "
                "כדי שהכלי יעבוד מהרגע הראשון. לפני שמציגים מספרים ללקוח - "
                "עדכן אותן מטבלת הריביות הממוצעות של בנק ישראל."
            )
        if self.is_stale:
            return (
                f"ריביות השוק עודכנו לאחרונה לפני {self.age_days} ימים. "
                "הריבית הממוצעת מתפרסמת מדי חודש, וערך ישן משנה את עמלת ההיוון."
            )
        return None


def load_rates(path: Path | None = None) -> dict:
    with open(path or RATES_FILE, encoding="utf-8") as f:
        return json.load(f)


def rates_status(data: dict, *, today: date | None = None) -> RatesStatus:
    today = today or date.today()
    as_of = data.get("as_of") or ""
    age = None
    try:
        age = (today - datetime.strptime(as_of, "%Y-%m-%d").date()).days
    except (ValueError, TypeError):
        age = None
    return RatesStatus(
        as_of=as_of or "לא צוין",
        verified=bool(data.get("verified")),
        source=data.get("source", "לא צוין"),
        age_days=age,
        is_stale=age is None or age > STALE_AFTER_DAYS,
    )


def market_rates_by_track_type(data: dict) -> dict[str, float]:
    """המילון שמנוע המיחזור מצפה לו: סוג מסלול -> ריבית ממוצעת."""
    return {k: float(v) for k, v in (data.get("average_rates_by_track_type") or {}).items()
            if v is not None}


def bank_variable_conventions(data: dict) -> list[dict]:
    return data.get("bank_variable_conventions") or []


if __name__ == "__main__":
    d = load_rates()
    st = rates_status(d)
    print(f"נכון ל: {st.as_of} | מאומת: {st.verified} | גיל: {st.age_days} ימים")
    print(f"מקור: {st.source}")
    if st.warning:
        print(f"\n⚠️  {st.warning}")
    print("\nריביות ממוצעות:")
    for k, v in market_rates_by_track_type(d).items():
        print(f"  {k:22} {v}%")
