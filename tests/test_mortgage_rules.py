#!/usr/bin/env python3
"""בדיקות למנוע הכללים (סעיף 5)."""
from __future__ import annotations

from mortgage.rules import evaluate_mix, has_blocking_violation, mix_shares
from mortgage.schedule import Track

RULES = {
    "minFixedShare": 0.3333,
    "maxVariableShare": 0.6667,
    "maxPrimeShare": 0.6667,
    "maxTermYears": 30,
    "ltvCaps": {"singleHome": 0.75},
    "ptiWarn": 0.35,
    "ptiMax": 0.40,
}


def _track(kind, balance):
    return Track(id=kind, kind=kind, balance=balance, rate=5.0, months_left=240, original_months=240)


def test_mix_shares_computed_correctly():
    tracks = [_track("fixedNonLinked", 400_000), _track("prime", 600_000)]
    shares = mix_shares(tracks)
    assert shares["fixed"] == 0.4
    assert shares["prime"] == 0.6


def test_valid_mix_has_no_violations():
    tracks = [_track("fixedNonLinked", 400_000), _track("prime", 600_000)]
    violations = evaluate_mix(tracks, RULES, term_years=25, ltv=0.6, property_type="singleHome")
    assert violations == []


def test_min_fixed_share_violation_is_blocking():
    tracks = [_track("prime", 1_000_000)]
    violations = evaluate_mix(tracks, RULES)
    assert has_blocking_violation(violations)
    assert any(v["rule"] == "minFixedShare" for v in violations)


def test_ltv_cap_violation_is_blocking():
    tracks = [_track("fixedNonLinked", 1_000_000)]
    violations = evaluate_mix(tracks, RULES, ltv=0.8, property_type="singleHome")
    assert has_blocking_violation(violations)
    assert any(v["rule"] == "ltvCap" for v in violations)


def test_pti_warning_is_not_blocking_but_pti_max_is():
    tracks = [_track("fixedNonLinked", 400_000), _track("prime", 600_000)]
    warn_violations = evaluate_mix(tracks, RULES, pti=0.37)
    assert not has_blocking_violation(warn_violations)
    assert any(v["rule"] == "ptiWarn" and v["severity"] == "warning" for v in warn_violations)

    block_violations = evaluate_mix(tracks, RULES, pti=0.45)
    assert has_blocking_violation(block_violations)
    assert any(v["rule"] == "ptiMax" for v in block_violations)


def test_missing_rules_config_is_blocking_not_silent():
    violations = evaluate_mix([_track("fixedNonLinked", 100_000)], {})
    assert has_blocking_violation(violations)
    assert "חסר נתון" in violations[0]["message"]
