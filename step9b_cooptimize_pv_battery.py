"""
Step 9b — Co‑Optimize PV size, Battery size (kWh,kW), and hourly dispatch.

This module builds a linear program (LP) to minimize annual total cost:
  annualized capex (PV + battery) + retail imports − NEM3 export credits (+ optional degradation cost)

Notes
- CSV‑only NEM3 export tables are loaded via helpers.nem3_export_rates
- Retail import price is built from helpers.electricity_rate_helpers plans
- Weather→PV per‑kW yield is computed using Step 9 core helpers (GHI‑based PVWatts‑style)

Outputs (per county)
- sam_optimized_load_profiles_<county>.csv
- sam_optimized_load_profiles_with_exports_<county>.csv

These match Step 9 column conventions so Step 10 can build aggregator files for Step 12 without changes.

Usage examples
- Separate co‑opt scenario (recommended), e.g., `baseline_coopt`:
    python3 step9b_cooptimize_pv_battery.py \
      --base-input-dir data/loadprofiles \
      --base-output-dir data/loadprofiles \
      --scenario baseline_coopt \
      --housing-type single-family-detached \
      --counties alameda los-angeles

- Override retail plan and allow grid charging and battery exports (if desired):
    python3 step9b_cooptimize_pv_battery.py \
      --scenario baseline_coopt \
      --housing-type single-family-detached \
      --counties alameda \
      --plan E-TOU-D \
      --allow-grid-charging \
      --allow-batt-export

Flags / configuration
- --base-input-dir (default: data/loadprofiles)
  Root where county inputs live: weather_TMY_<county>.csv and combined_profiles_<scenario>_<county>.csv
- --base-output-dir (default: data/loadprofiles)
  Root where step outputs are written under <scenario>/<housing_type>/<county>
- --scenario (required)
  Scenario folder to read/write (use a separate scenario like baseline_coopt to keep results clean)
- --housing-type (default: single-family-detached)
- --counties <list>
  County slugs or names; if omitted, auto-discovers folders under the scenario path
- --plan <name>
  Retail plan for the resolved utility (e.g., PG&E: E-TOU-D; SCE: TOU-D-4-9PM; SDG&E: TOU-ELEC). Defaults to the first plan found for the utility.
- --allow-grid-charging
  Enable Grid→Battery charging (off by default)
- --allow-batt-export
  Enable Battery→Grid exports (off by default — many utilities prohibit crediting non‑PV exports)
- --discount-rate (default: 0.07)
- --pv-capex-kw (default: 2830.0 $/kW)
- --batt-capex-kwh (default: 800.0 $/kWh)
- --batt-capex-kw (default: 0.0 $/kW)
- --pv-life-yrs (default: 25)
- --batt-life-yrs (default: 15)
- --batt-degrade-cost-kwh (default: 0.0 $/kWh throughput)

Assumptions
- Full‑year (8760) optimization for fidelity (SOC chronology). A 12×24 time‑slice variant can be added later.
- Annualized capex via CRF with discount rate and lifetimes above.
- Solver: PuLP (CBC). If PuLP is missing, a clear error is raised with installation instructions.
"""

from __future__ import annotations

import argparse
import os
from typing import List, Optional, Tuple

import pandas as pd

try:
    import pulp
except Exception as e:
    pulp = None

from datetime import datetime, timedelta

from helpers.main_helpers import (
    get_counties,
    get_scenario_path,
    slugify_county_name,
)
from helpers.utility_helpers import get_utility_for_county
from helpers.nem3_export_rates import get_export_rate_table_for_county
from helpers.electricity_rate_helpers import PGE_RATE_PLANS, SCE_RATE_PLANS, SDGE_RATE_PLANS

from step9_solar_storage_dispatch_core import (
    prepare_weather_and_load,
    pv_timeseries_ac_kwh,
    PR_BASE,
)


RATE_PLANS = {
    "PG&E": PGE_RATE_PLANS,
    "SCE": SCE_RATE_PLANS,
    "SDG&E": SDGE_RATE_PLANS,
}


def _timestamp_index_8760(year: int = 2018) -> List[pd.Timestamp]:
    start = datetime(year=year, month=1, day=1)
    return [start + timedelta(hours=h) for h in range(8760)]


def _hourly_import_rate(plan_details: dict, ts: pd.Timestamp) -> float:
    month = ts.month
    # Season mapping: consistent with step12 (Jun–Sep = summer)
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


def _ensure_pulp():
    if pulp is None:
        raise RuntimeError(
            "PuLP is not installed. Install with: pip install pulp (or use cvxpy/pyomo variant)."
        )


def _solve_lp(
    L: List[float],
    G: List[float],
    p_imp: List[float],
    p_exp: List[float],
    *,
    allow_grid_charging: bool = False,
    allow_batt_export: bool = False,
    c_pv_kw: float = 2830.0,           # $/kW
    c_batt_kwh: float = 800.0,         # $/kWh (approx, configurable)
    c_batt_kw: float = 0.0,            # $/kW PCS/inverter (optional)
    pv_life_yrs: int = 25,
    batt_life_yrs: int = 15,
    discount_rate: float = 0.07,
    c_deg_per_kwh: float = 0.0,        # degradation cost per kWh throughput
) -> Tuple[float, float, List[float]]:
    """Build and solve LP. Returns (PV_kw, B_E_kWh, flows vector pack).

    The flows vector pack is a list of per‑hour arrays in this order:
      [pv2load, pv2batt, pv2grid, batt2load, batt2grid, grid2load, grid2batt, soc]
    """
    _ensure_pulp()
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

    # Operating bill (imports − exports) + degradation
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
    PV_kw_val = float(pulp.value(PV_kw))
    B_E_val = float(pulp.value(B_E))
    flows = [
        [float(v.value()) for v in pv2load],
        [float(v.value()) for v in pv2batt],
        [float(v.value()) for v in pv2grid],
        [float(v.value()) for v in batt2load],
        [float(v.value()) for v in batt2grid],
        [float(v.value()) for v in grid2load],
        [float(v.value()) for v in grid2batt],
        [float(v.value()) for v in soc],
    ]
    return PV_kw_val, B_E_val, flows


def _write_step9_outputs(
    out_dir: str,
    county: str,
    timestamps: List[pd.Timestamp],
    L: List[float],
    G: List[float],
    PV_kw: float,
    flows: List[List[float]],
):
    # flows unpack
    pv2load, pv2batt, pv2grid, batt2load, batt2grid, grid2load, grid2batt, soc = flows
    pv_ac = [PV_kw * g for g in G]
    total_supply = [pl + bl + gl for pl, bl, gl in zip(pv2load, batt2load, grid2load)]
    diff = [ts - ll for ts, ll in zip(total_supply, L)]

    base_cols = {
        "timestamp": timestamps,
        "Load Profile": L,
        "System to Load": pv2load,
        "Battery to Load": batt2load,
        "Grid to Load": grid2load,
        "Solar + Battery to Load": [pl + bl for pl, bl in zip(pv2load, batt2load)],
        "Total Supply": total_supply,
        "Difference": diff,
        "System to Battery": pv2batt,
        "Grid to Battery": grid2batt,
        "Battery SOC": soc,
        "PV AC (kWh)": pv_ac,
        "PV to Grid (kWh)": pv2grid,
        # New: write battery export flow explicitly for downstream accounting
        "Battery to Grid (kWh)": batt2grid,
    }
    base_df = pd.DataFrame(base_cols)

    # Write base
    out_base = os.path.join(out_dir, f"sam_optimized_load_profiles_{county}.csv")
    base_df.to_csv(out_base, index=False)

    # Exports file (preferred by Step 10)
    # Exports = PV→Grid + Battery→Grid when battery export is allowed
    exp_df = pd.DataFrame({
        "timestamp": timestamps,
        "Exports to Grid (kWh)": [pg + bg for pg, bg in zip(pv2grid, batt2grid)],
    })
    out_exp = os.path.join(out_dir, f"sam_optimized_load_profiles_with_exports_{county}.csv")
    exp_df.to_csv(out_exp, index=False)


def _default_plan_for_utility(util: str) -> str:
    plans = list(RATE_PLANS.get(util, {}).keys())
    if not plans:
        return ""
    return plans[0]


def process(
    base_input_dir: str,
    base_output_dir: str,
    scenario: str,
    housing_type: str,
    counties: Optional[List[str]] = None,
    *,
    plan_override: Optional[str] = None,
    allow_grid_charging: bool = False,
    allow_batt_export: bool = False,
    discount_rate: float = 0.07,
    pv_capex_per_kw: float = 2830.0,
    batt_capex_per_kwh: float = 800.0,
    batt_capex_per_kw: float = 0.0,
    pv_life_yrs: int = 25,
    batt_life_yrs: int = 15,
    batt_degrade_cost_per_kwh: float = 0.0,
) -> None:
    scenario_path = get_scenario_path(base_input_dir, scenario, housing_type)
    counties_to_run = get_counties(scenario_path, counties)

    for county in counties_to_run:
        county_slug = slugify_county_name(county)
        out_dir = os.path.join(base_output_dir, scenario, housing_type, county_slug)
        os.makedirs(out_dir, exist_ok=True)

        # Weather + load (aligned to 8760)
        weather_file = os.path.join(base_input_dir, scenario, housing_type, county_slug, f"weather_TMY_{county_slug}.csv")
        load_file = os.path.join(scenario_path, county_slug, f"combined_profiles_{scenario}_{county_slug}.csv")
        if not (os.path.exists(weather_file) and os.path.exists(load_file)):
            print(f"[step9b] Missing inputs for {county_slug}; skipping.")
            continue

        weather_df, load_kwh = prepare_weather_and_load(weather_file, load_file, "electricity.real_and_simulated.for_typical_county_home.kwh")
        if len(load_kwh) != 8760:
            print(f"[step9b] Non‑8760 load for {county_slug}; length={len(load_kwh)} — skipping.")
            continue
        # PV per‑kW AC energy
        G = pv_timeseries_ac_kwh(weather_df, 1.0)
        if len(G) != 8760:
            print(f"[step9b] Non‑8760 weather for {county_slug}; length={len(G)} — skipping.")
            continue

        # Utility + rates
        util = get_utility_for_county(county_slug)
        if not util:
            print(f"[step9b] No utility for county {county_slug}; skipping.")
            continue
        plan_name = plan_override or _default_plan_for_utility(util)
        plan_details = RATE_PLANS.get(util, {}).get(plan_name)
        if not plan_details:
            print(f"[step9b] No plan details found for utility={util}, plan={plan_name}; skipping.")
            continue

        # NEM3 export table month×hour
        export_table = get_export_rate_table_for_county(base_dir=os.path.join("data", "NEM3"), utility=util, county_name_or_slug=county_slug)

        # Prices per hour
        ts_index = _timestamp_index_8760(2018)
        p_imp = [_hourly_import_rate(plan_details, ts) for ts in ts_index]
        p_exp = [float(export_table[ts.month][ts.hour]) for ts in ts_index]

        # Solve LP
        PV_kw, B_E_kWh, flows = _solve_lp(
            L=load_kwh,
            G=G,
            p_imp=p_imp,
            p_exp=p_exp,
            allow_grid_charging=allow_grid_charging,
            allow_batt_export=allow_batt_export,
            c_pv_kw=pv_capex_per_kw,
            c_batt_kwh=batt_capex_per_kwh,
            c_batt_kw=batt_capex_per_kw,
            pv_life_yrs=pv_life_yrs,
            batt_life_yrs=batt_life_yrs,
            discount_rate=discount_rate,
            c_deg_per_kwh=batt_degrade_cost_per_kwh,
        )

        # Write outputs (Step 9 compatibility)
        _write_step9_outputs(out_dir, county_slug, ts_index, load_kwh, G, PV_kw, flows)
        print(f"[step9b] {county_slug}: PV={PV_kw:.2f} kW, Battery={B_E_kWh:.2f} kWh")


def main():
    p = argparse.ArgumentParser(description="Step 9b: Co‑optimize PV/Battery sizing and hourly dispatch")
    p.add_argument("--base-input-dir", default="data/loadprofiles")
    p.add_argument("--base-output-dir", default="data/loadprofiles")
    p.add_argument("--scenario", required=True)
    p.add_argument("--housing-type", default="single-family-detached")
    p.add_argument("--counties", nargs="*")
    p.add_argument("--plan", help="Override plan name for the resolved utility (e.g., E-TOU-D, TOU-D-4-9PM)")
    p.add_argument("--allow-grid-charging", action="store_true")
    p.add_argument("--allow-batt-export", action="store_true")
    p.add_argument("--discount-rate", type=float, default=0.07)
    p.add_argument("--pv-capex-kw", type=float, default=2830.0)
    p.add_argument("--batt-capex-kwh", type=float, default=800.0)
    p.add_argument("--batt-capex-kw", type=float, default=0.0)
    p.add_argument("--pv-life-yrs", type=int, default=25)
    p.add_argument("--batt-life-yrs", type=int, default=15)
    p.add_argument("--batt-degrade-cost-kwh", type=float, default=0.0)
    args = p.parse_args()

    process(
        base_input_dir=args.base_input_dir,
        base_output_dir=args.base_output_dir,
        scenario=args.scenario,
        housing_type=args.housing_type,
        counties=args.counties,
        plan_override=args.plan,
        allow_grid_charging=args.allow_grid_charging,
        allow_batt_export=args.allow_batt_export,
        discount_rate=args.discount_rate,
        pv_capex_per_kw=args.pv_capex_kw,
        batt_capex_per_kwh=args.batt_capex_kwh,
        batt_capex_per_kw=args.batt_capex_kw,
        pv_life_yrs=args.pv_life_yrs,
        batt_life_yrs=args.batt_life_yrs,
        batt_degrade_cost_per_kwh=args.batt_degrade_cost_kwh,
    )


if __name__ == "__main__":
    main()
