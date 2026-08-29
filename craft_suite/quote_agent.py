#!/usr/bin/env python3
"""
סוכן הצעת מחיר: הופך תיאור חופשי של עבודה (טקסט שכתב בעל המקצוע) להצעת
מחיר מובנית - פירוט סעיפים, כמויות, מחיר יחידה וסה"כ - בעזרת Claude.

אותו דפוס בדיוק כמו condition_extraction.py: קלט טקסט חופשי -> פלט JSON
קבוע (structured output), כדי שהממשק (app.py) לא צריך "לפרסר" טקסט חופשי.
"""
from __future__ import annotations

import anthropic
import json

MODEL = "claude-opus-4-8"

# שיעור מע"מ נוכחי בישראל - יש לעדכן כאן אם השיעור משתנה.
VAT_RATE = 0.18

QUOTE_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "job_title": {
            "type": "string",
            "description": "כותרת קצרה לעבודה, למשל 'החלפת לוח חשמל ראשי'",
        },
        "items": {
            "type": "array",
            "description": "פירוט סעיפי העבודה (עבודה + חומרים) בנפרד",
            "items": {
                "type": "object",
                "properties": {
                    "description": {"type": "string", "description": "תיאור הסעיף"},
                    "quantity": {"type": "number", "description": "כמות"},
                    "unit": {"type": "string", "description": "יחידת מידה, למשל 'יח׳', 'מ״ר', 'שעה'"},
                    "unit_price": {"type": "number", "description": "מחיר ליחידה בש״ח, לפי מחירי שוק סבירים בישראל"},
                },
                "required": ["description", "quantity", "unit", "unit_price"],
                "additionalProperties": False,
            },
        },
        "notes": {
            "type": "string",
            "description": "הערות קצרות רלוונטיות להצעה (למשל: לא כולל פינוי פסולת, תוקף ההצעה 14 יום)",
        },
    },
    "required": ["job_title", "items", "notes"],
    "additionalProperties": False,
}

QUOTE_SYSTEM_PROMPT = """אתה עוזר לבעלי מקצוע בישראל (חשמלאים, אינסטלטורים, שיפוצניקים ובעלי
מקצוע דומים) להכין הצעת מחיר מסודרת ללקוח, מתוך תיאור חופשי וקצר שהם
כותבים על העבודה.

## המשימה שלך
לקרוא את תיאור העבודה, ולפרק אותו לסעיפים ברורים (עבודה + חומרים בנפרד
ככל שהגיוני), עם כמות, יחידת מידה ומחיר יחידה סביר לפי מחירי שוק נהוגים
בישראל לענף הרלוונטי. אם התיאור לא מציין כמויות - השתמש בהערכה סבירה
וציין זאת בהערות.

## כללים
- אל תמציא עבודה שלא נזכרה בתיאור.
- מחירים צריכים להיות ריאליים למחירי שוק ישראליים נוכחיים, לא מוגזמים
  ולא נמוכים מדי.
- אם חסר מידע קריטי לתמחור מדויק (למשל שטח, מרחק, סוג חומר) - תמחר לפי
  הנחת עבודה סבירה וציין את ההנחה הזו בהערות, כדי שבעל המקצוע יוכל
  לתקן לפני שליחה ללקוח.

החזר אך ורק JSON תקין בסכימה שסופקה - ללא טקסט נוסף לפני או אחרי."""


def draft_quote(job_description: str, *, trade: str | None = None) -> dict:
    """
    שולח את תיאור העבודה ל-Claude ומחזיר dict עם job_title/items/notes,
    ואז מוסיף חישוב סכומים (line_total לכל סעיף, subtotal, מע"מ, total)
    כדי שהקוד הקורא לא יצטרך לחשב בעצמו ולסמוך על חשבון של המודל.
    """
    client = anthropic.Anthropic()

    trade_line = f"תחום העבודה: {trade}\n\n" if trade else ""
    user_block = f"{trade_line}תיאור העבודה (כפי שכתב בעל המקצוע):\n{job_description}"

    response = client.messages.create(
        model=MODEL,
        max_tokens=4000,
        system=[{"type": "text", "text": QUOTE_SYSTEM_PROMPT, "cache_control": {"type": "ephemeral", "ttl": "1h"}}],
        output_config={"format": {"type": "json_schema", "schema": QUOTE_JSON_SCHEMA}},
        messages=[{"role": "user", "content": user_block}],
    )

    text_block = next(b.text for b in response.content if b.type == "text")
    quote = json.loads(text_block)

    for item in quote["items"]:
        item["line_total"] = round(item["quantity"] * item["unit_price"], 2)

    subtotal = round(sum(item["line_total"] for item in quote["items"]), 2)
    vat_amount = round(subtotal * VAT_RATE, 2)
    quote["subtotal"] = subtotal
    quote["vat_rate"] = VAT_RATE
    quote["vat_amount"] = vat_amount
    quote["total"] = round(subtotal + vat_amount, 2)

    return quote
