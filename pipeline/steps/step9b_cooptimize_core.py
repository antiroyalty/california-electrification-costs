from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import List

import pandas as pd

try:
    import pulp
except Exception:
    pulp = None


@dataclass(frozen=True)
class CooptInputs:
    load_kwh: List[float]
    pv_gen_per_kw: List[float]
    import_rates: List[float]
    export_rates: List[float]


@dataclass(frozen=True)
class FlowSeries:
    pv_to_load: List[float]
    pv_to_batt: List[float]
    pv_to_grid: List[float]
    batt_to_load: List[float]
    batt_to_grid: List[float]
    grid_to_load: List[float]
    grid_to_batt: List[float]
    soc: List[float]

    def as_list(self) -> List[List[float]]:
        return [
            self.pv_to_load,
            self.pv_to_batt,
            self.pv_to_grid,
            self.batt_to_load,
            self.batt_to_grid,
            self.grid_to_load,
            self.grid_to_batt,
            self.soc,
        ]


@dataclass(frozen=True)
class CooptResult:
    pv_kw: float
    batt_kwh: float
    batt_kw: float
    flows: FlowSeries


def _timestamp_index_8760(year: int = 2018) -> List[pd.Timestamp]:
    start = datetime(year=year, month=1, day=1)
    return [start + timedelta(hours=h) for h in range(8760)]


def _hourly_import_rate(plan_details: dict, ts: pd.Timestamp) -> float:
    month = ts.month
    # Season mapping: consistent with step12 (Jun-Sep = summer)
    season = "summer" if 6 <= month <= 9 else "winter"
    rates = plan_details.get(season, {})
    # day type (weekday/weekend) structure if available
    day_rates = rates.get("weekend") if ts.weekday() >= 5 else rates.get("weekdays")
    if not day_rates:
        day_rates = rates
    h = ts.hour
    # Common structures across PGE/SCE/SDGE helpers
    if "peakHours" in day_rates and h in day_rates.get("peakHours", []):
        return float(day_rates.get("peak", 0.0))
    if "partPeakHours" in day_rates and h in day_rates.get("partPeakHours", []):
        return float(day_rates.get("partPeak", 0.0))
    if "onPeakHours" in day_rates and h in day_rates.get("onPeakHours", []):
        return float(day_rates.get("onPeak", 0.0))
    if "midPeakHours" in day_rates and h in day_rates.get("midPeakHours", []):
        return float(day_rates.get("midPeak", 0.0))
    if "superOffPeakHours" in day_rates and h in day_rates.get("superOffPeakHours", []):
        return float(day_rates.get("superOffPeak", 0.0))
    return float(day_rates.get("offPeak", day_rates.get("peak", 0.0)))


def _crf(discount_rate: float, years: int) -> float:
    r = float(discount_rate)
    n = int(years)
    if r <= 0:
        return 1.0 / max(n, 1)
    a = (1 + r) ** n
    return r * a / (a - 1)


def _ensure_pulp() -> None:
    if pulp is None:
        raise RuntimeError(
            "PuLP is not installed. Install with: pip install pulp (or use cvxpy/pyomo variant)."
        )


def _solve_lp(
    inputs: CooptInputs,
    *,
    allow_grid_charging: bool = False,
    allow_batt_export: bool = True,
    c_pv_kw: float = 2830.0,           # $/kW
    c_batt_kwh: float = 800.0,         # $/kWh (approx, configurable)
    c_batt_kw: float = 0.0,            # $/kW PCS/inverter (optional)
    pv_life_yrs: int = 25,
    batt_life_yrs: int = 15,
    discount_rate: float = 0.07,
    c_deg_per_kwh: float = 0.0,        # degradation cost per kWh throughput
) -> CooptResult:
    """Build and solve LP. Returns CooptResult with sizing + flows.

    FlowSeries order mirrors Step 9 conventions:
      pv_to_load, pv_to_batt, pv_to_grid, batt_to_load, batt_to_grid,
      grid_to_load, grid_to_batt, soc
    """
    _ensure_pulp()
    L = inputs.load_kwh
    G = inputs.pv_gen_per_kw
    p_imp = inputs.import_rates
    p_exp = inputs.export_rates
    H = len(L)

    # Problem
    prob = pulp.LpProblem("CoOptimize_PV_Battery_Dispatch", pulp.LpMinimize)

    # Sizing
    PV_kw = pulp.LpVariable("PV_kw", lowBound=0, cat=pulp.LpContinuous)
    B_E = pulp.LpVariable("B_E_kWh", lowBound=0, cat=pulp.LpContinuous)
    B_P = pulp.LpVariable("B_P_kW", lowBound=0, cat=pulp.LpContinuous)

    # Flows per hour
    pv2load = [pulp.LpVariable(f"pv2load_{h}", lowBound=0) for h in range(H)]
    pv2batt = [pulp.LpVariable(f"pv2batt_{h}", lowBound=0) for h in range(H)]
    pv2grid = [pulp.LpVariable(f"pv2grid_{h}", lowBound=0) for h in range(H)]
    batt2load = [pulp.LpVariable(f"batt2load_{h}", lowBound=0) for h in range(H)]
    batt2grid = [pulp.LpVariable(f"batt2grid_{h}", lowBound=0) for h in range(H)]
    grid2load = [pulp.LpVariable(f"grid2load_{h}", lowBound=0) for h in range(H)]
    grid2batt = [pulp.LpVariable(f"grid2batt_{h}", lowBound=0) for h in range(H)]
    soc = [pulp.LpVariable(f"soc_{h}", lowBound=0) for h in range(H)]

    # Battery parameters (align with Step 9 defaults)
    SOC_MIN_FR = 0.20
    SOC_MAX_FR = 0.90
    from math import sqrt
    RTE = 0.96
    ETA_CH = sqrt(RTE)
    ETA_DIS = sqrt(RTE)

    # PV availability and load balance
    for h in range(H):
        # PV split bound
        prob += pv2load[h] + pv2batt[h] + pv2grid[h] <= PV_kw * float(G[h])
        # Load served
        prob += pv2load[h] + batt2load[h] + grid2load[h] == float(L[h])
        # Power limits
        prob += pv2batt[h] + grid2batt[h] <= B_P
        prob += batt2load[h] + batt2grid[h] <= B_P

    # Disallow/allow grid charging and batt exports per flags
    if not allow_grid_charging:
        for h in range(H):
            prob += grid2batt[h] == 0.0
    if not allow_batt_export:
        for h in range(H):
            prob += batt2grid[h] == 0.0

    # SOC dynamics and bounds; enforce cyclic SOC
    for h in range(H):
        h_next = 0 if (h == H - 1) else (h + 1)
        prob += (
            soc[h_next]
            == soc[h]
            + ETA_CH * (pv2batt[h] + grid2batt[h])
            - (1.0 / ETA_DIS) * (batt2load[h] + batt2grid[h])
        )
        # SOC bounds depend on capacity
        prob += soc[h] >= B_E * SOC_MIN_FR
        prob += soc[h] <= B_E * SOC_MAX_FR

    # Annualized capex
    crf_pv = _crf(discount_rate, pv_life_yrs)
    crf_batt = _crf(discount_rate, batt_life_yrs)
    capex_annual = PV_kw * c_pv_kw * crf_pv + B_E * c_batt_kwh * crf_batt + B_P * c_batt_kw * crf_batt

    # Operating bill (imports - exports) + degradation
    energy_cost = pulp.lpSum([
        grid2load[h] * float(p_imp[h]) - pv2grid[h] * float(p_exp[h]) - batt2grid[h] * float(p_exp[h])
        for h in range(H)
    ])
    degrade_cost = pulp.lpSum([
        c_deg_per_kwh * (batt2load[h] + batt2grid[h]) for h in range(H)
    ])

    prob += capex_annual + energy_cost + degrade_cost

    # Solve
    solver = pulp.PULP_CBC_CMD(msg=False)
    prob.solve(solver)
    if pulp.LpStatus[prob.status] != "Optimal":
        raise RuntimeError(f"LP did not solve to optimality: status={pulp.LpStatus[prob.status]}")

    # Extract values
    pv_kw_val = float(pulp.value(PV_kw))
    b_e_val = float(pulp.value(B_E))
    b_p_val = float(pulp.value(B_P))
    flows = FlowSeries(
        pv_to_load=[float(v.value()) for v in pv2load],
        pv_to_batt=[float(v.value()) for v in pv2batt],
        pv_to_grid=[float(v.value()) for v in pv2grid],
        batt_to_load=[float(v.value()) for v in batt2load],
        batt_to_grid=[float(v.value()) for v in batt2grid],
        grid_to_load=[float(v.value()) for v in grid2load],
        grid_to_batt=[float(v.value()) for v in grid2batt],
        soc=[float(v.value()) for v in soc],
    )
    return CooptResult(pv_kw=pv_kw_val, batt_kwh=b_e_val, batt_kw=b_p_val, flows=flows)
