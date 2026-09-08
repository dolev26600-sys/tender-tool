#!/usr/bin/env python3
"""מנוע ההמלצות (סעיף 7 באפיון).

היקף המימוש (MVP - ראה README לפירוט מה נדחה לגרסה הבאה): המנוע מייצר
תמהילים חוקיים על רשת של שלושה סוגי מסלול (קבועה לא צמודה / פריים /
משתנה לא צמודה) בצעדים של 25% (במקום 5% המלא באפיון, כדי לשמור על זמן
ריצה סביר ב-MVP - קל להרחיב את share_step ואת קבוצת הסוגים). מדרג
לפחות 4 חלופות בשם, בודק מחזור חלקי מול מלא מול אי-עשייה על כל תתי-
הקבוצות של המסלולים הקיימים, ובודק חלופת המתנה לתחנת יציאה.
"""
from __future__ import annotations

from dataclasses import replace
from itertools import combinations

from .config import ConfigBundle, MissingConfigError
from .fees import compute_prepayment_fee, total_prepayment_fee_for_tracks
from .metrics import combined_household_schedule, present_value, summarize
from .rules import evaluate_mix, has_blocking_violation
from .schedule import (
    Scenario, Track, VARIABLE_KINDS, _SCHEDULE_DISPATCH, _spitzer_real,
    apply_cpi_linkage, build_rate_path, generate_schedule,
)


def get_bank_rate(bank: dict, kind: str, level: str = "typ", term_years: int = None,
                   reset_months: int = None) -> float:
    tracks_cfg = bank.get("tracks") or {}
    cfg = tracks_cfg.get(kind)
    if not cfg:
        raise MissingConfigError(f"חסר נתון: בנק {bank.get('id')} לא מציע מסלול {kind}")

    if kind in ("fixedNonLinked", "fixedLinked"):
        by_term = cfg.get("byTerm") or {}
        entry = by_term.get(str(term_years))
        if not entry:
            raise MissingConfigError(
                f"חסר נתון: בנק {bank.get('id')} לא מפרסם ריבית ל-{kind} בתקופה {term_years} שנים"
            )
        return entry[level]

    if kind == "prime":
        margin_cfg = cfg.get("marginFromPrime")
        if not margin_cfg:
            raise MissingConfigError(f"חסר נתון: בנק {bank.get('id')} לא מפרסם מרווח לפריים")
        return margin_cfg[level]

    if kind in ("varNonLinked", "varLinked"):
        by_reset = cfg.get("byReset") or {}
        entry = by_reset.get(str(reset_months))
        if not entry:
            raise MissingConfigError(
                f"חסר נתון: בנק {bank.get('id')} לא מפרסם ריבית ל-{kind} עם תחנת יציאה {reset_months} חודשים"
            )
        return entry[level]

    raise MissingConfigError(f"חסר נתון: סוג מסלול לא נתמך בשליפת ריבית: {kind}")


def ltv_surcharge(bank: dict, ltv: float) -> float:
    if ltv is None:
        return 0.0
    for entry in bank.get("ltvSurcharge") or []:
        if ltv <= entry["upTo"] + 1e-9:
            return entry["delta"]
    return 0.0


def build_new_track(track_id: str, kind: str, amount: float, config: ConfigBundle, bank: dict,
                     term_years: int = None, reset_months: int = None, ltv: float = None,
                     level: str = "typ") -> Track:
    if kind == "prime":
        margin = get_bank_rate(bank, kind, level) + ltv_surcharge(bank, ltv)
        rate = config.rates["primeRate"] + margin
        return Track(id=track_id, kind=kind, balance=amount, rate=rate,
                     months_left=term_years * 12, original_months=term_years * 12,
                     schedule="spitzer", linked_to_cpi=False, bank_id=bank.get("id"))

    if kind in ("varNonLinked", "varLinked"):
        rate = get_bank_rate(bank, kind, level, reset_months=reset_months) + ltv_surcharge(bank, ltv)
        return Track(id=track_id, kind=kind, balance=amount, rate=rate,
                     months_left=term_years * 12, original_months=term_years * 12,
                     schedule="spitzer", linked_to_cpi=(kind == "varLinked"),
                     reset_every_months=reset_months, months_to_next_reset=reset_months,
                     bank_id=bank.get("id"))

    # fixedNonLinked / fixedLinked
    rate = get_bank_rate(bank, kind, level, term_years=term_years) + ltv_surcharge(bank, ltv)
    return Track(id=track_id, kind=kind, balance=amount, rate=rate,
                 months_left=term_years * 12, original_months=term_years * 12,
                 schedule="spitzer", linked_to_cpi=(kind == "fixedLinked"), bank_id=bank.get("id"))


def evaluate_alternative(tracks: list, scenarios: dict, discount_rate: float) -> dict:
    per_scenario = {}
    for name, scenario in scenarios.items():
        rows_by_track = {t.id: generate_schedule(t, scenario) for t in tracks}
        combined = combined_household_schedule(rows_by_track)
        payments = [row["payment"] for row in combined]
        total_payments = sum(payments)
        first_payment = payments[0] if payments else 0.0
        max_payment = max(payments) if payments else 0.0
        i = discount_rate / 100 / 12
        pv = sum(row["payment"] / (1 + i) ** row["month"] for row in combined) if i else total_payments
        per_scenario[name] = {
            "total_payments": total_payments, "first_payment": first_payment,
            "max_payment": max_payment, "pv": pv, "months": len(combined),
        }
    return {"per_scenario": per_scenario}


def _share_combinations(n_buckets: int, step: float) -> list:
    steps = int(round(1 / step))

    def rec(remaining_buckets, remaining_steps, acc):
        if remaining_buckets == 1:
            yield acc + [remaining_steps]
            return
        for s in range(remaining_steps + 1):
            yield from rec(remaining_buckets - 1, remaining_steps - s, acc + [s])

    return [[c * step for c in combo] for combo in rec(n_buckets, steps, [])]


DEFAULT_GRID_KINDS = ("fixedNonLinked", "prime", "varNonLinked")


def generate_alternatives(
    amount: float, term_years: int, config: ConfigBundle, rules_cfg: dict, scenarios: dict,
    discount_rate: float, kinds: tuple = DEFAULT_GRID_KINDS, share_step: float = 0.25,
    var_reset_months: int = 60, ltv: float = None, pti_income: float = None,
) -> list:
    """סורק רשת תמהילים חוקיים ומחזיר את כולם עם המדדים שלהם (לא מסונן
    לפי דירוג - ראה rank_alternatives). כל תמהיל שמפר כלל blocking מוצא
    מהתוצאה כאן, ולכן אף פעם לא יופיע בהמלצות (בדיקת קבלה 4)."""
    results = []
    combos = _share_combinations(len(kinds), share_step)
    for bank in config.banks():
        for shares in combos:
            tracks = []
            for idx, (kind, share) in enumerate(zip(kinds, shares)):
                if share <= 0:
                    continue
                try:
                    track = build_new_track(
                        f"{kind}_{idx}", kind, amount * share, config, bank,
                        term_years=term_years, reset_months=var_reset_months, ltv=ltv,
                    )
                except MissingConfigError:
                    tracks = None
                    break
                tracks.append(track)
            if not tracks:
                continue

            violations = evaluate_mix(tracks, rules_cfg, term_years=term_years, ltv=ltv,
                                       pti=None)
            if has_blocking_violation(violations):
                continue

            metrics = evaluate_alternative(tracks, scenarios, discount_rate)
            if pti_income:
                first_pti = metrics["per_scenario"]["base"]["first_payment"] / pti_income
                pti_violations = evaluate_mix(tracks, rules_cfg, pti=first_pti)
                violations = violations + pti_violations
                if has_blocking_violation(pti_violations):
                    continue

            results.append({
                "bank_id": bank["id"], "bank_name": bank.get("name", bank["id"]),
                "shares": dict(zip(kinds, shares)), "tracks": tracks,
                "violations": violations, "metrics": metrics,
            })
    return results


def _norm(values: list):
    lo, hi = min(values), max(values)
    if hi - lo < 1e-9:
        return lambda v: 0.0
    return lambda v: (v - lo) / (hi - lo)


def rank_alternatives(alternatives: list) -> dict:
    """בוחר לפחות 4 חלופות בשם מתוך רשימת התמהילים החוקיים (סעיף 7.1)."""
    if not alternatives:
        return {}

    cheapest = min(alternatives, key=lambda a: a["metrics"]["per_scenario"]["base"]["pv"])
    lowest_payment = min(alternatives, key=lambda a: a["metrics"]["per_scenario"]["base"]["first_payment"])
    combined_key = "combined" if "combined" in alternatives[0]["metrics"]["per_scenario"] else "base"
    most_resilient = min(alternatives, key=lambda a: a["metrics"]["per_scenario"][combined_key]["max_payment"])

    pv_norm = _norm([a["metrics"]["per_scenario"]["base"]["pv"] for a in alternatives])
    max_norm = _norm([a["metrics"]["per_scenario"][combined_key]["max_payment"] for a in alternatives])
    balanced = min(
        alternatives,
        key=lambda a: 0.5 * pv_norm(a["metrics"]["per_scenario"]["base"]["pv"])
        + 0.5 * max_norm(a["metrics"]["per_scenario"][combined_key]["max_payment"]),
    )

    named = {
        "cheapest": {"label": "הזול ביותר", "alternative": cheapest,
                     "explanation": "מינימום סך תשלומים בערך נוכחי - מתאים למי שלא רגיש לגובה ההחזר החודשי "
                                    "ומתכנן להישאר עם ההלוואה עד הסוף. מוותר: לרוב ההחזר הראשוני לא הנמוך ביותר."},
        "lowest_payment": {"label": "ההחזר הנמוך ביותר", "alternative": lowest_payment,
                            "explanation": "מינימום החזר חודשי ראשוני - מתאים למי שתזרים המזומנים החודשי הוא "
                                           "האילוץ המרכזי. מוותר: לרוב סך התשלומים לאורך התקופה גבוה יותר."},
        "most_resilient": {"label": "העמיד ביותר", "alternative": most_resilient,
                            "explanation": "מינימום ההחזר המקסימלי בתרחיש המשולב (ריבית ואינפלציה עולות יחד) - "
                                           "מתאים למי שרוצה ודאות שההחזר לא יצא משליטה. מוותר: לרוב לא הזול "
                                           "ביותר בתרחיש הבסיס."},
        "balanced": {"label": "המאוזן", "alternative": balanced,
                     "explanation": "ציון משוקלל בין עלות כוללת לעמידות בתרחישי לחץ - פשרה סבירה בלי קיצוניות "
                                    "לאף כיוון."},
    }
    return named


def apply_partial_prepayment(track: Track, extra_cash: float, variant: str) -> Track:
    """סעיף 7.4: פירעון חלקי - שתי תוצאות שונות: קיצור תקופה מול הקטנת החזר."""
    if extra_cash <= 0 or extra_cash >= track.balance:
        raise ValueError("סכום הפירעון החלקי חייב להיות חיובי וקטן מיתרת ההלוואה")
    new_balance = track.balance - extra_cash

    if variant == "reduce_payment":
        return replace(track, balance=new_balance)

    if variant == "shorten_term":
        i = track.rate / 100 / 12
        original_pmt = _SCHEDULE_DISPATCH.get(track.schedule, _spitzer_real)(
            track.balance, [track.rate] * track.months_left, track.months_left
        )[0].payment
        if i < 1e-12:
            new_months = new_balance / original_pmt
        else:
            ratio = 1 - i * new_balance / original_pmt
            if ratio <= 0:
                raise ValueError("סכום הפירעון החלקי גדול מדי לחישוב קיצור תקופה בפרמטרים אלה")
            import math
            new_months = -math.log(ratio) / math.log(1 + i)
        new_months = max(1, round(new_months))
        return replace(track, balance=new_balance, months_left=new_months)

    raise ValueError(f"variant לא מוכר: {variant}")


def shorten_term_only(track: Track, new_months_left: int) -> Track:
    """סעיף 7.4: קיצור תקופה בלבד בלי החלפת בנק (אותה ריבית)."""
    return replace(track, months_left=new_months_left)


def evaluate_refinance_subsets(
    existing_tracks: list, replacement_builder, config: ConfigBundle, rules_cfg: dict,
    scenarios: dict, discount_rate: float, notice_given: bool = False,
) -> list:
    """בודק את כל תתי-הקבוצות של המסלולים הקיימים: מחזור מלא מול כל מחזור
    חלקי אפשרי מול אי-עשייה (סעיף 7.2, בדיקת קבלה 5).

    replacement_builder(refinance_amount, remaining_avg_term_months) -> list[Track]
    בונה את התמהיל החדש עבור הסכום שממוחזר (לרוב שימוש ב-generate_alternatives
    ובחירת הזול ביותר, או תמהיל דיפולטיבי פשוט - הבחירה בידי הקורא).
    """
    results = []
    n = len(existing_tracks)
    all_ids = list(range(n))

    for size in range(0, n + 1):
        for combo in combinations(all_ids, size):
            subset = [existing_tracks[i] for i in combo]
            remainder = [existing_tracks[i] for i in all_ids if i not in combo]

            if subset:
                fee = total_prepayment_fee_for_tracks(subset, config, notice_given)
                if fee["has_missing_data"]:
                    results.append({
                        "subset_ids": [t.id for t in subset], "comparable": False,
                        "reason": "לא ניתן להשוות חלופה זו - חסר נתון בעמלת הפירעון המוקדם",
                    })
                    continue
                refinance_amount = sum(t.balance for t in subset)
                avg_term_months = round(sum(t.months_left for t in subset) / len(subset))
                new_tracks = replacement_builder(refinance_amount, avg_term_months)
            else:
                fee = {"total": 0.0, "has_missing_data": False, "per_track": []}
                new_tracks = []

            household = new_tracks + remainder
            violations = evaluate_mix(household, rules_cfg) if household else []
            metrics = evaluate_alternative(household, scenarios, discount_rate) if household else {
                "per_scenario": {name: {"total_payments": 0, "first_payment": 0, "max_payment": 0, "pv": 0}
                                  for name in scenarios}
            }
            total_cost_pv = metrics["per_scenario"]["base"]["pv"] + (fee["total"] or 0.0)

            results.append({
                "subset_ids": [t.id for t in subset], "is_full_refinance": size == n,
                "is_do_nothing": size == 0, "comparable": True, "fee": fee,
                "violations": violations, "blocked": has_blocking_violation(violations),
                "metrics": metrics, "total_cost_pv": total_cost_pv,
            })

    comparable = [r for r in results if r.get("comparable") and not r.get("blocked")]
    comparable.sort(key=lambda r: r["total_cost_pv"])
    return results, comparable


def refinance_headline(comparable_results: list) -> dict:
    """בדיקת קבלה 7: כשהחיסכון שלילי, הכלי צריך לומר זאת בכותרת ולא
    בהערת שוליים. הפונקציה הזו מחזירה את הנתון הגולמי ('worthwhile') -
    שכבת ה-UI אחראית להציג אותו בבירור בראש המסך, לא רק בפירוט."""
    if not comparable_results:
        return {"has_data": False}
    do_nothing = next((r for r in comparable_results if r.get("is_do_nothing")), None)
    refinance_options = [r for r in comparable_results if not r.get("is_do_nothing")]
    overall_best = comparable_results[0]
    if do_nothing is None or not refinance_options:
        return {"has_data": True, "best_is_do_nothing": do_nothing is overall_best,
                "savings": None, "worthwhile": None}
    best_refinance = min(refinance_options, key=lambda r: r["total_cost_pv"])
    savings = do_nothing["total_cost_pv"] - best_refinance["total_cost_pv"]
    return {
        "has_data": True,
        "best_is_do_nothing": overall_best is do_nothing,
        "best": overall_best,
        "do_nothing": do_nothing,
        "best_refinance": best_refinance,
        "savings": savings,
        "worthwhile": savings > 1e-6,
    }


def wait_for_reset_alternative(track: Track, config: ConfigBundle, new_rate_now: float,
                                discount_rate: float, base_scenario: Scenario) -> dict:
    """סעיף 7.3: מחזור היום עם עמלה מול המתנה לתחנת היציאה ומחזור בפטור."""
    if not track.is_variable() or not track.months_to_next_reset:
        return {"comparable": False, "reason": "רלוונטי רק למסלול משתנה עם תחנת יציאה ידועה"}
    n = track.months_to_next_reset
    if n <= 0 or n >= track.months_left:
        return {"comparable": False, "reason": "אין חלון המתנה משמעותי לפני תחנת היציאה"}

    fee_today = compute_prepayment_fee(track, config)
    if fee_today["has_missing_data"]:
        return {"comparable": False, "reason": "לא ניתן להשוות - חסר נתון בעמלת הפירעון המוקדם"}

    refi_now_track = Track(id=track.id, kind="fixedNonLinked", balance=track.balance, rate=new_rate_now,
                            months_left=track.months_left, original_months=track.months_left,
                            schedule=track.schedule, linked_to_cpi=False)
    rows_refi_now = generate_schedule(refi_now_track, base_scenario)
    pv_refinance_today = fee_today["total"] + present_value(rows_refi_now, discount_rate)

    dispatch = _SCHEDULE_DISPATCH.get(track.schedule, _spitzer_real)
    pre_rate_path = build_rate_path(track, base_scenario)[:n]
    pre_rows = dispatch(track.balance, pre_rate_path, n)
    balance_at_reset = pre_rows[-1].closing
    remaining = track.months_left - n
    post_track = Track(id=track.id, kind="fixedNonLinked", balance=balance_at_reset, rate=new_rate_now,
                        months_left=remaining, original_months=remaining, schedule=track.schedule,
                        linked_to_cpi=False)
    post_rows = generate_schedule(post_track, base_scenario)
    for row in post_rows:
        row.month += n
    combined_rows = pre_rows + post_rows
    if track.linked_to_cpi:
        combined_rows = apply_cpi_linkage(combined_rows, base_scenario.annual_inflation)
    pv_wait = present_value(combined_rows, discount_rate)

    winner = "wait" if pv_wait < pv_refinance_today else "refinance_today"
    return {
        "comparable": True, "months_to_reset": n,
        "pv_refinance_today": pv_refinance_today, "pv_wait": pv_wait,
        "winner": winner, "savings": abs(pv_wait - pv_refinance_today),
    }
