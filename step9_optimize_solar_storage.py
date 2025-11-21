"""
Step 9 (Optimization): Explicit PV + Storage size optimization under NEM3

Find solar_kw and battery_kwh that minimize annualized cost (EAC):
  EAC = Bill_NEM3(imports, exports, plan) + annualized_capex(PV, Battery)

For each county and utility, enumerate import plans and solve a 2D continuous
optimization problem over (solar_kw, battery_kwh). Use SciPy if available;
otherwise fall back to a simple coordinate-descent with golden-section search.

Outputs per county: data/loadprofiles/<scenario>/<housing_type>/<county>/
  optimized_sizes_<county>.csv with best plan and per-plan results.
"""

from __future__ import annotations

import argparse
import math
import os
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import pandas as pd

from helpers.main_helpers import (
    get_scenario_path,
    get_counties,
    slugify_county_name,
    log,
)
from helpers.utility_helpers import get_utility_for_county
from helpers.electricity_rate_helpers import PGE_RATE_PLANS, SCE_RATE_PLANS, SDGE_RATE_PLANS
from helpers.nem3_export_rates import (
    get_export_rate_table_for_county,
    default_options_for_utility,
    NEM3Options,
)
from step9_solar_storage_dispatch_core import (
    prepare_weather_and_load,
    pv_timeseries_ac_kwh,
    battery_dispatch_dynamic,
    temp_battery_capacity_kwh,
    compute_system_capacity_kW,
)
from step12_evaluate_electricity_rates import calculate_nem3_annual_costs


# Constants
TOTAL_LOAD_COLUMN_NAME = "electricity.real_and_simulated.for_typical_county_home.kwh"


def _rate_plans_for_utility(utility: str) -> List[str]:
    if utility == "PG&E":
        return list(PGE_RATE_PLANS.keys())
    if utility == "SCE":
        return list(SCE_RATE_PLANS.keys())
    if utility == "SDG&E":
        return list(SDGE_RATE_PLANS.keys())
    raise ValueError(f"Unknown utility: {utility}")


@dataclass
class CapexParams:
    pv_per_kw: float = 2500.0
    batt_per_kwh: float = 600.0


@dataclass
class OandMParams:
    pv_per_kw: float = 25.0
    batt_per_kwh: float = 10.0


@dataclass
class Incentives:
    pv: float = 0.0
    batt: float = 0.0


@dataclass
class Lifetimes:
    pv: int = 25
    batt: int = 10


@dataclass
class Bounds:
    solar_kw: Tuple[float, float]
    battery_kwh: Tuple[float, float]


@dataclass
class CountyContext:
    base_input_dir: str
    scenario: str
    housing_type: str
    county_slug: str
    utility: str
    weather_df: pd.DataFrame
    load_kwh: List[float]
    timestamps: pd.DatetimeIndex
    acc_table: Dict
    nem3_options: NEM3Options
    capex: CapexParams
    oam: OandMParams
    incentives: Incentives
    lifetimes: Lifetimes
    discount_rate: float
    bounds: Bounds


def _crf(r: float, n: int) -> float:
    if r <= 0:
        return 1.0 / max(1, n)
    return r * (1 + r) ** n / ((1 + r) ** n - 1)


def simulate_flows(solar_kw: float, battery_kwh: float, ctx: CountyContext) -> Tuple[List[float], List[float]]:
    pv = pv_timeseries_ac_kwh(ctx.weather_df, solar_kw)
    with temp_battery_capacity_kwh(battery_kwh):
        grid_demand, batt_charge, batt_discharge, grid_to_load, grid_to_batt, pv_to_batt, soc = battery_dispatch_dynamic(
            ctx.load_kwh, pv
        )
    system_to_load = [min(p, l) for p, l in zip(pv, ctx.load_kwh)]
    pv_exports = [max(0.0, float(p) - float(a) - float(b)) for p, a, b in zip(pv, system_to_load, pv_to_batt)]
    imports = [float(gl) + float(gb) for gl, gb in zip(grid_to_load, grid_to_batt)]
    return imports, pv_exports


def annualized_capex(solar_kw: float, battery_kwh: float, ctx: CountyContext) -> Tuple[float, float, float]:
    cap_pv = _crf(ctx.discount_rate, ctx.lifetimes.pv) * max(0.0, ctx.capex.pv_per_kw * solar_kw - ctx.incentives.pv) + ctx.oam.pv_per_kw * solar_kw
    cap_b = _crf(ctx.discount_rate, ctx.lifetimes.batt) * max(0.0, ctx.capex.batt_per_kwh * battery_kwh - ctx.incentives.batt) + ctx.oam.batt_per_kwh * battery_kwh
    return cap_pv + cap_b, cap_pv, cap_b


def nem3_bill(imports: List[float], exports: List[float], plan: str, ctx: CountyContext) -> float:
    res = calculate_nem3_annual_costs(
        ctx.timestamps,
        imports,
        exports,
        ctx.utility,
        plan,
        options=ctx.nem3_options,
        export_table=ctx.acc_table,
    )
    return float(res.get(plan, 0.0))


def eac_for_plan(x: Tuple[float, float], plan: str, ctx: CountyContext) -> float:
    # clip to bounds
    s = max(ctx.bounds.solar_kw[0], min(ctx.bounds.solar_kw[1], float(x[0])))
    b = max(ctx.bounds.battery_kwh[0], min(ctx.bounds.battery_kwh[1], float(x[1])))
    imports, exports = simulate_flows(s, b, ctx)
    bill = nem3_bill(imports, exports, plan, ctx)
    cap_total, _, _ = annualized_capex(s, b, ctx)
    return bill + cap_total


def _try_scipy_optimize(plan: str, ctx: CountyContext) -> Optional[Tuple[List[float], float]]:
    try:
        from scipy.optimize import differential_evolution, minimize

        bounds = [ctx.bounds.solar_kw, ctx.bounds.battery_kwh]
        # Global search with differential evolution, limited iterations
        de_res = differential_evolution(lambda v: eac_for_plan(v, plan, ctx), bounds=bounds, maxiter=20, polish=False)
        x0 = list(de_res.x)
        # Local refine with Powell
        pow_res = minimize(lambda v: eac_for_plan(v, plan, ctx), x0=x0, method="Powell")
        x = list(pow_res.x)
        val = float(pow_res.fun)
        return [float(x[0]), float(x[1])], val
    except Exception:
        return None


def _golden_section_1d(f, a: float, b: float, tol: float = 1e-2, maxiter: int = 50) -> Tuple[float, float]:
    invphi = (math.sqrt(5) - 1) / 2  # 1/phi
    invphi2 = (3 - math.sqrt(5)) / 2  # 1/phi^2
    (a, b) = (float(a), float(b))
    h = b - a
    if h <= tol:
        x = (a + b) / 2.0
        return x, f(x)
    n = int(math.ceil(math.log(tol / h) / math.log(invphi)))
    c = a + invphi2 * h
    d = a + invphi * h
    yc = f(c)
    yd = f(d)
    for _ in range(min(maxiter, n)):
        if yc < yd:
            b, d, yd = d, c, yc
            h = invphi * h
            c = a + invphi2 * h
            yc = f(c)
        else:
            a, c, yc = c, d, yd
            h = invphi * h
            d = a + invphi * h
            yd = f(d)
    x = (a + b) / 2.0
    return x, f(x)


def _coordinate_descent(plan: str, ctx: CountyContext, restarts: List[float]) -> Tuple[List[float], float]:
    best_x, best_val = None, float("inf")
    # Initial PV guess: 0.5 × PV_match
    pv_match = compute_system_capacity_kW(ctx.weather_df, ctx.load_kwh)
    pv_init = max(ctx.bounds.solar_kw[0], min(ctx.bounds.solar_kw[1], 0.5 * pv_match))
    for batt0 in restarts:
        x = [pv_init, max(ctx.bounds.battery_kwh[0], min(ctx.bounds.battery_kwh[1], batt0))]
        for _ in range(8):  # a few alternations are sufficient for well-behaved objectives
            # optimize solar_kw with battery fixed
            def f_s(s_kw: float) -> float:
                return eac_for_plan((s_kw, x[1]), plan, ctx)
            s_star, _ = _golden_section_1d(f_s, ctx.bounds.solar_kw[0], ctx.bounds.solar_kw[1])
            x[0] = s_star
            # optimize battery_kwh with solar fixed
            def f_b(b_kwh: float) -> float:
                return eac_for_plan((x[0], b_kwh), plan, ctx)
            b_star, _ = _golden_section_1d(f_b, ctx.bounds.battery_kwh[0], ctx.bounds.battery_kwh[1])
            x[1] = b_star
        val = eac_for_plan(tuple(x), plan, ctx)
        if val < best_val:
            best_x, best_val = list(x), float(val)
    return best_x or [pv_init, restarts[0]], best_val


def optimize_for_plan(plan: str, ctx: CountyContext) -> Tuple[List[float], float]:
    # Try SciPy if available
    res = _try_scipy_optimize(plan, ctx)
    if res is not None:
        return res
    # Fallback: coordinate descent
    return _coordinate_descent(plan, ctx, restarts=[0.0, 7.0, 13.5, 20.0])


def process(
    base_input_dir: str,
    base_output_dir: str,
    scenario: str,
    housing_type: str,
    counties: Optional[List[str]] = None,
    *,
    discount_rate: float = 0.06,
    pv_capex_per_kw: float = 2500.0,
    batt_capex_per_kwh: float = 600.0,
    pv_oam_per_kw: float = 25.0,
    batt_oam_per_kwh: float = 10.0,
    pv_incentive: float = 0.0,
    batt_incentive: float = 0.0,
    pv_life: int = 25,
    batt_life: int = 10,
    pv_kw_max_multiplier: float = 2.0,
    batt_kwh_max: float = 30.0,
) -> List[str]:
    scen_path = get_scenario_path(base_input_dir, scenario, housing_type)
    county_names = get_counties(scen_path, counties)
    written: List[str] = []

    for county in county_names:
        try:
            county_slug = slugify_county_name(county)
            utility = get_utility_for_county(county)
            plans = _rate_plans_for_utility(utility)

            county_dir = os.path.join(base_input_dir, scenario, housing_type, county_slug)
            weather_file = os.path.join(county_dir, f"weather_TMY_{county_slug}.csv")
            load_file = os.path.join(scen_path, county_slug, f"combined_profiles_{scenario}_{county_slug}.csv")
            if not os.path.exists(weather_file) or not os.path.exists(load_file):
                print(f"Missing inputs for {county_slug}; skipping")
                continue
            weather_df, load_kwh = prepare_weather_and_load(weather_file, load_file, TOTAL_LOAD_COLUMN_NAME)
            ts = pd.date_range(start="2018-01-01", periods=8760, freq="H")

            # Bounds: PV max defaults to 2 × PV-match size
            pv_match_kw = compute_system_capacity_kW(weather_df, load_kwh)
            bnds = Bounds(
                solar_kw=(0.0, max(0.1, pv_kw_max_multiplier * float(pv_match_kw))),
                battery_kwh=(0.0, float(batt_kwh_max)),
            )

            # ACC table, NEM3 options
            acc_table = get_export_rate_table_for_county(base_dir=os.path.join("data", "NEM3"), utility=utility, county_name_or_slug=county_slug)
            nem3_opts = default_options_for_utility(utility)

            ctx = CountyContext(
                base_input_dir=base_input_dir,
                scenario=scenario,
                housing_type=housing_type,
                county_slug=county_slug,
                utility=utility,
                weather_df=weather_df,
                load_kwh=load_kwh,
                timestamps=ts,
                acc_table=acc_table,
                nem3_options=nem3_opts,
                capex=CapexParams(pv_per_kw=pv_capex_per_kw, batt_per_kwh=batt_capex_per_kwh),
                oam=OandMParams(pv_per_kw=pv_oam_per_kw, batt_per_kwh=batt_oam_per_kwh),
                incentives=Incentives(pv=pv_incentive, batt=batt_incentive),
                lifetimes=Lifetimes(pv=pv_life, batt=batt_life),
                discount_rate=float(discount_rate),
                bounds=bnds,
            )

            rows = []
            best_plan, best_val, best_x = None, float("inf"), None
            for plan in plans:
                x_p, val_p = optimize_for_plan(plan, ctx)
                s, b = float(x_p[0]), float(x_p[1])
                imports, exports = simulate_flows(s, b, ctx)
                bill = nem3_bill(imports, exports, plan, ctx)
                cap_total, cap_pv, cap_b = annualized_capex(s, b, ctx)
                rows.append({
                    "plan": plan,
                    "solar_kw": s,
                    "battery_kwh": b,
                    "eac_total": val_p,
                    "bill_nem3": bill,
                    "capex_annual_pv": cap_pv,
                    "capex_annual_batt": cap_b,
                })
                if val_p < best_val:
                    best_plan, best_val, best_x = plan, val_p, (s, b)

            out = pd.DataFrame(rows)
            out["best"] = [row["plan"] == best_plan for _, row in out.iterrows()]
            out_path = os.path.join(base_input_dir, scenario, housing_type, county_slug, f"optimized_sizes_{county_slug}.csv")
            out.to_csv(out_path, index=False)
            written.append(out_path)
            log(at="step9_optimize_solar_storage", county=county_slug, best_plan=best_plan, solar_kw=best_x[0] if best_x else None, battery_kwh=best_x[1] if best_x else None, saved_to=out_path)
        except Exception as e:
            print(f"Optimization failed for {county}: {e}")

    return written


def main() -> None:
    p = argparse.ArgumentParser(description="Optimize PV and Storage sizes under NEM3")
    p.add_argument("--base-input-dir", default="data/loadprofiles")
    p.add_argument("--base-output-dir", default="data/loadprofiles")
    p.add_argument("--scenario", default="baseline")
    p.add_argument("--housing-type", default="single-family-detached")
    p.add_argument("--counties", nargs="*")
    # Financial params
    p.add_argument("--discount-rate", type=float, default=0.06)
    p.add_argument("--pv-capex-per-kw", type=float, default=2500.0)
    p.add_argument("--batt-capex-per-kwh", type=float, default=600.0)
    p.add_argument("--pv-oam-per-kw", type=float, default=25.0)
    p.add_argument("--batt-oam-per-kwh", type=float, default=10.0)
    p.add_argument("--pv-incentive", type=float, default=0.0)
    p.add_argument("--batt-incentive", type=float, default=0.0)
    p.add_argument("--pv-life", type=int, default=25)
    p.add_argument("--batt-life", type=int, default=10)
    # Bounds
    p.add_argument("--pv-kw-max-multiplier", type=float, default=2.0)
    p.add_argument("--batt-kwh-max", type=float, default=30.0)
    args = p.parse_args()

    counties = args.counties
    process(
        base_input_dir=args.base_input_dir,
        base_output_dir=args.base_output_dir,
        scenario=args.scenario,
        housing_type=args.housing_type,
        counties=counties,
        discount_rate=args.discount_rate,
        pv_capex_per_kw=args.pv_capex_per_kw,
        batt_capex_per_kwh=args.batt_capex_per_kwh,
        pv_oam_per_kw=args.pv_oam_per_kw,
        batt_oam_per_kwh=args.batt_oam_per_kwh,
        pv_incentive=args.pv_incentive,
        batt_incentive=args.batt_incentive,
        pv_life=args.pv_life,
        batt_life=args.batt_life,
        pv_kw_max_multiplier=args.pv_kw_max_multiplier,
        batt_kwh_max=args.batt_kwh_max,
    )


if __name__ == "__main__":
    main()

