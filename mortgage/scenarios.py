#!/usr/bin/env python3
"""תרחישי לחץ (סעיף 6 באפיון) - בסיס / עליית ריבית / אינפלציה גבוהה / משולב.

כל הפרמטרים (מדרוג עליית הריבית, הנחת האינפלציה הגבוהה) מגיעים כארגומנטים
ניתנים להגדרה - לא מקודדים כברירת מחדל שרירותית עמוק בקוד. קורא המנוע
(שכבת ה-UI) אחראי להעביר את ההנחות שהוגדרו בתצורה/ע"י המשתמש.
"""
from __future__ import annotations

from .schedule import Scenario

HORIZON_MONTHS_DEFAULT = 360


def _step_path(steps: list, ramp_months: int, horizon_months: int) -> list:
    path = []
    for m in range(1, horizon_months + 1):
        stage = min(len(steps), (m - 1) // ramp_months + 1)
        path.append(steps[stage - 1] if stage >= 1 else 0.0)
    return path


def build_standard_scenarios(
    base_inflation: float,
    high_inflation: float,
    rate_up_steps: list,
    ramp_months: int = 12,
    horizon_months: int = HORIZON_MONTHS_DEFAULT,
) -> dict:
    """בונה את ארבעת תרחישי הלחץ הסטנדרטיים (סעיף 6):
    בסיס / עליית ריבית / אינפלציה גבוהה / משולב.

    rate_up_steps: למשל [1.0, 2.0, 3.0] - עלייה מדורגת של העוגן ב-1%/2%/3%
    לאורך שלבים בני ramp_months חודשים כל אחד.
    """
    zero_path = [0.0] * horizon_months
    rate_up_path = _step_path(rate_up_steps, ramp_months, horizon_months)
    return {
        "base": Scenario(name="בסיס", annual_inflation=base_inflation, anchor_delta_path=zero_path),
        "rate_up": Scenario(name="עליית ריבית", annual_inflation=base_inflation, anchor_delta_path=rate_up_path),
        "inflation_up": Scenario(name="אינפלציה גבוהה", annual_inflation=high_inflation, anchor_delta_path=zero_path),
        "combined": Scenario(name="משולב (ריבית + אינפלציה)", annual_inflation=high_inflation, anchor_delta_path=rate_up_path),
    }
