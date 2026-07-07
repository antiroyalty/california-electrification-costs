from __future__ import annotations

from typing import Iterable

from .constants import DEFAULT_DISCOUNT_RATE


def annuity_factor(rate: float, n_years: float) -> float:
    """Return annuity factor A such that EAC = NPV * A.

    A = r / (1 - (1 + r)^-n). For non‑positive rate, approximate as 1/n.
    """
    r = float(rate)
    n = float(n_years)
    if n <= 0:
        return 1.0
    if r <= 0:
        return 1.0 / n
    return r / (1.0 - (1.0 + r) ** (-n))


def npv(rate: float, cash_flows: Iterable[float]) -> float:
    """Net Present Value for a sequence of cash flows.

    Cash flows are ordered by period t = 0, 1, 2, ...
    """
    r = float(rate)
    total = 0.0
    for t, cf in enumerate(cash_flows):
        try:
            total += float(cf) / ((1.0 + r) ** t)
        except Exception:
            continue
    return float(total)


def compute_npv_details_from_inputs(
    *,
    baseline_cost: float,
    scenario_cost: float,
    scenario_solar_cost: float,
    pv_storage_net_capex: float,
    electrification_net_capex: float | None,
    horizon_years: int = 25,
    discount_rate: float = DEFAULT_DISCOUNT_RATE,
) -> dict:
    """Compute NPV details from numeric inputs (no I/O).

    Returns a dict with NPV for:
      - solar + storage only (scenario_cost -> scenario_solar_cost savings)
      - all electrification (baseline_cost -> scenario_solar_cost savings)
    """
    h = int(horizon_years)
    if h <= 0:
        raise ValueError("horizon_years must be positive")
    b = float(baseline_cost)
    s = float(scenario_cost)
    ss = float(scenario_solar_cost)
    pv_net = float(pv_storage_net_capex)
    elec_net = None if electrification_net_capex is None else float(electrification_net_capex)

    annual_savings_with_solar = b - ss
    annual_savings_solar_only = s - ss

    cashflows_solar = [-pv_net] + [annual_savings_solar_only] * h
    npv_solar = npv(float(discount_rate), cashflows_solar)

    npv_all = None
    total_net = None
    if elec_net is not None:
        total_net = pv_net + elec_net
        cashflows_all = [-total_net] + [annual_savings_with_solar] * h
        npv_all = npv(float(discount_rate), cashflows_all)

    return {
        "horizon_years": h,
        "discount_rate": float(discount_rate),
        "baseline_cost": b,
        "scenario_cost": s,
        "scenario_solar_cost": ss,
        "solar_storage": {
            "net_capex": pv_net,
            "annual_savings": annual_savings_solar_only,
            "npv": float(npv_solar),
            "savings_definition": "scenario_cost - scenario_solar_cost",
        },
        "all_electrification": {
            "net_capex": float(total_net) if total_net is not None else None,
            "annual_savings": annual_savings_with_solar,
            "npv": float(npv_all) if npv_all is not None else None,
            "savings_definition": "baseline_cost - scenario_solar_cost",
        },
    }
