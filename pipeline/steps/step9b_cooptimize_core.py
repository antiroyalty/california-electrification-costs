from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import List, Optional, Tuple

import pandas as pd

from evaluations.eac import crf as _crf

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
    total_cost: float
    capex_annual: float
    import_cost: float
    export_credit: float
    degradation_cost: float
    flows: FlowSeries


# Battery operating parameters — shared between LP constraints and post-solve verification.
# If these change, both the LP and the invariant checks change together.
_SOC_MIN_FR = 0.20
_SOC_MAX_FR = 0.90
_RTE = 0.96  # Round-trip efficiency


def _verify_invariants(
    result: CooptResult,
    inputs: CooptInputs,
    *,
    tol: float = 1e-3,
) -> None:
    """Assert post-solve invariants on extracted float values.

    The LP constraints guarantee these hold in the solver model. This function
    verifies that the extracted floats satisfy them too — catching any floating
    point gaps between the model and the solution values.

    Raises AssertionError with a descriptive message if any invariant is violated.
    """
    f = result.flows
    H = len(inputs.load_kwh)

    for h in range(H):
        # 1. Load balance: every kWh of load must be served by exactly one source.
        served = f.pv_to_load[h] + f.batt_to_load[h] + f.grid_to_load[h]
        assert abs(served - inputs.load_kwh[h]) <= tol, (
            f"Load balance violated at hour {h}: "
            f"served={served:.4f} kWh, load={inputs.load_kwh[h]:.4f} kWh"
        )

        # 2. Non-negative flows: all physical flows must be >= 0.
        for name, val in [
            ("pv_to_load", f.pv_to_load[h]),
            ("pv_to_batt", f.pv_to_batt[h]),
            ("pv_to_grid", f.pv_to_grid[h]),
            ("batt_to_load", f.batt_to_load[h]),
            ("batt_to_grid", f.batt_to_grid[h]),
            ("grid_to_load", f.grid_to_load[h]),
            ("grid_to_batt", f.grid_to_batt[h]),
        ]:
            assert val >= -tol, (
                f"Negative flow {name}[{h}] = {val:.6f}"
            )

        # 3. PV generation bound: total PV output cannot exceed available generation.
        pv_out = f.pv_to_load[h] + f.pv_to_batt[h] + f.pv_to_grid[h]
        pv_avail = result.pv_kw * inputs.pv_gen_per_kw[h]
        assert pv_out <= pv_avail + tol, (
            f"PV output exceeds generation at hour {h}: "
            f"output={pv_out:.4f} kWh, available={pv_avail:.4f} kWh"
        )

        # 4. Battery SOC bounds.
        if result.batt_kwh > tol:
            soc_min = result.batt_kwh * _SOC_MIN_FR
            soc_max = result.batt_kwh * _SOC_MAX_FR
            assert f.soc[h] >= soc_min - tol, (
                f"SOC below minimum at hour {h}: soc={f.soc[h]:.4f}, min={soc_min:.4f}"
            )
            assert f.soc[h] <= soc_max + tol, (
                f"SOC above maximum at hour {h}: soc={f.soc[h]:.4f}, max={soc_max:.4f}"
            )

    # 5. Financial reconciliation: total cost must equal the sum of its components.
    expected_total = (
        result.capex_annual
        + result.import_cost
        - result.export_credit
        + result.degradation_cost
    )
    assert abs(result.total_cost - expected_total) <= tol, (
        f"Financial reconciliation failed: "
        f"total={result.total_cost:.4f}, "
        f"capex + imports - exports + degradation={expected_total:.4f}"
    )


def _timestamp_index_8760(year: int = 2018) -> List[pd.Timestamp]:
    start = datetime(year=year, month=1, day=1)
    return [start + timedelta(hours=h) for h in range(8760)]


def _hourly_import_rate(plan_details: dict, ts: pd.Timestamp) -> float:
    """Return the import rate ($/kWh) for a given timestamp.

    Rate plan dicts are structured as:
        plan_details[season]["weekdays" | "weekends"][rate_keys]

    BUG HISTORY (fixed 2026-03-03, caught by rate-helpers-test.py):
        The original code used rates.get("weekend") — singular — but every rate
        plan in electricity_rate_helpers.py uses "weekends" — plural. The silent
        fallback (if not day_rates: day_rates = rates) then set day_rates to the
        season dict, which has no rate keys, so the final .get("offPeak", .get("peak",
        0.0)) returned 0.0 for every weekend hour. Weekend import rates were zero
        across all PGE/SCE/SDGE plans for the entire run history.

        Impact: weekend solar arbitrage appeared artificially profitable in the LP
        (zero import cost means zero savings from shifting load), so the optimizer
        had less incentive to charge the battery on weekends. The zero export credit
        on weekends inflated apparent savings from weekday-only dispatch. The effect
        is partially self-canceling but not zero — results from any run before this
        fix should be treated as having incorrect weekend rate assumptions.
    """
    month = ts.month
    season = "summer" if 6 <= month <= 9 else "winter"
    rates = plan_details.get(season)
    if rates is None:
        raise KeyError(
            f"Season '{season}' not found in rate plan. "
            f"Available keys: {list(plan_details.keys())}"
        )

    day_type = "weekends" if ts.weekday() >= 5 else "weekdays"
    if day_type in rates:
        day_rates = rates[day_type]
    elif "weekdays" in rates or "weekends" in rates:
        # The plan has a weekday/weekend split but the requested key is missing.
        # This is the class of bug described above — fail loudly instead of
        # silently returning 0.
        raise KeyError(
            f"Rate plan has a weekday/weekend split but '{day_type}' key not found. "
            f"Available keys in '{season}': {list(rates.keys())}. "
            f"Check for 'weekdays'/'weekends' key name typos in electricity_rate_helpers.py."
        )
    else:
        # Plan has no day-type split; season-level rates apply directly.
        day_rates = rates

    h = ts.hour
    if "peakHours" in day_rates and h in day_rates["peakHours"]:
        return float(day_rates["peak"])
    if "partPeakHours" in day_rates and h in day_rates["partPeakHours"]:
        return float(day_rates["partPeak"])
    if "onPeakHours" in day_rates and h in day_rates["onPeakHours"]:
        return float(day_rates["onPeak"])
    if "midPeakHours" in day_rates and h in day_rates["midPeakHours"]:
        return float(day_rates["midPeak"])
    if "superOffPeakHours" in day_rates and h in day_rates["superOffPeakHours"]:
        return float(day_rates["superOffPeak"])
    if "offPeak" not in day_rates and "peak" not in day_rates:
        raise KeyError(
            f"No fallback rate key ('offPeak' or 'peak') found in {day_type}/{season} "
            f"rates at hour {h}. Available keys: {list(day_rates.keys())}"
        )
    return float(day_rates.get("offPeak", day_rates["peak"]))


def _ensure_pulp() -> None:
    if pulp is None:
        raise RuntimeError(
            "PuLP is not installed. Install with: pip install pulp (or use cvxpy/pyomo variant)."
        )


def _solve_lp(
    inputs: CooptInputs,
    *,
    fixed_pv_kw: float | None = None,
    fixed_batt_kwh: float | None = None,
    weights: Optional[List[float]] = None,
    cycle_monthly: bool = False,
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
    """Build and solve LP. Returns CooptResult with sizing, costs, and flows.

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
    if weights is None:
        weights = [1.0] * H
    if len(weights) != H:
        raise ValueError("weights length must match number of hours")

    # Problem
    prob = pulp.LpProblem("CoOptimize_PV_Battery_Dispatch", pulp.LpMinimize)

    # Sizing
    if fixed_pv_kw is None:
        PV_kw = pulp.LpVariable("PV_kw", lowBound=0, cat=pulp.LpContinuous)
    else:
        fixed_pv = float(fixed_pv_kw)
        PV_kw = pulp.LpVariable("PV_kw", lowBound=fixed_pv, upBound=fixed_pv, cat=pulp.LpContinuous)
    if fixed_batt_kwh is None:
        B_E = pulp.LpVariable("B_E_kWh", lowBound=0, cat=pulp.LpContinuous)
    else:
        fixed = float(fixed_batt_kwh)
        B_E = pulp.LpVariable("B_E_kWh", lowBound=fixed, upBound=fixed, cat=pulp.LpContinuous)
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

    # When grid charging is enabled, split SOC to prevent exporting grid-charged energy.
    batt2load_pv = batt2load_grid = soc_pv = soc_grid = None
    if allow_grid_charging:
        batt2load_pv = [pulp.LpVariable(f"batt2load_pv_{h}", lowBound=0) for h in range(H)]
        batt2load_grid = [pulp.LpVariable(f"batt2load_grid_{h}", lowBound=0) for h in range(H)]
        soc_pv = [pulp.LpVariable(f"soc_pv_{h}", lowBound=0) for h in range(H)]
        soc_grid = [pulp.LpVariable(f"soc_grid_{h}", lowBound=0) for h in range(H)]

    # Battery parameters — use module-level constants so LP and verifier stay in sync.
    from math import sqrt
    ETA_CH = sqrt(_RTE)
    ETA_DIS = sqrt(_RTE)

    # PV availability and load balance
    for h in range(H):
        # PV split bound
        prob += pv2load[h] + pv2batt[h] + pv2grid[h] <= PV_kw * float(G[h])
        # Load served
        prob += pv2load[h] + batt2load[h] + grid2load[h] == float(L[h])
        # Power limits
        prob += pv2batt[h] + grid2batt[h] <= B_P
        if allow_grid_charging:
            prob += batt2load_pv[h] + batt2load_grid[h] + batt2grid[h] <= B_P
            prob += batt2load[h] == batt2load_pv[h] + batt2load_grid[h]
        else:
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
        if cycle_monthly and H % 24 == 0:
            h_next = h - 23 if (h % 24 == 23) else (h + 1)
        else:
            h_next = 0 if (h == H - 1) else (h + 1)
        if allow_grid_charging:
            prob += (
                soc_pv[h_next]
                == soc_pv[h]
                + ETA_CH * pv2batt[h]
                - (1.0 / ETA_DIS) * (batt2load_pv[h] + batt2grid[h])
            )
            prob += (
                soc_grid[h_next]
                == soc_grid[h]
                + ETA_CH * grid2batt[h]
                - (1.0 / ETA_DIS) * batt2load_grid[h]
            )
            prob += soc[h] == soc_pv[h] + soc_grid[h]
        else:
            prob += (
                soc[h_next]
                == soc[h]
                + ETA_CH * (pv2batt[h] + grid2batt[h])
                - (1.0 / ETA_DIS) * (batt2load[h] + batt2grid[h])
            )
        # SOC bounds depend on capacity
        prob += soc[h] >= B_E * _SOC_MIN_FR
        prob += soc[h] <= B_E * _SOC_MAX_FR

    # Annualized capex (NPV framing, $/year equivalent over horizon N = pv_life_yrs).
    #
    # PV: paid once at t=0; lifetime = horizon, so K_pv = 1 and alpha_pv = 1/PVA = CRF(r, N).
    # Battery: paid at t=0 AND replaced at t=n_batt within the horizon, so
    #   K_batt = 1 + (1+r)^(-n_batt)   [PV of two purchases]
    #   alpha_batt = K_batt / PVA(r, N)
    # alpha_batt > CRF(r, n_batt) because CRF would amortize only one purchase over n_batt years
    # and ignore the replacement cost. The difference is the discounted cost of the second battery.
    r = float(discount_rate)
    N = int(pv_life_yrs)
    pva_n = ((1 - (1 + r) ** (-N)) / r) if r > 0 else float(N)
    alpha_pv = 1.0 / pva_n
    alpha_batt = (1.0 + (1.0 + r) ** (-batt_life_yrs)) / pva_n
    capex_annual = PV_kw * c_pv_kw * alpha_pv + B_E * c_batt_kwh * alpha_batt + B_P * c_batt_kw * alpha_batt

    # Operating bill (imports - exports) + degradation
    energy_cost = pulp.lpSum([
        float(weights[h])
        * (
            (grid2load[h] + grid2batt[h]) * float(p_imp[h])
            - pv2grid[h] * float(p_exp[h])
            - batt2grid[h] * float(p_exp[h])
        )
        for h in range(H)
    ])
    degrade_cost = pulp.lpSum([
        float(weights[h]) * c_deg_per_kwh * (batt2load[h] + batt2grid[h]) for h in range(H)
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
    capex_annual_val = float(pulp.value(capex_annual))
    import_cost_val = float(
        pulp.value(
            pulp.lpSum(
                [float(weights[h]) * (grid2load[h] + grid2batt[h]) * float(p_imp[h]) for h in range(H)]
            )
        )
    )
    export_credit_val = float(
        pulp.value(
            pulp.lpSum(
                [float(weights[h]) * (pv2grid[h] + batt2grid[h]) * float(p_exp[h]) for h in range(H)]
            )
        )
    )
    degradation_cost_val = float(pulp.value(degrade_cost))
    total_cost_val = capex_annual_val + import_cost_val - export_credit_val + degradation_cost_val
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
    result = CooptResult(
        pv_kw=pv_kw_val,
        batt_kwh=b_e_val,
        batt_kw=b_p_val,
        total_cost=total_cost_val,
        capex_annual=capex_annual_val,
        import_cost=import_cost_val,
        export_credit=export_credit_val,
        degradation_cost=degradation_cost_val,
        flows=flows,
    )
    _verify_invariants(result, inputs)
    return result


def build_monthly_hourly_inputs(
    inputs: CooptInputs,
    *,
    year: int = 2018,
) -> Tuple[CooptInputs, List[float]]:
    """Aggregate 8760 series into 12x24 monthly-hourly averages plus weights."""
    if len(inputs.load_kwh) != 8760:
        raise ValueError("Monthly-hourly aggregation expects 8760-length inputs.")
    ts = _timestamp_index_8760(year)
    df = pd.DataFrame(
        {
            "ts": ts,
            "load": inputs.load_kwh,
            "pv": inputs.pv_gen_per_kw,
            "imp": inputs.import_rates,
            "exp": inputs.export_rates,
        }
    )
    df["month"] = df["ts"].dt.month
    df["hour"] = df["ts"].dt.hour
    grouped = (
        df.groupby(["month", "hour"])
        .mean(numeric_only=True)
        .reset_index()
    )
    months = list(range(1, 13))
    hours = list(range(0, 24))
    load = []
    pv = []
    imp = []
    exp = []
    weights = []
    import calendar
    for m in months:
        days_in_month = calendar.monthrange(year, m)[1]
        for h in hours:
            row = grouped[(grouped["month"] == m) & (grouped["hour"] == h)]
            if row.empty:
                load.append(0.0)
                pv.append(0.0)
                imp.append(0.0)
                exp.append(0.0)
            else:
                load.append(float(row.iloc[0]["load"]))
                pv.append(float(row.iloc[0]["pv"]))
                imp.append(float(row.iloc[0]["imp"]))
                exp.append(float(row.iloc[0]["exp"]))
            weights.append(float(days_in_month))
    return CooptInputs(load, pv, imp, exp), weights
