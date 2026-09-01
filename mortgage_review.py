#!/usr/bin/env python3
"""
בקרת איכות על המלצת תמהיל, לפני שהיא יוצאת ללקוח ("חוות דעת שנייה").

שתי שכבות, בכוונה נפרדות:

1. **בדיקות כלל דטרמיניסטיות** (run_rule_checks) - מגבלות מספריות שאפשר
   לבדוק בוודאות בפייתון: שיעור מסלולים קבועים, LTV, יחס החזר להכנסה
   (גם בתרחיש קיצון), אורך תקופה, וחשיפה לעמלת פירעון מוקדם מול אופק
   התכנון שהלקוח הצהיר עליו.

2. **סקירת שיפוט של Claude** (ai_review) - מה שאי אפשר לנסח ככלל: האם
   התמהיל באמת מתיישב עם מה שהלקוח אמר בפגישה, מה הוחמץ, ומה כדאי לשאול
   אותו לפני שסוגרים.

הערה חשובה על הרגולציה: הקבועים למטה הם **ערכי ברירת מחדל לאימות**, לא
מקור סמכות. הוראות בנק ישראל משתנות מעת לעת, והכלי נועד להאיר נקודות
לבדיקה - לא להחליף את האחריות המקצועית של היועץ לוודא מול ההוראה העדכנית.
"""
from __future__ import annotations

import json
from typing import Optional

import anthropic

from mortgage_math import VARIABLE_TRACK_TYPES, blended_offer_stats, stress_test_stats

MODEL = "claude-opus-4-8"

FIXED_TRACK_TYPES = {"fixed_unlinked", "fixed_linked_cpi"}
CPI_LINKED_TRACK_TYPES = {"fixed_linked_cpi", "variable_linked_cpi"}

SEVERITY_CRITICAL = "critical"
SEVERITY_WARNING = "warning"
SEVERITY_NOTE = "note"

SEVERITY_ORDER = {SEVERITY_CRITICAL: 0, SEVERITY_WARNING: 1, SEVERITY_NOTE: 2}

SEVERITY_LABELS = {
    SEVERITY_CRITICAL: "🔴 עצור - לבדוק לפני שיוצא ללקוח",
    SEVERITY_WARNING: "🟡 שווה בדיקה",
    SEVERITY_NOTE: "⚪ לתשומת לב",
}

# --- ערכי ברירת מחדל לאימות מול הוראות בנק ישראל העדכניות ---------------
# אלה אינם ציטוט של ההוראה אלא ערכי סף מקובלים, שנועדו להצביע על מקומות
# שדורשים בדיקה. כל ממצא שמופק מהם מסומן במפורש כ"לאימות מול ההוראה".

MIN_FIXED_SHARE = 1 / 3          # שיעור מזערי מקובל של מסלולים בריבית קבועה
MAX_TERM_MONTHS = 30 * 12        # אורך תקופה מרבי מקובל
MAX_PTI = 0.40                   # סף מקובל אצל הבנקים בפועל
REGULATORY_MAX_PTI = 0.50        # תקרת בנק ישראל
MAX_STRESSED_PTI = 0.50          # יחס החזר בתרחיש קיצון - סף אזהרה

MAX_LTV_BY_BUYER = {
    "first_home": 0.75,   # דירה יחידה
    "improving": 0.70,    # משפרי דיור
    "investment": 0.50,   # דירה להשקעה / נוספת
}

BUYER_TYPE_LABELS = {
    "first_home": "דירה יחידה",
    "improving": "משפרי דיור",
    "investment": "דירה להשקעה/נוספת",
}


def _finding(severity: str, title: str, detail: str, action: str, *, source: str = "rule") -> dict:
    return {
        "severity": severity,
        "title": title,
        "detail": detail,
        "suggested_action": action,
        "source": source,
    }


def run_rule_checks(
    tracks: list[dict],
    stats: dict,
    stress: dict,
    *,
    property_value: Optional[float] = None,
    monthly_income: Optional[float] = None,
    buyer_type: Optional[str] = None,
    horizon_years: Optional[float] = None,
    other_monthly_obligations: Optional[float] = None,
) -> list[dict]:
    """
    בדיקות דטרמיניסטיות על התמהיל המוצע. כל פרמטר אופציונלי - בדיקה שאין
    לה נתונים פשוט לא רצה (עדיף לדלג מאשר להמציא). מחזיר רשימת ממצאים.
    """
    findings: list[dict] = []
    total = stats.get("total_amount", 0) or 0
    if total <= 0:
        return findings

    # --- שיעור מסלולים בריבית קבועה ---
    fixed_amount = sum(t.get("amount", 0) for t in tracks if t.get("track_type") in FIXED_TRACK_TYPES)
    fixed_share = fixed_amount / total
    if fixed_share < MIN_FIXED_SHARE:
        findings.append(_finding(
            SEVERITY_CRITICAL,
            "שיעור המסלולים בריבית קבועה נמוך מהמקובל",
            f"רק {fixed_share:.0%} מהתמהיל בריבית קבועה (סף מקובל: כשליש). "
            "ייתכן שהבנק יידרש לשנות את התמהיל, וייתכן שהתמהיל חושף את הלקוח לתנודתיות גבוהה מהנדרש.",
            "לאמת מול הוראות בנק ישראל העדכניות, ולשקול העברת חלק מהסכום למסלול קבוע.",
        ))

    # --- חשיפה לריבית משתנה ---
    variable_amount = sum(t.get("amount", 0) for t in tracks if t.get("track_type") in VARIABLE_TRACK_TYPES)
    variable_share = variable_amount / total
    if variable_share > 0.67:
        findings.append(_finding(
            SEVERITY_WARNING,
            "חשיפה גבוהה לריבית משתנה",
            f"{variable_share:.0%} מהתמהיל במסלולים בריבית משתנה. "
            "עלייה בריבית תשפיע על רוב ההחזר החודשי, לא על חלקו.",
            "לוודא שהלקוח מבין את המשמעות, ושההחזר בתרחיש הקיצון עדיין בר-קיימא עבורו.",
        ))

    # --- חשיפה למדד ---
    cpi_amount = sum(t.get("amount", 0) for t in tracks if t.get("track_type") in CPI_LINKED_TRACK_TYPES)
    cpi_share = cpi_amount / total
    if cpi_share > 0.5:
        findings.append(_finding(
            SEVERITY_WARNING,
            "חלק גדול מהתמהיל צמוד למדד",
            f"{cpi_share:.0%} מהקרן צמודה למדד המחירים לצרכן - כלומר יתרת החוב עצמה "
            "גדלה עם האינפלציה, לא רק ההחזר החודשי.",
            "להציג ללקוח את יתרת החוב הצפויה בעוד מספר שנים, לא רק את ההחזר החודשי ההתחלתי.",
        ))

    # --- אורך תקופה ---
    longest = stats.get("longest_track_period_months", 0)
    if longest > MAX_TERM_MONTHS:
        findings.append(_finding(
            SEVERITY_CRITICAL,
            "תקופת ההלוואה חורגת מהמקובל",
            f"המסלול הארוך ביותר הוא {longest} חודשים ({longest / 12:.1f} שנים), "
            f"מעל הסף המקובל של {MAX_TERM_MONTHS // 12} שנים.",
            "לאמת מול הוראות בנק ישראל העדכניות ולקצר את התקופה בהתאם.",
        ))

    # --- יחס מימון (LTV) ---
    if property_value and property_value > 0 and buyer_type in MAX_LTV_BY_BUYER:
        ltv = total / property_value
        max_ltv = MAX_LTV_BY_BUYER[buyer_type]
        if ltv > max_ltv:
            findings.append(_finding(
                SEVERITY_CRITICAL,
                "יחס המימון גבוה מהמותר לסוג הרוכש",
                f"יחס המימון הוא {ltv:.0%} משווי הנכס, מול סף מקובל של {max_ltv:.0%} "
                f"עבור {BUYER_TYPE_LABELS[buyer_type]}. הבנק צפוי לדחות או להקטין את הסכום.",
                "להקטין את סכום ההלוואה, להגדיל הון עצמי, או לאמת שסיווג הרוכש נכון.",
            ))
        elif ltv > max_ltv - 0.03:
            findings.append(_finding(
                SEVERITY_NOTE,
                "יחס המימון קרוב מאוד לתקרה",
                f"יחס המימון הוא {ltv:.0%} מול תקרה של {max_ltv:.0%}. "
                "שמאות נמוכה מהצפוי תוציא את התיק מהמסגרת.",
                "לוודא הערכת שמאי לפני ההגשה, או להשאיר מרווח ביטחון בסכום.",
            ))

    # --- יחס החזר להכנסה, גם בתרחיש קיצון ---
    if monthly_income and monthly_income > 0:
        initial_payment = stats.get("initial_total_monthly_payment", 0)

        # מ-1 ביולי 2026 בנק ישראל מחייב לחשב את יחס ההחזר על **כל**
        # התחייבויות הלווה יחד - משכנתא, הלוואות צרכניות, רכב וליסינג,
        # חובות כרטיסי אשראי, הלוואות חוץ-בנקאיות ומזונות. עד אז היה
        # אפשר לבחון כל הלוואה בנפרד. בדיקה שמסתכלת רק על תשלום המשכנתא
        # תיתן היום תשובה אופטימית מדי, ותפתיע בהגשה לבנק.
        # None = היועץ לא הזין; 0 = הוא הזין במפורש שאין. ההבחנה חשובה:
        # רק במקרה הראשון יש מה להזכיר לו.
        obligations_unknown = other_monthly_obligations is None
        other = float(other_monthly_obligations or 0.0)
        total_payment = initial_payment + other
        pti = total_payment / monthly_income

        obligations_note = (
            f" (מזה {other:,.0f} ₪ התחייבויות קיימות)" if other > 0 else ""
        )

        if pti > REGULATORY_MAX_PTI:
            findings.append(_finding(
                SEVERITY_CRITICAL,
                "יחס ההחזר חורג מתקרת בנק ישראל",
                f"סך ההחזרים החודשיים הוא {total_payment:,.0f} ₪{obligations_note}, "
                f"שהם {pti:.0%} מההכנסה - מעל תקרת בנק ישראל ({REGULATORY_MAX_PTI:.0%}). "
                "התיק צפוי להידחות.",
                "להקטין סכום, להאריך תקופה, או לסלק התחייבויות קיימות לפני ההגשה.",
            ))
        elif pti > MAX_PTI:
            findings.append(_finding(
                SEVERITY_CRITICAL,
                "יחס ההחזר גבוה מהסף שהבנקים מאשרים בפועל",
                f"סך ההחזרים החודשיים הוא {total_payment:,.0f} ₪{obligations_note}, "
                f"שהם {pti:.0%} מההכנסה. התקרה הרגולטורית היא {REGULATORY_MAX_PTI:.0%}, "
                f"אבל בנקים מאשרים בפועל סביב {MAX_PTI:.0%}.",
                "להאריך תקופה, להקטין סכום, לסלק התחייבויות קיימות, "
                "או לבחון הכנסות נוספות שניתן להציג לבנק.",
            ))

        if obligations_unknown:
            findings.append(_finding(
                SEVERITY_NOTE,
                "לא הוזנו התחייבויות קיימות",
                "מיולי 2026 הבנק מחשב את יחס ההחזר על כל ההלוואות של הלווה יחד - "
                "רכב, אשראי, הלוואות חוץ-בנקאיות ומזונות - ולא רק על המשכנתא. "
                "אם ללקוח יש התחייבויות שלא הוזנו, היחס בפועל גבוה מהמוצג כאן.",
                "לוודא מול הלקוח שאין החזרים נוספים, ולהזין אותם אם יש.",
            ))

        stressed_payment = stress.get("stressed_total_monthly_payment", 0) + other
        stressed_pti = stressed_payment / monthly_income
        if stressed_pti > MAX_STRESSED_PTI:
            findings.append(_finding(
                SEVERITY_WARNING,
                "בתרחיש קיצון ההחזר מגיע לרמה מסוכנת",
                f"בתרחיש של עליית ריבית ומדד, ההחזר מגיע ל-{stressed_pti:.0%} מההכנסה הנוכחית "
                f"(לעומת {pti:.0%} היום). זה התרחיש שמוביל לפיגורים.",
                "להקטין את החלק המשתנה/הצמוד, או לוודא שללקוח יש כרית ביטחון מספקת.",
            ))

    # --- חשיפה לעמלת פירעון מוקדם מול אופק התכנון של הלקוח ---
    if horizon_years and horizon_years > 0:
        horizon_months = horizon_years * 12
        exposed = [
            t for t in tracks
            if t.get("track_type") in FIXED_TRACK_TYPES and t.get("period_months", 0) > horizon_months * 1.5
        ]
        if exposed:
            exposed_amount = sum(t.get("amount", 0) for t in exposed)
            findings.append(_finding(
                SEVERITY_CRITICAL,
                "חשיפה לעמלת פירעון מוקדם מול תוכניות הלקוח",
                f"הלקוח ציין אופק של כ-{horizon_years:.0f} שנים, אבל {exposed_amount:,.0f} ₪ "
                "מהתמהיל נמצאים במסלולים בריבית קבועה לתקופה ארוכה בהרבה. "
                "פירעון מוקדם במסלול קבוע עלול לגרור עמלת היוון משמעותית.",
                "לשקול מסלול משתנה או תקופה קצרה יותר לחלק מהסכום, ולהציג ללקוח את עלות היציאה הצפויה.",
            ))

    return findings


AI_REVIEW_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "overall_verdict": {
            "type": "string",
            "description": "שורה תחתונה בעברית (2-4 משפטים): האם התמהיל נראה תקין לשליחה ללקוח, ומה הדבר החשוב ביותר לבדוק לפני",
        },
        "findings": {
            "type": "array",
            "description": "ממצאים שהבדיקות המספריות לא תופסות - סתירות מול מה שהלקוח אמר, שיקולים שהוחמצו, סיכונים שלא טופלו. ריק אם באמת אין.",
            "items": {
                "type": "object",
                "properties": {
                    "severity": {
                        "type": "string",
                        "enum": [SEVERITY_CRITICAL, SEVERITY_WARNING, SEVERITY_NOTE],
                    },
                    "title": {"type": "string", "description": "כותרת קצרה וממוקדת לממצא"},
                    "detail": {"type": "string", "description": "הסבר מדויק: מה בדיוק לא מתיישב, ועל סמך מה בנתונים"},
                    "suggested_action": {"type": "string", "description": "מה קונקרטית לעשות עם זה"},
                },
                "required": ["severity", "title", "detail", "suggested_action"],
                "additionalProperties": False,
            },
        },
        "questions_for_client": {
            "type": "array",
            "description": "שאלות שכדאי לשאול את הלקוח לפני סגירה, כי התשובה עשויה לשנות את התמהיל",
            "items": {"type": "string"},
        },
    },
    "required": ["overall_verdict", "findings", "questions_for_client"],
    "additionalProperties": False,
}

AI_REVIEW_SYSTEM_PROMPT = """אתה בודק עמית (peer reviewer) של יועץ משכנתאות מנוסה בישראל. היועץ בנה
תמהיל ועומד לשלוח אותו ללקוח - תפקידך לתפוס את מה שהוא עלול היה לפספס,
לפני שזה יוצא.

תקבל: התמהיל המוצע, **כל הנתונים המספריים כבר מחושבים** (החזר חודשי,
ריבית משוקללת, תרחיש קיצון), רשימת ממצאים מבדיקות מספריות שכבר רצו,
ותיאור חופשי של הלקוח ומה שנאמר בפגישה.

## המשימה
לחפש דווקא את מה שבדיקה מספרית לא תופסת:
1. **סתירות בין התמהיל למה שהלקוח אמר** - זה הכי חשוב. אם הלקוח אמר
   שהוא מתכנן למכור/לרשת/לפרוע מוקדם/להחליף עבודה/לצאת לחל"ת - האם
   התמהיל מתיישב עם זה? זו הטעות הקלאסית והיקרה ביותר בענף.
2. **שיקולים שהוחמצו** - עלות יציאה עתידית, יציבות תעסוקתית, הכנסה לא
   קבועה, הוצאות צפויות, גיל הלווים מול תקופת ההלוואה.
3. **סיכון שלא נאמר ללקוח** - משהו בתמהיל שהלקוח כנראה לא מבין את
   משמעותו, גם אם הוא חוקי ותקין.

## כללים
1. **אל תחשב מספרים מחדש** - הם סופקו לך מחושבים. השתמש בהם כפי שהם.
2. **אל תחזור על ממצאים שהבדיקות המספריות כבר מצאו** - הם מוצגים לך כדי
   שתדע מה כבר מכוסה. הוסף רק מה שהן לא תפסו.
3. **אל תמציא עובדות על הלקוח** שלא מופיעות בתיאור. אם משהו חסר כדי
   להעריך - זו שאלה ל-questions_for_client, לא ממצא.
4. **אם התמהיל באמת נראה תקין - אמור זאת** והשאר את findings ריק או כמעט
   ריק. אזעקת שווא שוחקת את הערך של הכלי. אל תייצר ממצאים כדי למלא מכסה.
5. severity: critical = עלול לגרום נזק כספי ממשי ללקוח או לפסילת התיק;
   warning = שווה בדיקה לפני סגירה; note = לתשומת לב בלבד.
6. כתוב בעברית מקצועית וישירה, ליועץ - לא ללקוח.

החזר אך ורק JSON תקין בסכימה שסופקה - ללא טקסט נוסף לפני או אחרי."""


def ai_review(
    tracks: list[dict],
    stats: dict,
    stress: dict,
    rule_findings: list[dict],
    *,
    client_context: str = "",
) -> dict:
    """סקירת השיפוט של Claude, על גבי הנתונים המחושבים והממצאים המספריים."""
    client = anthropic.Anthropic()

    payload = {
        "proposed_tracks": tracks,
        "computed_stats": stats,
        "stress_test": stress,
        "numeric_findings_already_caught": rule_findings,
    }

    blocks = "## התמהיל המוצע והנתונים המחושבים:\n```json\n" + json.dumps(
        payload, ensure_ascii=False, indent=2
    ) + "\n```"

    if client_context.strip():
        blocks += "\n\n## הלקוח ומה שנאמר בפגישה:\n" + client_context.strip()
    else:
        blocks += (
            "\n\n## הלקוח ומה שנאמר בפגישה:\n"
            "(לא סופק מידע על הלקוח - התייחס לכך שאי אפשר לבדוק התאמה לנסיבותיו, "
            "וכלול ב-questions_for_client את מה שצריך לדעת)"
        )

    response = client.messages.create(
        model=MODEL,
        max_tokens=8000,
        thinking={"type": "adaptive"},
        system=[{"type": "text", "text": AI_REVIEW_SYSTEM_PROMPT, "cache_control": {"type": "ephemeral", "ttl": "1h"}}],
        output_config={"format": {"type": "json_schema", "schema": AI_REVIEW_JSON_SCHEMA}},
        messages=[{"role": "user", "content": blocks}],
    )

    text_block = next(b.text for b in response.content if b.type == "text")
    return json.loads(text_block)


def review_mix(
    tracks: list[dict],
    *,
    property_value: Optional[float] = None,
    monthly_income: Optional[float] = None,
    buyer_type: Optional[str] = None,
    horizon_years: Optional[float] = None,
    other_monthly_obligations: Optional[float] = None,
    client_context: str = "",
    rate_increase_pct: float = 2.0,
    cpi_annual_pct: float = 3.0,
) -> dict:
    """
    השרשרת המלאה: חישוב מדויק -> בדיקות כלל -> סקירת Claude -> ממצאים
    ממוזגים וממויינים לפי חומרה.
    """
    stats = blended_offer_stats({"bank_name": "התמהיל המוצע", "tracks": tracks})
    stress = stress_test_stats(tracks, rate_increase_pct=rate_increase_pct, cpi_annual_pct=cpi_annual_pct)

    rule_findings = run_rule_checks(
        tracks,
        stats,
        stress,
        property_value=property_value,
        monthly_income=monthly_income,
        buyer_type=buyer_type,
        horizon_years=horizon_years,
        other_monthly_obligations=other_monthly_obligations,
    )

    review = ai_review(tracks, stats, stress, rule_findings, client_context=client_context)

    ai_findings = [{**f, "source": "ai"} for f in review.get("findings", [])]
    all_findings = sorted(
        rule_findings + ai_findings,
        key=lambda f: SEVERITY_ORDER.get(f.get("severity"), 99),
    )

    return {
        "stats": stats,
        "stress_test": stress,
        "findings": all_findings,
        "overall_verdict": review.get("overall_verdict", ""),
        "questions_for_client": review.get("questions_for_client", []),
    }
