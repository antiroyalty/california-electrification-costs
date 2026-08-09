"""
Helper: PV capex × battery capex grid sweep for co-optimized sizes.

Runs the Step 9b optimization model across a coarse grid of PV capex ($/kW)
and battery capex ($/kWh) for a single county, then writes:
- CSV with optimal PV/battery sizes and annualized cost components
- Single heatmap plot of total annual cost over the capex grid

Defaults are coarse for fast iteration.
"""

from __future__ import annotations

import argparse
import os
from dataclasses import dataclass
from typing import List, Optional, Tuple

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from helpers.main_helpers import get_scenario_path, slugify_county_name
from tariffs import NBTScenario, TariffCatalog, resolve_county_service_assignment
from tariffs.calendar import full_year_hourly_index
from pipeline.steps.step9_solar_storage_dispatch_core import (
    prepare_weather_and_load,
    pv_timeseries_ac_kwh,
)
from pipeline.steps.step9b_cooptimize_core import (
    CooptInputs,
    build_monthly_hourly_inputs,
    _solve_lp,
)


TOTAL_LOAD_COLUMN_NAME = "electricity.real_and_simulated.for_typical_county_home.kwh"


@dataclass
class GridSpec:
    pv_min: float
    pv_max: float
    pv_step: float
    batt_min: float
    batt_max: float
    batt_step: float


def _frange(start: float, stop: float, step: float) -> List[float]:
    if step <= 0:
        raise ValueError("Step must be > 0.")
    if start > stop:
        raise ValueError("Range start must be <= stop.")
    vals = []
    v = float(start)
    while v <= stop + 1e-9:
        vals.append(round(v, 10))
        v += step
    return vals


def _plot_heatmap(
    df: pd.DataFrame,
    x_key: str,
    y_key: str,
    z_key: str,
    out_path: str,
    title: str,
    xlabel: str,
    ylabel: str,
) -> None:
    piv = df.pivot(index=y_key, columns=x_key, values=z_key)
    x_vals = list(piv.columns)
    y_vals = list(piv.index)
    z = piv.values

    fig, ax = plt.subplots(figsize=(10.5, 6.0))
    im = ax.imshow(z, aspect="auto", origin="lower", interpolation="nearest", cmap="viridis")
    ax.set_xticks(range(len(x_vals)))
    ax.set_xticklabels([f"{v:g}" for v in x_vals])
    ax.set_yticks(range(len(y_vals)))
    ax.set_yticklabels([f"{v:g}" for v in y_vals])
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    ax.set_title(title)
    fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)

    try:
        min_idx = np.unravel_index(np.nanargmin(z), z.shape)
        iy, ix = int(min_idx[0]), int(min_idx[1])
        ax.scatter(ix, iy, s=48, c="red", marker="o", label="Min")
        ax.legend(loc="upper right", fontsize=8)
    except Exception:
        pass

    fig.tight_layout()
    fig.savefig(out_path, dpi=130)
    plt.close(fig)


def run(
    base_input_dir: str,
    experiments_root: str,
    scenario: str,
    housing_type: str,
    county: str,
    grid: GridSpec,
    *,
    plan_override: Optional[str],
    discount_rate: float,
    pv_life_yrs: int,
    batt_life_yrs: int,
    batt_capex_per_kw: float,
    allow_grid_charging: bool,
    allow_batt_export: bool,
    fine: bool,
    year: int,
    max_battery_kwh: float = 40.0,
) -> Tuple[str, str]:
    county_slug = slugify_county_name(county)
    scen_path = get_scenario_path(base_input_dir, scenario, housing_type)
    county_dir = os.path.join(scen_path, county_slug)
    weather_file = os.path.join(county_dir, f"weather_TMY_{county_slug}.csv")
    load_file = os.path.join(county_dir, f"combined_profiles_{scenario}_{county_slug}.csv")
    if not os.path.exists(weather_file):
        raise FileNotFoundError(f"Missing weather file: {weather_file}")
    if not os.path.exists(load_file):
        raise FileNotFoundError(f"Missing load file: {load_file}")

    weather_df, load_kwh = prepare_weather_and_load(weather_file, load_file, TOTAL_LOAD_COLUMN_NAME)
    if len(load_kwh) != 8760:
        raise ValueError(f"Expected 8760 hourly load values, got {len(load_kwh)}.")

    pv_gen_per_kw = pv_timeseries_ac_kwh(weather_df, 1.0)
    if len(pv_gen_per_kw) != 8760:
        raise ValueError(f"Expected 8760 PV hourly values, got {len(pv_gen_per_kw)}.")

    assignment = resolve_county_service_assignment(county_slug)
    nbt_scenario = NBTScenario(billing_year=year, nbt_vintage=year)
    tariff = TariffCatalog().bundle(assignment.utility, nbt_scenario, import_plan=plan_override)
    ts_index = full_year_hourly_index(year)
    p_imp = tariff.import_schedule.rates_for(ts_index)
    p_exp = [
        rate + tariff.acc_plus_rate
        for rate in tariff.export_schedule.rates_for(ts_index)
    ]

    inputs = CooptInputs(
        load_kwh=load_kwh,
        pv_gen_per_kw=pv_gen_per_kw,
        import_rates=p_imp,
        export_rates=p_exp,
    )

    weights = None
    cycle_monthly = False
    if not fine:
        inputs, weights = build_monthly_hourly_inputs(inputs, year=year)
        cycle_monthly = True

    pv_vals = _frange(grid.pv_min, grid.pv_max, grid.pv_step)
    batt_vals = _frange(grid.batt_min, grid.batt_max, grid.batt_step)

    records = []
    for pv_capex in pv_vals:
        for batt_capex in batt_vals:
            result = _solve_lp(
                inputs,
                allow_grid_charging=allow_grid_charging,
                allow_batt_export=allow_batt_export,
                c_pv_kw=pv_capex,
                c_batt_kwh=batt_capex,
                c_batt_kw=batt_capex_per_kw,
                pv_life_yrs=pv_life_yrs,
                batt_life_yrs=batt_life_yrs,
                discount_rate=discount_rate,
                c_deg_per_kwh=0.0,
                weights=weights,
                cycle_monthly=cycle_monthly,
                max_battery_kwh=max_battery_kwh,
            )
            records.append(
                {
                    "pv_capex_per_kw": float(pv_capex),
                    "batt_capex_per_kwh": float(batt_capex),
                    "pv_kw": float(result.pv_kw),
                    "batt_kwh": float(result.batt_kwh),
                    "batt_kw": float(result.batt_kw),
                    "total_cost": float(result.total_cost),
                    "capex_annual": float(result.capex_annual),
                    "import_cost": float(result.import_cost),
                    "export_credit": float(result.export_credit),
                    "degradation_cost": float(result.degradation_cost),
                    "max_battery_kwh": float(max_battery_kwh),
                    "meter_binary_count": int(result.meter_binary_count),
                    "solver_rounds": int(result.solver_rounds),
                }
            )

    if not records:
        raise RuntimeError("No results generated for the sweep.")

    out_dir = os.path.join(experiments_root, scenario, housing_type, county_slug)
    os.makedirs(out_dir, exist_ok=True)

    df = pd.DataFrame(records)
    csv_path = os.path.join(out_dir, f"capex_grid_{county_slug}.csv")
    df.to_csv(csv_path, index=False)

    png_path = os.path.join(out_dir, f"capex_grid_{county_slug}.png")
    title = (
        "Co-opt Total Cost: PV Capex × Battery Capex "
        f"({county_slug}, {tariff.import_schedule.plan_name})"
    )
    _plot_heatmap(
        df,
        x_key="pv_capex_per_kw",
        y_key="batt_capex_per_kwh",
        z_key="total_cost",
        out_path=png_path,
        title=title,
        xlabel="PV Capex ($/kW)",
        ylabel="Battery Capex ($/kWh)",
    )

    return csv_path, png_path


def main() -> None:
    p = argparse.ArgumentParser(description="PV capex × battery capex grid sweep (co-opt) for a county")
    p.add_argument("--base-input-dir", default="data/loadprofiles")
    p.add_argument("--experiments-root", default=os.path.join("data", "experiments", "capex_grid"))
    p.add_argument("--scenario", default="baseline_coopt")
    p.add_argument("--housing-type", default="single-family-detached")
    p.add_argument("--county", default="alameda")
    p.add_argument("--plan", help="Override plan name for resolved utility")
    # Capex grid (values are $/kW for PV, $/kWh for battery)
    p.add_argument("--pv-capex-min", type=float, default=1500.0)
    p.add_argument("--pv-capex-max", type=float, default=4000.0)
    p.add_argument("--pv-capex-step", type=float, default=250.0)
    p.add_argument("--batt-capex-min", type=float, default=500.0)
    p.add_argument("--batt-capex-max", type=float, default=1500.0)
    p.add_argument("--batt-capex-step", type=float, default=100.0)
    # Financial + solver params
    p.add_argument("--discount-rate", type=float, default=0.07)
    p.add_argument("--pv-life-yrs", type=int, default=25)
    p.add_argument("--batt-life-yrs", type=int, default=15)
    p.add_argument("--batt-capex-kw", type=float, default=0.0, help="Battery power capex ($/kW)")
    p.add_argument("--allow-grid-charging", action="store_true")
    p.add_argument(
        "--allow-batt-export",
        dest="allow_batt_export",
        action="store_true",
        default=True,
        help="Allow Battery→Grid exports (default: enabled)",
    )
    p.add_argument(
        "--disallow-batt-export",
        dest="allow_batt_export",
        action="store_false",
        help="Disable Battery→Grid exports",
    )
    p.add_argument(
        "--fine",
        action="store_true",
        help="Use full 8760 resolution (slower). Default is coarse monthly-hourly aggregation.",
    )
    p.add_argument("--year", type=int, default=2026)
    p.add_argument(
        "--max-battery-kwh",
        type=float,
        default=40.0,
        help="Explicit representative-household battery sizing ceiling (kWh)",
    )
    args = p.parse_args()

    grid = GridSpec(
        pv_min=args.pv_capex_min,
        pv_max=args.pv_capex_max,
        pv_step=args.pv_capex_step,
        batt_min=args.batt_capex_min,
        batt_max=args.batt_capex_max,
        batt_step=args.batt_capex_step,
    )

    csv_path, png_path = run(
        base_input_dir=args.base_input_dir,
        experiments_root=args.experiments_root,
        scenario=args.scenario,
        housing_type=args.housing_type,
        county=args.county,
        grid=grid,
        plan_override=args.plan,
        discount_rate=args.discount_rate,
        pv_life_yrs=args.pv_life_yrs,
        batt_life_yrs=args.batt_life_yrs,
        batt_capex_per_kw=args.batt_capex_kw,
        allow_grid_charging=args.allow_grid_charging,
        allow_batt_export=args.allow_batt_export,
        fine=args.fine,
        year=args.year,
        max_battery_kwh=args.max_battery_kwh,
    )

    print(f"Wrote CSV: {csv_path}")
    print(f"Wrote plot: {png_path}")


if __name__ == "__main__":
    main()
