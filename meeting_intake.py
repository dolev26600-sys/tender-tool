#!/usr/bin/env python3
"""
עיבוד הערות משיחת אפיון ללקוח -> שלושה פלטים שחוסכים את הזמן שאחרי הפגישה.

הבעיה שזה פותר: אחרי כל פגישה נשארת שעה של עבודה - לתעד, להקליד למערכת,
לשלוח ללקוח סיכום, ולהכין רשימת מסמכים. זו עלות קבועה לכל לקוח, ולכן היא
בדיוק מה שמגביל כמה לקוחות אפשר לטפל בהם.

שלושת הפלטים:
1. **רשומה מובנית** - השדות מסודרים ומוכנים להקלדה למערכת, במקום לחפור
   בהערות מפוזרות.
2. **הודעה ללקוח** - סיכום בשפה פשוטה עם רשימת המסמכים, מוכנה לשליחה.
   חוסכת גם את שיחות ה"מה סיכמנו?" שמגיעות אחר כך.
3. **משימות ושאלות פתוחות** - מה נשאר לך לעשות, ומה לא נשאל בפגישה וכדאי
   לברר לפני שממשיכים.

השדה החשוב ביותר הוא stated_plans: כל מה שהלקוח אמר על העתיד (למכור, לפרוע,
לרשת, להחליף עבודה). זה בדיוק הקלט שבקרת האיכות (mortgage_review) מצליבה
מול התמהיל - כך שהפגישה מזינה את הבדיקה בלי הקלדה נוספת.
"""
from __future__ import annotations

import json
from typing import Optional

import anthropic

MODEL = "claude-opus-4-8"

INTAKE_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "borrowers": {
            "type": "array",
            "description": "הלווים בעסקה. רק מה שנאמר בפועל - אל תמציא פרטים.",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "age": {"type": ["integer", "null"]},
                    "employment_type": {
                        "type": ["string", "null"],
                        "description": "שכיר / עצמאי / פנסיונר / אחר - כפי שנאמר",
                    },
                    "seniority": {"type": ["string", "null"], "description": "ותק בעבודה, אם צוין"},
                    "monthly_income": {"type": ["number", "null"], "description": "הכנסה חודשית בש\"ח, אם צוינה"},
                    "notes": {"type": "string", "description": "כל דבר רלוונטי נוסף שנאמר על הלווה הזה"},
                },
                "required": ["name", "age", "employment_type", "seniority", "monthly_income", "notes"],
                "additionalProperties": False,
            },
        },
        "transaction": {
            "type": "object",
            "properties": {
                "purpose": {
                    "type": ["string", "null"],
                    "description": "מטרת ההלוואה: רכישת דירה ראשונה / משפרי דיור / השקעה / מיחזור / כל מטרה",
                },
                "property_type": {"type": ["string", "null"], "description": "יד שנייה / קבלן / מגרש / אחר"},
                "property_value": {"type": ["number", "null"], "description": "שווי/מחיר הנכס בש\"ח"},
                "equity": {"type": ["number", "null"], "description": "הון עצמי זמין בש\"ח"},
                "loan_needed": {"type": ["number", "null"], "description": "סכום המשכנתא הנדרש בש\"ח"},
                "area": {"type": ["string", "null"], "description": "אזור/עיר, אם צוין"},
                "timeline": {"type": ["string", "null"], "description": "לוח זמנים - מתי צריך אישור/כסף"},
            },
            "required": ["purpose", "property_type", "property_value", "equity", "loan_needed", "area", "timeline"],
            "additionalProperties": False,
        },
        "existing_obligations": {
            "type": "array",
            "description": "הלוואות/התחייבויות קיימות שהוזכרו (רכב, אשראי, משכנתא קיימת)",
            "items": {"type": "string"},
        },
        "stated_plans": {
            "type": "array",
            "description": (
                "השדה הקריטי: כל מה שהלקוח אמר על העתיד ועלול להשפיע על התמהיל - "
                "כוונה למכור, לפרוע מוקדם, ירושה צפויה, מעבר לעצמאי, לידה, "
                "פרישה, שינוי הכנסה. ציטוט קרוב למה שנאמר, לא פרשנות."
            ),
            "items": {"type": "string"},
        },
        "constraints_and_preferences": {
            "type": "array",
            "description": "אילוצים והעדפות שנאמרו: תקרת החזר חודשי, העדפת יציבות, רתיעה מסיכון וכו'",
            "items": {"type": "string"},
        },
        "documents_needed": {
            "type": "array",
            "description": "המסמכים שהלקוח צריך להביא, בהתאם למה שעלה בפגישה (שכיר -> תלושים; עצמאי -> שומות; וכו')",
            "items": {"type": "string"},
        },
        "advisor_action_items": {
            "type": "array",
            "description": "מה נשאר ליועץ לעשות אחרי הפגישה",
            "items": {"type": "string"},
        },
        "open_questions": {
            "type": "array",
            "description": (
                "מה לא נשאל בפגישה וכדאי לברר לפני שממשיכים - במיוחד פרטים "
                "שבלעדיהם אי אפשר לבנות תמהיל נכון או להגיש לבנק"
            ),
            "items": {"type": "string"},
        },
        "client_message": {
            "type": "string",
            "description": (
                "הודעה מוכנה לשליחה ללקוח (WhatsApp/מייל): סיכום קצר ואנושי של מה שסוכם, "
                "רשימת המסמכים לשליחה, ומה השלב הבא. בעברית פשוטה, בלי ז'רגון מקצועי, "
                "בלי מספרים שלא נאמרו בפגישה. טון מקצועי וחם, לא שיווקי."
            ),
        },
    },
    "required": [
        "borrowers",
        "transaction",
        "existing_obligations",
        "stated_plans",
        "constraints_and_preferences",
        "documents_needed",
        "advisor_action_items",
        "open_questions",
        "client_message",
    ],
    "additionalProperties": False,
}

INTAKE_SYSTEM_PROMPT = """אתה עוזר של יועץ משכנתאות בישראל. קיבלת הערות או תמלול משיחת אפיון עם
לקוח, ותפקידך להפוך אותן לשלושה דברים: רשומה מובנית, רשימת משימות, והודעה
מוכנה לשליחה ללקוח.

## כללים קריטיים

1. **אל תמציא שום דבר.** אם פרט לא נאמר - השאר null או רשימה ריקה. יועץ
   שיסתמך על מספר שהמצאת יגיש לבנק נתון שגוי. חוסר מידע הוא תשובה לגיטימית,
   ניחוש הוא לא.
2. **stated_plans הוא השדה החשוב ביותר.** כל אמירה על העתיד - "נמכור בעוד
   כמה שנים", "תגיע ירושה", "אני עובר לעצמאי", "מתכננים ילד" - חייבת להיכנס
   לשם, קרוב ככל האפשר לניסוח המקורי. אלה בדיוק הדברים שנשכחים ואז סותרים
   את התמהיל שנבנה.
3. **open_questions צריך להיות שימושי, לא ממלא מקום.** רשום רק מה שבאמת
   חסר כדי להתקדם - למשל הכנסה שלא צוינה, ותק תעסוקתי, או הון עצמי מדויק.
   אם הפגישה הייתה יסודית, רשימה קצרה או ריקה היא תשובה נכונה.
4. **documents_needed צריך להתאים למה שעלה בפגישה.** שכיר ועצמאי צריכים
   מסמכים שונים; מיחזור דורש מסמכים אחרים מרכישה. אל תדביק רשימה גנרית.

## על ההודעה ללקוח (client_message)

- עברית פשוטה. הלקוח אינו איש מקצוע.
- אל תכניס מספרים שלא נאמרו בפגישה, ואל תבטיח שום דבר על ריביות או אישור.
- מבנה: משפט או שניים על מה שסוכם, רשימת מסמכים ברורה, ומשפט על השלב הבא.
- טון מקצועי וחם. לא שיווקי, לא מתרפס, בלי סופרלטיבים.
- אורך: קצר מספיק שיקראו את זה בטלפון.

החזר אך ורק JSON תקין בסכימה שסופקה - ללא טקסט נוסף לפני או אחרי."""


def process_meeting(notes: str, *, advisor_name: Optional[str] = None) -> dict:
    """
    הופך הערות/תמלול משיחת אפיון לרשומה מובנית + הודעה ללקוח + משימות.
    """
    if not notes.strip():
        raise ValueError("לא הוזנו הערות מהפגישה")

    client = anthropic.Anthropic()

    signature = f"\n\nשם היועץ לחתימה בהודעה ללקוח: {advisor_name}" if advisor_name else ""
    user_block = (
        "להלן ההערות/התמלול משיחת האפיון:\n\n```\n" + notes.strip() + "\n```" + signature
    )

    response = client.messages.create(
        model=MODEL,
        max_tokens=8000,
        thinking={"type": "adaptive"},
        system=[{"type": "text", "text": INTAKE_SYSTEM_PROMPT, "cache_control": {"type": "ephemeral", "ttl": "1h"}}],
        output_config={"format": {"type": "json_schema", "schema": INTAKE_JSON_SCHEMA}},
        messages=[{"role": "user", "content": user_block}],
    )

    text_block = next(b.text for b in response.content if b.type == "text")
    return json.loads(text_block)


def format_record_text(record: dict) -> str:
    """
    הרשומה כטקסט להעתקה/הדבקה למערכת ניהול הלקוחות, בסדר קבוע כדי שאפשר
    יהיה לעבור עליה במהירות באותו מקום בכל פעם.
    """
    lines: list[str] = ["=== רשומת לקוח משיחת אפיון ===", ""]

    lines.append("-- לווים --")
    for b in record.get("borrowers", []):
        parts = [b.get("name") or "ללא שם"]
        if b.get("age"):
            parts.append(f"גיל {b['age']}")
        if b.get("employment_type"):
            parts.append(b["employment_type"])
        if b.get("seniority"):
            parts.append(f"ותק {b['seniority']}")
        if b.get("monthly_income"):
            parts.append(f"הכנסה {b['monthly_income']:,.0f} ₪")
        lines.append("  • " + " · ".join(parts))
        if b.get("notes"):
            lines.append(f"    {b['notes']}")
    lines.append("")

    t = record.get("transaction", {})
    lines.append("-- העסקה --")
    for label, key, is_money in [
        ("מטרה", "purpose", False),
        ("סוג נכס", "property_type", False),
        ("אזור", "area", False),
        ("שווי נכס", "property_value", True),
        ("הון עצמי", "equity", True),
        ("סכום נדרש", "loan_needed", True),
        ("לוח זמנים", "timeline", False),
    ]:
        value = t.get(key)
        if value:
            lines.append(f"  {label}: {f'{value:,.0f} ₪' if is_money else value}")
    lines.append("")

    for title, key in [
        ("-- התחייבויות קיימות --", "existing_obligations"),
        ("-- תוכניות שהלקוח ציין (חשוב לתמהיל) --", "stated_plans"),
        ("-- אילוצים והעדפות --", "constraints_and_preferences"),
        ("-- מסמכים לאיסוף --", "documents_needed"),
        ("-- משימות ליועץ --", "advisor_action_items"),
        ("-- שאלות פתוחות --", "open_questions"),
    ]:
        items = record.get(key) or []
        if items:
            lines.append(title)
            lines.extend(f"  • {item}" for item in items)
            lines.append("")

    return "\n".join(lines)


def stated_plans_for_review(record: dict) -> str:
    """
    מייצר את הטקסט שנכנס ישירות לשדה "מה שהלקוח אמר בפגישה" בבקרת האיכות,
    כך שהפגישה מזינה את הבדיקה בלי הקלדה מחדש.
    """
    chunks: list[str] = []

    borrowers = record.get("borrowers", [])
    if borrowers:
        described = []
        for b in borrowers:
            bits = [b.get("name") or "לווה"]
            if b.get("age"):
                bits.append(f"גיל {b['age']}")  # ניסוח ניטרלי - לא מניחים מגדר מהשם
            if b.get("employment_type"):
                bits.append(b["employment_type"])
            if b.get("monthly_income"):
                bits.append(f"הכנסה {b['monthly_income']:,.0f} ₪")
            described.append(", ".join(bits))
        chunks.append("לווים: " + "; ".join(described) + ".")

    for label, key in [
        ("תוכניות שצוינו", "stated_plans"),
        ("אילוצים והעדפות", "constraints_and_preferences"),
        ("התחייבויות קיימות", "existing_obligations"),
    ]:
        items = record.get(key) or []
        if items:
            chunks.append(f"{label}: " + "; ".join(items) + ".")

    return "\n".join(chunks)
