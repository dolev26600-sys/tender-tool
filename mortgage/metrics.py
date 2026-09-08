#!/usr/bin/env python3
"""מדדי פלט על לוח סילוקין (סעיף 4.2 באפיון) - עובד על תוצאת generate_schedule."""
from __future__ import annotations


def present_value(rows: list, annual_discount_rate: float) -> float:
    """ערך נוכחי של כל התשלומים בלוח, בשיעור היוון שנתי נתון (%)."""
    i = annual_discount_rate / 100 / 12
    if abs(i) < 1e-12:
        return sum(row.payment for row in rows)
    return sum(row.payment / (1 + i) ** row.month for row in rows)


def summarize(rows: list) -> dict:
    """החזר ראשון/מקסימלי/ממוצע, סך תשלומים, סך ריבית+הצמדה."""
    if not rows:
        return {
            "first_payment": 0.0, "max_payment": 0.0, "avg_payment": 0.0,
            "total_payments": 0.0, "total_principal": 0.0, "total_interest_and_linkage": 0.0,
        }
    payments = [row.payment for row in rows]
    total_payments = sum(payments)
    total_principal = sum(row.principal for row in rows)
    return {
        "first_payment": payments[0],
        "max_payment": max(payments),
        "avg_payment": total_payments / len(payments),
        "total_payments": total_payments,
        "total_principal": total_principal,
        "total_interest_and_linkage": total_payments - total_principal,
    }


def balance_at(rows: list, month: int) -> float:
    """יתרה לסילוק בסוף חודש נתון (0 אם החודש אחרי סוף הלוח)."""
    for row in rows:
        if row.month == month:
            return row.closing
    return 0.0


def combined_household_schedule(track_rows_map: dict) -> list:
    """מאחד לוחות של כמה מסלולים לתשלום חודשי כולל אחד (לפי אינדקס חודש).

    track_rows_map: {track_id: [Row, ...]}. מסלולים באורכים שונים - מסלול
    שהסתיים תורם 0 מהחודש שאחרי סיומו.
    """
    if not track_rows_map:
        return []
    max_months = max((rows[-1].month if rows else 0) for rows in track_rows_map.values())
    totals = []
    for m in range(1, max_months + 1):
        total_payment = 0.0
        total_interest = 0.0
        total_principal = 0.0
        total_balance = 0.0
        for rows in track_rows_map.values():
            for row in rows:
                if row.month == m:
                    total_payment += row.payment
                    total_interest += row.interest
                    total_principal += row.principal
                    total_balance += row.closing
                    break
        totals.append({
            "month": m, "payment": total_payment, "interest": total_interest,
            "principal": total_principal, "balance": total_balance,
        })
    return totals


def pti_series(monthly_payments: list, monthly_income: float) -> list:
    """שיעור החזר מהכנסה בכל חודש - לא רק בהתחלה (דרישת סעיף 4.2)."""
    if not monthly_income:
        return [None] * len(monthly_payments)
    return [p / monthly_income for p in monthly_payments]


def sensitivity_table(build_rows_fn, rate_deltas: list, inflation_values: list) -> dict:
    """טבלת רגישות דו-ממדית: ריבית מול אינפלציה, תא = סך תשלומים (סעיף 6).

    build_rows_fn(rate_delta, inflation) -> list[Row] (לוח מלא תחת השילוב הזה).
    מחזיר {"rate_deltas":[...], "inflation_values":[...], "grid": [[total,...],...]}
    כאשר grid[i][j] תואם ל-rate_deltas[i] / inflation_values[j].
    """
    grid = []
    for rd in rate_deltas:
        row = []
        for infl in inflation_values:
            rows = build_rows_fn(rd, infl)
            row.append(summarize(rows)["total_payments"])
        grid.append(row)
    return {"rate_deltas": rate_deltas, "inflation_values": inflation_values, "grid": grid}
