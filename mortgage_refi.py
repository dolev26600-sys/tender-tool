#!/usr/bin/env python3
"""
חישובי מיחזור משכנתא - יתרת קרן, עמלת פירעון מוקדם, וכדאיות מיחזור.

**הכל דטרמיניסטי. אין כאן שום קריאה למודל שפה.** זו נקודה עקרונית: כדאיות
מיחזור היא שאלה חשבונאית עם תשובה נכונה אחת, והשגיאה הידועה בענף היא
דווקא חישוב "חיסכון" בלי לכלול את עלות היציאה. כלי שמנחש כאן מזיק יותר
משהוא מועיל.

## רכיבי עמלת הפירעון המוקדם (לפי מבנה העמלות בישראל)

1. **עמלת היוון / הפרשי ריבית** - הרכיב המשמעותי. נגבית רק כאשר ריבית
   ההלוואה גבוהה מהריבית הממוצעת במשק לאותו מסלול במועד הפירעון. מחושבת
   כהפרש בין הערך הנוכחי של יתרת התשלומים מהוונת בריבית השוק, לבין יתרת
   הקרן בפועל.
2. **עמלת פיצוי מדד** (רק בהלוואות צמודות מדד) - הסכום הנפרע כפול מחצית
   שיעור השינוי הממוצע במדד ב-12 החודשים שקדמו לפירעון.
3. **עמלת אי הודעה מוקדמת** - עד 0.1% מהסכום הנפרע. **נמנעת לחלוטין**
   במתן הודעה בכתב 10-45 יום מראש, ולכן ברירת המחדל כאן היא לא לגבות
   אותה (ולציין זאת ללקוח כפעולה שחוסכת כסף).
4. **עמלה תפעולית** - סכום חד-פעמי קטן (עד כ-60 ₪).

## הנחת ותק

על עמלת ההיוון חלה הנחה מדורגת (בטווח של כ-10%-40%) לפי המסלול והזמן
שחלף. הערך כאן הוא **פרמטר**, וברירת המחדל היא 0 - כלומר הערכה שמרנית
שמעריכה את העמלה כלפי מעלה. זה הכיוון הבטוח לצורך החלטה על מיחזור:
עדיף להפתיע את הלקוח לטובה מאשר להבטיח חיסכון שלא יתממש.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from mortgage_math import monthly_payment_shpitzer

CPI_LINKED_TRACK_TYPES = {"fixed_linked_cpi", "variable_linked_cpi"}

# מסלולים שבהם עמלת היוון בדרך כלל אינה רלוונטית: הריבית מתעדכנת ממילא
# לפי השוק, ולכן לבנק אין הפסד ריבית עתידי לפצות עליו.
NO_CAPITALIZATION_TRACK_TYPES = {"variable_prime"}

DEFAULT_OPERATIONAL_FEE = 60.0
NO_NOTICE_FEE_RATE = 0.001  # 0.1% - נמנעת בהודעה מוקדמת בכתב


def remaining_balance(
    principal: float,
    annual_rate_pct: float,
    total_months: int,
    months_elapsed: int,
) -> float:
    """
    יתרת הקרן בלוח סילוקין שפיצר אחרי months_elapsed תשלומים.

    B_k = P * [(1+r)^n - (1+r)^k] / [(1+r)^n - 1]
    """
    if total_months <= 0 or principal <= 0:
        return 0.0
    k = max(0, min(months_elapsed, total_months))
    if k >= total_months:
        return 0.0

    r = (annual_rate_pct / 100) / 12
    if r == 0:
        return principal * (1 - k / total_months)

    growth_n = (1 + r) ** total_months
    growth_k = (1 + r) ** k
    return principal * (growth_n - growth_k) / (growth_n - 1)


def present_value_of_payments(monthly_payment: float, annual_rate_pct: float, months: int) -> float:
    """ערך נוכחי של סדרת תשלומים חודשיים קבועים, מהוונת בריבית שנתית נתונה."""
    if months <= 0 or monthly_payment <= 0:
        return 0.0
    r = (annual_rate_pct / 100) / 12
    if r == 0:
        return monthly_payment * months
    return monthly_payment * (1 - (1 + r) ** -months) / r


def capitalization_fee(
    balance: float,
    loan_rate_pct: float,
    market_rate_pct: float,
    remaining_months: int,
    *,
    seniority_discount_pct: float = 0.0,
    track_type: str = "other",
) -> float:
    """
    עמלת היוון (הפרשי ריבית).

    ההיגיון: מהוונים את יתרת התשלומים שהלווה *היה* משלם, בריבית השוק
    הנוכחית. אם ריבית ההלוואה גבוהה מריבית השוק, הערך הנוכחי הזה גבוה
    מיתרת הקרן - וההפרש הוא ההפסד של הבנק, כלומר העמלה. אם ריבית השוק
    גבוהה או שווה, אין לבנק הפסד ואין עמלה.
    """
    if balance <= 0 or remaining_months <= 0:
        return 0.0
    if track_type in NO_CAPITALIZATION_TRACK_TYPES:
        return 0.0
    if market_rate_pct >= loan_rate_pct:
        return 0.0

    payment = monthly_payment_shpitzer(balance, loan_rate_pct, remaining_months)
    pv_at_market = present_value_of_payments(payment, market_rate_pct, remaining_months)

    gross_fee = max(0.0, pv_at_market - balance)
    return gross_fee * (1 - seniority_discount_pct / 100)


def index_compensation_fee(balance: float, avg_cpi_change_12m_pct: float, *, track_type: str = "other") -> float:
    """
    עמלת פיצוי מדד - רק במסלולים צמודי מדד. הסכום הנפרע כפול מחצית שיעור
    השינוי הממוצע במדד ב-12 החודשים שקדמו לפירעון.
    """
    if track_type not in CPI_LINKED_TRACK_TYPES:
        return 0.0
    if balance <= 0 or avg_cpi_change_12m_pct <= 0:
        return 0.0
    return balance * (avg_cpi_change_12m_pct / 100) / 2


@dataclass
class TrackExitCost:
    """פירוט עלות היציאה ממסלול בודד."""
    name: str
    track_type: str
    balance: float
    remaining_months: int
    loan_rate_pct: float
    market_rate_pct: float
    capitalization: float
    index_compensation: float
    no_notice: float

    @property
    def total(self) -> float:
        return self.capitalization + self.index_compensation + self.no_notice


@dataclass
class ExitCostBreakdown:
    """עלות היציאה הכוללת מהמשכנתא הקיימת."""
    tracks: list[TrackExitCost] = field(default_factory=list)
    operational_fee: float = DEFAULT_OPERATIONAL_FEE

    @property
    def total_balance(self) -> float:
        return sum(t.balance for t in self.tracks)

    @property
    def total_capitalization(self) -> float:
        return sum(t.capitalization for t in self.tracks)

    @property
    def total_index_compensation(self) -> float:
        return sum(t.index_compensation for t in self.tracks)

    @property
    def total_no_notice(self) -> float:
        return sum(t.no_notice for t in self.tracks)

    @property
    def total_fee(self) -> float:
        return (
            self.total_capitalization
            + self.total_index_compensation
            + self.total_no_notice
            + self.operational_fee
        )


def compute_exit_cost(
    tracks: list[dict],
    *,
    market_rates_by_track_type: dict[str, float],
    avg_cpi_change_12m_pct: float = 0.0,
    seniority_discount_pct: float = 0.0,
    give_advance_notice: bool = True,
    operational_fee: float = DEFAULT_OPERATIONAL_FEE,
) -> ExitCostBreakdown:
    """
    עלות יציאה מלאה ממשכנתא קיימת.

    כל track הוא dict עם: name, track_type, original_amount,
    annual_interest_rate_pct, original_period_months, months_elapsed.

    market_rates_by_track_type: ריבית השוק הנוכחית לכל סוג מסלול - זה
    הנתון שקובע אם בכלל יש עמלת היוון, ולכן חייב להיות מעודכן.
    """
    breakdown = ExitCostBreakdown(operational_fee=operational_fee)

    for t in tracks:
        track_type = t.get("track_type", "other")
        total_months = int(t.get("original_period_months", 0) or 0)
        elapsed = int(t.get("months_elapsed", 0) or 0)
        remaining_months = max(0, total_months - elapsed)

        balance = remaining_balance(
            float(t.get("original_amount", 0) or 0),
            float(t.get("annual_interest_rate_pct", 0) or 0),
            total_months,
            elapsed,
        )
        if balance <= 0:
            continue

        loan_rate = float(t.get("annual_interest_rate_pct", 0) or 0)
        market_rate = float(market_rates_by_track_type.get(track_type, loan_rate))

        cap = capitalization_fee(
            balance,
            loan_rate,
            market_rate,
            remaining_months,
            seniority_discount_pct=seniority_discount_pct,
            track_type=track_type,
        )
        idx = index_compensation_fee(balance, avg_cpi_change_12m_pct, track_type=track_type)
        no_notice = 0.0 if give_advance_notice else balance * NO_NOTICE_FEE_RATE

        breakdown.tracks.append(TrackExitCost(
            name=t.get("name", ""),
            track_type=track_type,
            balance=balance,
            remaining_months=remaining_months,
            loan_rate_pct=loan_rate,
            market_rate_pct=market_rate,
            capitalization=cap,
            index_compensation=idx,
            no_notice=no_notice,
        ))

    return breakdown


def current_monthly_payment(tracks: list[dict]) -> float:
    """ההחזר החודשי הנוכחי של המשכנתא הקיימת (סכום התשלומים בכל המסלולים)."""
    total = 0.0
    for t in tracks:
        total += monthly_payment_shpitzer(
            float(t.get("original_amount", 0) or 0),
            float(t.get("annual_interest_rate_pct", 0) or 0),
            int(t.get("original_period_months", 0) or 0),
        )
    return total


@dataclass
class TrackRefiAnalysis:
    """
    כדאיות מיחזור של **מסלול בודד**, בנפרד מהשאר.

    זה ההבדל בין מחשבון מיחזור לבין יועץ: מיחזור אינו החלטה של הכל-או-כלום.
    לקוח יכול להחזיק מסלול קבוע ישן וזול לצד מסלול פריים יקר - ואז נכון
    למחזר רק את השני. חישוב על המשכנתא כולה מטשטש את זה, ולפעמים אף הופך
    את התשובה.

    ההשוואה כאן היא בכוונה על אותה תקופה שנותרה: כך המספר מבטא שיפור
    ריבית נקי, בלי "חיסכון" מדומה שנובע מהארכת התקופה.
    """
    name: str
    track_type: str
    balance: float
    remaining_months: int
    loan_rate_pct: float
    current_monthly: float
    new_monthly: float
    exit_fee: float

    @property
    def monthly_saving(self) -> float:
        return self.current_monthly - self.new_monthly

    @property
    def breakeven_months(self) -> float | None:
        if self.monthly_saving <= 0:
            return None
        if self.exit_fee <= 0:
            return 0.0
        return self.exit_fee / self.monthly_saving

    def is_worthwhile_for(self, horizon_months: int) -> bool:
        be = self.breakeven_months
        return be is not None and be <= horizon_months


def analyze_tracks_separately(
    exit_cost: ExitCostBreakdown,
    *,
    new_offer_rate_pct: float,
) -> list[TrackRefiAnalysis]:
    """
    בודק כל מסלול בנפרד: האם *הוא* שווה מיחזור, בהינתן עלות היציאה שלו
    והריבית החדשה המוצעת. ההשוואה נעשית על התקופה שנותרה לאותו מסלול.
    """
    analyses = []
    for t in exit_cost.tracks:
        current = monthly_payment_shpitzer(t.balance, t.loan_rate_pct, t.remaining_months)
        new = monthly_payment_shpitzer(t.balance, new_offer_rate_pct, t.remaining_months)
        analyses.append(TrackRefiAnalysis(
            name=t.name,
            track_type=t.track_type,
            balance=t.balance,
            remaining_months=t.remaining_months,
            loan_rate_pct=t.loan_rate_pct,
            current_monthly=current,
            new_monthly=new,
            exit_fee=t.total,
        ))
    return analyses


@dataclass
class RefiAnalysis:
    """
    תוצאת ניתוח כדאיות מיחזור ללקוח בודד.

    evaluation_horizon_months הוא **הפרמטר המכריע**, ובכוונה אינו קבוע
    בקוד: אותו מיחזור בדיוק יכול להיות כדאי מאוד ללקוח שיישאר בנכס 20
    שנה, ולא כדאי כלל ללקוח שמתכנן למכור בעוד 4. הכלי לא אמור להכריע
    את זה במקום היועץ - הוא אמור להראות את נקודת האיזון ולתת ליועץ
    להשוות אותה לאופק האמיתי של הלקוח.
    """
    client_id: str
    client_name: str
    exit_cost: ExitCostBreakdown
    current_monthly: float
    new_monthly: float
    new_rate_pct: float
    new_term_months: int
    evaluation_horizon_months: int = 60

    @property
    def monthly_saving(self) -> float:
        return self.current_monthly - self.new_monthly

    @property
    def total_fee(self) -> float:
        return self.exit_cost.total_fee

    @property
    def breakeven_months(self) -> float | None:
        """
        כמה חודשים לוקח לחיסכון החודשי לכסות את עלות היציאה.
        None אם אין חיסכון חודשי כלל (ואז המיחזור לא מחזיר את עצמו לעולם).
        """
        if self.monthly_saving <= 0:
            return None
        return self.total_fee / self.monthly_saving

    def net_benefit_over(self, months: int) -> float:
        """תועלת נטו על פני חלון זמן נתון: חיסכון מצטבר פחות עלות היציאה."""
        return self.monthly_saving * months - self.total_fee

    @property
    def net_benefit(self) -> float:
        """תועלת נטו על פני אופק ההערכה שנקבע לניתוח הזה."""
        return self.net_benefit_over(self.evaluation_horizon_months)

    @property
    def is_worthwhile(self) -> bool:
        """
        כדאי אם נקודת האיזון נופלת בתוך אופק ההערכה. שים לב שזו קביעה
        יחסית לאופק שנבחר, לא אמת מוחלטת - ראה הערת המחלקה.
        """
        be = self.breakeven_months
        return be is not None and be <= self.evaluation_horizon_months

    @property
    def remaining_term_months(self) -> int:
        """התקופה שנותרה במשכנתא הקיימת (המסלול הארוך ביותר)."""
        return max((t.remaining_months for t in self.exit_cost.tracks), default=0)

    @property
    def rate_only_monthly_saving(self) -> float:
        """
        החיסכון החודשי שנובע **רק משיפור הריבית** - כלומר אם היו ממחזרים
        את אותו סכום בדיוק, לאותה תקופה שנותרה, בריבית החדשה.
        """
        term_neutral_payment = monthly_payment_shpitzer(
            self.exit_cost.total_balance, self.new_rate_pct, self.remaining_term_months
        )
        return self.current_monthly - term_neutral_payment

    @property
    def term_extension_monthly_saving(self) -> float:
        """
        החלק מה"חיסכון" החודשי שנובע רק מהארכת התקופה, לא משיפור תנאים.

        זה המספר שחושף את המלכודת: הארכת תקופה תמיד מקטינה את ההחזר
        החודשי, גם בלי שום שיפור בריבית - ובתמורה הלקוח משלם ריבית על
        פני יותר שנים. חיסכון שמורכב ברובו מהרכיב הזה אינו חיסכון.
        """
        return self.monthly_saving - self.rate_only_monthly_saving

    @property
    def saving_is_mostly_term_extension(self) -> bool:
        """True אם רוב ה"חיסכון" החודשי הוא בעצם הארכת תקופה."""
        if self.monthly_saving <= 0:
            return False
        return self.term_extension_monthly_saving > self.monthly_saving / 2

    @property
    def term_neutral_net_benefit(self) -> float:
        """
        תועלת נטו במיחזור מלא **בלי הארכת תקופה** - ההשוואה ההוגנת מול
        מיחזור חלקי, שגם הוא מחושב על התקופה שנותרה.
        """
        return self.rate_only_monthly_saving * self.evaluation_horizon_months - self.total_fee

    @property
    def track_analyses(self) -> list[TrackRefiAnalysis]:
        """כדאיות מיחזור לכל מסלול בנפרד."""
        return analyze_tracks_separately(self.exit_cost, new_offer_rate_pct=self.new_rate_pct)

    @property
    def worthwhile_tracks(self) -> list[TrackRefiAnalysis]:
        """רק המסלולים שכדאי למחזר בפני עצמם, באופק ההערכה שנבחר."""
        return [t for t in self.track_analyses if t.is_worthwhile_for(self.evaluation_horizon_months)]

    @property
    def partial_monthly_saving(self) -> float:
        """החיסכון החודשי אם ממחזרים **רק** את המסלולים שכדאי."""
        return sum(t.monthly_saving for t in self.worthwhile_tracks)

    @property
    def partial_exit_fee(self) -> float:
        """עלות היציאה אם ממחזרים רק את המסלולים שכדאי (בתוספת עמלה תפעולית)."""
        if not self.worthwhile_tracks:
            return 0.0
        return sum(t.exit_fee for t in self.worthwhile_tracks) + self.exit_cost.operational_fee

    @property
    def partial_net_benefit(self) -> float:
        """תועלת נטו במיחזור חלקי, על פני אופק ההערכה."""
        if not self.worthwhile_tracks:
            return 0.0
        return self.partial_monthly_saving * self.evaluation_horizon_months - self.partial_exit_fee

    @property
    def partial_beats_full(self) -> bool:
        """
        האם עדיף למחזר רק חלק מהמסלולים במקום את כולם. כשזה True, המלצה
        על מיחזור מלא משאירה כסף על השולחן - או גרוע מכך, מוכרת ללקוח
        עסקה שפוגעת בו במסלול אחד כדי להרוויח באחר.

        ההשוואה היא מול term_neutral_net_benefit ולא מול net_benefit,
        כי מיחזור חלקי מחושב על התקופה שנותרה - השוואה מול מיחזור מלא
        עם תקופה מוארכת הייתה משווה תפוחים לתפוזים ומטה את התוצאה.
        """
        return self.partial_net_benefit > self.term_neutral_net_benefit

    @property
    def best_net_benefit(self) -> float:
        """
        התועלת הטובה ביותר מבין מיחזור מלא (ללא הארכת תקופה) ומיחזור חלקי.
        זהו המספר שראוי לדרג לפיו לקוחות - הוא לא מתוגמל על הארכת תקופה.
        """
        return max(self.term_neutral_net_benefit, self.partial_net_benefit)

    @property
    def term_extended_months(self) -> int:
        """
        בכמה חודשים מתארכת התקופה ביחס לתקופה שנותרה כיום.

        זה המספר שחושף את המלכודת הנפוצה ביותר: הארכת תקופה מקטינה את
        ההחזר החודשי ונראית כמו "חיסכון" גם כשהריבית לא ירדה כלל.
        """
        longest_remaining = max((t.remaining_months for t in self.exit_cost.tracks), default=0)
        return self.new_term_months - longest_remaining


def analyze_refi(
    client_id: str,
    client_name: str,
    tracks: list[dict],
    *,
    market_rates_by_track_type: dict[str, float],
    new_offer_rate_pct: float,
    new_term_months: int,
    avg_cpi_change_12m_pct: float = 0.0,
    seniority_discount_pct: float = 0.0,
    give_advance_notice: bool = True,
    evaluation_horizon_months: int = 60,
) -> RefiAnalysis:
    """
    ניתוח כדאיות מיחזור ללקוח בודד: עלות היציאה מהמשכנתא הקיימת מול
    ההחזר החדש, ומתי (אם בכלל) זה מחזיר את עצמו.
    """
    exit_cost = compute_exit_cost(
        tracks,
        market_rates_by_track_type=market_rates_by_track_type,
        avg_cpi_change_12m_pct=avg_cpi_change_12m_pct,
        seniority_discount_pct=seniority_discount_pct,
        give_advance_notice=give_advance_notice,
    )

    new_monthly = monthly_payment_shpitzer(exit_cost.total_balance, new_offer_rate_pct, new_term_months)

    return RefiAnalysis(
        client_id=client_id,
        client_name=client_name,
        exit_cost=exit_cost,
        current_monthly=current_monthly_payment(tracks),
        new_monthly=new_monthly,
        new_rate_pct=new_offer_rate_pct,
        new_term_months=new_term_months,
        evaluation_horizon_months=evaluation_horizon_months,
    )
