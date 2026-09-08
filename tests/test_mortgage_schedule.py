#!/usr/bin/env python3
"""בדיקות למנוע לוח הסילוקין - כולל בדיקות קבלה 1 ו-2 מסעיף 12 באפיון."""
from __future__ import annotations

import math

import pytest

from mortgage.schedule import Scenario, Track, generate_schedule
from mortgage.metrics import present_value, summarize


BASE_SCENARIO = Scenario(name="בסיס", annual_inflation=0.0, anchor_delta_path=[])


def _spitzer_pmt(balance, annual_rate_pct, months):
    i = annual_rate_pct / 100 / 12
    if i == 0:
        return balance / months
    return balance * i / (1 - (1 + i) ** -months)


def test_spitzer_matches_closed_form_pmt():
    """בדיקת קבלה 1 (גרסה אנליטית): תמהיל ידוע (הלוואת שפיצר סטנדרטית)
    חייב להחזיר תשלום חודשי זהה לנוסחת שפיצר הסטנדרטית עד שקל אחד -
    זו אותה נוסחה שמחשבוני הבנקים משתמשים בה."""
    track = Track(id="t1", kind="fixedNonLinked", balance=1_000_000, rate=5.0,
                  months_left=240, original_months=240, schedule="spitzer")
    rows = generate_schedule(track, BASE_SCENARIO)
    expected_pmt = _spitzer_pmt(1_000_000, 5.0, 240)
    assert rows[0].payment == pytest.approx(expected_pmt, abs=0.01)
    # כל תשלום חודשי זהה (עד שקל, בגלל עיגול היתרה האחרונה)
    for row in rows[:-1]:
        assert row.payment == pytest.approx(expected_pmt, abs=0.01)
    # היתרה מתאפסת בדיוק בתום הלוח
    assert rows[-1].closing == pytest.approx(0.0, abs=0.01)


def test_spitzer_zero_rate_edge_case():
    track = Track(id="t1", kind="fixedNonLinked", balance=120_000, rate=0.0,
                  months_left=120, original_months=120, schedule="spitzer")
    rows = generate_schedule(track, BASE_SCENARIO)
    for row in rows:
        assert row.payment == pytest.approx(1000.0, abs=0.01)
        assert row.interest == pytest.approx(0.0, abs=1e-9)
    assert rows[-1].closing == pytest.approx(0.0, abs=0.01)


def test_equal_principal_has_declining_payment():
    track = Track(id="t1", kind="fixedNonLinked", balance=600_000, rate=4.0,
                  months_left=180, original_months=180, schedule="equalPrincipal")
    rows = generate_schedule(track, BASE_SCENARIO)
    principal_fixed = 600_000 / 180
    for row in rows:
        assert row.principal == pytest.approx(principal_fixed, abs=1.0)
    # ההחזר יורד לאורך הזמן (ריבית על יתרה יורדת)
    assert rows[0].payment > rows[-1].payment
    assert rows[-1].closing == pytest.approx(0.0, abs=0.01)


def test_bullet_schedule_pays_interest_only_then_principal_at_end():
    track = Track(id="t1", kind="bullet", balance=300_000, rate=6.0,
                  months_left=60, original_months=60, schedule="bullet")
    rows = generate_schedule(track, BASE_SCENARIO)
    for row in rows[:-1]:
        assert row.principal == pytest.approx(0.0, abs=1e-9)
    assert rows[-1].principal == pytest.approx(300_000, abs=0.01)
    assert rows[-1].closing == pytest.approx(0.0, abs=0.01)


def test_full_grace_accrues_interest_into_principal():
    track = Track(id="t1", kind="fixedNonLinked", balance=500_000, rate=6.0,
                  months_left=120, original_months=120, schedule="grace",
                  grace_months=12, grace_type="full")
    rows = generate_schedule(track, BASE_SCENARIO)
    grace_rows = rows[:12]
    for row in grace_rows:
        assert row.payment == pytest.approx(0.0, abs=1e-9)
    # היתרה גדלה בתקופת הגרייס המלא
    assert grace_rows[-1].closing > 500_000
    # אחרי הגרייס יש תשלומים רגילים ולוח מסתיים באפס
    assert rows[12].payment > 0
    assert rows[-1].closing == pytest.approx(0.0, abs=0.01)


def test_partial_grace_pays_interest_only_balance_unchanged():
    track = Track(id="t1", kind="fixedNonLinked", balance=500_000, rate=6.0,
                  months_left=120, original_months=120, schedule="grace",
                  grace_months=12, grace_type="partial")
    rows = generate_schedule(track, BASE_SCENARIO)
    grace_rows = rows[:12]
    for row in grace_rows:
        assert row.principal == pytest.approx(0.0, abs=1e-9)
        assert row.payment == pytest.approx(row.interest, abs=1e-6)
    assert grace_rows[-1].closing == pytest.approx(500_000, abs=0.01)


def test_acceptance_2_linked_with_zero_inflation_equals_unlinked():
    """בדיקת קבלה 2: מסלול צמוד בעל אינפלציה 0 מחזיר תוצאה זהה למסלול
    לא צמוד באותה ריבית."""
    linked = Track(id="linked", kind="fixedLinked", balance=800_000, rate=3.5,
                   months_left=200, original_months=200, schedule="spitzer",
                   linked_to_cpi=True)
    unlinked = Track(id="unlinked", kind="fixedNonLinked", balance=800_000, rate=3.5,
                     months_left=200, original_months=200, schedule="spitzer",
                     linked_to_cpi=False)
    scenario_zero_inflation = Scenario(name="בסיס", annual_inflation=0.0, anchor_delta_path=[])
    linked_rows = generate_schedule(linked, scenario_zero_inflation)
    unlinked_rows = generate_schedule(unlinked, scenario_zero_inflation)
    for l_row, u_row in zip(linked_rows, unlinked_rows):
        assert l_row.payment == pytest.approx(u_row.payment, abs=1e-6)
        assert l_row.closing == pytest.approx(u_row.closing, abs=1e-6)


def test_linked_with_positive_inflation_grows_balance_and_interest():
    """הצמדה עם אינפלציה חיובית מגדילה גם את הקרן וגם את הריבית שנגזרת
    ממנה - לא רק 'מוסיפים לריבית' כקיצור דרך."""
    linked = Track(id="linked", kind="fixedLinked", balance=800_000, rate=3.5,
                   months_left=200, original_months=200, schedule="spitzer",
                   linked_to_cpi=True)
    unlinked = Track(id="unlinked", kind="fixedNonLinked", balance=800_000, rate=3.5,
                     months_left=200, original_months=200, schedule="spitzer",
                     linked_to_cpi=False)
    scenario = Scenario(name="אינפלציה", annual_inflation=3.0, anchor_delta_path=[])
    linked_rows = generate_schedule(linked, scenario)
    unlinked_rows = generate_schedule(unlinked, scenario)
    # התשלום הנומינלי במסלול הצמוד גדל עם הזמן, ולא נשאר קבוע כמו הלא-צמוד
    assert linked_rows[-1].payment > linked_rows[0].payment
    assert unlinked_rows[-1].payment == pytest.approx(unlinked_rows[0].payment, abs=0.01)
    # בכל חודש נתון, התשלום הנומינלי הצמוד >= הלא-צמוד (המדד לא שלילי)
    for l_row, u_row in zip(linked_rows, unlinked_rows):
        assert l_row.payment >= u_row.payment - 1e-6


def test_variable_track_reprices_at_reset_under_rate_up_scenario():
    track = Track(id="v1", kind="varNonLinked", balance=500_000, rate=4.0,
                  months_left=120, original_months=120, schedule="spitzer",
                  reset_every_months=36, months_to_next_reset=6)
    scenario = Scenario(name="עליית ריבית", annual_inflation=0.0,
                        anchor_delta_path=[2.0] * 120)
    rows = generate_schedule(track, scenario)
    assert rows[5].rate == pytest.approx(4.0)  # לפני התחנה - הריבית הנוכחית
    assert rows[6].rate == pytest.approx(6.0)  # אחרי התחנה - עוגן+2%
    assert rows[-1].closing == pytest.approx(0.0, abs=0.01)


def test_present_value_and_summary_consistency():
    track = Track(id="t1", kind="fixedNonLinked", balance=1_000_000, rate=5.0,
                  months_left=240, original_months=240, schedule="spitzer")
    rows = generate_schedule(track, BASE_SCENARIO)
    summary = summarize(rows)
    assert summary["total_payments"] == pytest.approx(sum(r.payment for r in rows), abs=0.01)
    pv_at_zero = present_value(rows, 0.0)
    assert pv_at_zero == pytest.approx(summary["total_payments"], abs=0.01)
    pv_at_rate = present_value(rows, 5.0)
    assert pv_at_rate < summary["total_payments"]
