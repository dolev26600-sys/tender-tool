#!/usr/bin/env python3
"""בדיקות לשכבת התצורה - רעננות (45 יום), מיזוג כללי מחזור, שדה חסר."""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from mortgage.config import MissingConfigError, check_freshness, effective_rules, load_config, require


def test_load_sample_config_succeeds():
    config = load_config()
    assert config.rates["primeRate"] > 0
    assert config.rules["newLoan"]["maxTermYears"] == 30
    assert config.fees["operationalFee"] >= 0


def test_freshness_not_stale_when_recent():
    data = {"updatedAt": date.today().isoformat()}
    freshness = check_freshness(data)
    assert freshness.is_stale is False
    assert freshness.days_old == 0


def test_freshness_stale_after_45_days():
    old_date = (date.today() - timedelta(days=46)).isoformat()
    data = {"updatedAt": old_date}
    freshness = check_freshness(data)
    assert freshness.is_stale is True
    assert freshness.days_old == 46


def test_freshness_missing_updated_at_is_flagged():
    freshness = check_freshness({})
    assert freshness.is_stale is True
    assert freshness.updated_at is None


def test_effective_rules_new_loan():
    rules_cfg = {"newLoan": {"minFixedShare": 0.33, "maxTermYears": 30}}
    result = effective_rules(rules_cfg, "newLoan")
    assert result == {"minFixedShare": 0.33, "maxTermYears": 30}


def test_effective_rules_refinance_inherits_and_overrides():
    rules_cfg = {
        "newLoan": {"minFixedShare": 0.33, "maxTermYears": 30, "ltvCaps": {"singleHome": 0.75}},
        "refinanceInternal": {"maxTermYears": 25, "ltvCaps": {"singleHome": 0.70}},
    }
    result = effective_rules(rules_cfg, "refinanceInternal")
    assert result["minFixedShare"] == 0.33  # ירושה מ-newLoan
    assert result["maxTermYears"] == 25  # נדרס
    assert result["ltvCaps"]["singleHome"] == 0.70  # נדרס גם בתת-מפתח


def test_effective_rules_missing_new_loan_raises():
    with pytest.raises(MissingConfigError):
        effective_rules({}, "newLoan")


def test_require_missing_key_raises_with_context():
    with pytest.raises(MissingConfigError):
        require({"a": {"b": 1}}, "a", "c", error_context="בדיקה")


def test_require_present_key_returns_value():
    assert require({"a": {"b": 1}}, "a", "b") == 1
