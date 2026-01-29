"""
Step 9b — Co‑Optimize PV size, Battery size (kWh,kW), and hourly dispatch.

This module builds a linear program (LP) to minimize annual total cost:
  annualized capex (PV + battery) + retail imports − NEM3 export credits (+ optional degradation cost)

Notes
- CSV‑only NEM3 export tables are loaded via helpers.nem3_export_rates
- Retail import price is built from helpers.electricity_rate_helpers plans
- Weather→PV per‑kW yield is computed using Step 9 core helpers (GHI‑based PVWatts‑style)

Outputs (per county)
- solar_storage_dispatch_profiles_<county>.csv
- solar_storage_dispatch_profiles_with_exports_<county>.csv

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
- --allow-batt-export / --disallow-batt-export
  Enable or disable Battery→Grid exports (default: enabled)
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
from typing import List, Optional

import pandas as pd

from helpers.main_helpers import (
    get_counties,
    get_scenario_path,
    slugify_county_name,
)
from helpers.utility_helpers import get_utility_for_county
from helpers.nem3_export_rates import get_export_rate_table_for_county
from helpers.electricity_rate_helpers import PGE_RATE_PLANS, SCE_RATE_PLANS, SDGE_RATE_PLANS

from .step9_solar_storage_dispatch_core import (
    prepare_weather_and_load,
    pv_timeseries_ac_kwh,
)
from .step9b_cooptimize_core import (
    CooptInputs,
    FlowSeries,
    _hourly_import_rate,
    _solve_lp,
    _timestamp_index_8760,
)


RATE_PLANS = {
    "PG&E": PGE_RATE_PLANS,
    "SCE": SCE_RATE_PLANS,
    "SDG&E": SDGE_RATE_PLANS,
}


def _write_step9_outputs(
    out_dir: str,
    county: str,
    timestamps: List[pd.Timestamp],
    L: List[float],
    G: List[float],
    PV_kw: float,
    flows: FlowSeries,
):
    # flows unpack
    pv2load = flows.pv_to_load
    pv2batt = flows.pv_to_batt
    pv2grid = flows.pv_to_grid
    batt2load = flows.batt_to_load
    batt2grid = flows.batt_to_grid
    grid2load = flows.grid_to_load
    grid2batt = flows.grid_to_batt
    soc = flows.soc
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
    out_base = os.path.join(out_dir, f"solar_storage_dispatch_profiles_{county}.csv")
    base_df.to_csv(out_base, index=False)

    # Exports file (preferred by Step 10)
    # Exports = PV→Grid + Battery→Grid when battery export is allowed
    exp_df = pd.DataFrame({
        "timestamp": timestamps,
        "Exports to Grid (kWh)": [pg + bg for pg, bg in zip(pv2grid, batt2grid)],
    })
    out_exp = os.path.join(out_dir, f"solar_storage_dispatch_profiles_with_exports_{county}.csv")
    exp_df.to_csv(out_exp, index=False)


def _write_price_diagnostics(
    out_dir: str,
    county: str,
    timestamps: List[pd.Timestamp],
    p_imp: List[float],
    p_exp: List[float],
) -> None:
    if len(p_imp) != len(p_exp) or len(p_imp) != len(timestamps):
        raise ValueError("Price diagnostics requires aligned timestamps and price arrays.")

    diag_df = pd.DataFrame({
        "timestamp": timestamps,
        "import_price_usd_per_kwh": p_imp,
        "export_price_usd_per_kwh": p_exp,
    })
    diag_path = os.path.join(out_dir, f"coopt_price_series_{county}.csv")
    diag_df.to_csv(diag_path, index=False)

    stats = diag_df[["import_price_usd_per_kwh", "export_price_usd_per_kwh"]].describe(
        percentiles=[0.05, 0.5, 0.95]
    )
    stats_path = os.path.join(out_dir, f"coopt_price_stats_{county}.csv")
    stats.to_csv(stats_path)

    print(
        f"[step9b] Price stats for {county} "
        f"(import min/median/max=${stats.loc['min', 'import_price_usd_per_kwh']:.3f}/"
        f"{stats.loc['50%', 'import_price_usd_per_kwh']:.3f}/"
        f"{stats.loc['max', 'import_price_usd_per_kwh']:.3f}, "
        f"export min/median/max=${stats.loc['min', 'export_price_usd_per_kwh']:.3f}/"
        f"{stats.loc['50%', 'export_price_usd_per_kwh']:.3f}/"
        f"{stats.loc['max', 'export_price_usd_per_kwh']:.3f})"
    )

    try:
        import matplotlib.pyplot as plt

        diag_df["month"] = diag_df["timestamp"].dt.month
        monthly = diag_df.groupby("month")[["import_price_usd_per_kwh", "export_price_usd_per_kwh"]].mean()

        fig, axes = plt.subplots(2, 1, figsize=(10, 6), tight_layout=True)
        axes[0].plot(monthly.index, monthly["import_price_usd_per_kwh"], label="Import ($/kWh)", color="#1f77b4")
        axes[0].plot(monthly.index, monthly["export_price_usd_per_kwh"], label="Export ($/kWh)", color="#ff7f0e")
        axes[0].set_xlabel("Month")
        axes[0].set_ylabel("Avg Price ($/kWh)")
        axes[0].set_title("Monthly Average Prices")
        axes[0].legend()

        axes[1].hist(
            p_imp,
            bins=40,
            alpha=0.7,
            label="Import ($/kWh)",
            color="#1f77b4",
        )
        axes[1].hist(
            p_exp,
            bins=40,
            alpha=0.7,
            label="Export ($/kWh)",
            color="#ff7f0e",
        )
        axes[1].set_xlabel("Price ($/kWh)")
        axes[1].set_ylabel("Hours")
        axes[1].set_title("Price Distribution")
        axes[1].legend()

        fig_path = os.path.join(out_dir, f"coopt_price_diagnostics_{county}.png")
        fig.savefig(fig_path, dpi=150)
        plt.close(fig)
    except Exception as e:
        raise RuntimeError(f"Failed to write price diagnostics plot: {e}")


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
    allow_batt_export: bool = True,
    debug_prices: bool = False,
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
    capacity_records = []

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

        if debug_prices:
            _write_price_diagnostics(out_dir, county_slug, ts_index, p_imp, p_exp)

        # Solve LP
        inputs = CooptInputs(
            load_kwh=load_kwh,
            pv_gen_per_kw=G,
            import_rates=p_imp,
            export_rates=p_exp,
        )
        result = _solve_lp(
            inputs,
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
        _write_step9_outputs(out_dir, county_slug, ts_index, load_kwh, G, result.pv_kw, result.flows)
        print(f"[step9b] {county_slug}: PV={result.pv_kw:.2f} kW, Battery={result.batt_kwh:.2f} kWh")

        # Collect capacity summary for diagnostics cards
        capacity_records.append({
            "County": county_slug,
            "Solar Capacity (kW)": round(result.pv_kw, 2),
            "Battery Capacity (kWh)": round(result.batt_kwh, 2),
            "Battery Power Capacity (kW)": round(result.batt_kw, 2),
            "Coopt Total Cost": round(result.total_cost, 4),
            "Coopt Capex Annual": round(result.capex_annual, 4),
            "Coopt Import Cost": round(result.import_cost, 4),
            "Coopt Export Credit": round(result.export_credit, 4),
            "Coopt Degradation Cost": round(result.degradation_cost, 4),
            "Allow Grid Charging": bool(allow_grid_charging),
            "Allow Battery Export": bool(allow_batt_export),
        })

    # Write/merge capacity summary CSV for the scenario (compatible path with Step 9 diagnostics)
    try:
        if capacity_records:
            cap_dir = os.path.join(base_output_dir, scenario, housing_type, "CAPITAL_COSTS")
            os.makedirs(cap_dir, exist_ok=True)
            cap_path = os.path.join(cap_dir, "electrified_assets.csv")
            new_df = pd.DataFrame(capacity_records)
            if os.path.exists(cap_path):
                try:
                    old_df = pd.read_csv(cap_path)
                except Exception:
                    old_df = pd.DataFrame()
                # Merge on County (slug)
                if not old_df.empty:
                    # Drop overlapping counties in old, then append new
                    keep = [
                        r for _, r in old_df.iterrows()
                        if str(r.get("County", "")).strip().lower() not in set(new_df["County"].astype(str).str.lower())
                    ]
                    if keep:
                        old_kept = pd.DataFrame(keep)
                        merged = pd.concat([old_kept, new_df], ignore_index=True)
                    else:
                        merged = new_df
                else:
                    merged = new_df
                merged.to_csv(cap_path, index=False)
            else:
                new_df.to_csv(cap_path, index=False)
    except Exception as e:
        print(f"[step9b] Warning: could not write/merge capacity summary CSV: {e}")


# Where is the total cost for the co-optimized values?
def main():
    p = argparse.ArgumentParser(description="Step 9b: Co‑optimize PV/Battery sizing and hourly dispatch")
    p.add_argument("--base-input-dir", default="data/loadprofiles")
    p.add_argument("--base-output-dir", default="data/loadprofiles")
    p.add_argument("--scenario", required=True)
    p.add_argument("--housing-type", default="single-family-detached")
    p.add_argument("--counties", nargs="*")
    p.add_argument("--plan", help="Override plan name for the resolved utility (e.g., E-TOU-D, TOU-D-4-9PM)")
    p.add_argument("--allow-grid-charging", action="store_true")
    # Battery export flags (default: enabled)
    p.add_argument("--allow-batt-export", dest="allow_batt_export", action="store_true", default=True,
                   help="Allow Battery→Grid exports (default: enabled)")
    p.add_argument("--disallow-batt-export", dest="allow_batt_export", action="store_false",
                   help="Disable Battery→Grid exports")
    p.add_argument("--debug-prices", action="store_true", help="Write price diagnostics CSV/plot for each county")
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
        debug_prices=args.debug_prices,
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
