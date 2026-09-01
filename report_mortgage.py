#!/usr/bin/env python3
"""
עיצוב ושמירה של דו"ח השוואת הצעות משכנתא, על בסיס פלט mortgage_comparison.py.
"""
from __future__ import annotations

import datetime
import re
from pathlib import Path


def _fmt_money(value) -> str:
    try:
        return f"{value:,.0f} ₪"
    except (TypeError, ValueError):
        return str(value)


def format_report(comparison: dict, *, client_preferences: str | None = None) -> str:
    lines = []
    per_bank = comparison.get("per_bank", [])
    ranking = comparison.get("ranking", [])

    lines.append("\n=== השוואת הצעות משכנתא ===")
    lines.append(f"({len(per_bank)} הצעות הושוו)\n")

    if client_preferences:
        lines.append(f"העדפות/אילוצים שהוזנו: {client_preferences}\n")

    if ranking:
        lines.append("דירוג מומלץ: " + " > ".join(ranking) + "\n")

    recommendation = comparison.get("overall_recommendation")
    if recommendation:
        lines.append(f"המלצה כללית: {recommendation}\n")

    lines.append("--- פירוט לכל בנק ---\n")

    by_name = {b.get("bank_name"): b for b in per_bank}
    ordered_names = ranking if ranking else list(by_name.keys())

    for name in ordered_names:
        entry = by_name.get(name)
        if not entry:
            continue
        stats = entry.get("stats", {})
        stress = entry.get("stress_test", {})

        lines.append(f"[{name}]")
        lines.append(f"  סכום כולל: {_fmt_money(stats.get('total_amount'))}")
        lines.append(f"  ריבית ממוצעת משוקללת: {stats.get('blended_annual_interest_rate_pct')}%")
        lines.append(f"  החזר חודשי התחלתי: {_fmt_money(stats.get('initial_total_monthly_payment'))}")
        if stress:
            lines.append(
                f"  החזר חודשי בתרחיש קיצון (ריבית +{stress.get('rate_increase_pct')}%, "
                f"מדד +{stress.get('cpi_annual_pct')}%): {_fmt_money(stress.get('stressed_total_monthly_payment'))} "
                "(הערכה גסה להמחשה, לא תחזית מדויקת)"
            )

        pros = entry.get("pros") or []
        cons = entry.get("cons") or []
        if pros:
            lines.append("  יתרונות: " + "; ".join(pros))
        if cons:
            lines.append("  חסרונות: " + "; ".join(cons))

        risk_notes = entry.get("risk_notes")
        if risk_notes:
            lines.append(f"  הערכת סיכון: {risk_notes}")
        lines.append("")

    questions = comparison.get("questions_to_verify") or []
    if questions:
        lines.append("--- לוודא מול הבנקים לפני החלטה סופית ---")
        for q in questions:
            lines.append(f"  • {q}")
        lines.append("")

    lines.append(
        "הערה: דו\"ח זה הוא כלי עזר להחלטה ואינו תחליף לבדיקה סופית מול הבנק "
        "ולשיקול הדעת המקצועי של היועץ. מבחן הקיצון הוא הערכה גסה להמחשה בלבד."
    )

    return "\n".join(lines)


def save_report(report_text: str, banks: list[str], reports_dir) -> Path:
    reports_dir = Path(reports_dir)
    reports_dir.mkdir(parents=True, exist_ok=True)

    safe_names = "_".join(re.sub(r"[^0-9A-Za-zא-ת]+", "", b)[:15] for b in banks[:4]) or "השוואה"
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = reports_dir / f"mortgage_report_{safe_names}_{timestamp}.txt"
    out_path.write_text(report_text, encoding="utf-8")
    return out_path
