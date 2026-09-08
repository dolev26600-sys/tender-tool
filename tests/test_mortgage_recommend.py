#!/usr/bin/env python3
"""בדיקות למנוע ההמלצות - כולל בדיקות קבלה 4, 5, 6, 7 מסעיף 12."""
from __future__ import annotations

from dataclasses import replace

import pytest

from mortgage.config import load_config
from mortgage.recommend import (
    evaluate_refinance_subsets, generate_alternatives, rank_alternatives,
    refinance_headline, wait_for_reset_alternative,
)
from mortgage.schedule import Scenario, Track


@pytest.fixture
def config():
    return load_config()


BASE_SCENARIOS = {"base": Scenario(name="בסיס", annual_inflation=0.0, anchor_delta_path=[])}


def test_acceptance_4_blocking_mix_never_appears_in_alternatives(config):
    """בדיקת קבלה 4: תמהיל שמפר כלל חוסם (כאן: 100% פריים, בעוד
    minFixedShare=0.3333) לא מופיע בהמלצות באף תרחיש."""
    rules_cfg = {"minFixedShare": 0.3333, "maxVariableShare": 0.6667, "maxPrimeShare": 0.6667}
    alternatives = generate_alternatives(
        amount=1_000_000, term_years=20, config=config, rules_cfg=rules_cfg,
        scenarios=BASE_SCENARIOS, discount_rate=4.0,
        kinds=("fixedNonLinked", "prime", "varNonLinked"), share_step=0.5,
    )
    assert alternatives  # יש לפחות תמהילים חוקיים
    for alt in alternatives:
        assert alt["shares"]["fixedNonLinked"] >= 0.3333 - 1e-9, "תמהיל חוסם הגיע לתוצאה"


def test_generate_alternatives_ranks_four_named_options(config):
    rules_cfg = {"minFixedShare": 0.0, "maxVariableShare": 1.0, "maxPrimeShare": 1.0}
    scenarios = {
        "base": Scenario(name="בסיס", annual_inflation=2.0, anchor_delta_path=[]),
        "combined": Scenario(name="משולב", annual_inflation=5.0, anchor_delta_path=[3.0] * 240),
    }
    alternatives = generate_alternatives(
        amount=1_000_000, term_years=20, config=config, rules_cfg=rules_cfg,
        scenarios=scenarios, discount_rate=4.0,
        kinds=("fixedNonLinked", "prime", "varNonLinked"), share_step=0.5,
    )
    ranked = rank_alternatives(alternatives)
    assert set(ranked.keys()) == {"cheapest", "lowest_payment", "most_resilient", "balanced"}
    for entry in ranked.values():
        assert "explanation" in entry and entry["explanation"]


def test_acceptance_5_partial_refinance_beats_full_and_do_nothing(config):
    """בדיקת קבלה 5: מחזור חלקי מנצח מוצג גם כשמחזור מלא נבדק ונדחה.

    בונים משכנתא משני מסלולים: פריים יקר (9%, ללא עמלת היוון בכלל) ו-קבועה
    זולה (2%, מתחת לממוצע - עמלת היוון = 0). המחליף הזמין הוא 4% קבוע.
    מחזור המסלול היקר בלבד אמור לנצח: המסלול הזול כבר טוב מהחלופה, ואילו
    מחזור אותו יגרור ריבית גבוהה יותר בלי שום הצדקה.
    """
    expensive_prime = Track(id="prime_expensive", kind="prime", balance=400_000, rate=9.0,
                            months_left=240, original_months=240, schedule="spitzer")
    cheap_fixed = Track(id="fixed_cheap", kind="fixedNonLinked", balance=600_000, rate=2.0,
                        months_left=240, original_months=240, schedule="spitzer")
    existing = [expensive_prime, cheap_fixed]

    def replacement_builder(amount, avg_term_months):
        return [Track(id="new_fixed", kind="fixedNonLinked", balance=amount, rate=4.0,
                      months_left=avg_term_months, original_months=avg_term_months, schedule="spitzer")]

    all_results, comparable = evaluate_refinance_subsets(
        existing, replacement_builder, config,
        rules_cfg={"minFixedShare": 0.0, "maxVariableShare": 1.0, "maxPrimeShare": 1.0},
        scenarios=BASE_SCENARIOS, discount_rate=4.0,
    )
    assert comparable, "אמורות להיות חלופות ברות-השוואה"
    best = comparable[0]
    assert not best["is_do_nothing"], "אי-עשייה לא אמורה לנצח בתרחיש הזה"
    assert not best["is_full_refinance"], "מחזור מלא לא אמור לנצח - הוא ממחזר גם את המסלול הזול שלא כדאי לגעת בו"
    assert best["subset_ids"] == ["prime_expensive"]


def test_acceptance_6_wait_for_reset_shown_when_preferable(config):
    """בדיקת קבלה 6: חלופת ההמתנה לתחנה מוצגת כשהיא עדיפה.

    מסלול משתנה עם תחנת יציאה קרובה (6 חודשים) וריבית חוזה גבוהה יחסית -
    עמלת ההיוון מחושבת רק על 6 החודשים הקרובים ולכן קטנה, בעוד שהמתנה
    חוסכת אותה לגמרי. במקרה הזה ההמתנה אמורה לנצח.
    """
    track = Track(id="v1", kind="varNonLinked", balance=800_000, rate=7.0,
                  months_left=120, original_months=120, schedule="spitzer",
                  reset_every_months=36, months_to_next_reset=6)
    base_scenario = Scenario(name="בסיס", annual_inflation=0.0, anchor_delta_path=[])
    result = wait_for_reset_alternative(track, config, new_rate_now=5.0, discount_rate=4.0,
                                        base_scenario=base_scenario)
    assert result["comparable"] is True
    assert result["winner"] == "wait"
    assert result["pv_wait"] < result["pv_refinance_today"]


def test_wait_for_reset_not_comparable_when_no_reset_window():
    fixed = Track(id="f1", kind="fixedNonLinked", balance=500_000, rate=5.0,
                  months_left=120, original_months=120, schedule="spitzer")
    result = wait_for_reset_alternative(fixed, load_config(), new_rate_now=4.0,
                                        discount_rate=4.0, base_scenario=Scenario("בסיס"))
    assert result["comparable"] is False


def test_acceptance_7_negative_savings_flagged_clearly(config):
    """בדיקת קבלה 7: כשהחיסכון שלילי, הנתון הגולמי (worthwhile=False)
    זמין ל-UI כדי להציג זאת בכותרת. בונים הלוואה קיימת זולה מאוד (2%)
    מול מחליף יקר בהרבה (6%) - אין שום סיבה טובה למחזר."""
    cheap_existing = Track(id="cheap", kind="fixedNonLinked", balance=500_000, rate=2.0,
                           months_left=180, original_months=180, schedule="spitzer")

    def expensive_replacement_builder(amount, avg_term_months):
        return [Track(id="new", kind="fixedNonLinked", balance=amount, rate=6.0,
                      months_left=avg_term_months, original_months=avg_term_months, schedule="spitzer")]

    _, comparable = evaluate_refinance_subsets(
        [cheap_existing], expensive_replacement_builder, config,
        rules_cfg={"minFixedShare": 0.0, "maxVariableShare": 1.0, "maxPrimeShare": 1.0},
        scenarios=BASE_SCENARIOS, discount_rate=4.0,
    )
    headline = refinance_headline(comparable)
    assert headline["has_data"] is True
    assert headline["best_is_do_nothing"] is True
    assert headline["worthwhile"] is False
    assert headline["savings"] < 0
