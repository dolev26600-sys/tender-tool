#!/usr/bin/env python3
"""
CLI ראשי: מריץ את כל השרשרת על מכרז חדש -
PDF -> חילוץ תנאי סף (Claude) -> השוואה מול פרופיל החברה (Claude) -> דו"ח.

שימוש:
    python analyze_tender.py <path_to_pdf.pdf>
    python analyze_tender.py <path_to_pdf.pdf> --no-save

דורש משתנה סביבה ANTHROPIC_API_KEY מוגדר (מפתח API של Claude).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
TENDERS_DIR = BASE_DIR / "tenders"
REPORTS_DIR = BASE_DIR / "reports"
PROFILE_PATH = BASE_DIR / "company_profile.json"


def _check_api_key() -> None:
    if not os.environ.get("ANTHROPIC_API_KEY") and not os.environ.get("ANTHROPIC_AUTH_TOKEN"):
        print(
            "שגיאה: לא נמצא מפתח API של Claude.\n"
            "הגדר משתנה סביבה לפני ההרצה, למשל:\n"
            "  export ANTHROPIC_API_KEY='sk-ant-...'\n"
            "(אפשר להוסיף את השורה הזו גם לקובץ ~/.zshrc כדי שתישאר קבועה)",
            file=sys.stderr,
        )
        sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="ניתוח עמידה בתנאי סף של מכרז חדש, ישירות מקובץ PDF"
    )
    parser.add_argument("pdf_path", help="נתיב לקובץ ה-PDF של תנאי הסף במכרז")
    parser.add_argument("--no-save", action="store_true", help='לא לשמור את הדו"ח לקובץ')
    parser.add_argument(
        "--verification-passes",
        type=int,
        default=3,
        help="כמה מעברי בדיקה-עצמית להריץ אחרי החילוץ הראשוני, כדי לא לפספס תנאי סף (ברירת מחדל: 3)",
    )
    args = parser.parse_args()

    _check_api_key()

    # ייבוא מאוחר (אחרי בדיקת מפתח ה-API), כדי שהודעת השגיאה תוצג מיד
    # ולא רק אחרי שגיאת ייבוא מבלבלת של anthropic.
    from pdf_extraction import extract_text_from_pdf
    from condition_extraction import extract_and_verify_conditions, save_conditions
    from eligibility_engine import evaluate_eligibility
    from report import format_report, save_report

    pdf_path = Path(args.pdf_path)
    if not pdf_path.exists():
        print(f"שגיאה: הקובץ לא נמצא: {pdf_path}", file=sys.stderr)
        sys.exit(1)

    if not PROFILE_PATH.exists():
        print(f"שגיאה: לא נמצא קובץ פרופיל החברה: {PROFILE_PATH}", file=sys.stderr)
        sys.exit(1)

    print(f"שלב 1/3: מחלץ טקסט מ-{pdf_path.name} ...")
    pdf_text = extract_text_from_pdf(pdf_path)
    print(f"  חולצו {len(pdf_text):,} תווים.")

    print("שלב 2/3: מחלץ תנאי סף בעזרת Claude, עם בדיקה-עצמית מרובת-מעברים כדי לא לפספס אף תנאי ...")
    conditions = extract_and_verify_conditions(
        pdf_text,
        source_hint=pdf_path.name,
        max_verification_passes=args.verification_passes,
        on_progress=lambda msg: print(f"  {msg}"),
    )
    saved_path = save_conditions(conditions, TENDERS_DIR)
    n_conditions = len(conditions.get("conditions", []))
    print(f"  נשמר: {saved_path.relative_to(BASE_DIR)} ({n_conditions} תנאי סף שזוהו לאחר הבדיקה)")

    print("שלב 3/3: משווה מול פרופיל החברה ...")
    with open(PROFILE_PATH, encoding="utf-8") as f:
        profile = json.load(f)
    evaluation = evaluate_eligibility(profile, conditions)

    report_text = format_report(conditions, evaluation)
    print(report_text)

    if not args.no_save:
        out_path = save_report(report_text, conditions.get("tender_id", "unknown"), REPORTS_DIR)
        print(f'הדו"ח נשמר גם ב: {out_path.relative_to(BASE_DIR)}')


if __name__ == "__main__":
    main()
