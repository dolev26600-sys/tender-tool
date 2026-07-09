#!/usr/bin/env python3
"""
מנוע ההשוואה הגנרי בין פרופיל החברה (company_profile.json) לבין תנאי הסף
של מכרז נתון (tenders/<tender_id>_conditions.json) - בעזרת Claude, במקום
לוגיקת if/else ידנית לכל תנאי (כפי שהיה ב-MVP המקורי).

כל עוד שני קבצי ה-JSON נשארים באותה סכימה, המנוע הזה לא צריך להשתנות בין
מכרז למכרז - זה מה שהופך את הכלי מ"סקריפט חד פעמי" ל"כלי חי".
"""
from __future__ import annotations

import json

import anthropic

MODEL = "claude-opus-4-8"

STATUS_MET = "met"
STATUS_LIKELY = "likely_met"
STATUS_GAP = "gap"
STATUS_UNKNOWN = "unknown"

STATUS_LABELS = {
    STATUS_MET: "✅ עומדים",
    STATUS_LIKELY: "🟡 כנראה עומדים - נדרש אימות/פרטים מדויקים",
    STATUS_GAP: "🔴 פער - לא עומדים כרגע",
    STATUS_UNKNOWN: "⚪ לא ניתן לקבוע - חסר מידע בפרופיל החברה",
}

EVAL_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "overall_summary": {
            "type": "string",
            "description": "סיכום כללי קצר (2-4 משפטים) של מוכנות הארגון מול המכרז - מגמה כללית, הפערים המרכזיים, ומה הצעד הבא הכי חשוב",
        },
        "results": {
            "type": "array",
            "description": "תוצאת ההשוואה עבור כל תנאי סף במכרז, בדיוק לפי סדר וה-id של תנאי המכרז",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string", "description": "מספר הסעיף, זהה ל-id בקובץ תנאי המכרז"},
                    "status": {
                        "type": "string",
                        "enum": [STATUS_MET, STATUS_LIKELY, STATUS_GAP, STATUS_UNKNOWN],
                    },
                    "reasoning": {
                        "type": "string",
                        "description": "נימוק מפורט בעברית: אילו נתונים בפרופיל החברה תומכים (או לא) בעמידה בתנאי, ומה בדיוק חסר כדי לעבור מ-likely_met ל-met",
                    },
                    "missing_info": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "רשימת פרטים קונקרטיים וספציפיים שחסרים בפרופיל כדי לקבוע סטטוס ודאי (ריק אם אין)",
                    },
                },
                "required": ["id", "status", "reasoning", "missing_info"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["overall_summary", "results"],
    "additionalProperties": False,
}

EVALUATION_SYSTEM_PROMPT = """אתה יועץ המסייע לארגון בתחום בריאות הנפש (דיור, שיקום, הוסטלים,
דיור מוגן, מסגרות לינה חוץ-ביתיות) להעריך אם הוא עומד בתנאי הסף של מכרזים
ממשלתיים, לפני שהארגון מחליט אם לגשת אליהם.

תקבל שני קבצי JSON:
1. פרופיל הארגון - נתונים עובדתיים על הארגון: ותק, היקף פעילות, ניסיון
   תפעולי, הכשרות זמינות בצוות, פרטי מנהלים, מסמכים קיימים וכו'.
2. תנאי הסף של מכרז ספציפי - רשימת דרישות, כל אחת עם מספר סעיף, קטגוריה,
   נוסח הדרישה, סוג (mandatory/alternative/procedural), וסוג ההוכחה הנדרשת.

## המשימה
עבור **כל תנאי סף** ברשימה, קבע סטטוס אחד מתוך ארבעה, וכתוב נימוק מפורט:

- **met** - הפרופיל מכיל מידע מפורש וחד-משמעי שהארגון עומד בתנאי במלואו
  (כולל תאריכים/מספרים קונקרטיים כשהתנאי דורש אותם, לא רק הצהרה כללית).
- **likely_met** - יש בפרופיל התאמה חזקה/סבירה לתנאי (למשל תחום ניסיון
  מתאים, הכשרה רלוונטית), אבל חסרים פרטים קונקרטיים (תאריכים מדויקים,
  מספרים, שם איש קשר לאימות) כדי לקבוע בוודאות מלאה. תמיד פרט ב-missing_info
  בדיוק אילו פרטים חסרים.
- **gap** - הפרופיל מראה בבירור שהארגון *אינו* עומד בתנאי (למשל תחום
  התמחות שונה לגמרי, ותק לא מספיק גם אם משלימים את כל הנתונים החסרים).
- **unknown** - אין בפרופיל שום מידע רלוונטי לתנאי הזה (למשל שדה מסומן
  "לא צוין - יש להשלים", או שהתנאי כלל לא קשור לתחומי המידע שיש בפרופיל).
  זהו "חוסר מידע", לא פער מהותי - אל תבלבל בין השניים.

## כללים חשובים
1. **תנאים חלופיים (type=alternative)**: תנאים עם אותו alternative_group
   הם קבוצה שמספיק לעמוד באחד ממנה. העריך כל תנאי בקבוצה בנפרד לפי גופו,
   אבל ציין בנימוק אם ההערכה של תנאי אחד בקבוצה משפיעה על הצורך (או אי-הצורך)
   לעמוד באחרים באותה קבוצה.
2. **תנאים לפי אשכול (applies_per_cluster=true)**: אלה דרישות שצריך למנות
   אדם/משאב מתאים לכל יחידה/אשכול בנפרד (למשל "מנהל מסגרת" לכל מסגרת).
   אם בפרופיל יש כמה מנהלים עם פרטים שונים, בדוק אם יש **מספיק** מנהלים
   שעונים על הדרישה (לא רק אחד), וציין זאת בנימוק.
3. **תנאים נהליים (type=procedural)**: כמו ערבות הצעה - אלה בדרך כלל אינם
   תלויים בפרופיל המקצועי של הארגון אלא בפעולה מנהלתית/פיננסית נפרדת (הפקת
   ערבות). סמן כ-unknown עם הסבר שזה תלוי בפעולה נפרדת, לא בנתוני הפרופיל.
4. **דיוק לפני אופטימיות**: אל תסמן met אלא אם יש עוגן עובדתי מפורש וממוקד
   בפרופיל (תאריך, מספר, שם, רישיון קונקרטי). אם התנאי דורש "2+ שנים מתוך
   5 האחרונות" והפרופיל רק אומר "יש ניסיון" בלי תאריכים - זה likely_met, לא
   met, ו-missing_info חייב לפרט בדיוק אילו תאריכים/מספרים חסרים.
5. **שדות "לא צוין - יש להשלים"** בפרופיל משמעם חוסר מידע (unknown לגבי
   אותו פרט הספציפי), לא פער אוטומטי - אלא אם כן ברור מהקשר אחר בפרופיל
   שהארגון בכל מקרה לא עומד בדרישה.
6. כתוב בעברית תקנית, ברורה ומעשית - הנימוקים מיועדים לאדם שיחליט האם
   לגשת למכרז ומה להשלים קודם.

החזר אך ורק JSON תקין בסכימה שסופקה, עם תוצאה אחת לכל תנאי ברשימת
conditions של המכרז - ללא טקסט נוסף לפני או אחרי."""


def evaluate_eligibility(profile: dict, tender: dict) -> dict:
    """
    מריץ השוואה סמנטית גנרית בין פרופיל החברה לתנאי מכרז נתון, בעזרת Claude.
    מחזיר dict עם 'overall_summary' ו-'results' (רשימה מועשרת בפרטי כל תנאי
    מקובץ המכרז המקורי, לנוחות התצוגה בדו"ח).

    חיסכון בעלות: פרופיל החברה נשלח בשלמותו בכל בדיקת מכרז, אבל הוא כמעט
    אף פעם לא משתנה בין מכרז למכרז - לכן הוא ממוקם *לפני* נקודת ה-cache,
    ותנאי המכרז הספציפי (שכן משתנה בכל פעם) מגיע *אחריה*. כך בדיקת מכרז
    שנייה/שלישית באותו יום (עד שעה) קוראת את הפרופיל מהמטמון בעלות מופחתת.
    """
    client = anthropic.Anthropic()

    profile_block = "## פרופיל הארגון (JSON):\n```json\n" + json.dumps(profile, ensure_ascii=False, indent=2) + "\n```"
    tender_block = "## תנאי הסף של המכרז (JSON):\n```json\n" + json.dumps(tender, ensure_ascii=False, indent=2) + "\n```"

    response = client.messages.create(
        model=MODEL,
        max_tokens=16000,
        thinking={"type": "adaptive"},
        system=[{"type": "text", "text": EVALUATION_SYSTEM_PROMPT, "cache_control": {"type": "ephemeral", "ttl": "1h"}}],
        output_config={"format": {"type": "json_schema", "schema": EVAL_JSON_SCHEMA}},
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": profile_block, "cache_control": {"type": "ephemeral", "ttl": "1h"}},
                    {"type": "text", "text": tender_block},
                ],
            }
        ],
    )

    text_block = next(b.text for b in response.content if b.type == "text")
    result = json.loads(text_block)

    # מעשירים כל תוצאה בפרטי התנאי המקוריים (קטגוריה/נוסח/סוג), לנוחות התצוגה
    conditions_by_id = {c["id"]: c for c in tender.get("conditions", [])}
    for r in result.get("results", []):
        cond = conditions_by_id.get(r["id"], {})
        r["category"] = cond.get("category", "")
        r["requirement"] = cond.get("requirement", "")
        r["type"] = cond.get("type", "")
        r["alternative_group"] = cond.get("alternative_group")
        r["status_label"] = STATUS_LABELS.get(r["status"], r["status"])

    return result


if __name__ == "__main__":
    import sys
    from pathlib import Path

    if len(sys.argv) < 2:
        print("שימוש: python eligibility_engine.py <path_to_tender_conditions.json>")
        sys.exit(1)

    tender_path = Path(sys.argv[1])
    profile_path = Path(__file__).parent / "company_profile.json"

    with open(tender_path, encoding="utf-8") as f:
        tender_data = json.load(f)
    with open(profile_path, encoding="utf-8") as f:
        profile_data = json.load(f)

    evaluation = evaluate_eligibility(profile_data, tender_data)
    print(json.dumps(evaluation, ensure_ascii=False, indent=2))
