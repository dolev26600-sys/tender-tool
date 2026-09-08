#!/usr/bin/env python3
"""בדיקות למנוע עמלת הפירעון המוקדם - כולל בדיקות קבלה 3 ו-8 מסעיף 12."""
from __future__ import annotations

import copy

import pytest

from mortgage.config import ConfigBundle, Freshness, load_config
from mortgage.fees import compute_prepayment_fee
from mortgage.schedule import Track


@pytest.fixture
def config() -> ConfigBundle:
    return load_config()


def _dummy_freshness():
    return Freshness(updated_at="2026-09-08", days_old=0, is_stale=False, label="")


def test_acceptance_3_no_fee_when_contract_rate_below_average(config):
    """בדיקת קבלה 3: עמלת היוון על מסלול שריביתו נמוכה מהממוצע מחזירה אפס."""
    low_rate_track = Track(id="t1", kind="fixedNonLinked", balance=500_000, rate=1.0,
                            months_left=180, original_months=180, schedule="spitzer")
    result = compute_prepayment_fee(low_rate_track, config)
    assert result["components"]["capitalization"]["amount"] == 0.0
    assert result["components"]["capitalization"]["applicable"] is True


def test_capitalization_fee_positive_when_contract_rate_above_average(config):
    high_rate_track = Track(id="t1", kind="fixedNonLinked", balance=500_000, rate=9.0,
                            months_left=180, original_months=180, schedule="spitzer")
    result = compute_prepayment_fee(high_rate_track, config)
    cap = result["components"]["capitalization"]
    assert cap["applicable"] is True
    assert cap["amount"] > 0


def test_prime_track_never_has_capitalization_fee(config):
    prime_track = Track(id="t1", kind="prime", balance=300_000, rate=5.5,
                        months_left=180, original_months=180, schedule="spitzer")
    result = compute_prepayment_fee(prime_track, config)
    assert result["components"]["capitalization"]["amount"] == 0.0
    assert result["components"]["capitalization"]["applicable"] is False


def test_variable_track_exempt_exactly_at_reset_station(config):
    track = Track(id="t1", kind="varNonLinked", balance=400_000, rate=9.0,
                  months_left=180, original_months=180, schedule="spitzer",
                  reset_every_months=36, months_to_next_reset=0)
    result = compute_prepayment_fee(track, config)
    assert result["components"]["capitalization"]["amount"] == 0.0
    assert "תחנת" in result["components"]["capitalization"]["reason"]


def test_acceptance_8_missing_config_field_produces_visible_message(config):
    """בדיקת קבלה 8: שדה תצורה חסר מייצר הודעה גלויה ולא ערך שקט.

    fees.json לדוגמה משאיר בכוונה את indexationDiff.lagDays לא מוגדר -
    מוודאים שזה מסומן missing=True עם הודעה, ושסך העמלה (total) הופך
    ל-None (לא מוערך בשקט) כשיש רכיב חסר במסלול צמוד."""
    linked_track = Track(id="t1", kind="fixedLinked", balance=500_000, rate=2.0,
                         months_left=180, original_months=180, schedule="spitzer",
                         linked_to_cpi=True)
    result = compute_prepayment_fee(linked_track, config)
    indexation = result["components"]["indexationDiff"]
    assert indexation["missing"] is True
    assert "חסר נתון" in indexation["reason"]
    assert result["has_missing_data"] is True
    assert result["total"] is None


def test_missing_average_rate_table_is_reported_not_defaulted(config):
    stripped_rates = copy.deepcopy(config.rates)
    del stripped_rates["boiAverageRates"]["fixedNonLinked"]
    stripped_config = ConfigBundle(
        rates=stripped_rates, rules=config.rules, fees=config.fees,
        rates_freshness=_dummy_freshness(), rules_freshness=_dummy_freshness(),
        fees_freshness=_dummy_freshness(),
    )
    track = Track(id="t1", kind="fixedNonLinked", balance=500_000, rate=9.0,
                 months_left=180, original_months=180, schedule="spitzer")
    result = compute_prepayment_fee(track, stripped_config)
    cap = result["components"]["capitalization"]
    assert cap["missing"] is True
    assert "חסר נתון" in cap["reason"]
    assert result["total"] is None


def test_no_notice_fee_waived_with_advance_notice(config):
    track = Track(id="t1", kind="fixedNonLinked", balance=500_000, rate=1.0,
                 months_left=180, original_months=180, schedule="spitzer")
    without_notice = compute_prepayment_fee(track, config, notice_given=False)
    with_notice = compute_prepayment_fee(track, config, notice_given=True)
    assert without_notice["components"]["noNotice"]["amount"] > 0
    assert with_notice["components"]["noNotice"]["amount"] == 0.0
