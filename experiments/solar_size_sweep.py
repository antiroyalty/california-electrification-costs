"""
Experimental PV size sweep helper (does not alter the main pipeline).

Given a scenario, housing type, and counties, sweeps PV size as a fraction of the
"annual-energy match" size (e.g., 10%..100%) and records:
  - Annual flows (PV gross, PV→Load, PV→Battery, Battery→Load, Grid→Load, Grid→Battery)
  - PV capacity (kW)
  - PV capex estimates (base and after incentives)
  - Optional: total annual bill from rate engine (Step 10/11/13) written to a
    separate experiments tree so the main data/loadprofiles is unchanged.

Outputs are written under data/experiments/solar_size_sweep/...
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Iterable, List, Optional, Dict

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

from main_helpers import slugify_county_name, get_scenario_path, get_counties

# Reuse PV + dispatch implementation from Step 9 DIY
import step9_my_own_solar_storage as diy
from helpers.capital_costs_helper import get_solar_cost_params, calculate_solar_storage_cost, apply_solar_storage_incentives


@dataclass
class SweepOptions:
    enable_pv_surplus_to_battery: bool = True
    grid_charging_enabled: bool = True
    compute_bills: bool = False


def _paths_for_county(base_input_dir: str, scenario: str, housing_type: str, county: str) -> Dict[str, str]:
    county_slug = slugify_county_name(county)
    scen_path = get_scenario_path(base_input_dir, scenario, housing_type)
    return {
        "weather": os.path.join(scen_path, county_slug, f"weather_TMY_{county_slug}.csv"),
        "load":    os.path.join(scen_path, county_slug, f"combined_profiles_{scenario}_{county_slug}.csv"),
    }


def _collect_metrics(load_profile: List[float], pv: List[float], bc: List[float], bd: List[float], gtl: List[float], gtb: List[float], ptb: List[float]) -> Dict[str, float]:
    system_to_load = [min(s, l) for s, l in zip(pv, load_profile)]
    return {
        "pv_gross_kwh": float(sum(pv)),
        "pv_to_load_kwh": float(sum(system_to_load)),
        "pv_to_battery_kwh": float(sum(ptb)),
        "battery_to_load_kwh": float(sum(bd)),
        "grid_to_load_kwh": float(sum(gtl)),
        "grid_to_battery_kwh": float(sum(gtb)),
        "load_total_kwh": float(sum(load_profile)),
    }


def _pv_capex_rows(solar_kw: float, utility: Optional[str] = None) -> Dict[str, float]:
    # Pull parameters from capital cost helper
    dollars_per_watt, labour_pct, design_pct, storage_cost = get_solar_cost_params({
        # Using the NEW/CRIS structure is not required; get_solar_cost_params handles both formats.
        # Here we provide only enough structure to get the parameters from the configured helper.
        # If the helper uses global constants, these are ignored.
        "solar": {}, "storage": {}
    })
    base_total, _pv_only = calculate_solar_storage_cost(
        solar_kw, dollars_per_watt, labour_pct, design_pct, storage_cost=0.0
    )
    # Net with incentives for PV only (ITC); storage net (if included) left separate.
    pv_net = apply_solar_storage_incentives(base_total, utility or "")
    # If you want PV+Storage net, add storage_cost to base_total before calling apply_*.
    base_with_storage, _ = calculate_solar_storage_cost(
        solar_kw, dollars_per_watt, labour_pct, design_pct, storage_cost=storage_cost
    )
    pvst_net = apply_solar_storage_incentives(base_with_storage, utility or "")
    return {
        "pv_capex_base": float(base_total),
        "pv_capex_net": float(pv_net),
        "pvst_capex_base": float(base_with_storage),
        "pvst_capex_net": float(pvst_net),
    }


def _ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def _plot_summaries(df: pd.DataFrame, out_dir: str, county_slug: str) -> None:
    # Plot flows vs fraction
    fig, ax = plt.subplots(figsize=(8.5, 4.8))
    x = df["fraction"].values
    for col, color, label in [
        ("pv_to_load_kwh", "#ff7f0e", "PV→Load"),
        ("battery_to_load_kwh", "#2ca02c", "Battery→Load"),
        ("grid_to_load_kwh", "#7f7f7f", "Grid→Load"),
    ]:
        ax.plot(x, df[col].values, marker="o", color=color, label=label)
    ax.set_xlabel("PV size as fraction of annual-load match")
    ax.set_ylabel("Annual energy (kWh)")
    ax.set_title(f"Flows vs PV size — {county_slug}")
    ax.grid(True, axis="y", alpha=0.3, linestyle=":")
    ax.legend(loc="best", fontsize=8)
    fig.tight_layout()
    fig.savefig(os.path.join(out_dir, f"sweep_flows_vs_fraction_{county_slug}.png"), dpi=130)
    plt.close(fig)

    # Plot PV net capex vs fraction
    fig, ax = plt.subplots(figsize=(8.5, 4.6))
    ax.plot(x, df["pv_capex_net"].values, marker="o", color="#ffbb78", label="PV net capex")
    ax.set_xlabel("PV size as fraction of annual-load match")
    ax.set_ylabel("$ (net, with incentives)")
    ax.set_title(f"PV net capex vs PV size — {county_slug}")
    ax.grid(True, axis="y", alpha=0.3, linestyle=":")
    fig.tight_layout()
    fig.savefig(os.path.join(out_dir, f"sweep_capex_vs_fraction_{county_slug}.png"), dpi=130)
    plt.close(fig)


def _write_hourly_for_fraction(out_dir: str, county_slug: str, load_profile: List[float], pv: List[float], bd: List[float], gtl: List[float], gtb: List[float], ptb: List[float], soc: List[float]) -> None:
    idx = pd.date_range(start="2018-01-01", periods=8760, freq="H")
    system_to_load = [min(s, l) for s, l in zip(pv, load_profile)]
    df = pd.DataFrame({
        "Load Profile": load_profile,
        "System to Load": system_to_load,
        "Battery to Load": bd,
        "Grid to Load": gtl,
        "Solar + Battery to Load": [a + b for a, b in zip(system_to_load, bd)],
        "Total Supply": [a + b + c for a, b, c in zip(system_to_load, bd, gtl)],
        "Difference": [l - (a + b + c) for l, a, b, c in zip(load_profile, system_to_load, bd, gtl)],
        "System to Battery": ptb,
        "Grid to Battery": gtb,
        "Battery SOC": soc,
    }, index=idx)
    df.to_csv(os.path.join(out_dir, f"sam_optimized_load_profiles_{county_slug}.csv"))


def _compute_bill_for_fraction(exp_base: str, scenario: str, housing_type: str, counties: List[str]) -> Optional[str]:
    """Run Steps 10/11/13 into the experiment tree and return totals CSV dir path."""
    try:
        import step10_get_loads_for_rates as Step10
        import step11_evaluate_gas_rates as Step11
        import step13_combine_total_annual_costs as Step13
    except Exception:
        return None

    # Electricity: both input and output under the experiment tree
    Step10.process(exp_base, exp_base, scenario, [housing_type], counties)
    # Gas: read from canonical, write into experiment tree
    Step11.process("data/loadprofiles", exp_base, scenario, [housing_type], counties)
    # Totals
    Step13.process(exp_base, exp_base, scenario, [housing_type], counties)
    return os.path.join(exp_base, scenario)


def run_for_county(
    base_input_dir: str,
    scenario: str,
    housing_type: str,
    county: str,
    fractions: Iterable[float],
    *,
    options: SweepOptions = SweepOptions(),
    experiments_root: str = "data/experiments/solar_size_sweep",
) -> pd.DataFrame:
    """Run PV-size sweep for a single county and return a summary DataFrame."""
    county_slug = slugify_county_name(county)
    paths = _paths_for_county(base_input_dir, scenario, housing_type, county)
    if not os.path.exists(paths["weather"]) or not os.path.exists(paths["load"]):
        raise FileNotFoundError(f"Missing inputs for {county}: {paths}")

    # Load weather and load using the Step 9 helper to keep alignments identical
    weather_df, load_profile = diy._prepare_weather_and_load(paths["weather"], paths["load"])  # type: ignore
    # Base capacity for annual-energy match
    base_kw = diy._compute_system_capacity_kW(weather_df, load_profile)  # type: ignore

    rows: List[Dict] = []
    exp_county_dir = os.path.join(experiments_root, scenario, housing_type, county_slug)
    _ensure_dir(exp_county_dir)

    for f in fractions:
        f = float(f)
        f = max(0.0, f)
        system_kw = base_kw * f
        # PV AC series via DIY model
        pv_series = diy._pv_timeseries_ac_kwh(weather_df, system_kw)  # type: ignore
        # Dispatch using current Step 9 flags (but allow per-call overrides)
        _, bc, bd, gtl, gtb, ptb, soc = diy._simple_battery_dispatch(  # type: ignore
            load_profile,
            pv_series,
            enable_pv_surplus_to_battery=options.enable_pv_surplus_to_battery,
            grid_charging_enabled=options.grid_charging_enabled,
        )
        m = _collect_metrics(load_profile, pv_series, bc, bd, gtl, gtb, ptb)
        cap = _pv_capex_rows(system_kw, utility=None)
        row = {"fraction": f, "solar_kw": float(system_kw), **m, **cap}
        rows.append(row)

        # Optionally write hourly & compute bills for this fraction
        if options.compute_bills:
            exp_scen_root = os.path.join(experiments_root, f"pvsize_{int(round(f*100))}pct")
            exp_scen_dir = os.path.join(exp_scen_root, scenario, housing_type, county_slug)
            _ensure_dir(exp_scen_dir)
            _write_hourly_for_fraction(exp_scen_dir, county_slug, load_profile, pv_series, bd, gtl, gtb, ptb, soc)
            totals_base = _compute_bill_for_fraction(exp_scen_root, scenario, housing_type, [county])
            # Read back the total annual bill if available
            try:
                from plot_scenario_comparison_helper import _latest_totals_csv
                totals_csv = _latest_totals_csv(exp_scen_root, scenario, housing_type, county_slug)
                df = pd.read_csv(totals_csv, index_col="scenario")
                # scenario with solarstorage row usually named f"{scenario}.solarstorage"
                scen_key = f"{scenario}.solarstorage"
                if scen_key in df.index:
                    row["annual_bill_with_solar"] = float(df.loc[scen_key].iloc[0])
                else:
                    row["annual_bill_with_solar"] = float(df.iloc[0].iloc[0])
            except Exception:
                row["annual_bill_with_solar"] = np.nan

    out_df = pd.DataFrame(rows).sort_values("fraction")
    # Save county summary and plots
    out_df.to_csv(os.path.join(exp_county_dir, f"sweep_summary_{county_slug}.csv"), index=False)
    _plot_summaries(out_df, exp_county_dir, county_slug)
    return out_df


def run(
    base_input_dir: str,
    scenario: str,
    housing_type: str,
    counties: Optional[List[str]] = None,
    fractions: Optional[Iterable[float]] = None,
    *,
    options: SweepOptions = SweepOptions(),
    experiments_root: str = "data/experiments/solar_size_sweep",
) -> Dict[str, pd.DataFrame]:
    """Run the PV-size sweep for one or more counties and return per-county DataFrames."""
    fractions = fractions or [i/10.0 for i in range(1, 11)]
    scen_path = get_scenario_path(base_input_dir, scenario, housing_type)
    county_list = get_counties(scen_path, counties)
    results: Dict[str, pd.DataFrame] = {}
    for county in county_list:
        try:
            df = run_for_county(
                base_input_dir,
                scenario,
                housing_type,
                county,
                fractions,
                options=options,
                experiments_root=experiments_root,
            )
            results[county] = df
        except Exception as e:
            print(f"Sweep failed for {county}: {e}")
    return results

