#!/usr/bin/env python3
"""
חילוץ תנאי סף ממכרז חדש (טקסט שחולץ מ-PDF) לפורמט JSON קבוע, בעזרת Claude.

הפלט תואם בדיוק לסכימה של tenders/tender_68_2026_conditions.json - כך שמנוע
ההשוואה (eligibility_engine.py) יודע לקרוא כל מכרז חדש בלי שום שינוי קוד.
זהו הבסיס להכללה האוטומטית: כל עוד הסכימה נשמרת, רק הנתונים משתנים בין מכרז
למכרז.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Callable, Optional

import anthropic

MODEL = "claude-opus-4-8"

# כמות ברירת המחדל של מעברי בדיקה-עצמית אחרי החילוץ הראשוני (ראה
# extract_and_verify_conditions למטה). המטרה: לא לפספס אף תנאי סף.
DEFAULT_VERIFICATION_PASSES = 3

# סכימת פריט תנאי סף בודד - משותפת לחילוץ הראשוני ולמעברי הבדיקה החוזרת.
_CONDITION_ITEM_SCHEMA = {
    "type": "object",
    "properties": {
        "id": {
            "type": "string",
            "description": "מספר הסעיף במכרז בדיוק כפי שמופיע, למשל '4.3.1.2'",
        },
        "category": {
            "type": "string",
            "description": "קטגוריית התנאי בעברית, למשל 'מנהלי', 'מקצועי - ארגוני', 'מקצועי - מנהל מסגרת'",
        },
        "requirement": {
            "type": "string",
            "description": "נוסח הדרישה המלא בעברית, כפי שמופיע במכרז (לא לקצר או לפרפרז)",
        },
        "type": {
            "type": "string",
            "enum": ["mandatory", "alternative", "procedural"],
            "description": (
                "mandatory=תנאי סף חובה עצמאי; "
                "alternative=חלק מקבוצת תנאים חלופית (מספיק לעמוד באחד מהם); "
                "procedural=תנאי טכני/נהלי (כמו ערבות הצעה) שאינו תנאי סף מהותי"
            ),
        },
        "alternative_group": {
            "type": ["string", "null"],
            "description": "מזהה קבוצת התנאים החלופית (רק אם type=alternative), למשל '4.3.1'. אחרת null.",
        },
        "applies_per_cluster": {
            "type": ["boolean", "null"],
            "description": "true אם התנאי חל בנפרד על כל יחידה/אשכול/בעל תפקיד (למשל דרישות מ'מנהל מסגרת' לכל מסגרת). אחרת null.",
        },
        "proof_needed": {
            "type": "string",
            "description": "האסמכתא/מסמך/נספח הנדרש להוכחת עמידה בתנאי, כפי שמצוין במכרז",
        },
    },
    "required": [
        "id",
        "category",
        "requirement",
        "type",
        "alternative_group",
        "applies_per_cluster",
        "proof_needed",
    ],
    "additionalProperties": False,
}

# סכימת ה-JSON שהמודל מחויב להחזיר (structured outputs) - זהה במבנה שלה
# לקובץ tenders/tender_68_2026_conditions.json הקיים.
CONDITION_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "tender_id": {
            "type": "string",
            "description": "מספר/מזהה המכרז כפי שמופיע במסמך, למשל '68/2026'",
        },
        "tender_title": {
            "type": "string",
            "description": "כותרת/נושא המכרז כפי שמופיע במסמך",
        },
        "conditions": {
            "type": "array",
            "description": "רשימת תנאי הסף (תנאי כניסה/השתתפות) בלבד - לא אמות מידה לאיכות/ניקוד",
            "items": _CONDITION_ITEM_SCHEMA,
        },
    },
    "required": ["tender_id", "tender_title", "conditions"],
    "additionalProperties": False,
}

# סכימת הפלט של מעבר בדיקה-חוזרת (verification pass) - ראה verify_conditions.
VERIFICATION_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "complete": {
            "type": "boolean",
            "description": "true אם אחרי סריקה חוזרת ומדוקדקת של הטקסט המקורי, אין אף תנאי סף חסר ואין שגיאות בתנאים הקיימים",
        },
        "missing_conditions": {
            "type": "array",
            "description": "תנאי סף שהיו בטקסט המקורי אך הוחמצו בסבב הקודם - להוסיף אותם (ריק אם לא נמצא כלום)",
            "items": _CONDITION_ITEM_SCHEMA,
        },
        "corrected_conditions": {
            "type": "array",
            "description": "גרסה מתוקנת ומלאה של תנאים קיימים שיש בהם טעות (ניסוח חלקי, סיווג שגוי וכו') - עם אותו id של התנאי הקיים. ריק אם הכל תקין.",
            "items": _CONDITION_ITEM_SCHEMA,
        },
        "notes": {
            "type": "string",
            "description": "הסבר קצר בעברית: מה נבדק בסבב הזה, ומה (אם בכלל) נמצא/תוקן",
        },
    },
    "required": ["complete", "missing_conditions", "corrected_conditions", "notes"],
    "additionalProperties": False,
}

# דוגמה קיימת (few-shot) מתוך tender_68_2026_conditions.json, כדי לעגן את
# המודל בדיוק על הפורמט והרמה הנכונה של פירוט.
_EXAMPLE_OUTPUT = {
    "tender_id": "68/2026",
    "tender_title": 'מתן שירותי "בית מעברי" בשירותי בריאות הנפש',
    "conditions": [
        {
            "id": "4.2.1",
            "category": "מנהלי",
            "requirement": "רישום כדין בישראל (אם חלה חובת רישום)",
            "type": "mandatory",
            "alternative_group": None,
            "applies_per_cluster": None,
            "proof_needed": "מסמכי התאגדות / רישום",
        },
        {
            "id": "4.3.1.1",
            "category": "מקצועי - ארגוני",
            "requirement": "רישיון מוסד גריאטרי בתוקף הכולל מחלקה לתשושי נפש עם 25+ מיטות",
            "type": "alternative",
            "alternative_group": "4.3.1",
            "applies_per_cluster": None,
            "proof_needed": "רישיון מוסד (נספח 5)",
        },
        {
            "id": "4.3.2.1.1",
            "category": "מקצועי - מנהל מסגרת",
            "requirement": "תואר שני + רישוי בתחום רלוונטי (MD פסיכיאטריה / MSW עו\"ס / פסיכולוגיה קלינית-שיקומית / קרימינולוגיה קלינית / ריפוי בעיסוק / סיעוד פסיכיאטרי)",
            "type": "mandatory",
            "alternative_group": None,
            "applies_per_cluster": True,
            "proof_needed": "תעודות השכלה + רישיון (נספח 6א'/6ב')",
        },
    ],
}

EXTRACTION_SYSTEM_PROMPT = f"""אתה עוזר משפטי-מקצועי המתמחה בניתוח מכרזים ממשלתיים בישראל,
עבור ארגון בתחום בריאות הנפש (דיור, שיקום, הוסטלים, דיור מוגן).

המשימה שלך: לקרוא טקסט שחולץ ממסמך "תנאי סף" (תנאי כניסה/השתתפות) של מכרז,
ולהוציא ממנו את **תנאי הסף בלבד** במבנה JSON קבוע.

## מה כן לחלץ
תנאי סף (Eligibility Conditions) הם דרישות "עובר/לא עובר" - אם המציע לא עומד
בהן, ההצעה שלו נפסלת על הסף ולא נבדקת לגופה. הן מופיעות בדרך כלל בסעיף שנקרא
"תנאי סף להשתתפות במכרז" או דומה לו, וכוללות בדרך כלל:
- תנאים מנהליים (רישום כדין, ניהול פנקסים, היעדר הרשעות, עסק חי וכו')
- ניסיון ארגוני נדרש (שנים, היקף, סוג אוכלוסייה)
- דרישות השכלה/רישוי/ותק מבעלי תפקידים מרכזיים (מנהלים, אנשי מקצוע)
- לעיתים גם ערבות הצעה (תנאי טכני-נהלי, לא תנאי סף מהותי - סמן type="procedural")

## מה לא לחלץ
אל תכלול "אמות מידה לאיכות" / "אמות מידה לניקוד" / "מחיר" - אלה קריטריונים
שמשפיעים על הדירוג התחרותי בין המציעים שכן עברו את תנאי הסף, לא תנאי סף עצמם.

## כללים חשובים
1. שמור על נוסח הדרישה (requirement) מדויק ומלא ככל האפשר, כפי שהוא מנוסח
   במכרז - אל תקצר, תפשט או תפרש. אם יש רשימה סגורה (למשל תארים מוכרים),
   כלול אותה במלואה.
2. מספרי הסעיפים (id) חייבים להיות בדיוק כפי שמופיעים במסמך המקורי.
3. תנאים "חלופיים" (type="alternative") הם קבוצה של 2+ תנאים שמספיק לעמוד
   באחד מהם - למשל "ניסיון X *או* רישיון Y". תן להם alternative_group משותף
   (למשל מספר הסעיף המשותף, כמו "4.3.1").
4. applies_per_cluster=true כאשר התנאי חל בנפרד על כל יחידה/מסגרת/אשכול -
   בדרך כלל דרישות מבעלי תפקידים (מנהל מסגרת, איש מקצוע) שצריך למנות עבור
   כל יחידה/אשכול בנפרד, ולא דרישה ארגונית כללית אחת.
5. אם לא ברור אם תנאי מסוים הוא תנאי סף או אמת מידה לאיכות - העדף להכליל אותו
   (עדיף חילוץ יתר על פספוס תנאי סף אמיתי).
6. אם הטקסט חלקי/לא ברור במקום מסוים, עשה כמיטב יכולתך על סמך מה שיש, ואל
   תמציא מספרי סעיפים או ניסוחים שלא מופיעים בטקסט.

## דוגמה למבנה הפלט הרצוי (ממכרז אחר, לצורך המחשה בלבד - אל תעתיק את התוכן):
```json
{json.dumps(_EXAMPLE_OUTPUT, ensure_ascii=False, indent=2)}
```

החזר אך ורק JSON תקין בסכימה שסופקה - ללא טקסט נוסף לפני או אחרי."""


def extract_conditions(pdf_text: str, *, source_hint: Optional[str] = None) -> dict:
    """
    שולח את טקסט המכרז ל-Claude ומחזיר dict בסכימת תנאי הסף הקבועה.
    """
    client = anthropic.Anthropic()

    hint_line = f"רמז לזיהוי המכרז (שם הקובץ המקורי): {source_hint}\n\n" if source_hint else ""
    user_content = (
        f"{hint_line}"
        "להלן הטקסט שחולץ ממסמך תנאי הסף של המכרז (ייתכנו שגיאות עיצוב קלות "
        "כתוצאה מחילוץ אוטומטי מ-PDF - התעלם מהן והתמקד בתוכן):\n\n"
        "```\n" + pdf_text + "\n```"
    )

    response = client.messages.create(
        model=MODEL,
        max_tokens=16000,
        thinking={"type": "adaptive"},
        system=EXTRACTION_SYSTEM_PROMPT,
        output_config={"format": {"type": "json_schema", "schema": CONDITION_JSON_SCHEMA}},
        messages=[{"role": "user", "content": user_content}],
    )

    text_block = next(b.text for b in response.content if b.type == "text")
    return json.loads(text_block)


VERIFICATION_SYSTEM_PROMPT = """אתה עורך בקרת איכות קפדני על חילוץ תנאי סף ממכרז ממשלתי (עבור ארגון
בתחום בריאות הנפש). קיבלת את הטקסט המקורי המלא של המכרז, ואת רשימת תנאי
הסף שכבר חולצו ממנו בסבב קודם.

## המשימה שלך
לקרוא את הטקסט המקורי **מחדש, שורה אחר שורה, מהתחלה ועד הסוף**, כאילו אתה
לא ראית את הרשימה הקיימת, ולבדוק:

1. **תנאי סף חסרים** - האם יש בטקסט תנאי/דרישת סף כלשהי (מנהלית, ניסיון
   ארגוני, השכלה/רישוי של בעלי תפקידים, ערבות וכו') שלא מופיעה ברשימה
   הקיימת? שים לב במיוחד לתנאים ש"מוסתרים" בתוך פסקאות ארוכות, נספחים,
   הערות שוליים, או מפוצלים על פני כמה סעיפי משנה.
2. **טעויות בתנאים קיימים** - האם יש תנאי שהניסוח שלו בפועל שונה/חלקי
   לעומת המקור, שסווג בטעות (mandatory לעומת alternative לעומת procedural),
   שה-alternative_group שלו שגוי, או שה-applies_per_cluster שגוי?

## כללים
- היה חשדן וקפדני - המטרה היא לא לפספס אף תנאי סף אמיתי. אם יש ספק אם
  משהו הוא תנאי סף - עדיף לכלול אותו כ-missing_conditions ולתת לשלב הבא
  להחליט, מאשר להשמיט אותו.
- אל תדווח שוב על תנאים שכבר קיימים ונכונים - רק על מה שחסר או שגוי.
- אל תמציא תנאים שלא מופיעים בטקסט המקורי בפירוש.
- אם אחרי סריקה מדוקדקת לא מצאת שום דבר חסר או שגוי - סמן complete=true
  והשאר את שתי הרשימות ריקות.

החזר אך ורק JSON תקין בסכימה שסופקה - ללא טקסט נוסף לפני או אחרי."""


def verify_conditions(pdf_text: str, conditions: dict) -> dict:
    """
    מעבר בדיקה-חוזרת יחיד: קורא שוב את טקסט המכרז המלא מול רשימת התנאים
    הנוכחית, ומחזיר dict עם complete/missing_conditions/corrected_conditions/notes.
    """
    client = anthropic.Anthropic()

    user_content = (
        "## הטקסט המקורי המלא של המכרז:\n```\n" + pdf_text + "\n```\n\n"
        "## תנאי הסף שכבר חולצו (לבדיקה חוזרת):\n```json\n"
        + json.dumps(conditions, ensure_ascii=False, indent=2)
        + "\n```"
    )

    response = client.messages.create(
        model=MODEL,
        max_tokens=16000,
        thinking={"type": "adaptive"},
        system=VERIFICATION_SYSTEM_PROMPT,
        output_config={"format": {"type": "json_schema", "schema": VERIFICATION_JSON_SCHEMA}},
        messages=[{"role": "user", "content": user_content}],
    )

    text_block = next(b.text for b in response.content if b.type == "text")
    return json.loads(text_block)


def _apply_verification_result(conditions: dict, verification: dict) -> bool:
    """
    ממזג תוצאות מעבר בדיקה לתוך conditions (in-place). מחזיר True אם היה
    שינוי בפועל (תנאי נוסף או תוקן).
    """
    existing_by_id = {c["id"]: i for i, c in enumerate(conditions["conditions"])}
    changed = False

    for corrected in verification.get("corrected_conditions", []):
        idx = existing_by_id.get(corrected["id"])
        if idx is not None and conditions["conditions"][idx] != corrected:
            conditions["conditions"][idx] = corrected
            changed = True

    for missing in verification.get("missing_conditions", []):
        if missing["id"] not in existing_by_id:
            conditions["conditions"].append(missing)
            existing_by_id[missing["id"]] = len(conditions["conditions"]) - 1
            changed = True

    return changed


def extract_and_verify_conditions(
    pdf_text: str,
    *,
    source_hint: Optional[str] = None,
    max_verification_passes: int = DEFAULT_VERIFICATION_PASSES,
    on_progress: Optional[Callable[[str], None]] = None,
) -> dict:
    """
    חילוץ תנאי סף עם בדיקה-עצמית מרובת-מעברים: אחרי החילוץ הראשוני, קוראים
    שוב ל-Claude עד max_verification_passes פעמים כדי לוודא שלא הוחמץ אף
    תנאי סף ושאין טעויות - כל מעבר קורא מחדש את הטקסט המלא של המכרז מול
    הרשימה הנוכחית. עוצר מוקדם אם מעבר מסוים לא מוצא שום דבר לתקן/להוסיף.

    on_progress, אם סופק, נקרא עם הודעת התקדמות בעברית לכל מעבר (לשימוש
    ע"י ה-CLI כדי להציג למשתמש שהבדיקה אכן מתבצעת).
    """
    def log(msg: str) -> None:
        if on_progress:
            on_progress(msg)

    log("מחלץ תנאי סף (סבב ראשוני)...")
    conditions = extract_conditions(pdf_text, source_hint=source_hint)
    log(f"  נמצאו {len(conditions.get('conditions', []))} תנאי סף בסבב הראשוני.")

    for pass_num in range(1, max_verification_passes + 1):
        log(f"מעבר בדיקה-עצמית {pass_num}/{max_verification_passes}: קורא שוב את המכרז לוודא שלא הוחמץ כלום...")
        verification = verify_conditions(pdf_text, conditions)
        changed = _apply_verification_result(conditions, verification)

        n_missing = len(verification.get("missing_conditions", []))
        n_corrected = len(verification.get("corrected_conditions", []))
        if n_missing or n_corrected:
            log(f"  ⚠️  נמצאו תיקונים: {n_missing} תנאים חדשים שהוחמצו קודם, {n_corrected} תיקונים לתנאים קיימים.")
            note = verification.get("notes")
            if note:
                log(f"  הערת הבודק: {note}")
        else:
            log("  לא נמצא שום דבר חסר/שגוי במעבר הזה.")

        if verification.get("complete") and not changed:
            log(f"  הבדיקה הושלמה מוקדם - {len(conditions.get('conditions', []))} תנאי סף סופיים, אין עוד ממצאים.")
            break
    else:
        log(f"  הגיע למספר המרבי של מעברי בדיקה ({max_verification_passes}) - {len(conditions.get('conditions', []))} תנאי סף סופיים.")

    return conditions


def save_conditions(conditions: dict, tenders_dir) -> Path:
    """שומר את תנאי המכרז שחולצו כקובץ JSON בתיקיית tenders/, בתבנית שם עקבית."""
    tenders_dir = Path(tenders_dir)
    tenders_dir.mkdir(parents=True, exist_ok=True)

    tender_id = conditions.get("tender_id", "unknown")
    safe_id = re.sub(r"[^0-9A-Za-z]+", "_", tender_id).strip("_") or "unknown"
    out_path = tenders_dir / f"tender_{safe_id}_conditions.json"

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(conditions, f, ensure_ascii=False, indent=2)

    return out_path


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("שימוש: python condition_extraction.py <path_to_pdf_text_file>")
        sys.exit(1)
    with open(sys.argv[1], encoding="utf-8") as f:
        raw_text = f.read()
    result = extract_conditions(raw_text, source_hint=sys.argv[1])
    print(json.dumps(result, ensure_ascii=False, indent=2))
