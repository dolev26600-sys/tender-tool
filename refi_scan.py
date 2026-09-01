#!/usr/bin/env python3
"""
סריקת מאגר לקוחות לאיתור מועמדים למיחזור.

קורא ייצוא CSV של משכנתאות קיימות (שורה אחת לכל מסלול, מקובצות לפי
client_id), מריץ על כל לקוח את ניתוח הכדאיות מ-mortgage_refi, ומחזיר
רשימה מדורגת.

**הכל דטרמיניסטי - אין כאן קריאה למודל שפה.** הדירוג הוא תוצאה של חשבון,
לא של שיפוט.

עמודות ה-CSV הנדרשות:
    client_id, client_name, track_type, original_amount,
    annual_interest_rate_pct, original_period_months, months_elapsed
עמודות אופציונליות:
    phone, track_name
"""
from __future__ import annotations

import csv
import io
from typing import Iterable

from mortgage_refi import RefiAnalysis, analyze_refi

REQUIRED_COLUMNS = {
    "client_id",
    "track_type",
    "original_amount",
    "annual_interest_rate_pct",
    "original_period_months",
    "months_elapsed",
}

NUMERIC_COLUMNS = {
    "original_amount": float,
    "annual_interest_rate_pct": float,
    "original_period_months": int,
    "months_elapsed": int,
}


class CsvFormatError(ValueError):
    """שגיאת מבנה בקובץ ה-CSV, עם הודעה שאפשר להראות למשתמש כמו שהיא."""


def parse_rows(csv_text: str) -> list[dict]:
    """
    קורא את ה-CSV ומחזיר רשימת שורות מנוקות. נכשל בהודעה ברורה - עדיף
    לעצור על קובץ פגום מאשר לדרג לקוחות על סמך מספרים שנקראו לא נכון.
    """
    reader = csv.DictReader(io.StringIO(csv_text))
    if reader.fieldnames is None:
        raise CsvFormatError("הקובץ ריק או שאינו CSV תקין.")

    headers = {h.strip() for h in reader.fieldnames}
    missing = REQUIRED_COLUMNS - headers
    if missing:
        raise CsvFormatError(
            "חסרות עמודות חובה בקובץ: " + ", ".join(sorted(missing))
            + ". אפשר להוריד קובץ לדוגמה מהעמוד ולהתאים אליו את הייצוא."
        )

    rows: list[dict] = []
    for line_no, raw in enumerate(reader, start=2):
        row = {(k.strip() if k else k): (v.strip() if isinstance(v, str) else v) for k, v in raw.items()}
        if not row.get("client_id"):
            continue  # שורה ריקה - מדלגים בשקט

        for col, caster in NUMERIC_COLUMNS.items():
            value = row.get(col, "")
            try:
                row[col] = caster(float(value)) if value not in ("", None) else 0
            except (TypeError, ValueError):
                raise CsvFormatError(
                    f"שורה {line_no}: הערך בעמודה '{col}' אינו מספר תקין ({value!r})."
                ) from None

        if row["months_elapsed"] > row["original_period_months"]:
            raise CsvFormatError(
                f"שורה {line_no}: months_elapsed ({row['months_elapsed']}) גדול מ-"
                f"original_period_months ({row['original_period_months']}) - המשכנתא כבר הסתיימה?"
            )

        rows.append(row)

    if not rows:
        raise CsvFormatError("לא נמצאו שורות עם client_id בקובץ.")

    return rows


def group_by_client(rows: Iterable[dict]) -> dict[str, dict]:
    """מקבץ שורות מסלולים ללקוחות. שומר על סדר ההופעה בקובץ."""
    clients: dict[str, dict] = {}
    for row in rows:
        cid = row["client_id"]
        if cid not in clients:
            clients[cid] = {
                "client_id": cid,
                "client_name": row.get("client_name") or cid,
                "phone": row.get("phone", ""),
                "tracks": [],
            }
        clients[cid]["tracks"].append({
            "name": row.get("track_name", ""),
            "track_type": row.get("track_type", "other"),
            "original_amount": row["original_amount"],
            "annual_interest_rate_pct": row["annual_interest_rate_pct"],
            "original_period_months": row["original_period_months"],
            "months_elapsed": row["months_elapsed"],
        })
    return clients


def scan(
    csv_text: str,
    *,
    market_rates_by_track_type: dict[str, float],
    new_offer_rate_pct: float,
    new_term_months: int,
    avg_cpi_change_12m_pct: float = 0.0,
    seniority_discount_pct: float = 0.0,
    evaluation_horizon_months: int = 60,
) -> list[RefiAnalysis]:
    """
    מריץ ניתוח כדאיות על כל הלקוחות בקובץ, ומחזיר אותם ממוינים לפי
    התועלת הנטו (הגבוהה ביותר ראשונה).
    """
    clients = group_by_client(parse_rows(csv_text))

    results = [
        analyze_refi(
            c["client_id"],
            c["client_name"],
            c["tracks"],
            market_rates_by_track_type=market_rates_by_track_type,
            new_offer_rate_pct=new_offer_rate_pct,
            new_term_months=new_term_months,
            avg_cpi_change_12m_pct=avg_cpi_change_12m_pct,
            seniority_discount_pct=seniority_discount_pct,
            evaluation_horizon_months=evaluation_horizon_months,
        )
        for c in clients.values()
    ]

    return sorted(results, key=lambda a: a.best_net_benefit, reverse=True)


def recommendation(a: RefiAnalysis) -> str:
    """
    ההמלצה התפעולית ללקוח בודד: מיחזור חלקי, מיחזור מלא, או לא למחזר.
    מבוססת על ההשוואה הניטרלית-לתקופה, כדי שהמלצה לא תיווצר מהארכת תקופה.
    """
    if a.partial_beats_full and a.worthwhile_tracks:
        return "מיחזור חלקי"
    if a.term_neutral_net_benefit > 0:
        return "מיחזור מלא"
    return "לא למחזר"


def to_summary_rows(results: list[RefiAnalysis], phones: dict[str, str] | None = None) -> list[dict]:
    """שורות סיכום להצגה בטבלה ולייצוא חזרה ל-CSV."""
    phones = phones or {}
    rows = []
    for a in results:
        rec = recommendation(a)
        tracks_to_refi = ", ".join(t.name or t.track_type for t in a.worthwhile_tracks)
        rows.append({
            "לקוח": a.client_name,
            "טלפון": phones.get(a.client_id, ""),
            "המלצה": rec,
            "תועלת נטו": round(a.best_net_benefit),
            "מסלולים למיחזור": tracks_to_refi if rec == "מיחזור חלקי" else ("הכל" if rec == "מיחזור מלא" else "—"),
            "חיסכון חודשי": round(
                a.partial_monthly_saving if rec == "מיחזור חלקי" else a.rate_only_monthly_saving
            ),
            "עלות יציאה": round(a.partial_exit_fee if rec == "מיחזור חלקי" else a.total_fee),
            "יתרת קרן": round(a.exit_cost.total_balance),
            "החזר היום": round(a.current_monthly),
            "אשליית הארכת תקופה": "כן" if a.saving_is_mostly_term_extension else "",
        })
    return rows
