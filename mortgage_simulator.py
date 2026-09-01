#!/usr/bin/env python3
"""
סימולטור תמהילים: מתיאור מצב בשפה חופשית -> כמה תמהילים מועמדים, כל אחד
מורץ על כמה תרחישי עתיד, עם הסבר איזה מתאים ללקוח הזה ולמה.

## איך זה שונה ממחשבון תמהיל רגיל

מחשבון רגיל דורש שתבנה את התמהיל בעצמך והוא מחשב אותו. כאן ההיפך: אתה
מתאר סיטואציה, והמערכת **מציעה** תמהילים שמתאימים לה, מריצה את כולם על
מספר תרחישים, ומנמקת.

## חלוקת העבודה - קריטית

- **Claude מציע ומסביר.** הוא בונה תמהילים מועמדים מתוך הבנת המצב, ואחר
  כך מנמק על סמך מספרים מוכנים.
- **פייתון מחשב.** כל מספר במסמך הזה - החזר חודשי, עלות כוללת, עמלת
  פירעון מוקדם, תרחישי ריבית - מחושב דטרמיניסטית. המודל לא עושה חשבון.

זה לא עניין של סגנון: מספר שגוי בהמלצת משכנתא עולה ללקוח עשרות אלפי
שקלים, ונראה סביר לחלוטין על המסך.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Optional

import anthropic

from mortgage_math import (
    VARIABLE_TRACK_TYPES,
    blended_offer_stats,
    monthly_payment_shpitzer,
)
from mortgage_refi import (
    CPI_LINKED_TRACK_TYPES,
    capitalization_fee,
    remaining_balance,
)

MODEL = "claude-opus-4-8"


# ------------------------------------------------------------- תרחישי עתיד

@dataclass
class Scenario:
    """
    תרחיש עתיד יחיד. הכל דטרמיניסטי - התרחישים הם הנחות מפורשות, לא תחזית.

    rate_change_pct משפיע רק על מסלולים בריבית משתנה; cpi_annual_pct משפיע
    רק על מסלולים צמודי מדד. כך שכל תמהיל מגיב לתרחיש לפי ההרכב שלו בפועל,
    וזו בדיוק הנקודה של ההשוואה.
    """
    key: str
    label: str
    rate_change_pct: float = 0.0
    cpi_annual_pct: float = 2.0
    description: str = ""


DEFAULT_SCENARIOS = [
    Scenario("base", "בסיס - השוק נשאר כמו היום", 0.0, 2.0,
             "אין שינוי בריבית, אינפלציה מתונה"),
    Scenario("rate_up_1", "עליית ריבית מתונה", 1.0, 2.5,
             "הריבית עולה בנקודה אחת"),
    Scenario("rate_up_3", "עליית ריבית חדה", 3.0, 3.0,
             "תרחיש קיצון - הריבית עולה ב-3 נקודות"),
    Scenario("inflation", "אינפלציה גבוהה", 0.5, 5.0,
             "המדד מזנק, יתרת החוב הצמודה גדלה"),
    Scenario("rate_down", "ירידת ריבית", -1.0, 1.5,
             "הריבית יורדת - בודק מי מרוויח מזה ומי תקוע"),
]


# --------------------------------------------------- חישוב תמהיל בתרחיש

@dataclass
class TrackOutcome:
    name: str
    track_type: str
    amount: float
    period_months: int
    base_rate_pct: float
    effective_rate_pct: float
    effective_amount: float
    monthly_payment: float


@dataclass
class MixOutcome:
    """תוצאת הרצת תמהיל אחד בתרחיש אחד."""
    scenario_key: str
    scenario_label: str
    tracks: list[TrackOutcome] = field(default_factory=list)

    @property
    def total_monthly(self) -> float:
        return sum(t.monthly_payment for t in self.tracks)

    @property
    def total_cost(self) -> float:
        """
        עלות כוללת משוערת: סכום כל התשלומים לאורך חיי ההלוואה בתרחיש הזה.
        הערכה - מניחה שתנאי התרחיש נשארים קבועים לכל התקופה.
        """
        return sum(t.monthly_payment * t.period_months for t in self.tracks)


def run_mix_in_scenario(tracks: list[dict], scenario: Scenario) -> MixOutcome:
    """
    מריץ תמהיל בתרחיש נתון. מסלולים משתנים סופגים את שינוי הריבית,
    ומסלולים צמודים סופגים שנה אחת של הצמדה על הקרן (קירוב להמחשה).
    """
    outcome = MixOutcome(scenario_key=scenario.key, scenario_label=scenario.label)

    for t in tracks:
        amount = float(t.get("amount", 0) or 0)
        rate = float(t.get("annual_interest_rate_pct", 0) or 0)
        months = int(t.get("period_months", 0) or 0)
        track_type = t.get("track_type", "other")

        effective_rate = rate
        if track_type in VARIABLE_TRACK_TYPES:
            effective_rate = max(0.0, rate + scenario.rate_change_pct)

        effective_amount = amount
        if track_type in CPI_LINKED_TRACK_TYPES:
            effective_amount = amount * (1 + scenario.cpi_annual_pct / 100)

        outcome.tracks.append(TrackOutcome(
            name=t.get("name", ""),
            track_type=track_type,
            amount=amount,
            period_months=months,
            base_rate_pct=rate,
            effective_rate_pct=round(effective_rate, 3),
            effective_amount=round(effective_amount, 2),
            monthly_payment=round(monthly_payment_shpitzer(effective_amount, effective_rate, months), 2),
        ))

    return outcome


def early_repayment_cost_at(
    tracks: list[dict],
    *,
    year: int,
    market_rates_by_track_type: dict[str, float],
    avg_cpi_change_12m_pct: float = 2.0,
) -> dict:
    """
    כמה יעלה ללקוח לפרוע את התמהיל הזה מוקדם, בשנה מסוימת.

    זו השאלה שהכי נשכחת בהשוואת תמהילים: שני תמהילים עם החזר חודשי כמעט
    זהה יכולים להיות רחוקים מאוד זה מזה ברגע שהלקוח רוצה לצאת. תמהיל עם
    מסלול קבוע ארוך "זול" בחודש - ויקר מאוד ביציאה.
    """
    months_elapsed = year * 12
    total_balance = 0.0
    total_fee = 0.0
    per_track = []

    for t in tracks:
        amount = float(t.get("amount", 0) or 0)
        rate = float(t.get("annual_interest_rate_pct", 0) or 0)
        months = int(t.get("period_months", 0) or 0)
        track_type = t.get("track_type", "other")

        if months_elapsed >= months:
            continue  # המסלול כבר הסתיים

        balance = remaining_balance(amount, rate, months, months_elapsed)
        remaining_months = months - months_elapsed
        market_rate = float(market_rates_by_track_type.get(track_type, rate))

        fee = capitalization_fee(
            balance, rate, market_rate, remaining_months, track_type=track_type
        )
        if track_type in CPI_LINKED_TRACK_TYPES and avg_cpi_change_12m_pct > 0:
            fee += balance * (avg_cpi_change_12m_pct / 100) / 2

        total_balance += balance
        total_fee += fee
        per_track.append({
            "name": t.get("name", ""),
            "track_type": track_type,
            "balance": round(balance, 2),
            "fee": round(fee, 2),
        })

    return {
        "year": year,
        "remaining_balance": round(total_balance, 2),
        "exit_fee": round(total_fee, 2),
        "per_track": per_track,
    }


def evaluate_mix(
    mix: dict,
    *,
    scenarios: Optional[list[Scenario]] = None,
    market_rates_by_track_type: Optional[dict[str, float]] = None,
    early_repayment_years: tuple[int, ...] = (3, 5, 10),
) -> dict:
    """
    מריץ תמהיל אחד על כל התרחישים ועל נקודות פירעון מוקדם. פונקציה טהורה,
    ללא קריאת רשת - כל המספרים כאן דטרמיניסטיים.
    """
    scenarios = scenarios or DEFAULT_SCENARIOS
    tracks = mix.get("tracks", [])
    stats = blended_offer_stats({"bank_name": mix.get("name", ""), "tracks": tracks})

    outcomes = [run_mix_in_scenario(tracks, s) for s in scenarios]
    base = next((o for o in outcomes if o.scenario_key == "base"), outcomes[0] if outcomes else None)

    exits = []
    if market_rates_by_track_type:
        exits = [
            early_repayment_cost_at(
                tracks, year=y, market_rates_by_track_type=market_rates_by_track_type
            )
            for y in early_repayment_years
        ]

    worst = max(outcomes, key=lambda o: o.total_monthly) if outcomes else None

    return {
        "name": mix.get("name", ""),
        "rationale": mix.get("rationale", ""),
        "tracks": stats["tracks"],
        "total_amount": stats["total_amount"],
        "blended_rate_pct": stats["blended_annual_interest_rate_pct"],
        "base_monthly": round(base.total_monthly, 2) if base else 0.0,
        "base_total_cost": round(base.total_cost, 2) if base else 0.0,
        "worst_case_monthly": round(worst.total_monthly, 2) if worst else 0.0,
        "worst_case_scenario": worst.scenario_label if worst else "",
        "payment_spread": round(worst.total_monthly - base.total_monthly, 2) if (worst and base) else 0.0,
        "scenarios": [
            {
                "key": o.scenario_key,
                "label": o.scenario_label,
                "monthly": round(o.total_monthly, 2),
                "total_cost": round(o.total_cost, 2),
            }
            for o in outcomes
        ],
        "early_repayment": exits,
    }


# ------------------------------------------- הצעת תמהילים מתוך תיאור מצב

MIX_PROPOSAL_SCHEMA = {
    "type": "object",
    "properties": {
        "understood_situation": {
            "type": "string",
            "description": "סיכום קצר של מה שהבנת מהתיאור - כדי שהיועץ יראה מיד אם פספסת משהו",
        },
        "missing_info": {
            "type": "array",
            "description": "פרטים שחסרים ועשויים לשנות את ההמלצה (ריק אם התיאור מספיק)",
            "items": {"type": "string"},
        },
        "mixes": {
            "type": "array",
            "description": "3-4 תמהילים מועמדים, שונים זה מזה באופי ולא רק במספרים",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "שם קצר ומאפיין, למשל 'שמרני - דגש על יציבות'"},
                    "rationale": {"type": "string", "description": "למה התמהיל הזה מתאים לסיטואציה הספציפית הזו"},
                    "tracks": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string"},
                                "track_type": {
                                    "type": "string",
                                    "enum": [
                                        "fixed_unlinked", "fixed_linked_cpi", "variable_prime",
                                        "variable_unlinked", "variable_linked_cpi", "eligibility", "other",
                                    ],
                                },
                                "amount": {"type": "number"},
                                "period_months": {"type": "integer"},
                                "annual_interest_rate_pct": {"type": "number"},
                                "linkage": {"type": "string", "enum": ["cpi_linked", "unlinked"]},
                            },
                            "required": ["name", "track_type", "amount", "period_months",
                                         "annual_interest_rate_pct", "linkage"],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": ["name", "rationale", "tracks"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["understood_situation", "missing_info", "mixes"],
    "additionalProperties": False,
}

PROPOSAL_SYSTEM_PROMPT = """אתה עוזר של יועץ משכנתאות מנוסה בישראל. היועץ מתאר לך סיטואציה של לקוח
בשפה חופשית, ואתה מציע כמה תמהילים מועמדים שיורצו אחר כך בסימולציה.

## המשימה
הצע 3-4 תמהילים שנבדלים זה מזה **באופי**, לא רק במספרים - למשל אחד שמרני
עם דגש על ודאות, אחד שמנצל ריבית נמוכה יותר במחיר חשיפה, ואחד שבנוי סביב
אילוץ ספציfי שהלקוח ציין (תקרת החזר, כוונה לפרוע מוקדם, אי-יציבות בהכנסה).

## כללים
1. **סכום המסלולים בכל תמהיל חייב להיות שווה לסכום ההלוואה** שהיועץ ציין.
   אם לא צוין סכום מדויק - גזור אותו מהנתונים (מחיר נכס פחות הון עצמי)
   וציין זאת ב-understood_situation.
2. **השתמש בריביות שהיועץ נתן.** אם הוא לא נתן ריביות, השתמש בהערכות
   סבירות לשוק הישראלי, וכתוב ב-missing_info במפורש שהריביות משוערות
   ושצריך להחליף אותן בריביות אמיתיות מהבנק.
3. **התאם לאילוצים שנאמרו.** אם הלקוח אמר "החזר עד 7,000" - אל תציע
   תמהיל שחורג מזה בתרחיש הבסיס. אם אמר שיפרע מוקדם - אל תמלא את התמהיל
   במסלולים קבועים ארוכים.
4. **אל תמציא עובדות על הלקוח.** מה שלא נאמר - נכנס ל-missing_info.
5. **אל תחשב החזרים חודשיים או עלויות.** זה נעשה במדויק אחרי שלב זה.
   תפקידך להציע הרכב, לא לחשב אותו.
6. שיעור המסלולים בריבית קבועה בכל תמהיל צריך להיות לפחות כשליש, אלא אם
   היועץ ביקש אחרת במפורש.

החזר אך ורק JSON תקין בסכימה שסופקה - ללא טקסט נוסף לפני או אחרי."""


def propose_mixes(situation: str, *, loan_amount: Optional[float] = None) -> dict:
    """מתיאור מצב חופשי -> כמה תמהילים מועמדים. לא מחשב מספרים."""
    if not situation.strip():
        raise ValueError("לא הוזן תיאור מצב")

    client = anthropic.Anthropic()

    user_block = "## הסיטואציה כפי שהיועץ תיאר אותה:\n" + situation.strip()
    if loan_amount:
        user_block += f"\n\n## סכום ההלוואה: {loan_amount:,.0f} ₪"

    response = client.messages.create(
        model=MODEL,
        max_tokens=8000,
        thinking={"type": "adaptive"},
        system=[{"type": "text", "text": PROPOSAL_SYSTEM_PROMPT, "cache_control": {"type": "ephemeral", "ttl": "1h"}}],
        output_config={"format": {"type": "json_schema", "schema": MIX_PROPOSAL_SCHEMA}},
        messages=[{"role": "user", "content": user_block}],
    )

    text_block = next(b.text for b in response.content if b.type == "text")
    return json.loads(text_block)


# ------------------------------------------------- ניתוח והשוואה מנומקים

COMPARISON_SCHEMA = {
    "type": "object",
    "properties": {
        "recommendation": {
            "type": "string",
            "description": "איזה תמהיל מתאים ללקוח הזה ולמה, בהתייחסות מפורשת לנסיבות שתוארו (3-6 משפטים)",
        },
        "per_mix": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "best_for": {"type": "string", "description": "לאיזה סוג לקוח/מצב התמהיל הזה מתאים"},
                    "main_risk": {"type": "string", "description": "הסיכון המרכזי בתמהיל הזה, לפי מספרי התרחישים"},
                },
                "required": ["name", "best_for", "main_risk"],
                "additionalProperties": False,
            },
        },
        "what_to_tell_the_client": {
            "type": "string",
            "description": "איך להסביר את ההמלצה ללקוח בשפה פשוטה, בלי ז'רגון",
        },
    },
    "required": ["recommendation", "per_mix", "what_to_tell_the_client"],
    "additionalProperties": False,
}

COMPARISON_SYSTEM_PROMPT = """אתה עוזר של יועץ משכנתאות בישראל. קיבלת כמה תמהילים מועמדים ללקוח,
**עם כל המספרים כבר מחושבים במדויק**: החזר חודשי בכל תרחיש, עלות כוללת,
פער בין תרחיש בסיס לתרחיש הגרוע, ועלות פירעון מוקדם בשנים שונות.

## המשימה
לנתח ולהמליץ - **בלי לחשב מחדש שום מספר**. השתמש במספרים שסופקו כפי שהם.

התייחס במפורש ל:
1. **התאמה לנסיבות שתוארו** - זה העיקר. תקרת החזר שנאמרה, כוונה לפרוע
   מוקדם, אי-יציבות תעסוקתית, אופק הישארות בנכס.
2. **פער החשיפה** - כמה ההחזר קופץ בין תרחיש הבסיס לתרחיש הגרוע. תמהיל
   עם פער קטן שווה יותר ללקוח שההכנסה שלו לא יציבה, גם אם הוא יקר יותר.
3. **עלות היציאה** - אם הלקוח ציין כוונה לפרוע מוקדם, תמהיל שזול בחודש
   אבל יקר ביציאה הוא בחירה גרועה עבורו. השווה במפורש.

## כללים
- אל תמציא מספרים ואל תעגל מחדש. אם מספר לא סופק - אל תתייחס אליו.
- אם ההפרש בין תמהילים זניח, אמור זאת בכנות במקום להמציא העדפה.
- what_to_tell_the_client נכתב ללקוח, לא ליועץ: עברית פשוטה, בלי מונחים
  מקצועיים, בלי הבטחות.

החזר אך ורק JSON תקין בסכימה שסופקה - ללא טקסט נוסף לפני או אחרי."""


def compare_mixes(evaluations: list[dict], situation: str) -> dict:
    """מנתח את התמהילים המחושבים ומנמק המלצה. לא מחשב - רק מפרש."""
    client = anthropic.Anthropic()

    payload = "## התמהילים עם כל המספרים המחושבים:\n```json\n" + json.dumps(
        evaluations, ensure_ascii=False, indent=2
    ) + "\n```\n\n## הסיטואציה:\n" + situation.strip()

    response = client.messages.create(
        model=MODEL,
        max_tokens=8000,
        thinking={"type": "adaptive"},
        system=[{"type": "text", "text": COMPARISON_SYSTEM_PROMPT, "cache_control": {"type": "ephemeral", "ttl": "1h"}}],
        output_config={"format": {"type": "json_schema", "schema": COMPARISON_SCHEMA}},
        messages=[{"role": "user", "content": payload}],
    )

    text_block = next(b.text for b in response.content if b.type == "text")
    return json.loads(text_block)


def simulate(
    situation: str,
    *,
    loan_amount: Optional[float] = None,
    market_rates_by_track_type: Optional[dict[str, float]] = None,
    scenarios: Optional[list[Scenario]] = None,
) -> dict:
    """
    השרשרת המלאה: תיאור -> הצעת תמהילים (Claude) -> חישוב מדויק (פייתון)
    -> השוואה מנומקת (Claude).
    """
    proposal = propose_mixes(situation, loan_amount=loan_amount)

    evaluations = [
        evaluate_mix(
            mix,
            scenarios=scenarios,
            market_rates_by_track_type=market_rates_by_track_type,
        )
        for mix in proposal.get("mixes", [])
    ]

    comparison = compare_mixes(evaluations, situation) if evaluations else {}

    return {
        "understood_situation": proposal.get("understood_situation", ""),
        "missing_info": proposal.get("missing_info", []),
        "evaluations": evaluations,
        "comparison": comparison,
    }
