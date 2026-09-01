#!/usr/bin/env python3
"""
חילוץ תנאי הצעה/אישור עקרוני למשכנתא (טקסט שחולץ מ-PDF של בנק) לפורמט JSON
קבוע, בעזרת Claude - כדי שמנוע ההשוואה (mortgage_comparison.py) יוכל להשוות
הצעות מבנקים שונים בלי לוגיקת פענוח ידנית לכל מסמך.

הכלל המרכזי: Claude מחלץ נתונים בלבד (מה כתוב במסמך) - כל חישוב (החזר
חודשי, ריבית משוקללת, מבחן קיצון) מתבצע אח"כ בפייתון (mortgage_math.py),
לא ע"י המודל.
"""
from __future__ import annotations

import json
from typing import Optional

import anthropic

MODEL = "claude-opus-4-8"

TRACK_TYPES = [
    "fixed_unlinked",       # קבועה לא צמודה (קל"צ)
    "fixed_linked_cpi",     # קבועה צמודה מדד (ק"צ)
    "variable_prime",       # פריים
    "variable_unlinked",    # משתנה לא צמודה (מש"ל)
    "variable_linked_cpi",  # משתנה צמודה מדד (מש"צ)
    "eligibility",          # מסלול זכאות/מסובסד
    "other",
]

_TRACK_ITEM_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {
            "type": "string",
            "description": "שם המסלול כפי שמופיע במסמך, למשל 'קבועה לא צמודה' או 'פריים -0.4%'",
        },
        "track_type": {
            "type": "string",
            "enum": TRACK_TYPES,
            "description": "סיווג המסלול לפי הסוג הפיננסי שלו",
        },
        "amount": {"type": "number", "description": "סכום הקרן במסלול הזה, בש\"ח"},
        "period_months": {"type": "integer", "description": "תקופת ההלוואה במסלול, בחודשים"},
        "annual_interest_rate_pct": {
            "type": "number",
            "description": "ריבית שנתית נומינלית של המסלול, כפי שמופיעה במסמך (למשל 4.9 עבור 4.9%). עבור פריים - הריבית הכוללת (פריים+/-מרווח) אם ידועה, אחרת ריבית הפריים הנוכחית שצוינה במסמך",
        },
        "prime_margin_pct": {
            "type": ["number", "null"],
            "description": "המרווח מפריים אם מצוין (חיובי או שלילי, למשל -0.4), אחרת null",
        },
        "rate_reset_period_months": {
            "type": ["integer", "null"],
            "description": "כל כמה חודשים מתעדכנת הריבית (רלוונטי למסלולים משתנים, למשל 60), אחרת null",
        },
        "linkage": {
            "type": "string",
            "enum": ["cpi_linked", "unlinked"],
            "description": "האם המסלול צמוד למדד המחירים לצרכן",
        },
    },
    "required": [
        "name",
        "track_type",
        "amount",
        "period_months",
        "annual_interest_rate_pct",
        "prime_margin_pct",
        "rate_reset_period_months",
        "linkage",
    ],
    "additionalProperties": False,
}

OFFER_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "bank_name": {"type": "string", "description": "שם הבנק/הגוף המלווה שהנפיק את ההצעה"},
        "offer_date": {"type": ["string", "null"], "description": "תאריך ההצעה/האישור העקרוני, כפי שמופיע"},
        "validity_date": {"type": ["string", "null"], "description": "תאריך תפוגת תוקף ההצעה, אם מצוין"},
        "total_loan_amount": {"type": "number", "description": "סכום ההלוואה הכולל המבוקש/המאושר, בש\"ח"},
        "tracks": {
            "type": "array",
            "description": "רשימת מסלולי המשכנתא (התמהיל) בהצעה",
            "items": _TRACK_ITEM_SCHEMA,
        },
        "fees": {
            "type": "array",
            "description": "עמלות/דמי טיפול שמצוינים במפורש בהצעה (למשל דמי הערכת שווי, דמי פתיחת תיק)",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "amount": {"type": "number"},
                },
                "required": ["name", "amount"],
                "additionalProperties": False,
            },
        },
        "effective_annual_interest_rate_pct": {
            "type": ["number", "null"],
            "description": "ריבית אפקטיבית שנתית משוקללת, רק אם מצוינת במפורש במסמך (אל תחשב בעצמך)",
        },
        "early_repayment_note": {
            "type": ["string", "null"],
            "description": "הערה על עמלת פירעון מוקדם אם מצוינת (לרוב לא ידועה מראש, רק תנאי/נוסחה)",
        },
        "notes": {
            "type": "string",
            "description": "כל מידע רלוונטי נוסף שלא נכנס לשדות למעלה (תנאים מיוחדים, ביטוחים נדרשים וכו')",
        },
    },
    "required": [
        "bank_name",
        "offer_date",
        "validity_date",
        "total_loan_amount",
        "tracks",
        "fees",
        "effective_annual_interest_rate_pct",
        "early_repayment_note",
        "notes",
    ],
    "additionalProperties": False,
}

EXTRACTION_SYSTEM_PROMPT = """אתה עוזר מקצועי המסייע ליועץ משכנתאות בישראל לחלץ נתונים מדויקים ממסמכי
"אישור עקרוני" / הצעת משכנתא שמנפיקים בנקים למשכנתאות.

## המשימה
לקרוא טקסט שחולץ ממסמך כזה, ולהוציא ממנו במבנה JSON קבוע: שם הבנק, תמהיל
המסלולים המוצע (כל מסלול עם סכום, תקופה, ריבית, סוג צמידה), עמלות שצוינו
במפורש, וכל מידע רלוונטי אחר.

## כללים חשובים
1. **חלץ בלבד - אל תחשב.** אם ריבית אפקטיבית משוקללת לא מופיעה במפורש
   במסמך - השאר את effective_annual_interest_rate_pct כ-null. אל תנסה
   לחשב אותה בעצמך; חישוב כזה נעשה בנפרד ובאופן מדויק מחוץ למשימה שלך.
2. **מספרים בדיוק כפי שמופיעים** - סכומים, ריביות ותקופות חייבים להיות
   מדויקים למקור. אל תעגל, אל תמיר יחידות (למשל שנים לחודשים - בצע המרה
   רק אם ברור וחד-משמעי מהטקסט, ותציין זאת ב-notes אם ביצעת המרה).
3. **סיווג מסלולים (track_type)**: זהה לפי המאפיינים בפועל - "קבועה" +
   "לא צמודה"/"צמודה מדד" -> fixed_*; "פריים" -> variable_prime; "משתנה
   כל X שנים" בלי הצמדה -> variable_unlinked; עם הצמדה -> variable_linked_cpi;
   מסלול מסובסד/זכאות ממשרד השיכון -> eligibility.
4. אם יש כמה מסלולים מאותו סוג (למשל שני חלקים בפריים), כלול אותם
   כפריטים נפרדים ברשימת tracks.
5. אם פרט מסוים לא מופיע כלל במסמך - סמן null (למספרים/תאריכים) או השאר
   ריק, ואל תמציא ערך.
6. סכום כל ה-amount במסלולים אמור להיות קרוב לסכום ההלוואה הכולל
   (total_loan_amount) - אם יש פער משמעותי, ציין זאת ב-notes.

החזר אך ורק JSON תקין בסכימה שסופקה - ללא טקסט נוסף לפני או אחרי."""


def extract_offer(pdf_text: str, *, source_hint: Optional[str] = None) -> dict:
    """שולח את טקסט הצעת המשכנתא ל-Claude ומחזיר dict בסכימת ההצעה הקבועה."""
    client = anthropic.Anthropic()

    hint_line = f"רמז לזיהוי המסמך (שם הקובץ המקורי): {source_hint}\n\n" if source_hint else ""
    pdf_block = (
        f"{hint_line}"
        "להלן הטקסט שחולץ ממסמך הצעת/אישור עקרוני למשכנתא (ייתכנו שגיאות עיצוב "
        "קלות כתוצאה מחילוץ אוטומטי מ-PDF - התעלם מהן והתמקד בתוכן):\n\n"
        "```\n" + pdf_text + "\n```"
    )

    response = client.messages.create(
        model=MODEL,
        max_tokens=8000,
        thinking={"type": "adaptive"},
        system=[{"type": "text", "text": EXTRACTION_SYSTEM_PROMPT, "cache_control": {"type": "ephemeral", "ttl": "1h"}}],
        output_config={"format": {"type": "json_schema", "schema": OFFER_JSON_SCHEMA}},
        messages=[{"role": "user", "content": pdf_block}],
    )

    text_block = next(b.text for b in response.content if b.type == "text")
    return json.loads(text_block)


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("שימוש: python mortgage_offer_extraction.py <path_to_pdf_text_file>")
        sys.exit(1)
    with open(sys.argv[1], encoding="utf-8") as f:
        raw_text = f.read()
    result = extract_offer(raw_text, source_hint=sys.argv[1])
    print(json.dumps(result, ensure_ascii=False, indent=2))
