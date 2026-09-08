#!/usr/bin/env python3
"""עמלת פירעון מוקדם על כל רכיביה (סעיף 4.3 באפיון).

הפלט הוא תמיד פירוט רכיבים, לא מספר יחיד: עמלת היוון, הנחה, עמלה
תפעולית, עמלת אי-הודעה מוקדמת (עם טיפ ביטול), הפרשי הצמדה, ופטור בתחנת
יציאה. כל רכיב שאין לו נתון מלא בתצורה מסומן "חסר נתון" (missing=True)
ולא מוערך בשקט - וסך העמלה (total) הוא None כל עוד יש רכיב חסר.
"""
from __future__ import annotations

from .config import ConfigBundle, MissingConfigError
from .schedule import Track, _SCHEDULE_DISPATCH, _spitzer_real

_TERM_BUCKETS = [("0-2", 0.0, 2.0), ("2-5", 2.0, 5.0), ("5-10", 5.0, 10.0),
                 ("10-15", 10.0, 15.0), ("15-20", 15.0, 20.0), ("20-30", 20.0, 30.0)]


def _average_rate_for_remaining(avg_table: dict, remaining_years: float):
    for key, lo, hi in _TERM_BUCKETS:
        if (lo == 0 and lo <= remaining_years <= hi) or (lo < remaining_years <= hi):
            if key in avg_table:
                return key, avg_table[key]
            return key, None
    return None, None


def _discount_for_remaining(fees_cfg: dict, remaining_years: float) -> float:
    entries = (fees_cfg.get("capitalization") or {}).get("discountsByRemainingTerm") or []
    for entry in entries:
        key = entry["remainingYears"]
        if key.endswith("+"):
            lo = float(key[:-1])
            if remaining_years >= lo:
                return entry["discount"]
        else:
            lo, hi = key.split("-")
            if float(lo) <= remaining_years <= float(hi):
                return entry["discount"]
    return 0.0


def capitalization_fee(track: Track, config: ConfigBundle) -> dict:
    """רכיב עמלת ההיוון (הליבה של סעיף 4.3, רכיבים 1-2).

    רק כשריבית החוזה גבוהה מהריבית הממוצעת המפורסמת *לתקופה שנותרה*.
    בוחרים את שכבת הריבית הממוצעת לפי מסלולים משתנים - התקופה הרלוונטית
    היא עד התחנה הקרובה, לא כל יתרת חיי ההלוואה (ראה feeApplicability).
    """
    fees_cfg = config.fees
    applicability = (fees_cfg.get("feeApplicability") or {}).get(track.kind, "full")

    if applicability == "none":
        return {"applicable": False, "amount": 0.0, "missing": False,
                "reason": "מסלול פטור מעמלת היוון (לפי הגדרת סוג המסלול בתצורה)"}

    if applicability == "toNextReset":
        if not track.months_to_next_reset or track.months_to_next_reset <= 0:
            return {"applicable": False, "amount": 0.0, "missing": False,
                    "reason": "פטור מעמלת היוון - נמצא בתחנת יציאה"}
        term_months = track.months_to_next_reset
    else:
        term_months = track.months_left

    avg_table_key = "fixedLinked" if track.linked_to_cpi else "fixedNonLinked"
    avg_table = (config.rates.get("boiAverageRates") or {}).get(avg_table_key)
    if not avg_table:
        return {"applicable": None, "amount": None, "missing": True,
                "reason": f"חסר נתון: אין טבלת ריבית ממוצעת ({avg_table_key}) בתצורת rates.json"}

    remaining_years = term_months / 12
    bucket_key, avg_rate = _average_rate_for_remaining(avg_table, remaining_years)
    if avg_rate is None:
        return {"applicable": None, "amount": None, "missing": True,
                "reason": f"חסר נתון: אין ריבית ממוצעת פרסומית לתקופה הנותרת ({remaining_years:.1f} שנים)"}

    if track.rate <= avg_rate:
        return {"applicable": True, "amount": 0.0, "missing": False, "avg_rate": avg_rate,
                "bucket": bucket_key,
                "reason": f"ריבית החוזה ({track.rate:.2f}%) אינה גבוהה מהריבית הממוצעת "
                          f"הפרסומית לתקופה ({avg_rate:.2f}%) - אין עמלת היוון"}

    dispatch = _SCHEDULE_DISPATCH.get(track.schedule, _spitzer_real)
    contract_rate_path = [track.rate] * term_months
    avg_rate_path = [avg_rate] * term_months
    contract_rows = dispatch(track.balance, contract_rate_path, term_months)
    avg_rows = dispatch(track.balance, avg_rate_path, term_months)

    i_avg = avg_rate / 100 / 12
    diff_pv = sum(
        (c.payment - a.payment) / (1 + i_avg) ** c.month
        for c, a in zip(contract_rows, avg_rows)
    )
    diff_pv = max(diff_pv, 0.0)

    discount = _discount_for_remaining(fees_cfg, remaining_years)
    amount = diff_pv * (1 - discount)

    return {
        "applicable": True, "missing": False,
        "before_discount": diff_pv, "discount_rate": discount, "amount": amount,
        "avg_rate": avg_rate, "bucket": bucket_key,
        "reason": f"מחושב לפי טבלת ריביות ממוצעות מתאריך {config.rates.get('updatedAt')} "
                  f"(שכבה: {avg_table_key} / {bucket_key} שנים)",
    }


def _operational_fee(config: ConfigBundle) -> dict:
    value = config.fees.get("operationalFee")
    if value is None:
        return {"amount": None, "missing": True, "reason": "חסר נתון: עמלה תפעולית לא הוגדרה בתצורה"}
    return {"amount": float(value), "missing": False,
            "reason": f"עמלה תפעולית קבועה, מתצורה מתאריך {config.fees.get('updatedAt')}"}


def _no_notice_fee(track: Track, config: ConfigBundle, notice_given: bool) -> dict:
    cfg = config.fees.get("noNoticeFee")
    if not cfg or "days" not in cfg:
        return {"amount": None, "missing": True, "reason": "חסר נתון: פרמטר ימי הודעה מוקדמת לא הוגדר בתצורה"}
    days = cfg["days"]
    daily_rate = track.rate / 100 / 365
    full_amount = track.balance * daily_rate * days
    amount = 0.0 if notice_given else full_amount
    return {
        "amount": amount, "missing": False, "days": days, "waivable": True,
        "full_amount_if_not_waived": full_amount,
        "reason": (f"נמנעה - ניתנה הודעה מראש {days} ימים" if notice_given else
                   f"ריבית {days} ימים על היתרה. טיפ: אפשר להימנע מהעמלה הזו "
                   f"({full_amount:,.0f} ש\"ח) ע\"י הודעה מראש {days} ימים לבנק."),
    }


def _indexation_diff(track: Track, config: ConfigBundle) -> dict:
    if not track.linked_to_cpi:
        return {"applies": False, "amount": 0.0, "missing": False}
    cfg = config.fees.get("indexationDiff") or {}
    lag_days = cfg.get("lagDays")
    if lag_days is None:
        return {"applies": True, "amount": None, "missing": True,
                "reason": "חסר נתון: פרמטר פער ההצמדה (lagDays) לא הוגדר בתצורה עבור מסלול צמוד"}
    monthly_inflation_assumption = cfg.get("assumedMonthlyRate")
    if monthly_inflation_assumption is None:
        return {"applies": True, "amount": None, "missing": True,
                "reason": "חסר נתון: הנחת המדד החודשית (assumedMonthlyRate) לא הוגדרה בתצורה"}
    amount = track.balance * monthly_inflation_assumption * (lag_days / 30)
    return {"applies": True, "amount": amount, "missing": False,
            "reason": f"הפרש הצמדה משוער בגין {lag_days} ימי פיגור בפרסום המדד"}


def compute_prepayment_fee(track: Track, config: ConfigBundle, notice_given: bool = False) -> dict:
    """מחזיר פירוט מלא של כל רכיבי עמלת הפירעון המוקדם למסלול נתון,
    בתוספת סכום כולל (או None אם יש רכיב עם נתון חסר - סעיף 12 בדיקה 8)."""
    components = {
        "capitalization": capitalization_fee(track, config),
        "operational": _operational_fee(config),
        "noNotice": _no_notice_fee(track, config, notice_given),
        "indexationDiff": _indexation_diff(track, config),
    }
    has_missing = any(c.get("missing") for c in components.values())
    total = None
    if not has_missing:
        total = sum(c.get("amount") or 0.0 for c in components.values())
    return {
        "track_id": track.id, "components": components, "total": total,
        "has_missing_data": has_missing,
        "as_of": f"מחושב לפי טבלת ריביות ותצורת עמלות מתאריך {config.fees.get('updatedAt')}",
    }


def total_prepayment_fee_for_tracks(tracks: list, config: ConfigBundle, notice_given: bool = False) -> dict:
    per_track = [compute_prepayment_fee(t, config, notice_given) for t in tracks]
    has_missing = any(p["has_missing_data"] for p in per_track)
    total = None if has_missing else sum(p["total"] for p in per_track)
    return {"per_track": per_track, "total": total, "has_missing_data": has_missing}
