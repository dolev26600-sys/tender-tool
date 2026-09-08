#!/usr/bin/env python3
"""
מנוע לוח הסילוקין - הבסיס לכל שאר החישובים במערכת (ראה סעיף 0 ו-4.1 באפיון).

עקרון מרכזי: לכל מסלול בונים לוח סילוקין חודשי מלא ("שורה" אחת ללוח לכל
חודש: יתרת פתיחה, ריבית, קרן, יתרת סגירה) - לא נוסחת קיצור. הלוח הזה הוא
מקור האמת לכל מדד אחר (סכום תשלומים, ערך נוכחי, השוואה לתרחישי לחץ וכו').

מודל ההצמדה למדד (linked_to_cpi): מחשבים קודם לוח "ריאלי" (לא צמוד) לפי
סוג הלוח (שפיצר/קרן שווה/בלון/גרייס) וריבית החוזה החודשית, ורק אז מכפילים
כל שדה בשורה של חודש m במקדם הצמדה מצטבר עד אותו חודש. זה נובע מהדרישה
המפורשת באפיון: "לא מוסיפים אינפלציה לריבית כקיצור דרך" - ההצמדה מגדילה
את הקרן, ולכן גם את הריבית שנגזרת ממנה. אפשר להוכיח שההצמדה האחידה הזו
לכל שדה בשורה עקבית מתמטית (ריבית_נומינלית(m) = ריבית_ריאלית(m) * מקדם(m)
וכן הלאה) - ומכאן גם בדיקת הקבלה: אינפלציה 0 => מקדם 1 בכל חודש => תוצאה
זהה למסלול לא צמוד באותה ריבית.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


VARIABLE_KINDS = {"prime", "varNonLinked", "varLinked", "varMakam"}
FIXED_KINDS = {"fixedNonLinked", "fixedLinked"}


@dataclass
class Track:
    id: str
    kind: str
    balance: float
    rate: float  # ריבית שנתית נוכחית, אחוזים (למשל 5.25)
    months_left: int
    original_months: int
    schedule: str = "spitzer"  # spitzer | equalPrincipal | bullet | grace
    linked_to_cpi: bool = False
    reset_every_months: Optional[int] = None
    months_to_next_reset: Optional[int] = None
    margin_over_anchor: Optional[float] = None
    bank_id: Optional[str] = None
    grace_months: int = 0
    grace_type: str = "none"  # none | full | partial
    post_grace_schedule: str = "spitzer"

    def is_variable(self) -> bool:
        # פריים מתעדכן בפועל כל חודש עם ריבית בנק ישראל (ראה טבלת סוגי
        # המסלולים בסעיף 2.2 באפיון: "תחנת יציאה - חודשית בפועל"), ולכן
        # אין לו reset_every_months להגדיר והוא תמיד נחשב משתנה. בלי זה
        # מסלול פריים היה נראה חסין לחלוטין לעליית ריבית בתרחישי הלחץ.
        if self.kind == "prime":
            return True
        return self.kind in VARIABLE_KINDS and self.reset_every_months is not None


@dataclass
class Scenario:
    name: str
    annual_inflation: float = 0.0  # אחוזים
    anchor_delta_path: list = field(default_factory=list)  # תוספת מצטברת לעוגן (נ"א) לפי חודש, אינדקס 0 = חודש 1


@dataclass
class Row:
    month: int
    opening: float
    rate: float
    payment: float
    interest: float
    principal: float
    closing: float


def _pmt(balance: float, monthly_rate: float, n_months: int) -> float:
    if n_months <= 0:
        return balance
    if abs(monthly_rate) < 1e-12:
        return balance / n_months
    return balance * monthly_rate / (1 - (1 + monthly_rate) ** (-n_months))


def build_rate_path(track: Track, scenario: Scenario) -> list:
    """מחזיר ריבית שנתית (%) לכל חודש בלוח, בלי הצמדה (זו מטופלת בנפרד)."""
    months = track.months_left
    if not track.is_variable():
        return [track.rate] * months

    is_prime = track.kind == "prime"
    reset_every = (track.reset_every_months or 1) if is_prime else track.reset_every_months
    next_reset = track.months_to_next_reset
    if next_reset is None:
        next_reset = 0 if is_prime else reset_every

    path = []
    current_rate = track.rate
    for m in range(1, months + 1):
        if m > next_reset:
            delta = 0.0
            if scenario.anchor_delta_path:
                idx = min(m - 1, len(scenario.anchor_delta_path) - 1)
                delta = scenario.anchor_delta_path[idx]
            current_rate = track.rate + delta
            next_reset += reset_every
        path.append(current_rate)
    return path


def _spitzer_real(balance: float, rate_path: list, months: int) -> list:
    rows = []
    bal = balance
    pmt = None
    prev_rate = None
    for m in range(months):
        annual_rate = rate_path[m]
        i = annual_rate / 100 / 12
        remaining = months - m
        if pmt is None or annual_rate != prev_rate:
            pmt = _pmt(bal, i, remaining)
            prev_rate = annual_rate
        interest = bal * i
        principal = pmt - interest
        if m == months - 1:
            principal = bal
            pmt = principal + interest
        closing = bal - principal
        rows.append(Row(m + 1, bal, annual_rate, pmt, interest, principal, closing))
        bal = closing
    return rows


def _equal_principal_real(balance: float, rate_path: list, months: int) -> list:
    rows = []
    bal = balance
    principal_fixed = balance / months if months else 0.0
    for m in range(months):
        annual_rate = rate_path[m]
        i = annual_rate / 100 / 12
        interest = bal * i
        principal = principal_fixed if m < months - 1 else bal
        payment = principal + interest
        closing = bal - principal
        rows.append(Row(m + 1, bal, annual_rate, payment, interest, principal, closing))
        bal = closing
    return rows


def _bullet_real(balance: float, rate_path: list, months: int) -> list:
    rows = []
    bal = balance
    for m in range(months):
        annual_rate = rate_path[m]
        i = annual_rate / 100 / 12
        interest = bal * i
        principal = 0.0 if m < months - 1 else bal
        payment = principal + interest
        closing = bal - principal
        rows.append(Row(m + 1, bal, annual_rate, payment, interest, principal, closing))
        bal = closing
    return rows


def _grace_real(balance: float, rate_path: list, months: int, grace_months: int,
                 grace_type: str, post_schedule: str) -> list:
    rows = []
    bal = balance
    grace_months = min(grace_months, months)
    for m in range(grace_months):
        annual_rate = rate_path[m]
        i = annual_rate / 100 / 12
        interest = bal * i
        if grace_type == "full":
            payment = 0.0
            principal = -interest  # יתרה גדלה - הריבית נצברת לקרן
            closing = bal + interest
        else:  # partial - משלמים ריבית בלבד
            payment = interest
            principal = 0.0
            closing = bal
        rows.append(Row(m + 1, bal, annual_rate, payment, interest, principal, closing))
        bal = closing

    remaining_months = months - grace_months
    if remaining_months > 0:
        tail_rate_path = rate_path[grace_months:]
        dispatch = _SCHEDULE_DISPATCH.get(post_schedule, _spitzer_real)
        tail = dispatch(bal, tail_rate_path, remaining_months)
        for idx, row in enumerate(tail):
            row.month = grace_months + idx + 1
        rows.extend(tail)
    return rows


_SCHEDULE_DISPATCH = {
    "spitzer": _spitzer_real,
    "equalPrincipal": _equal_principal_real,
    "bullet": _bullet_real,
    "balloon": _bullet_real,
}


def _generate_real_schedule(track: Track, rate_path: list) -> list:
    months = track.months_left
    if track.schedule == "grace" or track.grace_months > 0:
        return _grace_real(track.balance, rate_path, months, track.grace_months,
                            track.grace_type, track.post_grace_schedule)
    dispatch = _SCHEDULE_DISPATCH.get(track.schedule, _spitzer_real)
    return dispatch(track.balance, rate_path, months)


def apply_cpi_linkage(rows: list, annual_inflation: float) -> list:
    """מכפיל כל שדה כספי בשורה של חודש m במקדם הצמדה מצטבר עד חודש m.

    ראה הסבר מתמטי בראש הקובץ: מקדם(m) = (1+פ)^(m/12) כאשר פ אינפלציה
    שנתית. עם אינפלציה 0 מקדם(m)=1 תמיד -> שקול ללוח הריאלי (בדיקת קבלה 2).
    """
    if abs(annual_inflation) < 1e-12:
        return rows
    monthly_factor = (1 + annual_inflation / 100) ** (1 / 12)
    out = []
    for row in rows:
        factor = monthly_factor ** row.month
        out.append(Row(
            month=row.month,
            opening=row.opening * factor,
            rate=row.rate,
            payment=row.payment * factor,
            interest=row.interest * factor,
            principal=row.principal * factor,
            closing=row.closing * factor,
        ))
    return out


def generate_schedule(track: Track, scenario: Optional[Scenario] = None) -> list:
    """נקודת הכניסה הראשית: מחזיר את הלוח המלא (נומינלי) עבור מסלול נתון
    תחת תרחיש נתון (ברירת מחדל: תרחיש בסיס בלי אינפלציה ובלי שינוי ריבית)."""
    if scenario is None:
        scenario = Scenario(name="בסיס", annual_inflation=0.0, anchor_delta_path=[])
    rate_path = build_rate_path(track, scenario)
    real_rows = _generate_real_schedule(track, rate_path)
    if track.linked_to_cpi:
        return apply_cpi_linkage(real_rows, scenario.annual_inflation)
    return real_rows
