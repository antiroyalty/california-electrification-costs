from __future__ import annotations

from typing import Iterable, Optional

from .eac import crf
from .npv import npv as _npv


def _to_float(x, default: float = 0.0) -> float:
    try:
        return float(x)
    except Exception:
        return float(default)


def present_value_energy(
    annual_kwh_year1: float,
    years: int,
    discount_rate: float,
    degradation_rate: float = 0.0,
) -> float:
    """Present value of energy over the asset life, with optional annual degradation.

    Energy in year t (1-indexed) = annual_kwh_year1 * (1 - d)^(t-1).
    Discount factor for year t = 1 / (1 + r)^t.
    """
    a = _to_float(annual_kwh_year1)
    r = _to_float(discount_rate)
    d = max(0.0, _to_float(degradation_rate))
    n = int(years or 0)
    if a <= 0 or n <= 0:
        return 0.0
    pv_e = 0.0
    level = a
    for t in range(1, n + 1):
        pv_e += level / ((1.0 + r) ** t)
        level *= (1.0 - d)
    return float(pv_e)


def lcoe_crf_simple(
    capex: float,
    fixed_om_per_year: float,
    annual_generation_kwh: float,
    discount_rate: float,
    lifetime_years: float,
    *,
    variable_om_per_kwh: float = 0.0,
) -> float:
    """Closed-form LCOE using CRF and a constant annual generation (no degradation).

    LCOE = (capex*CRF + fixed_om + variable_om_per_kwh*annual_kwh) / annual_kwh
    Returns 0.0 if annual_kwh <= 0.
    """
    a_kwh = _to_float(annual_generation_kwh)
    if a_kwh <= 0:
        return 0.0
    annualized_capex = _to_float(capex) * crf(_to_float(discount_rate), _to_float(lifetime_years))
    fixed_om = _to_float(fixed_om_per_year)
    vom = _to_float(variable_om_per_kwh) * a_kwh
    return float((annualized_capex + fixed_om + vom) / a_kwh)


def lcoe_npv_from_params(
    capex: float,
    fixed_om_per_year: float,
    annual_generation_kwh_year1: float,
    discount_rate: float,
    lifetime_years: int,
    *,
    degradation_rate: float = 0.0,
    variable_om_per_kwh: float = 0.0,
) -> float:
    """LCOE via NPV of costs divided by NPV of energy, with degradation.

    Costs: capex at t=0, fixed O&M each year (real $), and variable O&M tied to energy.
    Energy: annual_kwh_year1 degraded by (1 - d)^(t-1), discounted by (1 + r)^t.
    Returns 0.0 if PV(energy) == 0.
    """
    # Present value of energy
    pv_energy = present_value_energy(annual_generation_kwh_year1, lifetime_years, discount_rate, degradation_rate)
    if pv_energy <= 0:
        return 0.0

    # Present value of costs
    r = _to_float(discount_rate)
    a1 = _to_float(annual_generation_kwh_year1)
    d = max(0.0, _to_float(degradation_rate))
    fixed = _to_float(fixed_om_per_year)
    vom_per_kwh = _to_float(variable_om_per_kwh)

    costs = [_to_float(capex)]  # t = 0
    level = a1
    for _t in range(1, int(lifetime_years or 0) + 1):
        annual_cost = fixed + vom_per_kwh * level
        costs.append(annual_cost)
        level *= (1.0 - d)

    pv_costs = _npv(r, costs)
    return float(pv_costs / pv_energy) if pv_energy > 0 else 0.0


def lcoe_from_schedules(
    annual_costs: Iterable[float],
    annual_generation_kwh: Iterable[float],
    discount_rate: float,
) -> float:
    """General LCOE = PV(costs) / PV(energy) from explicit schedules.

    annual_costs: include t=0 capex as first element; subsequent entries are yearly O&M.
    annual_generation_kwh: energy produced in each year (t=1..N). If first element corresponds to t=1,
      you may insert a 0 for t=0 to keep alignment.
    Returns 0.0 if PV(energy) == 0.
    """
    pv_cost = _npv(_to_float(discount_rate), list(annual_costs))
    # Energy starts at t=1; prepend 0 so discount aligns with NPV convention
    energy_series = [0.0] + list(annual_generation_kwh)
    pv_energy = _npv(_to_float(discount_rate), energy_series)
    if pv_energy <= 0:
        return 0.0
    return float(pv_cost / pv_energy)

