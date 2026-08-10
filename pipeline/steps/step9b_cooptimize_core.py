from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import List, Optional, Tuple

import pandas as pd

from evaluations.eac import crf as _crf, alpha_batt_npv as _alpha_batt_npv
from evaluations.constants import DEFAULT_DISCOUNT_RATE
from appliances.solar_system import SolarSystemAppliance
from appliances.battery_storage import BatteryStorageAppliance
from appliances.electric_base import IncentiveScenario

# See step9b_cooptimize_pv_battery.py for the full note on why these must
# match the appliance classes step14 uses for reporting, not a standalone
# guess — a caller that sizes here without reconciling would repeat the bug
# found 2026-07-06.
#
# Net (not gross) of full_incentives: 2026-07-07 — the LP's sizing decision
# should reflect what the modeled decision-maker actually pays. Config's
# default incentive scenario is full_incentives, so a caller that sizes here
# without an explicit override should assume the same. Real production runs
# (mod_solar_storage.run) pass the net cost under whichever incentive
# scenario Config actually specifies, not this static default — see that
# module for why.
_DEFAULT_PV_CAPEX_PER_KW = SolarSystemAppliance.per_kw_cost_net(IncentiveScenario.FULL_INCENTIVES)
_DEFAULT_BATT_CAPEX_PER_KWH = BatteryStorageAppliance.per_kwh_cost_net(IncentiveScenario.FULL_INCENTIVES)
# Representative-household sizing domain. This is an explicit modeling bound,
# not a tariff value. It implements the 30–40 kWh range documented in the
# optimization design notes and can be overridden for sensitivity analyses.
DEFAULT_MAX_BATTERY_KWH = 40.0
# On a several-thousand-dollar annual objective this proves the solution to
# substantially less than one cent while avoiding work that cannot affect any
# reported research value.
HIGHS_MIP_RELATIVE_GAP = 1e-6
# If the first continuous relaxation exploits many intervals, adding only the
# currently violated rows can make a later constraint-generation round harder
# than the compact eager model. This affects performance only, never the
# feasible region or optimum.
METER_BINARY_EAGER_THRESHOLD = 96
# Constraint generation terminates on its own: every round pins at least one
# previously unconstrained interval, so it cannot exceed the interval count.
# This cap exists to fail loudly instead of grinding for hours if that argument
# is ever broken by a change to the disjunction logic. It is deliberately far
# above the round count any real county needs (SDG&E, the worst case, converges
# in a handful of rounds).
MAX_METER_DIRECTION_ROUNDS = 64

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
    meter_binary_count: int
    solver_rounds: int


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

        # 5. A meter interval has one direction: import or export, never both.
        grid_import = f.grid_to_load[h] + f.grid_to_batt[h]
        grid_export = f.pv_to_grid[h] + f.batt_to_grid[h]
        assert not (grid_import > tol and grid_export > tol), (
            f"Simultaneous grid import/export at hour {h}: "
            f"import={grid_import:.4f}, export={grid_export:.4f}"
        )

    # 6. Financial reconciliation: total cost must equal the sum of its components.
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
    if "offPeak" in day_rates:
        return float(day_rates["offPeak"])
    if "peak" in day_rates:
        return float(day_rates["peak"])
    raise KeyError(
        f"No fallback rate key ('offPeak' or 'peak') found in {day_type}/{season} "
        f"rates at hour {h}. Available keys: {list(day_rates.keys())}"
    )


def _ensure_pulp() -> None:
    if pulp is None:
        raise RuntimeError(
            "PuLP is not installed. Install with: pip install pulp (or use cvxpy/pyomo variant)."
        )


def _meter_direction_hours(inputs: CooptInputs, *, tolerance: float = 1e-9) -> list[int]:
    """Hours whose non-convex price ordering requires an import/export binary.

    When the import price is strictly greater than the export price,
    simultaneous import and export is dominated and an LP needs no mode
    variable. Equal-price hours retain a binary because otherwise a solver may
    return a physically invalid but objective-equivalent degenerate solution.
    """

    return [
        hour
        for hour, (import_rate, export_rate) in enumerate(
            zip(inputs.import_rates, inputs.export_rates)
        )
        if float(export_rate) >= float(import_rate) - tolerance
    ]


def _solve_with_highs(problem) -> None:
    """Solve a PuLP linear model with SciPy's HiGHS MILP backend.

    PuLP remains the readable model-construction layer. Converting its sparse
    linear expressions here avoids CBC's severe branch-and-bound slowdown on
    the 8,760-hour formulation while preserving one authoritative model.
    """

    try:
        import numpy as np
        from scipy.optimize import Bounds, LinearConstraint, milp
        from scipy.sparse import coo_matrix
    except ImportError as exc:
        raise RuntimeError(
            "Full-resolution co-optimization requires scipy.optimize.milp (HiGHS)"
        ) from exc

    variables = list(problem.variables())
    variable_index = {variable: index for index, variable in enumerate(variables)}
    objective = np.array(
        [float(problem.objective.get(variable, 0.0)) for variable in variables],
        dtype=float,
    )
    lower_bounds = np.array(
        [
            -np.inf if variable.lowBound is None else float(variable.lowBound)
            for variable in variables
        ],
        dtype=float,
    )
    upper_bounds = np.array(
        [
            np.inf if variable.upBound is None else float(variable.upBound)
            for variable in variables
        ],
        dtype=float,
    )
    integrality = np.array(
        [1 if variable.cat == pulp.LpInteger else 0 for variable in variables],
        dtype=np.uint8,
    )

    row_indices: list[int] = []
    column_indices: list[int] = []
    coefficients: list[float] = []
    constraint_lower: list[float] = []
    constraint_upper: list[float] = []
    for row, constraint in enumerate(problem.constraints.values()):
        for variable, coefficient in constraint.items():
            row_indices.append(row)
            column_indices.append(variable_index[variable])
            coefficients.append(float(coefficient))
        rhs = float(-constraint.constant)
        if constraint.sense == pulp.LpConstraintLE:
            constraint_lower.append(-np.inf)
            constraint_upper.append(rhs)
        elif constraint.sense == pulp.LpConstraintGE:
            constraint_lower.append(rhs)
            constraint_upper.append(np.inf)
        elif constraint.sense == pulp.LpConstraintEQ:
            constraint_lower.append(rhs)
            constraint_upper.append(rhs)
        else:
            raise ValueError(f"Unknown PuLP constraint sense {constraint.sense}")

    matrix = coo_matrix(
        (coefficients, (row_indices, column_indices)),
        shape=(len(constraint_lower), len(variables)),
    ).tocsr()
    result = milp(
        c=objective,
        integrality=integrality,
        bounds=Bounds(lower_bounds, upper_bounds),
        constraints=LinearConstraint(
            matrix,
            np.asarray(constraint_lower, dtype=float),
            np.asarray(constraint_upper, dtype=float),
        ),
        options={"presolve": True, "mip_rel_gap": HIGHS_MIP_RELATIVE_GAP},
    )
    if not result.success or result.x is None:
        raise RuntimeError(
            f"HiGHS MILP did not solve to optimality: status={result.status}, "
            f"message={result.message}"
        )
    for variable, value in zip(variables, result.x):
        variable.varValue = float(value)


def _solve_lp(
    inputs: CooptInputs,
    *,
    fixed_pv_kw: float | None = None,
    fixed_batt_kwh: float | None = None,
    weights: Optional[List[float]] = None,
    cycle_monthly: bool = False,
    allow_grid_charging: bool = False,
    allow_batt_export: bool = True,
    c_pv_kw: float = _DEFAULT_PV_CAPEX_PER_KW,   # $/kW — see appliances.solar_system, configurable
    c_batt_kwh: float = _DEFAULT_BATT_CAPEX_PER_KWH,  # $/kWh — see appliances.battery_storage, configurable
    c_batt_kw: float = 0.0,            # $/kW PCS/inverter (optional)
    pv_life_yrs: int = 25,
    batt_life_yrs: int = 15,
    discount_rate: float = DEFAULT_DISCOUNT_RATE,
    c_deg_per_kwh: float = 0.0,        # degradation cost per kWh throughput
    max_battery_kwh: float = DEFAULT_MAX_BATTERY_KWH,
    max_pv_to_annual_load_ratio: float = 1.5,
    solver_backend: str = "highs",
) -> CooptResult:
    """Build and solve the sparse MILP. Return sizing, costs, and flows.

    FlowSeries order mirrors Step 9 conventions:
      pv_to_load, pv_to_batt, pv_to_grid, batt_to_load, batt_to_grid,
      grid_to_load, grid_to_batt, soc

    PV, battery, and flow decisions remain continuous. The model first solves
    their LP relaxation, then creates binary meter-direction variables only at
    intervals whose relaxed solution actually imports and exports at once.
    ``max_battery_kwh`` is the explicit household sizing ceiling and, with the
    1C constraint, supplies a tight battery-power bound for those disjunctions.
    A fixed-size sensitivity is itself an explicit override and therefore uses
    its fixed capacity as the bound.
    """
    _ensure_pulp()
    L = inputs.load_kwh
    G = inputs.pv_gen_per_kw
    p_imp = inputs.import_rates
    p_exp = inputs.export_rates
    H = len(L)
    lengths = {
        "load_kwh": len(L),
        "pv_gen_per_kw": len(G),
        "import_rates": len(p_imp),
        "export_rates": len(p_exp),
    }
    if len(set(lengths.values())) != 1 or H == 0:
        raise ValueError(f"All CooptInputs series must have the same nonzero length: {lengths}")
    if any(float(value) < 0 for series in (L, G, p_imp, p_exp) for value in series):
        raise ValueError("Loads, PV availability, and tariff rates must be non-negative")
    if max_battery_kwh < 0:
        raise ValueError("max_battery_kwh cannot be negative")
    if max_pv_to_annual_load_ratio <= 0:
        raise ValueError("max_pv_to_annual_load_ratio must be positive")
    if solver_backend not in {"highs", "cbc"}:
        raise ValueError("solver_backend must be 'highs' or 'cbc'")
    if weights is None:
        weights = [1.0] * H
    if len(weights) != H:
        raise ValueError("weights length must match number of hours")

    # Problem
    prob = pulp.LpProblem("CoOptimize_PV_Battery_Dispatch", pulp.LpMinimize)

    # Sizing. California NBT permits systems sized up to 150% of recent or
    # projected annual usage; deriving the cap from this profile prevents the
    # model from turning a representative household into a merchant generator.
    weighted_load = sum(float(weights[h]) * float(L[h]) for h in range(H))
    weighted_pv_yield = sum(float(weights[h]) * float(G[h]) for h in range(H))
    pv_kw_cap = (
        max_pv_to_annual_load_ratio * weighted_load / weighted_pv_yield
        if weighted_pv_yield > 0
        else 0.0
    )
    if fixed_pv_kw is None:
        PV_kw = pulp.LpVariable("PV_kw", lowBound=0, upBound=pv_kw_cap, cat=pulp.LpContinuous)
    else:
        fixed_pv = float(fixed_pv_kw)
        if fixed_pv < 0:
            raise ValueError("fixed_pv_kw cannot be negative")
        if fixed_pv > pv_kw_cap + 1e-9:
            raise ValueError(
                f"fixed_pv_kw={fixed_pv:.3f} exceeds the NBT 150% sizing cap "
                f"of {pv_kw_cap:.3f} kW for this profile"
            )
        PV_kw = pulp.LpVariable("PV_kw", lowBound=fixed_pv, upBound=fixed_pv, cat=pulp.LpContinuous)
    if fixed_batt_kwh is None:
        battery_capacity_bound = float(max_battery_kwh)
        B_E = pulp.LpVariable(
            "B_E_kWh", lowBound=0, upBound=battery_capacity_bound, cat=pulp.LpContinuous
        )
    else:
        fixed = float(fixed_batt_kwh)
        if fixed < 0:
            raise ValueError("fixed_batt_kwh cannot be negative")
        # Fixed-size sweeps explicitly override the default household sizing
        # domain; their own fixed capacity is still a finite, tight bound.
        battery_capacity_bound = fixed
        B_E = pulp.LpVariable("B_E_kWh", lowBound=fixed, upBound=fixed, cat=pulp.LpContinuous)
    B_P = pulp.LpVariable(
        "B_P_kW", lowBound=0, upBound=battery_capacity_bound, cat=pulp.LpContinuous
    )
    prob += B_P <= B_E  # at most 1C power, consistent with residential batteries

    # Flows per hour
    pv_availability_bounds = [pv_kw_cap * float(G[h]) for h in range(H)]
    pv2load = [
        pulp.LpVariable(f"pv2load_{h}", lowBound=0, upBound=min(float(L[h]), pv_availability_bounds[h]))
        for h in range(H)
    ]
    pv2batt = [
        pulp.LpVariable(
            f"pv2batt_{h}", lowBound=0,
            upBound=min(battery_capacity_bound, pv_availability_bounds[h]),
        )
        for h in range(H)
    ]
    pv2grid = [
        pulp.LpVariable(f"pv2grid_{h}", lowBound=0, upBound=pv_availability_bounds[h])
        for h in range(H)
    ]
    batt2load = [
        pulp.LpVariable(
            f"batt2load_{h}", lowBound=0,
            upBound=min(float(L[h]), battery_capacity_bound),
        )
        for h in range(H)
    ]
    batt2grid = [
        pulp.LpVariable(
            f"batt2grid_{h}", lowBound=0,
            upBound=battery_capacity_bound if allow_batt_export else 0.0,
        )
        for h in range(H)
    ]
    grid2load = [
        pulp.LpVariable(f"grid2load_{h}", lowBound=0, upBound=float(L[h]))
        for h in range(H)
    ]
    grid2batt = [
        pulp.LpVariable(
            f"grid2batt_{h}", lowBound=0,
            upBound=battery_capacity_bound if allow_grid_charging else 0.0,
        )
        for h in range(H)
    ]
    soc = [
        pulp.LpVariable(f"soc_{h}", lowBound=0, upBound=battery_capacity_bound)
        for h in range(H)
    ]
    grid_import_mode: dict[int, object] = {}
    import_bounds = [
        float(L[h]) + (battery_capacity_bound if allow_grid_charging else 0.0)
        for h in range(H)
    ]
    export_bounds = [
        pv_availability_bounds[h]
        + (battery_capacity_bound if allow_batt_export else 0.0)
        for h in range(H)
    ]

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
    #
    # These coefficients are the same ones evaluations.eac uses for EAC reporting
    # (crf, alpha_batt_npv) — computed here via the shared primitives so the LP
    # and the reporting layer cannot silently drift apart.
    N = int(pv_life_yrs)
    alpha_pv = _crf(discount_rate, N)
    alpha_batt = _alpha_batt_npv(discount_rate, batt_life_yrs, N)
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

    # Solve with exact constraint generation. Each intermediate problem is a
    # relaxation of the physical meter model. If its global optimum has no
    # simultaneous import/export, it is feasible for the full model while also
    # furnishing a lower bound, which proves it is the full model's optimum.
    # Otherwise add tight binary disjunctions only at the violating intervals.
    solver_rounds = 0
    while True:
        solver_rounds += 1
        if solver_rounds > MAX_METER_DIRECTION_ROUNDS:
            raise RuntimeError(
                f"Meter-direction constraint generation did not converge within "
                f"{MAX_METER_DIRECTION_ROUNDS} rounds ({len(grid_import_mode)} binaries "
                f"pinned over {H} intervals). The relaxation is not tightening, which "
                f"indicates a defect in the disjunction bounds rather than a hard instance."
            )
        if solver_backend == "highs":
            _solve_with_highs(prob)
        else:
            solver = pulp.PULP_CBC_CMD(msg=False)
            prob.solve(solver)
            if pulp.LpStatus[prob.status] != "Optimal":
                raise RuntimeError(
                    f"CBC MILP did not solve to optimality: status={pulp.LpStatus[prob.status]}"
                )

        violations = []
        for h in range(H):
            imported = float(grid2load[h].value()) + float(grid2batt[h].value())
            exported = float(pv2grid[h].value()) + float(batt2grid[h].value())
            if imported > 1e-7 and exported > 1e-7:
                if h in grid_import_mode:
                    raise RuntimeError(
                        f"Meter-direction constraint violated solver tolerance at hour {h}: "
                        f"import={imported}, export={exported}"
                    )
                violations.append(h)
        if not violations:
            break

        hours_to_constrain = set(violations)
        if solver_rounds == 1 and len(violations) > METER_BINARY_EAGER_THRESHOLD:
            hours_to_constrain.update(_meter_direction_hours(inputs))

        for h in sorted(hours_to_constrain):
            if h in grid_import_mode:
                continue
            if import_bounds[h] <= 0 or export_bounds[h] <= 0:
                if h in violations:
                    raise RuntimeError(
                        f"Simultaneous meter flow at hour {h} despite a zero physical bound"
                    )
                continue
            mode = pulp.LpVariable(f"grid_import_mode_{h}", cat=pulp.LpBinary)
            grid_import_mode[h] = mode
            # Disaggregate the disjunction by physical flow. These bounds are
            # equivalent to the summed meter-direction constraints at integer
            # mode values, but their LP relaxation is materially tighter: a
            # small PV bound cannot borrow the battery's capacity allowance,
            # and vice versa.
            prob += grid2load[h] <= float(L[h]) * mode
            prob += grid2batt[h] <= (
                battery_capacity_bound if allow_grid_charging else 0.0
            ) * mode
            prob += pv2grid[h] <= pv_availability_bounds[h] * (1 - mode)
            prob += batt2grid[h] <= (
                battery_capacity_bound if allow_batt_export else 0.0
            ) * (1 - mode)

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
        meter_binary_count=len(grid_import_mode),
        solver_rounds=solver_rounds,
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
