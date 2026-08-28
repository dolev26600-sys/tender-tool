#!/usr/bin/env python3
"""
חישובים פיננסיים דטרמיניסטיים להשוואת הצעות משכנתא (לוח סילוקין שפיצר,
נתונים מצרפים לכל הצעה, ומבחן קיצון). בכוונה *לא* משתמשים ב-Claude לחשבון
- כל מה שאפשר לחשב במדויק מחושב בפייתון, ו-Claude (ב-mortgage_comparison.py)
מקבל את המספרים המוכנים ומשתמש בהם רק לניתוח/המלצה איכותית, לא לחישוב.

הערה חשובה: מבחן הקיצון כאן הוא **קירוב פשוט להמחשה**, לא תחליף לחישוב
פיננסי מלא/מבחן רגישות רשמי - יש לציין זאת בכל מקום שהתוצאה מוצגת.
"""
from __future__ import annotations

VARIABLE_TRACK_TYPES = {"variable_prime", "variable_unlinked", "variable_linked_cpi"}


def monthly_payment_shpitzer(principal: float, annual_rate_pct: float, months: int) -> float:
    """לוח סילוקין שפיצר (תשלום חודשי קבוע) - הנוסחה הסטנדרטית להחזר חודשי."""
    if months <= 0 or principal <= 0:
        return 0.0
    r = (annual_rate_pct / 100) / 12
    if r == 0:
        return principal / months
    factor = (1 + r) ** months
    return principal * r * factor / (factor - 1)


def blended_offer_stats(offer: dict) -> dict:
    """מחשב נתונים מצרפים להצעה שלמה (סכום כולל, ריבית ממוצעת משוקללת,
    החזר חודשי התחלתי כולל) מתוך רשימת המסלולים שלה. מעשיר כל מסלול
    ב-initial_monthly_payment."""
    tracks = offer.get("tracks", [])
    total_amount = sum(t.get("amount", 0) for t in tracks)
    total_monthly = 0.0
    weighted_rate_sum = 0.0
    max_period = 0
    enriched_tracks = []

    for t in tracks:
        amount = t.get("amount", 0)
        rate = t.get("annual_interest_rate_pct", 0)
        months = t.get("period_months", 0)
        payment = monthly_payment_shpitzer(amount, rate, months)
        total_monthly += payment
        weighted_rate_sum += rate * amount
        max_period = max(max_period, months)
        enriched_tracks.append({**t, "initial_monthly_payment": round(payment, 2)})

    blended_rate = (weighted_rate_sum / total_amount) if total_amount else 0.0

    return {
        "bank_name": offer.get("bank_name", "?"),
        "total_amount": round(total_amount, 2),
        "initial_total_monthly_payment": round(total_monthly, 2),
        "blended_annual_interest_rate_pct": round(blended_rate, 3),
        "longest_track_period_months": max_period,
        "tracks": enriched_tracks,
    }


def stress_test_stats(
    tracks: list[dict],
    *,
    rate_increase_pct: float = 2.0,
    cpi_annual_pct: float = 3.0,
) -> dict:
    """
    קירוב פשוט לתרחיש קיצון: מסלולים בריבית משתנה מקבלים תוספת של
    rate_increase_pct לריבית, ומסלולים צמודי מדד מקבלים תוספת חד-פעמית
    של cpi_annual_pct ליתרת הקרן (כאילו עברה שנה אחת של אינפלציה).
    זו הערכה גסה למטרות השוואה בין הצעות - לא תחזית מדויקת.
    """
    stressed_tracks = []
    total_monthly = 0.0

    for t in tracks:
        amount = t.get("amount", 0)
        rate = t.get("annual_interest_rate_pct", 0)
        months = t.get("period_months", 0)

        if t.get("track_type") in VARIABLE_TRACK_TYPES:
            rate = rate + rate_increase_pct
        if t.get("linkage") == "cpi_linked":
            amount = amount * (1 + cpi_annual_pct / 100)

        payment = monthly_payment_shpitzer(amount, rate, months)
        total_monthly += payment
        stressed_tracks.append({**t, "stressed_monthly_payment": round(payment, 2)})

    return {
        "rate_increase_pct": rate_increase_pct,
        "cpi_annual_pct": cpi_annual_pct,
        "stressed_total_monthly_payment": round(total_monthly, 2),
        "tracks": stressed_tracks,
    }
