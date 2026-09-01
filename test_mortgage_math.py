#!/usr/bin/env python3
"""
בדיקות למנועי החישוב הפיננסיים (mortgage_math, mortgage_refi, mortgage_review).

למה יש כאן בדיקות בכלל: כל המספרים שהכלים האלה מפיקים מגיעים בסוף להחלטה
של לקוח על סכום שש-ספרתי. שכבת ה-AI אפשר "להסתכל ולראות אם נשמע הגיוני";
את שכבת החשבון אי אפשר - טעות בנוסחה נראית סבירה לחלוטין על המסך. לכן כל
פונקציה מספרית נבדקת כאן מול תוצאה שחושבה עצמאית או מול תכונה מתמטית
שחייבת להתקיים.

הרצה:
    python3 -m pytest test_mortgage_math.py -q
    python3 test_mortgage_math.py          (ללא pytest - מריץ הכל ומדפיס)
"""
from __future__ import annotations

from mortgage_math import (
    blended_offer_stats,
    monthly_payment_shpitzer,
    stress_test_stats,
)
from mortgage_refi import (
    analyze_refi,
    capitalization_fee,
    compute_exit_cost,
    index_compensation_fee,
    present_value_of_payments,
    remaining_balance,
)
from mortgage_review import run_rule_checks


def approx(a: float, b: float, tol: float = 0.01) -> bool:
    return abs(a - b) <= tol


# ------------------------------------------------------- לוח סילוקין שפיצר

def test_shpitzer_known_value():
    """1,000,000 ₪ ב-5% ל-300 חודשים. ערך ידוע: כ-5,845.90 ₪."""
    assert approx(monthly_payment_shpitzer(1_000_000, 5.0, 300), 5845.90, tol=0.5)


def test_shpitzer_zero_interest():
    """בריבית 0 התשלום הוא פשוט קרן חלקי מספר חודשים."""
    assert approx(monthly_payment_shpitzer(240_000, 0.0, 240), 1000.0)


def test_shpitzer_degenerate_inputs():
    assert monthly_payment_shpitzer(0, 5.0, 300) == 0.0
    assert monthly_payment_shpitzer(100_000, 5.0, 0) == 0.0


def test_shpitzer_monotonic_in_rate():
    """ריבית גבוהה יותר => תשלום חודשי גבוה יותר. תכונה שחייבת להתקיים."""
    low = monthly_payment_shpitzer(800_000, 3.0, 300)
    high = monthly_payment_shpitzer(800_000, 6.0, 300)
    assert high > low


def test_shpitzer_longer_term_lowers_payment():
    short = monthly_payment_shpitzer(800_000, 5.0, 180)
    long = monthly_payment_shpitzer(800_000, 5.0, 360)
    assert long < short


# ------------------------------------------------------------- יתרת קרן

def test_remaining_balance_at_start_equals_principal():
    assert approx(remaining_balance(1_000_000, 5.0, 300, 0), 1_000_000, tol=1.0)


def test_remaining_balance_at_end_is_zero():
    assert approx(remaining_balance(1_000_000, 5.0, 300, 300), 0.0, tol=1.0)


def test_remaining_balance_decreases_over_time():
    balances = [remaining_balance(1_000_000, 5.0, 300, k) for k in range(0, 301, 30)]
    assert all(balances[i] > balances[i + 1] for i in range(len(balances) - 1))


def test_remaining_balance_amortization_identity():
    """
    בדיקה חזקה: יתרת הקרן אחרי k תשלומים חייבת לשוות את הערך הנוכחי של
    יתרת התשלומים, מהוונת בריבית ההלוואה עצמה. זו זהות מתמטית - אם היא
    נשברת, אחת משתי הנוסחאות שגויה.
    """
    principal, rate, n, k = 900_000, 4.7, 300, 84
    balance = remaining_balance(principal, rate, n, k)
    payment = monthly_payment_shpitzer(principal, rate, n)
    pv = present_value_of_payments(payment, rate, n - k)
    assert approx(balance, pv, tol=1.0)


def test_remaining_balance_zero_interest_is_linear():
    assert approx(remaining_balance(240_000, 0.0, 240, 120), 120_000, tol=1.0)


# ------------------------------------------------------------ עמלת היוון

def test_no_capitalization_fee_when_market_rate_higher():
    """ריבית השוק גבוהה מריבית ההלוואה => לבנק אין הפסד => אין עמלה."""
    assert capitalization_fee(700_000, 3.5, 5.5, 240, track_type="fixed_unlinked") == 0.0


def test_no_capitalization_fee_when_rates_equal():
    assert capitalization_fee(700_000, 4.5, 4.5, 240, track_type="fixed_unlinked") == 0.0


def test_capitalization_fee_positive_when_loan_rate_higher():
    """ריבית ההלוואה גבוהה מהשוק => יש עמלה."""
    fee = capitalization_fee(700_000, 5.5, 3.5, 240, track_type="fixed_unlinked")
    assert fee > 0


def test_capitalization_fee_grows_with_rate_gap():
    small_gap = capitalization_fee(700_000, 5.0, 4.5, 240, track_type="fixed_unlinked")
    big_gap = capitalization_fee(700_000, 6.5, 3.0, 240, track_type="fixed_unlinked")
    assert big_gap > small_gap


def test_capitalization_fee_grows_with_remaining_term():
    """ככל שנותרו יותר שנים, הפסד הריבית של הבנק גדול יותר."""
    short = capitalization_fee(700_000, 5.5, 3.5, 60, track_type="fixed_unlinked")
    long = capitalization_fee(700_000, 5.5, 3.5, 300, track_type="fixed_unlinked")
    assert long > short


def test_prime_track_has_no_capitalization_fee():
    """בפריים הריבית מתעדכנת לפי השוק ממילא - אין הפסד ריבית עתידי."""
    assert capitalization_fee(700_000, 6.0, 3.0, 240, track_type="variable_prime") == 0.0


def test_seniority_discount_reduces_fee():
    full = capitalization_fee(700_000, 5.5, 3.5, 240, track_type="fixed_unlinked")
    discounted = capitalization_fee(
        700_000, 5.5, 3.5, 240, seniority_discount_pct=30.0, track_type="fixed_unlinked"
    )
    assert approx(discounted, full * 0.7, tol=1.0)


# -------------------------------------------------------- עמלת פיצוי מדד

def test_index_fee_only_for_linked_tracks():
    assert index_compensation_fee(500_000, 3.0, track_type="fixed_unlinked") == 0.0
    assert index_compensation_fee(500_000, 3.0, track_type="variable_prime") == 0.0
    assert index_compensation_fee(500_000, 3.0, track_type="fixed_linked_cpi") > 0


def test_index_fee_is_half_the_cpi_change():
    """הסכום הנפרע כפול מחצית שיעור השינוי במדד."""
    assert approx(index_compensation_fee(500_000, 4.0, track_type="fixed_linked_cpi"), 10_000.0)


def test_index_fee_zero_when_no_inflation():
    assert index_compensation_fee(500_000, 0.0, track_type="fixed_linked_cpi") == 0.0


# ------------------------------------------------------ עלות יציאה מלאה

def _sample_existing_tracks():
    """משכנתא שנלקחה בשיא הריבית (2023) - בדיוק הקהל למיחזור."""
    return [
        {
            "name": "קבועה לא צמודה",
            "track_type": "fixed_unlinked",
            "original_amount": 500_000,
            "annual_interest_rate_pct": 5.9,
            "original_period_months": 300,
            "months_elapsed": 30,
        },
        {
            "name": "פריים",
            "track_type": "variable_prime",
            "original_amount": 400_000,
            "annual_interest_rate_pct": 6.1,
            "original_period_months": 300,
            "months_elapsed": 30,
        },
    ]


def test_exit_cost_sums_components():
    market = {"fixed_unlinked": 4.3, "variable_prime": 5.2}
    bd = compute_exit_cost(_sample_existing_tracks(), market_rates_by_track_type=market)
    assert approx(
        bd.total_fee,
        bd.total_capitalization + bd.total_index_compensation + bd.total_no_notice + bd.operational_fee,
        tol=0.01,
    )


def test_exit_cost_prime_contributes_no_capitalization():
    market = {"fixed_unlinked": 4.3, "variable_prime": 5.2}
    bd = compute_exit_cost(_sample_existing_tracks(), market_rates_by_track_type=market)
    prime = next(t for t in bd.tracks if t.track_type == "variable_prime")
    assert prime.capitalization == 0.0


def test_advance_notice_removes_no_notice_fee():
    market = {"fixed_unlinked": 4.3, "variable_prime": 5.2}
    with_notice = compute_exit_cost(
        _sample_existing_tracks(), market_rates_by_track_type=market, give_advance_notice=True
    )
    without = compute_exit_cost(
        _sample_existing_tracks(), market_rates_by_track_type=market, give_advance_notice=False
    )
    assert with_notice.total_no_notice == 0.0
    assert without.total_no_notice > 0
    assert without.total_fee > with_notice.total_fee


def test_exit_cost_balance_less_than_original():
    market = {"fixed_unlinked": 4.3, "variable_prime": 5.2}
    bd = compute_exit_cost(_sample_existing_tracks(), market_rates_by_track_type=market)
    assert 0 < bd.total_balance < 900_000


# ------------------------------------------------------- כדאיות מיחזור

def test_refi_verdict_depends_on_client_horizon():
    """
    הבדיקה המרכזית של כל המנוע, ומקורה בממצא אמיתי: מיחזור מ-5.9%/6.1%
    ל-4.2% חוסך כ-875 ₪ בחודש - אבל גורר עמלת היוון של כ-75,000 ₪, ולכן
    נקודת האיזון היא כ-86 חודשים.

    המשמעות: אותו מיחזור בדיוק *אינו* כדאי ללקוח שמתכנן 5 שנים, ו*כן*
    כדאי ללקוח שיישאר 15. אין תשובה אחת - ולכן הכלי חייב לחשוף את נקודת
    האיזון ולא להכריע לבד.
    """
    market = {"fixed_unlinked": 4.3, "variable_prime": 5.2}
    common = dict(
        market_rates_by_track_type=market,
        new_offer_rate_pct=4.2,
        new_term_months=270,
    )

    short = analyze_refi("c1", "אופק קצר", _sample_existing_tracks(),
                         evaluation_horizon_months=60, **common)
    long = analyze_refi("c1", "אופק ארוך", _sample_existing_tracks(),
                        evaluation_horizon_months=180, **common)

    assert short.monthly_saving > 0 and long.monthly_saving > 0
    assert short.breakeven_months > 60
    assert not short.is_worthwhile          # החיסכון החודשי לבדו מטעה
    assert long.is_worthwhile               # ובאופק ארוך זה כן משתלם
    assert short.net_benefit < 0 < long.net_benefit


def test_capitalization_fee_is_material_not_rounding():
    """
    שמירה מפני רגרסיה: אם מישהו יבטל בטעות את עמלת ההיוון, החישוב עדיין
    "יעבוד" ופשוט יראה חיסכון גדול יותר - שגיאה שקטה ומסוכנת. הבדיקה
    מוודאת שהעמלה נשארת רכיב מהותי ולא מתאפסת.
    """
    market = {"fixed_unlinked": 4.3, "variable_prime": 5.2}
    a = analyze_refi(
        "c1", "לקוח לדוגמה", _sample_existing_tracks(),
        market_rates_by_track_type=market, new_offer_rate_pct=4.2, new_term_months=270,
    )
    assert a.total_fee > 0.05 * a.exit_cost.total_balance


def test_refi_not_worthwhile_when_new_rate_is_worse():
    market = {"fixed_unlinked": 4.3, "variable_prime": 5.2}
    a = analyze_refi(
        "c2", "לקוח לדוגמה", _sample_existing_tracks(),
        market_rates_by_track_type=market,
        new_offer_rate_pct=7.5,
        new_term_months=270,
    )
    assert a.monthly_saving < 0
    assert a.breakeven_months is None
    assert not a.is_worthwhile


def test_refi_breakeven_math_is_consistent():
    """נקודת האיזון חייבת לקיים: חיסכון חודשי * חודשי איזון = עלות היציאה."""
    market = {"fixed_unlinked": 4.3, "variable_prime": 5.2}
    a = analyze_refi(
        "c3", "לקוח לדוגמה", _sample_existing_tracks(),
        market_rates_by_track_type=market,
        new_offer_rate_pct=4.2,
        new_term_months=270,
    )
    assert approx(a.monthly_saving * a.breakeven_months, a.total_fee, tol=1.0)


def test_refi_longer_term_lowers_payment_but_is_not_free():
    """
    מלכודת קלאסית: הארכת התקופה מקטינה את ההחזר ונראית כמו "חיסכון",
    גם כשהריבית לא השתנתה בכלל. הבדיקה מוודאת שהמנוע אכן מראה חיסכון
    חודשי במקרה כזה - כלומר שהמספר לבדו מטעה, ולכן הכלי חייב להציג גם
    את התקופה, לא רק את ההחזר.
    """
    market = {"fixed_unlinked": 5.9, "variable_prime": 6.1}  # שוק זהה להלוואה => אין עמלת היוון
    same_rate_longer_term = analyze_refi(
        "c4", "לקוח לדוגמה", _sample_existing_tracks(),
        market_rates_by_track_type=market,
        new_offer_rate_pct=6.0,
        new_term_months=360,
    )
    assert same_rate_longer_term.monthly_saving > 0
    assert same_rate_longer_term.term_extended_months > 0


# ------------------------------------------- מיחזור חלקי והפרדת הארכת תקופה

def _refi(new_term_months=270, horizon=60):
    market = {"fixed_unlinked": 4.3, "variable_prime": 5.2}
    return analyze_refi(
        "c", "לקוח", _sample_existing_tracks(),
        market_rates_by_track_type=market,
        new_offer_rate_pct=4.2,
        new_term_months=new_term_months,
        evaluation_horizon_months=horizon,
    )


def test_term_extension_is_separated_from_rate_improvement():
    """
    הארכת תקופה חייבת להיספר בנפרד משיפור ריבית. בלי ההפרדה הזו, כל
    מיחזור עם תקופה ארוכה יותר נראה מוצלח.
    """
    same_term = _refi(new_term_months=270)
    longer_term = _refi(new_term_months=360)

    assert approx(same_term.term_extension_monthly_saving, 0.0, tol=1.0)
    assert longer_term.term_extension_monthly_saving > 0
    # שיפור הריבית זהה בשני המקרים - רק התקופה שונה
    assert approx(same_term.rate_only_monthly_saving, longer_term.rate_only_monthly_saving, tol=1.0)


def test_term_extension_illusion_is_flagged():
    """מיחזור בלי שיפור ריבית כלל, רק תקופה ארוכה יותר - חייב להידלק."""
    market = {"fixed_unlinked": 5.9, "variable_prime": 6.1}
    a = analyze_refi(
        "c", "לקוח", _sample_existing_tracks(),
        market_rates_by_track_type=market,
        new_offer_rate_pct=6.0,          # גרוע יותר מהריבית הקיימת
        new_term_months=400,             # אבל תקופה ארוכה בהרבה
        evaluation_horizon_months=60,
    )
    assert a.monthly_saving > 0                    # "חוסך" בחודש
    assert a.saving_is_mostly_term_extension       # אבל זו אשליה


def test_partial_refi_can_reverse_the_decision():
    """
    הממצא המרכזי: חישוב על המשכנתא כולה יכול להגיד "לא כדאי" בזמן
    שמיחזור של חלק מהמסלולים דווקא משתלם. זה ההבדל בין לוותר על לקוח
    לבין למצוא אצלו עסקה.
    """
    a = _refi(horizon=60)
    assert a.term_neutral_net_benefit < 0     # מיחזור מלא: לא כדאי
    assert a.partial_net_benefit > 0          # מיחזור חלקי: כן
    assert a.partial_beats_full


def test_partial_refi_excludes_tracks_with_big_exit_fee():
    """המסלול הקבוע היקר לצאת ממנו לא ייכלל; הפריים (בלי עמלת היוון) כן."""
    a = _refi(horizon=60)
    chosen = {t.track_type for t in a.worthwhile_tracks}
    assert "variable_prime" in chosen
    assert "fixed_unlinked" not in chosen


def test_best_net_benefit_never_rewards_term_extension():
    """
    הדירוג בין לקוחות חייב להתבסס על מספר שלא מתנפח מהארכת תקופה,
    אחרת לקוחות ידורגו לפי כמה מותחים להם את ההלוואה.
    """
    short = _refi(new_term_months=270)
    long = _refi(new_term_months=400)
    assert approx(short.best_net_benefit, long.best_net_benefit, tol=1.0)


def test_track_level_breakeven_consistency():
    a = _refi()
    for t in a.track_analyses:
        if t.breakeven_months and t.exit_fee > 0:
            assert approx(t.monthly_saving * t.breakeven_months, t.exit_fee, tol=1.0)


# ------------------------------------------------------ אופטימיזציית תמהיל

from mortgage_optimizer import Constraints, optimize  # noqa: E402

_OPT_RATES = {
    "fixed_unlinked": 4.6,
    "fixed_linked_cpi": 3.4,
    "variable_prime": 5.4,
}
_OPT_MARKET = {
    "fixed_unlinked": 4.3,
    "fixed_linked_cpi": 3.2,
    "variable_prime": 5.2,
}


def _opt(**kwargs):
    c = Constraints(loan_amount=1_200_000, term_months=300, **kwargs.pop("constraints", {}))
    return optimize(_OPT_RATES, c, step_pct=10, **kwargs)


def test_linked_track_is_not_treated_as_cheap():
    """
    רגרסיה על באג אמיתי: ריבית נקובה של מסלול צמוד נמוכה יותר, אבל הקרן
    גדלה עם המדד. בלי התיקון, האופטימיזציה מתכנסת תמיד לצמוד ומדווחת
    עליו כזול ביותר - טעות שנראית סבירה לחלוטין על המסך.
    """
    res = _opt(expected_cpi_pct=2.0)
    cheapest = res["best"]["cheapest_total"]
    linked_amount = cheapest.allocation.get("fixed_linked_cpi", 0)
    assert linked_amount < 1_200_000, "הזול ביותר לא אמור להיות 100% צמוד"


def test_nominal_payment_is_lower_than_effective_for_linked():
    """ההחזר שהלקוח משלם בחודש הראשון נמוך מהעלות האפקטיבית, במסלול צמוד."""
    res = _opt(expected_cpi_pct=3.0)
    lowest = res["best"]["lowest_monthly"]
    if lowest.cpi_share > 0:
        assert lowest.base_monthly_nominal < lowest.base_monthly


def test_zero_inflation_makes_linked_and_unlinked_comparable():
    """כשהאינפלציה הצפויה 0, ריבית נקובה של צמוד כן ברת-השוואה ישירה."""
    res = _opt(expected_cpi_pct=0.0)
    cheapest = res["best"]["cheapest_total"]
    assert cheapest.allocation.get("fixed_linked_cpi", 0) > 0


def test_min_fixed_share_constraint_is_respected():
    res = _opt()
    for cand in res["best"].values():
        assert cand.fixed_share >= 1 / 3 - 1e-6


def test_max_monthly_payment_filters_candidates():
    """התקרה נבדקת מול ההחזר בפועל, לא מול העלות האפקטיבית."""
    res = _opt(constraints={"max_monthly_payment": 6500})
    for cand in res["best"].values():
        assert cand.base_monthly_nominal <= 6500 + 1e-6


def test_impossible_constraints_fail_with_clear_message():
    try:
        _opt(constraints={"max_monthly_payment": 500})
    except ValueError as e:
        assert "תקרת ההחזר" in str(e)
    else:
        raise AssertionError("היה צריך להיכשל על אילוץ בלתי אפשרי")


def test_most_stable_has_no_more_exposure_than_cheapest():
    res = _opt()
    assert res["best"]["most_stable"].exposure <= res["best"]["cheapest_total"].exposure + 1e-6


def test_frontier_is_monotonic():
    """חזית יעילות: ככל שהעלות עולה, החשיפה יורדת. אחרת זו לא חזית."""
    res = _opt()
    frontier = res["frontier"]
    assert frontier
    for a, b in zip(frontier, frontier[1:]):
        assert b.total_cost >= a.total_cost - 1e-6
        assert b.exposure <= a.exposure + 1e-6


def test_frontier_collapses_when_one_track_dominates():
    """
    כשמסלול אחד גם הזול ביותר וגם היציב ביותר, אין דילמה - והחזית מצטמצמת
    לנקודה אחת. זו תשובה נכונה, לא תקלה: המנוע לא אמור להמציא פשרה
    כשאין מה לפשר עליו.
    """
    res = _opt()  # קבועה לא צמודה 4.6% מנצחת גם צמודה (3.4+2) וגם פריים 5.4
    assert len(res["frontier"]) == 1
    assert res["frontier"][0].exposure == 0


def test_frontier_expands_when_a_real_tradeoff_exists():
    """כשמסלול משתנה באמת זול יותר, נוצרת דילמה אמיתית והחזית נפרשת."""
    cheap_prime = {**_OPT_RATES, "variable_prime": 3.9}
    c = Constraints(loan_amount=1_200_000, term_months=300)
    res = optimize(cheap_prime, c, step_pct=10, expected_cpi_pct=2.0)
    assert len(res["frontier"]) >= 2
    # הקצה הזול חשוף יותר מהקצה היציב - זו בדיוק המשמעות של חזית
    assert res["frontier"][0].exposure > res["frontier"][-1].exposure


def test_cheapest_exit_beats_others_on_exit_cost():
    res = _opt(early_exit_year=5, market_rates=_OPT_MARKET)
    best_exit = res["best"]["cheapest_exit"]
    for key, cand in res["best"].items():
        if key != "cheapest_exit" and cand.exit_fee is not None:
            assert best_exit.exit_fee <= cand.exit_fee + 1e-6


# ------------------------------------------------ בדיקות הכלל של בקרת האיכות

def _sound_mix():
    return [
        {"name": "קבועה", "track_type": "fixed_unlinked", "amount": 400_000,
         "period_months": 240, "annual_interest_rate_pct": 4.5, "linkage": "unlinked"},
        {"name": "פריים", "track_type": "variable_prime", "amount": 350_000,
         "period_months": 300, "annual_interest_rate_pct": 5.4, "linkage": "unlinked"},
        {"name": "משתנה", "track_type": "variable_unlinked", "amount": 250_000,
         "period_months": 300, "annual_interest_rate_pct": 4.8, "linkage": "unlinked"},
    ]


def _checks_for(tracks, **kwargs):
    stats = blended_offer_stats({"bank_name": "x", "tracks": tracks})
    stress = stress_test_stats(tracks)
    return run_rule_checks(tracks, stats, stress, **kwargs)


def test_sound_mix_produces_no_findings():
    """הבדיקה החשובה ביותר: אין אזעקות שווא על תמהיל תקין."""
    findings = _checks_for(
        _sound_mix(), property_value=1_600_000, monthly_income=25_000,
        buyer_type="first_home", horizon_years=25,
    )
    assert findings == []


def test_checks_skip_when_data_missing():
    """בלי נתוני לקוח, הבדיקות התלויות בהם פשוט לא רצות - לא ממציאות."""
    assert _checks_for(_sound_mix()) == []


def test_low_fixed_share_is_flagged():
    tracks = [
        {"name": "קבועה", "track_type": "fixed_unlinked", "amount": 100_000,
         "period_months": 240, "annual_interest_rate_pct": 4.5, "linkage": "unlinked"},
        {"name": "פריים", "track_type": "variable_prime", "amount": 900_000,
         "period_months": 300, "annual_interest_rate_pct": 5.4, "linkage": "unlinked"},
    ]
    titles = [f["title"] for f in _checks_for(tracks)]
    assert any("קבועה" in t for t in titles)


def test_ltv_over_limit_is_flagged():
    findings = _checks_for(_sound_mix(), property_value=1_100_000, buyer_type="first_home")
    assert any("מימון" in f["title"] for f in findings)
    assert any(f["severity"] == "critical" for f in findings)


def test_investment_buyer_has_stricter_ltv():
    """אותה עסקה בדיוק: תקינה לדירה יחידה, חורגת לדירה להשקעה."""
    ok = _checks_for(_sound_mix(), property_value=1_400_000, buyer_type="first_home")
    bad = _checks_for(_sound_mix(), property_value=1_400_000, buyer_type="investment")
    assert not any("מימון" in f["title"] for f in ok)
    assert any("מימון" in f["title"] for f in bad)


def test_high_pti_is_flagged():
    findings = _checks_for(_sound_mix(), monthly_income=10_000)
    assert any("החזר להכנסה" in f["title"] for f in findings)


def test_early_repayment_exposure_flagged_against_short_horizon():
    """הכשל המתועד בענף: מסלול קבוע ארוך מול לקוח שמתכנן לפרוע מוקדם."""
    findings = _checks_for(_sound_mix(), horizon_years=3)
    assert any("פירעון מוקדם" in f["title"] for f in findings)


def test_no_early_repayment_flag_for_long_horizon():
    findings = _checks_for(_sound_mix(), horizon_years=25)
    assert not any("פירעון מוקדם" in f["title"] for f in findings)


# ------------------------------------------------------------------ runner

if __name__ == "__main__":
    import sys
    import traceback

    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_") and callable(f)]
    passed, failed = 0, []
    for name, fn in tests:
        try:
            fn()
            passed += 1
        except Exception:  # noqa: BLE001 - זה runner של בדיקות, רוצים לראות הכל
            failed.append((name, traceback.format_exc()))

    print(f"\n{passed}/{len(tests)} בדיקות עברו")
    for name, tb in failed:
        print(f"\n❌ {name}\n{tb}")
    sys.exit(1 if failed else 0)
