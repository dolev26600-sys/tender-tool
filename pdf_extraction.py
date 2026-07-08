#!/usr/bin/env python3
"""
חילוץ טקסט מקובצי PDF של מכרזים.

אסטרטגיה:
1. מנסה pdftotext -layout (חלק מ-poppler) - שומר על מבנה טבלאות/עמודות טוב יותר.
2. אם pdftotext לא מותקן, או שהפלט שלו נראה "לא נקי" (קצר מדי/כמעט ריק),
   נופל ל-pdfplumber (ספריית Python, לא דורשת התקנה חיצונית).

כך אין תלות קשיחה בהתקנת poppler במערכת - הכלי עובד גם בלעדיו, פשוט
עם pdfplumber כברירת מחדל.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional


def _extract_with_pdftotext(pdf_path: Path) -> Optional[str]:
    """מנסה לחלץ טקסט בעזרת pdftotext -layout. מחזיר None אם הכלי לא זמין או נכשל."""
    if not shutil.which("pdftotext"):
        return None
    try:
        result = subprocess.run(
            ["pdftotext", "-layout", str(pdf_path), "-"],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode != 0:
            print(f"אזהרה: pdftotext החזיר שגיאה: {result.stderr.strip()}", file=sys.stderr)
            return None
        return result.stdout
    except subprocess.TimeoutExpired:
        print("אזהרה: pdftotext לקח יותר מדי זמן, עובר ל-pdfplumber", file=sys.stderr)
        return None


def _extract_with_pdfplumber(pdf_path: Path) -> str:
    try:
        import pdfplumber
    except ImportError as e:
        raise RuntimeError(
            "לא נמצא pdftotext במערכת ולא מותקנת הספרייה pdfplumber.\n"
            "התקן אחת מהאפשרויות:\n"
            "  pip install -r requirements.txt      (מתקין את pdfplumber)\n"
            "  brew install poppler                 (מתקין את pdftotext, אופציונלי)"
        ) from e

    text_parts = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            text_parts.append(page.extract_text() or "")
    return "\n\n".join(text_parts)


def _looks_clean(text: str, min_chars: int = 200) -> bool:
    """בדיקה היוריסטית פשוטה - האם הטקסט שחולץ נראה תקין (לא ריק/קטוע)."""
    return len(text.strip()) >= min_chars


def extract_text_from_pdf(pdf_path) -> str:
    """
    מחלץ טקסט מקובץ PDF. מנסה pdftotext -layout קודם, ונופל ל-pdfplumber
    אם הראשון לא זמין או שהתוצאה נראית לא נקייה.
    """
    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        raise FileNotFoundError(f"הקובץ לא נמצא: {pdf_path}")

    text = _extract_with_pdftotext(pdf_path)
    if text is not None:
        if _looks_clean(text):
            return text
        print(
            "אזהרה: הטקסט שחולץ עם pdftotext נראה קצר/לא נקי, מנסה pdfplumber כגיבוי",
            file=sys.stderr,
        )

    return _extract_with_pdfplumber(pdf_path)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("שימוש: python pdf_extraction.py <path_to_pdf>")
        sys.exit(1)
    print(extract_text_from_pdf(sys.argv[1]))
