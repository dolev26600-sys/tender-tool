#!/usr/bin/env python3
"""מנוע הכללים (סעיף 5 באפיון) - בודק תמהיל מוצע מול rules.json ומחזיר
רשימת הפרות עם חומרה: blocking (חוסם) / warning (אזהרה) / info (מידע).

תמהיל שמפר כלל blocking לא נכנס לרשימת ההמלצות (ראה recommend.py ובדיקת
קבלה 4). אין שום סף מקודד כאן - כל הסף מגיע מ-rules_cfg (תוצר
config.effective_rules).
"""
from __future__ import annotations

from .schedule import Track, FIXED_KINDS, VARIABLE_KINDS


def mix_shares(tracks: list) -> dict:
    total = sum(t.balance for t in tracks)
    if total <= 0:
        return {"fixed": 0.0, "variable": 0.0, "prime": 0.0}
    fixed = sum(t.balance for t in tracks if t.kind in FIXED_KINDS) / total
    variable = sum(t.balance for t in tracks if t.kind in VARIABLE_KINDS) / total
    prime = sum(t.balance for t in tracks if t.kind == "prime") / total
    return {"fixed": fixed, "variable": variable, "prime": prime}


def evaluate_mix(
    tracks: list,
    rules_cfg: dict,
    term_years: float = None,
    ltv: float = None,
    property_type: str = None,
    pti: float = None,
) -> list:
    """מחזיר רשימת dict הפרות: {"severity","rule","message"}.
    רשימה ריקה = התמהיל תקין מול הכללים שסופקו."""
    if not rules_cfg:
        return [{"severity": "blocking", "rule": "config", "message": "חסר נתון: אין כללי רגולציה מוגדרים"}]

    violations = []
    shares = mix_shares(tracks)

    if "minFixedShare" in rules_cfg and shares["fixed"] < rules_cfg["minFixedShare"] - 1e-9:
        violations.append({
            "severity": "blocking", "rule": "minFixedShare",
            "message": f"שיעור המסלולים בריבית קבועה ({shares['fixed']:.1%}) נמוך מהמינימום "
                       f"הנדרש ({rules_cfg['minFixedShare']:.1%})",
        })

    if "maxVariableShare" in rules_cfg and shares["variable"] > rules_cfg["maxVariableShare"] + 1e-9:
        violations.append({
            "severity": "blocking", "rule": "maxVariableShare",
            "message": f"שיעור המסלולים בריבית משתנה ({shares['variable']:.1%}) חורג מהמקסימום "
                       f"המותר ({rules_cfg['maxVariableShare']:.1%})",
        })

    if "maxPrimeShare" in rules_cfg and shares["prime"] > rules_cfg["maxPrimeShare"] + 1e-9:
        violations.append({
            "severity": "blocking", "rule": "maxPrimeShare",
            "message": f"שיעור מסלול הפריים ({shares['prime']:.1%}) חורג מהמקסימום "
                       f"המותר ({rules_cfg['maxPrimeShare']:.1%})",
        })

    if term_years is not None and "maxTermYears" in rules_cfg and term_years > rules_cfg["maxTermYears"] + 1e-9:
        violations.append({
            "severity": "blocking", "rule": "maxTermYears",
            "message": f"תקופת ההלוואה ({term_years:.0f} שנים) חורגת מהמקסימום "
                       f"המותר ({rules_cfg['maxTermYears']} שנים)",
        })

    if ltv is not None and property_type is not None:
        cap = (rules_cfg.get("ltvCaps") or {}).get(property_type)
        if cap is not None and ltv > cap + 1e-9:
            violations.append({
                "severity": "blocking", "rule": "ltvCap",
                "message": f"שיעור המימון ({ltv:.1%}) חורג מהמקסימום המותר לסוג הנכס "
                           f"({property_type}: {cap:.1%})",
            })

    if pti is not None:
        pti_max = rules_cfg.get("ptiMax")
        pti_warn = rules_cfg.get("ptiWarn")
        if pti_max is not None and pti > pti_max + 1e-9:
            violations.append({
                "severity": "blocking", "rule": "ptiMax",
                "message": f"שיעור ההחזר מהכנסה ({pti:.1%}) חורג מהמקסימום המותר ({pti_max:.1%})",
            })
        elif pti_warn is not None and pti > pti_warn + 1e-9:
            violations.append({
                "severity": "warning", "rule": "ptiWarn",
                "message": f"שיעור ההחזר מהכנסה ({pti:.1%}) גבוה מסף האזהרה ({pti_warn:.1%})",
            })

    return violations


def has_blocking_violation(violations: list) -> bool:
    return any(v["severity"] == "blocking" for v in violations)
