#!/usr/bin/env python3
"""
עיצוב ושמירה של דו"ח עמידה בתנאי סף, על בסיס פלט eligibility_engine.py.
"""
from __future__ import annotations

import datetime
from pathlib import Path


def format_report(tender: dict, evaluation: dict) -> str:
    lines = []
    tender_id = tender.get("tender_id", "?")
    tender_title = tender.get("tender_title", "")
    n_conditions = len(tender.get("conditions", []))
    lines.append(f"\n=== בדיקת עמידה בתנאי סף — מכרז {tender_id}: {tender_title} ===")
    lines.append(f"({n_conditions} תנאי סף נבדקו)\n")

    summary = evaluation.get("overall_summary")
    if summary:
        lines.append(f"סיכום כללי: {summary}\n")

    results = evaluation.get("results", [])
    flagged = [r for r in results if r.get("status") in ("gap", "unknown")]
    if flagged:
        lines.append("⚠️  דברים לבדוק/להשלים לפני שניגשים למכרז:")
        for r in flagged:
            lines.append(f"  • [{r.get('id', '?')}] {r.get('status_label', r.get('status'))} — {r.get('requirement', '')[:120]}")
        lines.append("")
    else:
        lines.append("✅ לא נמצאו פערים או חוסרי מידע - כל תנאי הסף עומדים או כנראה עומדים.\n")

    lines.append("--- פירוט מלא לכל תנאי ---\n")

    for r in results:
        alt_note = ""
        if r.get("type") == "alternative" and r.get("alternative_group"):
            alt_note = f"  [חלק מקבוצת תנאים תחליפית: {r['alternative_group']}]"

        lines.append(f"[{r.get('id', '?')}] {r.get('category', '')}{alt_note}")
        lines.append(f"  דרישה: {r.get('requirement', '')}")
        lines.append(f"  סטטוס: {r.get('status_label', r.get('status', '?'))}")
        lines.append(f"  נימוק: {r.get('reasoning', '')}")

        missing = r.get("missing_info") or []
        if missing:
            lines.append("  חסר להשלמה: " + "; ".join(missing))
        lines.append("")

    return "\n".join(lines)


def save_report(report_text: str, tender_id: str, reports_dir) -> Path:
    reports_dir = Path(reports_dir)
    reports_dir.mkdir(parents=True, exist_ok=True)

    safe_id = tender_id.replace("/", "_").replace(" ", "_")
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = reports_dir / f"report_{safe_id}_{timestamp}.txt"
    out_path.write_text(report_text, encoding="utf-8")
    return out_path
