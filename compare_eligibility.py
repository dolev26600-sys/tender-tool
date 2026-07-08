#!/usr/bin/env python3
"""
כלי בדיקת עמידה בתנאי סף - משווה בין פרופיל חברה (company_profile.json)
לתנאי סף של מכרז שכבר קיים כ-JSON (tenders/<tender_id>_conditions.json),
ומפיק דו"ח סטטוס לכל תנאי (✅ עומדים / 🟡 כנראה עומדים / 🔴 פער / ⚪ חסר מידע).

ההשוואה עצמה מתבצעת ב-eligibility_engine.py באמצעות קריאה ל-Claude API -
השוואה סמנטית גנרית, לא if/else ידני לכל תנאי.

שימוש:
    python compare_eligibility.py tenders/tender_68_2026_conditions.json

הערה: זהו הנתיב "המהיר" - למכרז שתנאיו כבר חולצו וקיימים כ-JSON. עבור מכרז
חדש שיש לו רק PDF, השתמש ב-analyze_tender.py שמריץ גם את שלב החילוץ
האוטומטי מה-PDF.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from eligibility_engine import evaluate_eligibility
from report import format_report


def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def main():
    if len(sys.argv) < 2:
        print("שימוש: python compare_eligibility.py <path_to_tender_conditions.json>")
        sys.exit(1)

    tender_path = Path(sys.argv[1])
    profile_path = Path(__file__).parent / "company_profile.json"

    tender = load_json(tender_path)
    profile = load_json(profile_path)

    evaluation = evaluate_eligibility(profile, tender)
    print(format_report(tender, evaluation))


if __name__ == "__main__":
    main()
