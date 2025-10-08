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
from helpers.payback_period_helper import CAPITAL_COSTS_NEW
from capital_cost_map_builder import LIFETIMES
from step15_payback_periods import vehicle_annual_adders_from_ledger


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
    # Pull parameters from capital cost helper (use NEW structure by default)
    dollars_per_watt, labour_pct, design_pct, storage_cost = get_solar_cost_params(CAPITAL_COSTS_NEW)
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


def _crf(rate: float, n_years: float) -> float:
    if rate <= 0 or n_years <= 0:
        return 1.0 / max(n_years, 1.0)
    r = float(rate)
    n = float(n_years)
    return (r * (1 + r) ** n) / (((1 + r) ** n) - 1)


def _read_capital_ledger(base_input_dir: str, scenario: str, housing_type: str) -> Optional[pd.DataFrame]:
    cap_dir = os.path.join(base_input_dir, "capital_costs")
    fname = f"capital_costs_{scenario}_{housing_type.replace('-', '_')}.csv"
    path = os.path.join(cap_dir, fname)
    if not os.path.exists(path):
        return None
    try:
        return pd.read_csv(path)
    except Exception:
        return None


def _eac_baseline_components(
    ledger: Optional[pd.DataFrame],
    scenario: str,
    county_slug: str,
    discount_rate: float = 0.07,
) -> Dict[str, float]:
    """Compute annualized capex for 'electric' (ex PV/storage) and 'gas', and vehicle O&M from the ledger.
    Independent of PV size.
    """
    capex_electric = 0.0
    capex_gas = 0.0
    vehicle_om = 0.0
    if ledger is None or ledger.empty:
        return {"capex_electric": 0.0, "capex_gas": 0.0, "vehicle_om": 0.0}
    df = ledger.copy()
    df = df[df['county_slug'].str.lower() == county_slug.lower()]
    # Use 'full_incentives' rows by default
    if 'incentive_scenario' in df.columns:
        df['incentive_scenario'] = df['incentive_scenario'].str.lower()
        df = df[df['incentive_scenario'] == 'full_incentives']
    # Annualize per-row
    for _, r in df.iterrows():
        try:
            lt = float(r.get('lifetime_years', 15) or 15)
            c = _crf(discount_rate, lt)
            if r.get('appliance_category') == 'electric' and r.get('appliance_type') not in ('solar', 'storage'):
                capex_electric += float(r.get('net_cost', 0.0)) * c
            if r.get('appliance_category') == 'gas':
                capex_gas += float(r.get('base_cost', 0.0)) * c
        except Exception:
            continue
    # Vehicle O&M
    try:
        adders = vehicle_annual_adders_from_ledger(df)
        if county_slug in adders.index:
            ev_val = float(adders.loc[county_slug, 'ev_operating']) if 'ev_operating' in adders.columns else 0.0
            ice_val = float(adders.loc[county_slug, 'ice_operating']) if 'ice_operating' in adders.columns else 0.0
            scen_l = (scenario or '').lower()
            if ('ev' in scen_l) or (ev_val > 0):
                vehicle_om += ev_val
            if ('ice' in scen_l) or (ice_val > 0 and 'ev' not in scen_l):
                vehicle_om += ice_val
    except Exception:
        pass
    return {
        "capex_electric": float(capex_electric),
        "capex_gas": float(capex_gas),
        "vehicle_om": float(vehicle_om),
    }


def _plot_eac(df: pd.DataFrame, out_dir: str, county_slug: str) -> None:
    comps = [
        ('capex_pv_annual', '#fdae6b', 'PV capex (annualized)'),
        ('capex_storage_annual', '#9ecae1', 'Storage capex (annualized)'),
        ('capex_electric', '#31a354', 'Electrification capex (annualized)'),
        ('capex_gas', '#756bb1', 'Gas capex (annualized)'),
        ('annual_bill_with_solar', '#1f77b4', 'Annual energy bill (with solar+storage)'),
        ('vehicle_om', '#d62728', 'Vehicle O&M'),
    ]
    x = df['fraction'].values
    bottoms = np.zeros_like(x, dtype=float)
    fig, ax = plt.subplots(figsize=(9.5, 5.0))
    for key, color, label in comps:
        vals = pd.to_numeric(df.get(key, pd.Series([0.0] * len(df))), errors='coerce').fillna(0.0).values
        ax.bar(x, vals, bottom=bottoms, color=color, label=label)
        bottoms = bottoms + vals
    ax.set_xlabel('PV size as fraction of annual-load match')
    ax.set_ylabel('$ per year')
    ax.set_title(f'EAC components vs PV size — {county_slug}')
    ax.legend(loc='best', fontsize=8, frameon=False)
    ax.grid(True, axis='y', linestyle=':', alpha=0.4)
    fig.tight_layout()
    fig.savefig(os.path.join(out_dir, f"sweep_eac_vs_fraction_{county_slug}.png"), dpi=130)
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
    # Read ledger once per county to compute baseline components
    ledger = _read_capital_ledger(base_input_dir, scenario, housing_type)
    base_eac = _eac_baseline_components(ledger, scenario, county_slug)
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
        # Annualized PV & storage capex per fraction
        crf_pv = _crf(0.07, LIFETIMES.get('solar', 25))
        crf_st = _crf(0.07, LIFETIMES.get('storage', 15))
        pv_net = cap["pv_capex_net"]
        pvst_net = cap["pvst_capex_net"]
        storage_net = max(0.0, pvst_net - pv_net)
        capex_pv_annual = pv_net * crf_pv
        capex_storage_annual = storage_net * crf_st

        row = {
            "fraction": f,
            "solar_kw": float(system_kw),
            **m,
            **cap,
            "capex_pv_annual": float(capex_pv_annual),
            "capex_storage_annual": float(capex_storage_annual),
            # Add baseline EAC components (independent of PV size)
            "capex_electric": base_eac.get("capex_electric", 0.0),
            "capex_gas": base_eac.get("capex_gas", 0.0),
            "vehicle_om": base_eac.get("vehicle_om", 0.0),
        }
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
    # Save EAC plot if bills present or even without (bills column may be NaN)
    _plot_eac(out_df, exp_county_dir, county_slug)
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
