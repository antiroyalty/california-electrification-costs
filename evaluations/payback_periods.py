from __future__ import annotations

from typing import Literal, Tuple


SavingsType = Literal["with_solar", "scenario_only", "no_savings"]


def choose_annual_savings(
    baseline_annual_cost: float,
    scenario_annual_cost: float,
    scenario_solar_annual_cost: float,
) -> Tuple[float, SavingsType]:
    """Select the annual savings value and its type.

    Preference order:
    1) with_solar if positive
    2) scenario_only if positive
    3) no_savings (return a tiny epsilon to avoid divide‑by‑zero in callers)
    """
    try:
        b = float(baseline_annual_cost)
        s = float(scenario_annual_cost)
        ss = float(scenario_solar_annual_cost)
    except Exception:
        return 0.01, "no_savings"

    sav_with = b - ss
    sav_only = b - s
    if sav_with > 0:
        return float(sav_with), "with_solar"
    if sav_only > 0:
        return float(sav_only), "scenario_only"
    return 0.01, "no_savings"


def compute_payback_years(net_capital_cost: float, annual_savings: float) -> float:
    """Compute simple payback period in years.

    Returns +inf when annual_savings <= 0.
    """
    try:
        num = float(net_capital_cost)
        den = float(annual_savings)
    except Exception:
        return float("inf")
    if den <= 0:
        return float("inf")
    return num / den
