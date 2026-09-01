#!/usr/bin/env python3
"""
מנוע השוואה בין כמה הצעות משכנתא מבנקים שונים (אחרי שכל אחת חולצה
ב-mortgage_offer_extraction.py). כל המספרים (החזר חודשי, ריבית משוקללת,
מבחן קיצון) כבר חושבו במדויק בפייתון ב-mortgage_math.py - Claude מקבל
אותם מוכנים ומשתמש בהם רק לניתוח איכותי והמלצה מנומקת, לא לחישוב.
"""
from __future__ import annotations

import json
from typing import Optional

import anthropic

from mortgage_math import blended_offer_stats, stress_test_stats

MODEL = "claude-opus-4-8"

COMPARISON_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "ranking": {
            "type": "array",
            "description": "שמות הבנקים מסודרים מהמומלץ ביותר לפחות מומלץ, לפי שיקול הדעת המקצועי",
            "items": {"type": "string"},
        },
        "overall_recommendation": {
            "type": "string",
            "description": "המלצה כללית מנומקת (3-6 משפטים) - איזו הצעה עדיפה ולמה, בהתחשב בתמהיל, בעלות הכוללת, וברמת הסיכון (חשיפה לריבית משתנה/מדד)",
        },
        "per_bank": {
            "type": "array",
            "description": "ניתוח לכל בנק בנפרד, לפי אותו סדר כמו ranking",
            "items": {
                "type": "object",
                "properties": {
                    "bank_name": {"type": "string"},
                    "pros": {"type": "array", "items": {"type": "string"}},
                    "cons": {"type": "array", "items": {"type": "string"}},
                    "risk_notes": {
                        "type": "string",
                        "description": "הערכת רמת הסיכון של התמהיל (חשיפה לעליית ריבית/מדד) בהתבסס על תוצאות מבחן הקיצון שסופקו",
                    },
                },
                "required": ["bank_name", "pros", "cons", "risk_notes"],
                "additionalProperties": False,
            },
        },
        "questions_to_verify": {
            "type": "array",
            "description": "פרטים חשובים שכדאי לוודא מול הבנק לפני החלטה סופית (עמלות נסתרות, תוקף ההצעה, ביטוחים נדרשים וכו')",
            "items": {"type": "string"},
        },
    },
    "required": ["ranking", "overall_recommendation", "per_bank", "questions_to_verify"],
    "additionalProperties": False,
}

COMPARISON_SYSTEM_PROMPT = """אתה עוזר של יועץ משכנתאות מוסמך בישראל. תקבל כמה הצעות משכנתא מבנקים
שונים, כאשר **כל הנתונים המספריים כבר חושבו ומוכנים** (סכום כולל, ריבית
ממוצעת משוקללת, החזר חודשי התחלתי, והחזר חודשי בתרחיש קיצון של עליית
ריבית/מדד). בנוסף ייתכנו העדפות/אילוצים של הלקוח.

## המשימה שלך
לנתח את ההצעות ולתת המלצה מנומקת - **אתה לא מחשב מספרים, רק מנתח את
המספרים שכבר סופקו לך**. התייחס במפורש ל:
1. עלות (ריבית משוקללת, החזר חודשי, עלות כוללת משוערת לאורך התקופה).
2. סיכון - חשיפה לריבית משתנה ולהצמדה למדד, ומה קורה בתרחיש הקיצון.
3. גמישות (תקופת ההלוואה, אפשרויות פירעון מוקדם אם ידוע).
4. התאמה להעדפות/אילוצים של הלקוח, אם סופקו.

## כללים חשובים
1. אל תמציא נתונים שלא סופקו לך - אם משהו חסר (למשל עמלת פירעון מוקדם
   לא ידועה), ציין זאת ב-questions_to_verify במקום להניח.
2. היה מאוזן ומקצועי - זו כלי עזר להחלטה, לא תחליף לבדיקה סופית מול
   הבנק ולשיקול הדעת של היועץ/הלקוח. ציין זאת בבירור אם רלוונטי.
3. כתוב בעברית תקנית, ברורה ומעשית, בטון של יועץ מקצועי ולא שיווקי.
4. אם ההצעות קרובות מאוד זו לזו במספרים, אמור זאת בכנות במקום להמציא
   העדפה מלאכותית.

החזר אך ורק JSON תקין בסכימה שסופקה - ללא טקסט נוסף לפני או אחרי."""


def build_offer_analysis(
    raw_offer: dict,
    *,
    rate_increase_pct: float = 2.0,
    cpi_annual_pct: float = 3.0,
) -> dict:
    """מעשיר הצעה גולמית אחת (מ-mortgage_offer_extraction) בכל הנתונים
    המספריים המחושבים: סטטיסטיקות מצרפיות + מבחן קיצון. פונקציה טהורה,
    אין קריאת רשת."""
    stats = blended_offer_stats(raw_offer)
    stress = stress_test_stats(
        raw_offer.get("tracks", []),
        rate_increase_pct=rate_increase_pct,
        cpi_annual_pct=cpi_annual_pct,
    )
    return {
        "bank_name": raw_offer.get("bank_name", "?"),
        "offer_date": raw_offer.get("offer_date"),
        "validity_date": raw_offer.get("validity_date"),
        "fees": raw_offer.get("fees", []),
        "effective_annual_interest_rate_pct": raw_offer.get("effective_annual_interest_rate_pct"),
        "early_repayment_note": raw_offer.get("early_repayment_note"),
        "notes": raw_offer.get("notes", ""),
        "stats": stats,
        "stress_test": stress,
    }


def compare_offers(analyzed_offers: list[dict], *, client_preferences: Optional[str] = None) -> dict:
    """
    משווה כמה הצעות שכבר עברו build_offer_analysis, ומחזיר דירוג + המלצה
    מנומקת + ניתוח פר-בנק, בעזרת Claude. client_preferences הוא טקסט חופשי
    אופציונלי (למשל "מעדיף יציבות על פני ריבית נמוכה", "תקציב חודשי עד 6000 ש\"ח").
    """
    if len(analyzed_offers) < 2:
        raise ValueError("צריך לפחות שתי הצעות כדי להשוות")

    client = anthropic.Anthropic()

    offers_block = "## ההצעות לניתוח (עם כל הנתונים המספריים המחושבים מראש):\n```json\n" + json.dumps(
        analyzed_offers, ensure_ascii=False, indent=2
    ) + "\n```"

    prefs_block = ""
    if client_preferences and client_preferences.strip():
        prefs_block = "\n\n## העדפות/אילוצים של הלקוח:\n" + client_preferences.strip()

    response = client.messages.create(
        model=MODEL,
        max_tokens=8000,
        thinking={"type": "adaptive"},
        system=[{"type": "text", "text": COMPARISON_SYSTEM_PROMPT, "cache_control": {"type": "ephemeral", "ttl": "1h"}}],
        output_config={"format": {"type": "json_schema", "schema": COMPARISON_JSON_SCHEMA}},
        messages=[{"role": "user", "content": offers_block + prefs_block}],
    )

    text_block = next(b.text for b in response.content if b.type == "text")
    result = json.loads(text_block)

    stats_by_bank = {o["bank_name"]: o for o in analyzed_offers}
    for entry in result.get("per_bank", []):
        offer = stats_by_bank.get(entry["bank_name"], {})
        entry["stats"] = offer.get("stats", {})
        entry["stress_test"] = offer.get("stress_test", {})

    return result


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("שימוש: python mortgage_comparison.py <offer1.json> <offer2.json> [...]")
        sys.exit(1)

    raw_offers = []
    for path in sys.argv[1:]:
        with open(path, encoding="utf-8") as f:
            raw_offers.append(json.load(f))

    analyzed = [build_offer_analysis(o) for o in raw_offers]
    comparison = compare_offers(analyzed)
    print(json.dumps(comparison, ensure_ascii=False, indent=2))
