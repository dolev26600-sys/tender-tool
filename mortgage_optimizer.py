#!/usr/bin/env python3
"""
אופטימיזציית תמהיל: בהינתן הריביות שהיועץ הזין, מוצא את החלוקה **הנכונה
מספרית** בין המסלולים - לא מציע, מחשב.

## למה זה שונה מהצעת תמהילים

מודל שפה יכול להציע תמהיל שנשמע סביר. הוא לא יכול לסרוק עשרת אלפים
חלוקות אפשריות ולמצוא את זו שמינימלית באמת. זה מה שקורה כאן: חיפוש ממצה
על מרחב החלוקות, עם אילוצים, לפי מטרה מוגדרת.

**אין כאן שום קריאה למודל שפה.** הכל אריתמטיקה.

## המתח שהאופטימיזציה חושפת

אין "תמהיל אופטימלי" אחד - יש חזית יעילות. תמהיל זול יותר כמעט תמיד
חשוף יותר, ותמהיל יציב יותר כמעט תמיד יקר יותר. לכן המנוע מחזיר את
האופטימום **לכל מטרה בנפרד**, ואת החזית שביניהן, במקום להעמיד פנים
שיש תשובה אחת.
"""
from __future__ import annotations

from dataclasses import dataclass
from itertools import product
from typing import Iterable, Optional

from mortgage_math import VARIABLE_TRACK_TYPES, monthly_payment_shpitzer
from mortgage_refi import CPI_LINKED_TRACK_TYPES, capitalization_fee, remaining_balance

FIXED_TRACK_TYPES = {"fixed_unlinked", "fixed_linked_cpi"}

TRACK_LABELS = {
    "fixed_unlinked": "קבועה לא צמודה",
    "fixed_linked_cpi": "קבועה צמודה מדד",
    "variable_prime": "פריים",
    "variable_unlinked": "משתנה לא צמודה",
    "variable_linked_cpi": "משתנה צמודה מדד",
}


@dataclass
class Constraints:
    """
    אילוצים על התמהיל. max_monthly_payment הוא האילוץ שהכי משנה בפועל -
    הוא מה שהופך את החיפוש מ"מה הכי זול" ל"מה הכי זול שהלקוח יכול לעמוד בו".
    """
    loan_amount: float
    term_months: int
    min_fixed_share: float = 1 / 3
    max_variable_share: float = 2 / 3
    max_monthly_payment: Optional[float] = None
    max_cpi_linked_share: Optional[float] = None


@dataclass
class Candidate:
    """חלוקה אחת שנבדקה, עם כל המדדים שלה."""
    allocation: dict[str, float]
    base_monthly: float          # בסיס אפקטיבי - כולל אינפלציה צפויה על מסלולים צמודים
    base_monthly_nominal: float  # ההחזר בפועל בחודש הראשון, מה שהלקוח רואה
    worst_monthly: float
    total_cost: float
    fixed_share: float
    variable_share: float
    cpi_share: float
    exit_fee: Optional[float] = None

    @property
    def exposure(self) -> float:
        """כמה ההחזר החודשי קופץ בתרחיש הגרוע. מדד הסיכון של התמהיל."""
        return self.worst_monthly - self.base_monthly

    def to_tracks(self, rates: dict[str, float], term_months: int) -> list[dict]:
        """ממיר את החלוקה לרשימת מסלולים בפורמט שכל שאר הכלים מבינים."""
        return [
            {
                "name": TRACK_LABELS.get(tt, tt),
                "track_type": tt,
                "amount": round(amount, 2),
                "period_months": term_months,
                "annual_interest_rate_pct": rates[tt],
                "linkage": "cpi_linked" if tt in CPI_LINKED_TRACK_TYPES else "unlinked",
            }
            for tt, amount in self.allocation.items()
            if amount > 0
        ]


def _compositions(total_steps: int, n_buckets: int) -> Iterable[tuple[int, ...]]:
    """
    כל הדרכים לחלק total_steps יחידות ל-n_buckets דליים.
    למשל 20 יחידות (של 5% כל אחת) בין 5 מסלולים.
    """
    if n_buckets == 1:
        yield (total_steps,)
        return
    for first in range(total_steps + 1):
        for rest in _compositions(total_steps - first, n_buckets - 1):
            yield (first, *rest)


def _evaluate(
    allocation: dict[str, float],
    rates: dict[str, float],
    term_months: int,
    *,
    stress_rate_pct: float,
    stress_cpi_pct: float,
    expected_cpi_pct: float,
) -> tuple[float, float, float, float]:
    """
    מחזיר (החזר בסיס נומינלי, החזר בתרחיש גרוע, עלות כוללת, החזר בסיס מוצג).

    ## למה מסלול צמוד מקבל טיפול מיוחד

    ריבית של מסלול צמוד מדד אינה בת-השוואה ישירה לריבית של מסלול לא צמוד:
    בצמוד, **הקרן עצמה גדלה** עם המדד לאורך כל התקופה. מסלול צמוד ב-3.4%
    כשהאינפלציה 2% עולה בפועל כמו מסלול לא צמוד ב-5.4% בערך.

    בלי התיקון הזה כל אופטימיזציה תתכנס תמיד למסלולים צמודים, כי הריבית
    הנקובה שלהם נמוכה - וזו טעות שנראית סבירה לחלוטין על המסך.

    לכן: העלות הכוללת וההשוואה בין מסלולים מחושבות לפי ריבית אפקטיבית
    (נקובה + אינפלציה צפויה) למסלולים צמודים, וההחזר ההתחלתי המוצג ללקוח
    מחושב לפי הריבית הנקובה - כי זה מה שהוא באמת ישלם בחודש הראשון.
    """
    base_monthly_nominal = 0.0   # מה שהלקוח משלם בחודש הראשון
    base_monthly_effective = 0.0  # בסיס להשוואה ולעלות כוללת
    worst_monthly = 0.0

    for track_type, amount in allocation.items():
        if amount <= 0:
            continue
        rate = rates[track_type]
        is_linked = track_type in CPI_LINKED_TRACK_TYPES
        is_variable = track_type in VARIABLE_TRACK_TYPES

        base_monthly_nominal += monthly_payment_shpitzer(amount, rate, term_months)

        effective_rate = rate + expected_cpi_pct if is_linked else rate
        base_monthly_effective += monthly_payment_shpitzer(amount, effective_rate, term_months)

        stressed_rate = effective_rate
        if is_variable:
            stressed_rate += stress_rate_pct
        if is_linked:
            stressed_rate += max(0.0, stress_cpi_pct - expected_cpi_pct)
        worst_monthly += monthly_payment_shpitzer(amount, stressed_rate, term_months)

    return (
        base_monthly_effective,
        worst_monthly,
        base_monthly_effective * term_months,
        base_monthly_nominal,
    )


def _exit_fee(
    allocation: dict[str, float],
    rates: dict[str, float],
    term_months: int,
    *,
    year: int,
    market_rates: dict[str, float],
) -> float:
    """עלות היציאה מהתמהיל בשנה נתונה - הרכיב שנעלם מהשוואות רגילות."""
    months_elapsed = year * 12
    if months_elapsed >= term_months:
        return 0.0

    total = 0.0
    for track_type, amount in allocation.items():
        if amount <= 0:
            continue
        rate = rates[track_type]
        balance = remaining_balance(amount, rate, term_months, months_elapsed)
        total += capitalization_fee(
            balance,
            rate,
            market_rates.get(track_type, rate),
            term_months - months_elapsed,
            track_type=track_type,
        )
    return total


def optimize(
    rates: dict[str, float],
    constraints: Constraints,
    *,
    step_pct: float = 5.0,
    stress_rate_pct: float = 2.0,
    stress_cpi_pct: float = 3.0,
    expected_cpi_pct: float = 2.0,
    early_exit_year: Optional[int] = None,
    market_rates: Optional[dict[str, float]] = None,
    linked_policy: str = "only_if_needed",
) -> dict:
    """
    סורק את כל החלוקות האפשריות ומחזיר את האופטימום לכל מטרה, את חזית
    היעילות, ואת המדיניות שהופעלה בפועל.

    ## linked_policy - מדיניות מסלולים צמודי מדד

    - ``"exclude"`` - לעולם לא צמוד.
    - ``"only_if_needed"`` (ברירת מחדל) - קודם מחפש **בלי** מסלולים צמודים.
      רק אם אין אף חלוקה שעומדת באילוצים בלעדיהם, הוא מרחיב את החיפוש
      ומסמן זאת במפורש.
    - ``"allow"`` - צמוד נשקל ככל מסלול אחר.

    ברירת המחדל מקודדת עמדה מקצועית: הריבית הנקובה של מסלול צמוד נמוכה,
    ולכן הוא מוריד את ההחזר החודשי - אבל בפועל הוא יקר יותר, כי הקרן
    גדלה עם המדד. לכן מגיעים אליו כשהלקוח לא יכול לעמוד בהחזר אחרת.

    השווי של המנגנון הזה הוא שהוא **מזהה את המקרה הזה לבד**: אם התוצאה
    חוזרת עם ``linked_required=True``, זה אומר שהלקוח לא עומד באילוצים
    בלי מסלול צמוד - וזו אינפורמציה, לא רק בחירה טכנית.

    rates: ריבית שנתית לכל סוג מסלול שזמין, למשל
        {"fixed_unlinked": 4.6, "variable_prime": 5.4, "fixed_linked_cpi": 3.4}
    """
    if linked_policy not in ("exclude", "only_if_needed", "allow"):
        raise ValueError(f"linked_policy לא מוכר: {linked_policy}")

    unlinked_rates = {k: v for k, v in rates.items() if k not in CPI_LINKED_TRACK_TYPES}
    has_linked_available = any(k in CPI_LINKED_TRACK_TYPES for k in rates)

    search_kwargs = dict(
        step_pct=step_pct,
        stress_rate_pct=stress_rate_pct,
        stress_cpi_pct=stress_cpi_pct,
        expected_cpi_pct=expected_cpi_pct,
        early_exit_year=early_exit_year,
        market_rates=market_rates,
    )

    if linked_policy == "allow":
        result = _search(rates, constraints, **search_kwargs)
        result["linked_policy_applied"] = "allow"
        result["linked_required"] = False
        return result

    if not unlinked_rates:
        raise ValueError(
            "לא הוזנו ריביות לאף מסלול לא צמוד. עם מדיניות שמעדיפה לא צמוד, "
            "צריך לפחות מסלול אחד כזה."
        )

    try:
        result = _search(unlinked_rates, constraints, **search_kwargs)
        result["linked_policy_applied"] = linked_policy
        result["linked_required"] = False
        return result
    except ValueError:
        if linked_policy == "exclude" or not has_linked_available:
            raise

    # לא נמצאה חלוקה בלי צמוד - מרחיבים, ומסמנים שזה מה שקרה
    result = _search(rates, constraints, **search_kwargs)
    result["linked_policy_applied"] = "only_if_needed"
    result["linked_required"] = True
    result["linked_required_note"] = (
        "לא נמצאה אף חלוקה שעומדת באילוצים בלי מסלול צמוד מדד. "
        "כלומר הלקוח אינו עומד בתקרת ההחזר עם מסלולים לא צמודים בלבד. "
        "המסלול הצמוד מוריד את ההחזר ההתחלתי, אך מייקר את העלות הכוללת - "
        "שווה לבחון קודם הארכת תקופה או הקטנת סכום."
    )
    return result


def _search(
    rates: dict[str, float],
    constraints: Constraints,
    *,
    step_pct: float = 5.0,
    stress_rate_pct: float = 2.0,
    stress_cpi_pct: float = 3.0,
    expected_cpi_pct: float = 2.0,
    early_exit_year: Optional[int] = None,
    market_rates: Optional[dict[str, float]] = None,
) -> dict:
    """החיפוש הממצה עצמו, ללא מדיניות. ראה optimize."""
    track_types = [t for t in rates if rates[t] is not None]
    if not track_types:
        raise ValueError("לא הוזנו ריביות לאף מסלול")

    total_steps = int(round(100 / step_pct))
    unit = constraints.loan_amount / total_steps

    candidates: list[Candidate] = []

    for combo in _compositions(total_steps, len(track_types)):
        allocation = {tt: combo[i] * unit for i, tt in enumerate(track_types)}

        fixed_share = sum(v for k, v in allocation.items() if k in FIXED_TRACK_TYPES) / constraints.loan_amount
        variable_share = sum(v for k, v in allocation.items() if k in VARIABLE_TRACK_TYPES) / constraints.loan_amount
        cpi_share = sum(v for k, v in allocation.items() if k in CPI_LINKED_TRACK_TYPES) / constraints.loan_amount

        # אילוצים - נבדקים לפני החישוב היקר, כדי לחסוך עבודה
        if fixed_share < constraints.min_fixed_share - 1e-9:
            continue
        if variable_share > constraints.max_variable_share + 1e-9:
            continue
        if constraints.max_cpi_linked_share is not None and cpi_share > constraints.max_cpi_linked_share + 1e-9:
            continue

        base, worst, cost, nominal = _evaluate(
            allocation, rates, constraints.term_months,
            stress_rate_pct=stress_rate_pct, stress_cpi_pct=stress_cpi_pct,
            expected_cpi_pct=expected_cpi_pct,
        )

        # תקרת ההחזר נבדקת מול ההחזר בפועל - זה מה שיורד מהחשבון של הלקוח
        if constraints.max_monthly_payment is not None and nominal > constraints.max_monthly_payment + 1e-6:
            continue

        fee = None
        if early_exit_year is not None and market_rates:
            fee = _exit_fee(
                allocation, rates, constraints.term_months,
                year=early_exit_year, market_rates=market_rates,
            )

        candidates.append(Candidate(
            allocation=allocation,
            base_monthly=round(base, 2),
            base_monthly_nominal=round(nominal, 2),
            worst_monthly=round(worst, 2),
            total_cost=round(cost, 2),
            fixed_share=round(fixed_share, 4),
            variable_share=round(variable_share, 4),
            cpi_share=round(cpi_share, 4),
            exit_fee=round(fee, 2) if fee is not None else None,
        ))

    if not candidates:
        raise ValueError(
            "לא נמצאה אף חלוקה שעומדת באילוצים. "
            "כנראה תקרת ההחזר החודשי נמוכה מדי לסכום ולתקופה שהוזנו - "
            "אפשר להאריך תקופה, להקטין סכום, או להעלות את התקרה."
        )

    best = {
        "cheapest_total": min(candidates, key=lambda c: c.total_cost),
        "lowest_monthly": min(candidates, key=lambda c: c.base_monthly_nominal),
        "most_stable": min(candidates, key=lambda c: c.exposure),
    }
    if early_exit_year is not None and market_rates:
        best["cheapest_exit"] = min(candidates, key=lambda c: (c.exit_fee or 0.0))

    return {
        "n_candidates_evaluated": len(candidates),
        "best": best,
        "frontier": _efficient_frontier(candidates),
    }


def _efficient_frontier(candidates: list[Candidate]) -> list[Candidate]:
    """
    חזית היעילות בין עלות כוללת לחשיפה: כל התמהילים שאי אפשר לשפר בממד
    אחד בלי להחמיר באחר. זה מה שמראה ליועץ את מרחב הבחירה האמיתי, במקום
    מספר בודד שמתחזה ל"תשובה".
    """
    ordered = sorted(candidates, key=lambda c: (c.total_cost, c.exposure))
    frontier: list[Candidate] = []
    best_exposure = float("inf")
    for c in ordered:
        if c.exposure < best_exposure - 1e-9:
            frontier.append(c)
            best_exposure = c.exposure
    return frontier


def describe(candidate: Candidate, rates: dict[str, float]) -> str:
    """תיאור טקסטואלי קצר של חלוקה, לתצוגה."""
    parts = [
        f"{TRACK_LABELS.get(tt, tt)} {amount:,.0f} ₪ ({rates[tt]}%)"
        for tt, amount in candidate.allocation.items()
        if amount > 0
    ]
    return " · ".join(parts)
