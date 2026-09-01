#!/usr/bin/env python3
"""
חילוץ מסלולי משכנתא קיימת מתוך **דוח יתרות** של הבנק, לפורמט שמנוע
המיחזור (mortgage_refi.py) יודע לעבוד איתו.

## למה זה מסמך אחר מהצעת משכנתא

mortgage_offer_extraction.py קורא *הצעה* - משכנתא שעוד לא נלקחה, ולכן
מדובר בסכום מקורי ותקופה מקורית. דוח יתרות מתאר משכנתא **חיה**: מה
היתרה היום, כמה תשלומים נשארו, ומה ההחזר בפועל. אלה נתונים אחרים, והם
עדיפים על שחזור מהסכום המקורי - במיוחד במסלול צמוד מדד, שבו שחזור
נומינלי מפספס את ההצמדה שנצברה ונותן יתרה נמוכה מדי.

## מה קריטי לחלץ ולרוב מפספסים

**מועד עדכון הריבית הבא במסלול משתנה.** בתחנת עדכון הריבית אין עמלת
היוון בכלל. לקוח שנמצא שלושה חודשים לפני תחנה יכול לחסוך את מלוא
העמלה בהמתנה - וזו לעיתים ההמלצה השווה ביותר בכל התיק. בלי השדה הזה
הכלי מחשב עמלה שהלקוח כלל לא היה צריך לשלם.

## הכלל שלא משתנה

Claude מחלץ מה שכתוב במסמך. שום חישוב לא נעשה כאן - כל המספרים
הנגזרים (יתרה משוחזרת, עמלת היוון, כדאיות) מחושבים בפייתון.
"""
from __future__ import annotations

import json
from typing import Optional

import anthropic

MODEL = "claude-opus-4-8"

TRACK_TYPES = [
    "fixed_unlinked",
    "fixed_linked_cpi",
    "variable_prime",
    "variable_unlinked",
    "variable_linked_cpi",
    "eligibility",
    "other",
]

_BALANCE_TRACK_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string", "description": "שם/מספר המסלול כפי שמופיע בדוח, למשל 'הלוואה 3 - קבועה לא צמודה'"},
        "track_type": {"type": "string", "enum": TRACK_TYPES, "description": "סיווג המסלול לפי הסוג הפיננסי"},
        "current_balance": {
            "type": ["number", "null"],
            "description": "יתרת הקרן לסילוק **היום**, בש\"ח, כפי שמופיעה בדוח. זה השדה החשוב ביותר. במסלול צמוד מדד - היתרה המוצמדת אם מצוינת",
        },
        "remaining_months": {
            "type": ["integer", "null"],
            "description": "מספר התשלומים/החודשים שנותרו במסלול. אם מצוין תאריך סיום בלבד ולא מספר חודשים - השאר null וציין את התאריך ב-notes",
        },
        "current_monthly_payment": {
            "type": ["number", "null"],
            "description": "ההחזר החודשי בפועל במסלול הזה, בש\"ח, אם מצוין",
        },
        "annual_interest_rate_pct": {
            "type": ["number", "null"],
            "description": "הריבית השנתית הנוכחית במסלול (למשל 4.9 עבור 4.9%)",
        },
        "original_amount": {
            "type": ["number", "null"],
            "description": "סכום ההלוואה המקורי במסלול, אם מופיע בדוח. משמש רק לבדיקת סבירות מול היתרה - לא לחישוב",
        },
        "original_period_months": {
            "type": ["integer", "null"],
            "description": "התקופה המקורית בחודשים, אם מופיעה",
        },
        "months_elapsed": {
            "type": ["integer", "null"],
            "description": "כמה חודשים כבר שולמו, אם מצוין או ניתן לקרוא ישירות מהדוח",
        },
        "rate_reset_period_months": {
            "type": ["integer", "null"],
            "description": "כל כמה חודשים מתעדכנת הריבית במסלול משתנה (למשל 60 עבור 'משתנה כל 5 שנים'). null במסלול קבוע",
        },
        "next_reset_date": {
            "type": ["string", "null"],
            "description": "התאריך הבא שבו מתעדכנת הריבית ('תחנה'), כפי שמופיע בדוח. קריטי - בתחנה אין עמלת היוון. אם לא מופיע, null",
        },
        "prime_margin_pct": {
            "type": ["number", "null"],
            "description": "המרווח מפריים אם מצוין (למשל -0.4), אחרת null",
        },
        "rate_anchor": {
            "type": ["string", "null"],
            "description": "העוגן שאליו צמודה הריבית המשתנה כפי שמנוסח בדוח (למשל 'עוגן אג\"ח ממשלתי', 'ריבית הפריים', 'עוגן מק\"מ'). זה נתון של ההלוואה הספציפית - אל תשלים לפי מה שמקובל בבנק",
        },
        "linkage": {"type": "string", "enum": ["cpi_linked", "unlinked"], "description": "האם המסלול צמוד מדד"},
        "notes": {"type": "string", "description": "פרטים שלא נכנסו לשדות (תאריך סיום, פיגורים, גרירה, פירעון חלקי שבוצע)"},
    },
    "required": [
        "name", "track_type", "current_balance", "remaining_months", "current_monthly_payment",
        "annual_interest_rate_pct", "original_amount", "original_period_months", "months_elapsed",
        "rate_reset_period_months", "next_reset_date", "prime_margin_pct", "rate_anchor",
        "linkage", "notes",
    ],
    "additionalProperties": False,
}

BALANCE_REPORT_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "bank_name": {"type": "string", "description": "שם הבנק שהנפיק את דוח היתרות"},
        "report_date": {"type": ["string", "null"], "description": "התאריך שאליו נכון הדוח, כפי שמופיע"},
        "borrower_name": {"type": ["string", "null"], "description": "שם הלווה אם מופיע"},
        "total_balance": {
            "type": ["number", "null"],
            "description": "סך יתרת החוב לסילוק כפי שמצוין בדוח (אל תחשב בעצמך - רק אם מופיע מספר מסוכם)",
        },
        "total_monthly_payment": {
            "type": ["number", "null"],
            "description": "סך ההחזר החודשי כפי שמצוין בדוח, אם מופיע",
        },
        "quoted_early_repayment_fee": {
            "type": ["number", "null"],
            "description": "עמלת פירעון מוקדם נקובה, אם הדוח כולל אותה (למשל במכתב כוונות לסילוק). אחרת null",
        },
        "tracks": {"type": "array", "description": "מסלולי המשכנתא הקיימת", "items": _BALANCE_TRACK_SCHEMA},
        "document_type": {
            "type": "string",
            "enum": ["balance_report", "payoff_letter", "offer", "unknown"],
            "description": "סוג המסמך: דוח יתרות רגיל, מכתב כוונות לסילוק (כולל עמלה נקובה), הצעה למשכנתא חדשה, או לא ברור",
        },
        "notes": {"type": "string", "description": "מידע רלוונטי נוסף מהדוח"},
    },
    "required": [
        "bank_name", "report_date", "borrower_name", "total_balance", "total_monthly_payment",
        "quoted_early_repayment_fee", "tracks", "document_type", "notes",
    ],
    "additionalProperties": False,
}

EXTRACTION_SYSTEM_PROMPT = """אתה עוזר מקצועי המסייע ליועץ משכנתאות בישראל לחלץ נתונים מדויקים מ**דוח
יתרות** של משכנתא קיימת (או ממכתב כוונות לסילוק) שהנפיק בנק למשכנתאות.

## המשימה
לקרוא טקסט שחולץ ממסמך כזה ולהוציא ממנו, במבנה JSON קבוע: שם הבנק,
תאריך הדוח, וכל מסלול במשכנתא הקיימת - עם היתרה הנוכחית, התקופה
שנותרה, ההחזר החודשי והריבית.

## כללים חשובים
1. **חלץ בלבד - אל תחשב.** אם היתרה הכוללת לא מסוכמת בדוח, השאר
   total_balance כ-null. אל תסכום בעצמך ואל תגזור יתרה מסכום מקורי.
   כל חישוב נעשה מחוץ למשימה שלך, במדויק.
2. **היתרה הנוכחית היא השדה החשוב ביותר.** זה מה שמייחד דוח יתרות
   מהצעה. חפש "יתרה לסילוק", "יתרת קרן", "יתרה נוכחית", "יתרת חוב".
   במסלול צמוד מדד קח את היתרה המוצמדת אם הדוח מבחין בין נומינלית
   למוצמדת, וציין זאת ב-notes של המסלול.
3. **מועד עדכון הריבית הבא (next_reset_date) קריטי.** בכל מסלול משתנה
   חפש "מועד שינוי הריבית", "תחנה", "מועד עדכון", "תאריך שינוי ריבית
   הבא". זה נתון ששווה ללקוח כסף רב, ולעיתים קרובות הוא מופיע בדוח
   בשורה נפרדת או בהערת שוליים. אם אינו מופיע - null, אל תנחש.
4. **rate_anchor - רק מה שכתוב.** אם הדוח מציין את העוגן של הריבית
   המשתנה, העתק אותו כלשונו. אל תשלים לפי מה שמקובל באותו בנק: העוגן
   הוא תנאי של ההלוואה הספציפית, ובאותו בנק יש הלוואות עם עוגנים שונים.
5. **מספרים בדיוק כפי שמופיעים.** אל תעגל ואל תמיר יחידות, למעט המרה
   ברורה וחד-משמעית של שנים לחודשים - ואז ציין זאת ב-notes.
6. **סיווג מסלולים**: "קבועה" + "לא צמודה"/"צמודה מדד" -> fixed_*;
   "פריים" -> variable_prime; "משתנה כל X שנים" בלי הצמדה ->
   variable_unlinked; עם הצמדה -> variable_linked_cpi; זכאות/מסובסד ->
   eligibility.
7. **אם פרט לא מופיע - null.** אל תמציא, אל תשלים מהיגיון, ואל תעתיק
   ערך ממסלול אחר. שדה ריק עדיף על ערך שגוי: היועץ ישלים אותו ידנית,
   אבל מספר שגוי ייכנס לחישוב בשקט.
8. אם המסמך אינו דוח יתרות אלא הצעה למשכנתא חדשה - סמן document_type
   כ-"offer" וציין זאת ב-notes.

החזר אך ורק JSON תקין בסכימה שסופקה - ללא טקסט נוסף לפני או אחרי."""


def extract_balance_report(pdf_text: str, *, source_hint: Optional[str] = None) -> dict:
    """שולח את טקסט דוח היתרות ל-Claude ומחזיר dict בסכימה הקבועה."""
    client = anthropic.Anthropic()

    hint_line = f"רמז לזיהוי המסמך (שם הקובץ המקורי): {source_hint}\n\n" if source_hint else ""
    pdf_block = (
        f"{hint_line}"
        "להלן הטקסט שחולץ מדוח יתרות של משכנתא קיימת (ייתכנו שגיאות עיצוב "
        "כתוצאה מחילוץ אוטומטי מ-PDF, במיוחד בטבלאות - התעלם מהן והתמקד בתוכן):\n\n"
        "```\n" + pdf_text + "\n```"
    )

    response = client.messages.create(
        model=MODEL,
        max_tokens=8000,
        thinking={"type": "adaptive"},
        system=[{
            "type": "text",
            "text": EXTRACTION_SYSTEM_PROMPT,
            "cache_control": {"type": "ephemeral", "ttl": "1h"},
        }],
        output_config={"format": {"type": "json_schema", "schema": BALANCE_REPORT_JSON_SCHEMA}},
        messages=[{"role": "user", "content": pdf_block}],
    )

    text_block = next(b.text for b in response.content if b.type == "text")
    return json.loads(text_block)


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("שימוש: python mortgage_balance_extraction.py <path_to_pdf_text_file>")
        sys.exit(1)
    with open(sys.argv[1], encoding="utf-8") as f:
        raw = f.read()
    print(json.dumps(extract_balance_report(raw, source_hint=sys.argv[1]), ensure_ascii=False, indent=2))


# =====================================================================
#  עיבוד דטרמיניסטי של מה ש-Claude חילץ. מכאן ואילך אין מודל שפה.
# =====================================================================

import re  # noqa: E402
from datetime import date, datetime  # noqa: E402

_DATE_PATTERNS = ("%d/%m/%Y", "%d.%m.%Y", "%d-%m-%Y", "%Y-%m-%d", "%d/%m/%y", "%d.%m.%y")

# פער מותר בין סכום היתרות במסלולים לבין הסכום הכולל שהדוח מצהיר עליו.
TOTAL_MISMATCH_TOLERANCE_PCT = 1.0


def parse_report_date(value: str | None) -> date | None:
    """מפרש תאריך ישראלי (יום/חודש/שנה) על כמה מפרידים נפוצים."""
    if not value:
        return None
    cleaned = re.sub(r"[^\d/.\-]", "", str(value).strip())
    for fmt in _DATE_PATTERNS:
        try:
            return datetime.strptime(cleaned, fmt).date()
        except ValueError:
            continue
    return None


def months_between(start: date, end: date) -> int:
    """מספר חודשים שלמים מ-start ל-end (עשוי להיות שלילי)."""
    months = (end.year - start.year) * 12 + (end.month - start.month)
    if end.day < start.day:
        months -= 1
    return months


def months_to_next_reset(
    next_reset_date: str | None,
    rate_reset_period_months: int | None = None,
    *,
    today: date | None = None,
) -> int | None:
    """
    כמה חודשים נותרו לתחנת עדכון הריבית הבאה.

    אם התאריך שבדוח כבר עבר - הדוח ישן, והתחנה האמיתית התגלגלה קדימה.
    אז מגלגלים אותה בקפיצות של תקופת העדכון. אם תקופת העדכון לא ידועה
    מחזירים None ולא 0: להחזיר 0 פירושו להצהיר "אתה בתחנה", וזה מאפס
    עמלת היוון אמיתית על סמך ניחוש. הכיוון הבטוח הוא להשאיר את העמלה.
    """
    target = parse_report_date(next_reset_date)
    if target is None:
        return None
    today = today or date.today()
    delta = months_between(today, target)
    if delta >= 0:
        return delta
    period = rate_reset_period_months or 0
    if period <= 0:
        return None
    while delta < 0:
        delta += period
    return delta


def to_refi_tracks(report: dict, *, today: date | None = None) -> list[dict]:
    """
    ממיר דוח יתרות שחולץ לרשימת המסלולים שמנוע המיחזור מצפה לה.

    שדות חסרים נשארים חסרים - resolve_track_state במנוע כבר יודע לבחור
    בין מספר מדווח לשחזור, ואין טעם למלא כאן ערכי ברירת מחדל שייראו
    כמו נתונים אמיתיים.
    """
    tracks = []
    for t in report.get("tracks") or []:
        reset_period = t.get("rate_reset_period_months")
        track = {
            "name": t.get("name") or "",
            "track_type": t.get("track_type") or "other",
            "annual_interest_rate_pct": t.get("annual_interest_rate_pct"),
            "current_balance": t.get("current_balance"),
            "remaining_months": t.get("remaining_months"),
            "current_monthly_payment": t.get("current_monthly_payment"),
            "original_amount": t.get("original_amount"),
            "original_period_months": t.get("original_period_months"),
            "months_elapsed": t.get("months_elapsed"),
            "rate_reset_period_months": reset_period,
            "months_to_next_reset": months_to_next_reset(
                t.get("next_reset_date"), reset_period, today=today
            ),
            "rate_anchor": t.get("rate_anchor"),
        }
        tracks.append({k: v for k, v in track.items() if v is not None})
    return tracks


def validate_report(report: dict, *, today: date | None = None) -> list[dict]:
    """
    בדיקות שפיות דטרמיniסטיות על מה שחולץ, לפני שמריצים ניתוח כדאיות.

    כל פריט: {"severity": "blocker"/"warn"/"note", "field": str, "message": str}.
    blocker פירושו שאי אפשר לחשב את המסלול בכלל בלי השלמה ידנית.
    """
    issues: list[dict] = []

    if report.get("document_type") == "offer":
        issues.append({
            "severity": "warn", "field": "document_type",
            "message": "המסמך נראה כהצעה למשכנתא חדשה ולא כדוח יתרות. "
                       "להשוואת הצעות יש להשתמש בכלי השוואת ההצעות.",
        })

    tracks = report.get("tracks") or []
    if not tracks:
        issues.append({"severity": "blocker", "field": "tracks",
                       "message": "לא זוהה אף מסלול בדוח. ייתכן שהקובץ סרוק כתמונה ולא כטקסט."})
        return issues

    for i, t in enumerate(tracks, start=1):
        label = t.get("name") or f"מסלול {i}"

        has_balance = bool(t.get("current_balance"))
        can_reconstruct = bool(t.get("original_amount")) and bool(t.get("original_period_months"))
        if not has_balance and not can_reconstruct:
            issues.append({"severity": "blocker", "field": f"tracks[{i}].current_balance",
                           "message": f"{label}: אין יתרה נוכחית ואי אפשר לשחזר אותה. יש להשלים ידנית."})

        if not t.get("annual_interest_rate_pct"):
            issues.append({"severity": "blocker", "field": f"tracks[{i}].annual_interest_rate_pct",
                           "message": f"{label}: לא נקראה ריבית. בלעדיה אי אפשר לחשב עמלת היוון."})

        if not t.get("remaining_months") and not can_reconstruct:
            issues.append({"severity": "blocker", "field": f"tracks[{i}].remaining_months",
                           "message": f"{label}: לא נקראה התקופה שנותרה."})

        # השדה ששווה כסף: מסלול משתנה רב-שנתי בלי תאריך תחנה
        period = t.get("rate_reset_period_months") or 0
        is_variable = str(t.get("track_type", "")).startswith("variable")
        if is_variable and t.get("track_type") != "variable_prime":
            if not t.get("next_reset_date"):
                issues.append({"severity": "warn", "field": f"tracks[{i}].next_reset_date",
                               "message": f"{label}: לא נמצא מועד עדכון הריבית הבא. בתחנה אין עמלת היוון, "
                                          "ולכן בלי התאריך הזה החישוב עלול להראות עמלה שהלקוח לא באמת חייב. "
                                          "שווה לבקש אותו מהבנק."})
            elif period > 12 and months_to_next_reset(
                    t.get("next_reset_date"), period, today=today) is None:
                issues.append({"severity": "warn", "field": f"tracks[{i}].next_reset_date",
                               "message": f"{label}: מועד התחנה שבדוח כבר עבר ותדירות העדכון לא ידועה, "
                                          "ולכן לא ניתן לגלגל אותו קדימה. הכלי מחשב עמלת היוון מלאה - "
                                          "זה הצד הבטוח, אבל ייתכן שהעמלה בפועל נמוכה יותר."})
            if not period:
                issues.append({"severity": "note", "field": f"tracks[{i}].rate_reset_period_months",
                               "message": f"{label}: לא נקראה תדירות עדכון הריבית. "
                                          "מסלול שמתעדכן שנתית או תכוף יותר פטור מעמלת היוון לגמרי."})
            if not t.get("rate_anchor"):
                issues.append({"severity": "note", "field": f"tracks[{i}].rate_anchor",
                               "message": f"{label}: לא צוין העוגן של הריבית המשתנה. "
                                          "העוגן הוא תנאי של ההלוואה הספציפית ומשתנה בין בנקים ובין ותקים."})

    declared = report.get("total_balance")
    summed = sum(float(t.get("current_balance") or 0) for t in tracks)
    if declared and summed > 0:
        gap_pct = abs(float(declared) - summed) / float(declared) * 100
        if gap_pct > TOTAL_MISMATCH_TOLERANCE_PCT:
            issues.append({"severity": "warn", "field": "total_balance",
                           "message": f"סכום היתרות במסלולים ({summed:,.0f} ₪) לא תואם את היתרה הכוללת "
                                      f"שבדוח ({float(declared):,.0f} ₪), פער של {gap_pct:.1f}%. "
                                      "ייתכן שמסלול לא נקרא."})
    return issues


def blockers(issues: list[dict]) -> list[dict]:
    return [i for i in issues if i["severity"] == "blocker"]
