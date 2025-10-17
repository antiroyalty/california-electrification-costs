"""
Experimental Battery size sweep helper (does not alter the main pipeline).

Given a scenario, housing type, and counties, sweeps Battery usable capacity
from 0.1 kWh to 15 kWh (default points: 0.1, 3, 5, 7.5, 10, 12.5, 15) while keeping
PV size aligned with the main Step 9 sizing (annual‑match × PV_SIZE_FRACTION).

Reuses Step 9 DIY PV and dispatch functions directly, so behavior stays aligned
with the main pipeline (PV→battery, grid charging toggles, dispatch window, etc.).

Outputs per county under data/experiments/battery_size_sweep/...:
  - CSV: sweep_summary_battery_<county_slug>.csv
  - Plots: flows vs capacity, EAC vs capacity (stacked), with battery utilization overlay
"""

from __future__ import annotations

import contextlib
import os
import shutil
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

from main_helpers import slugify_county_name, get_scenario_path, get_counties

# Reuse Step 9 (DIY) PV + dispatch implementation
import step9_my_own_solar_storage as diy
from capital_cost_map_builder import LIFETIMES
from appliances.battery_storage import BatteryStorageAppliance
from appliances.electric_base import IncentiveScenario
from step15_payback_periods import vehicle_annual_adders_from_ledger


@dataclass
class BatterySweepOptions:
    compute_bills: bool = False


def _paths_for_county(base_input_dir: str, scenario: str, housing_type: str, county: str) -> Dict[str, str]:
    cslug = slugify_county_name(county)
    scen_path = get_scenario_path(base_input_dir, scenario, housing_type)
    return {
        "weather": os.path.join(scen_path, cslug, f"weather_TMY_{cslug}.csv"),
        "load": os.path.join(scen_path, cslug, f"combined_profiles_{scenario}_{cslug}.csv"),
    }


def _ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


@contextlib.contextmanager
def _temp_battery_capacity_kwh(kwh: float):
    prev = getattr(diy, 'BATTERY_CAPACITY_KWH', 13.5)
    try:
        setattr(diy, 'BATTERY_CAPACITY_KWH', float(kwh))
        yield
    finally:
        setattr(diy, 'BATTERY_CAPACITY_KWH', prev)


def _crf(rate: float, n_years: float) -> float:
    if rate <= 0 or n_years <= 0:
        return 1.0 / max(n_years, 1.0)
    r = float(rate)
    n = float(n_years)
    return (r * (1 + r) ** n) / (((1 + r) ** n) - 1)


def _collect_metrics(load_profile: List[float], pv: List[float], bd: List[float], gtl: List[float], gtb: List[float], ptb: List[float]) -> Dict[str, float]:
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


def _read_capital_summary_with_pv(base_input_dir: str, scenario: str, housing_type: str) -> Optional[pd.DataFrame]:
    cap_dir = os.path.join(base_input_dir, "capital_costs")
    fname = f"capital_costs_summary_with_pv_{scenario}_{housing_type.replace('-', '_')}.csv"
    path = os.path.join(cap_dir, fname)
    if not os.path.exists(path):
        return None
    try:
        return pd.read_csv(path)
    except Exception:
        return None


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
    capex_electric = 0.0
    capex_gas = 0.0
    vehicle_om = 0.0
    if ledger is None or ledger.empty:
        return {"capex_electric": 0.0, "capex_gas": 0.0, "vehicle_om": 0.0}
    df = ledger.copy()
    df = df[df['county_slug'].str.lower() == county_slug.lower()]
    if 'incentive_scenario' in df.columns:
        df['incentive_scenario'] = df['incentive_scenario'].str.lower()
        df = df[df['incentive_scenario'] == 'full_incentives']
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


def _battery_costs_for_kwh(kwh: float) -> Dict[str, float]:
    """Compute storage base and net cost for a target capacity by scaling the
    BatteryStorageAppliance (12.5 kWh per unit) linearly by kWh.
    """
    unit = BatteryStorageAppliance(num_units=1, lifetime_years=LIFETIMES.get('storage', 15))
    per_kwh_capex = float(unit.base_cost) / float(unit.capacity_kwh)
    per_kwh_net = float(unit.get_net_cost(IncentiveScenario.FULL_INCENTIVES)) / float(unit.capacity_kwh)
    # Full incentives assumed for EAC components
    return {
        "storage_capex": per_kwh_capex * float(kwh),
        "storage_net": per_kwh_net * float(kwh),
    }


def _plot_flows(df: pd.DataFrame, out_dir: str, county_slug: str, scenario: Optional[str] = None) -> None:
    fig, ax = plt.subplots(figsize=(8.8, 4.8))
    x = df["battery_kwh"].values
    for col, color, label in [
        ("pv_to_load_kwh", "#ff7f0e", "PV→Load"),
        ("pv_to_battery_kwh", "#9467bd", "PV→Battery"),
        ("battery_to_load_kwh", "#2ca02c", "Battery→Load"),
        ("grid_to_load_kwh", "#7f7f7f", "Grid→Load"),
    ]:
        ax.plot(x, df[col].values, marker="o", color=color, label=label)
    ax.set_xlabel("Battery capacity (kWh)")
    ax.set_ylabel("Annual energy (kWh)")
    scen_suffix = f" — {scenario}" if scenario else ""
    ax.set_title(f"Flows vs Battery size — {county_slug}{scen_suffix}")
    ax.grid(True, axis="y", alpha=0.3, linestyle=":")
    ax.legend(loc="best", fontsize=8)
    fig.tight_layout()
    path = os.path.join(out_dir, f"battery_sweep_flows_{county_slug}.png")
    fig.savefig(path, dpi=130)
    print(f"Saved flows plot: {os.path.abspath(path)}")
    plt.close(fig)


def _plot_eac(df: pd.DataFrame, out_dir: str, county_slug: str, scenario: Optional[str] = None) -> None:
    """Stacked EAC bars vs. battery size with even categorical spacing.

    Uses categorical positions (0..N-1) so bars are evenly spaced, and the
    capacity (kWh) values are shown as x-tick labels. This avoids uneven
    spacing from numeric x positions when capacities are not on a uniform grid.
    """
    # Prefer split bills if present; fallback to single combined bill
    if 'annual_bill_electric' in df.columns and 'annual_bill_gas' in df.columns:
        comps = [
            ('capex_pv_annual', '#fdae6b', 'PV capex (annualized)'),
            ('capex_storage_annual', '#9ecae1', 'Storage capex (annualized)'),
            ('capex_electric', '#31a354', 'Electrification capex (annualized)'),
            ('capex_gas', '#756bb1', 'Gas capex (annualized)'),
            ('vehicle_om', '#d62728', 'Vehicle O&M'),
            ('annual_bill_electric', '#1f77b4', 'Annual electricity bill'),
            ('annual_bill_gas', '#17becf', 'Annual gas bill'),
        ]
    else:
        comps = [
            ('capex_pv_annual', '#fdae6b', 'PV capex (annualized)'),
            ('capex_storage_annual', '#9ecae1', 'Storage capex (annualized)'),
            ('capex_electric', '#31a354', 'Electrification capex (annualized)'),
            ('capex_gas', '#756bb1', 'Gas capex (annualized)'),
            ('annual_bill_with_solar', '#1f77b4', 'Annual energy bill (with solar+storage)'),
            ('vehicle_om', '#d62728', 'Vehicle O&M'),
        ]

    data = df.copy()
    if 'battery_kwh' in data.columns:
        data = data.sort_values('battery_kwh')
    x_labels = pd.to_numeric(data.get('battery_kwh', pd.Series([])), errors='coerce').fillna(0.0).tolist()
    x = np.arange(len(x_labels), dtype=float)

    bottoms = np.zeros_like(x, dtype=float)
    fig, ax = plt.subplots(figsize=(11.5, 5.0))
    width = 0.72  # simple, consistent bar width (categorical units)

    for key, color, label in comps:
        vals = pd.to_numeric(data.get(key, pd.Series([0.0] * len(data))), errors='coerce').fillna(0.0).values
        btm = bottoms.copy()
        ax.bar(x, vals, width=width, bottom=bottoms, color=color, label=label)
        for xi, v, b in zip(x, vals, btm):
            v_float = float(v) if np.isfinite(v) else 0.0
            if v_float > 0:
                ax.text(float(xi), float(b + v_float / 2.0), f"{v_float:.0f}",
                        ha='center', va='center', fontsize=7, color='black')
        bottoms = bottoms + vals

    # Totals above each bar
    totals = np.asarray(bottoms, dtype=float)
    if totals.size > 0 and np.isfinite(totals).any():
        ymax = float(np.nanmax(totals))
        if ymax > 0:
            ax.set_ylim(0.0, ymax * 1.08)
        yoff = max(1.0, 0.02 * ymax) if ymax > 0 else 1.0
        for xi, tot in zip(x, totals):
            tval = float(tot) if np.isfinite(tot) else 0.0
            if tval > 0:
                ax.text(float(xi), tval + yoff, f"{tval:.0f}", ha='center', va='bottom', fontsize=8, color='black')

    # Axes, ticks, and layout
    ax.set_xlabel('Battery capacity (kWh)')
    ax.set_ylabel('$ per year')
    scen_suffix = f" — {scenario}" if scenario else ""
    ax.set_title(f'EAC vs Battery size — {county_slug}{scen_suffix}')
    ax.set_xticks(x)
    ax.set_xticklabels([f"{v:g}" for v in x_labels])
    ax.set_xlim(-0.5, len(x_labels) - 0.5)
    ax.grid(True, axis='y', linestyle=':', alpha=0.4)
    ax.legend(loc='center left', bbox_to_anchor=(1.08, 0.5), fontsize=8, frameon=False)
    fig.tight_layout(rect=[0.06, 0, 0.78, 1])

    path = os.path.join(out_dir, f"battery_sweep_eac_{county_slug}.png")
    fig.savefig(path, dpi=130)
    print(f"Saved EAC plot: {os.path.abspath(path)}")
    plt.close(fig)


def _write_hourly(out_dir: str, county_slug: str, load_profile: List[float], pv: List[float], bd: List[float], gtl: List[float], gtb: List[float], ptb: List[float], soc: List[float]) -> None:
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


def _ensure_rate_inputs(exp_scen_dir: str, base_input_dir: str, scenario: str, housing_type: str, county_slug: str, timestamps: pd.DatetimeIndex, load_profile: List[float]) -> None:
    # Reuse mapping logic from the solar sweep by importing and calling its helper
    try:
        import experiments.solar_size_sweep as sss  # type: ignore
        return sss._ensure_rate_inputs_for_fraction(exp_scen_dir, base_input_dir, scenario, housing_type, county_slug, timestamps, load_profile)  # type: ignore
    except Exception:
        # Minimal fallback: write default electric and zero gas
        e_prefix, e_column = "electricity_loads_", "total_load"
        g_prefix, g_column = "gas_loads_", "load.gas.building_avg.therms"
        elec_default_path = os.path.join(exp_scen_dir, f"{e_prefix}{county_slug}.csv")
        pd.DataFrame({"timestamp": timestamps, e_column: load_profile}).to_csv(elec_default_path, index=False)
        gdf = pd.DataFrame({"timestamp": timestamps, g_column: [0.0] * len(timestamps)})
        gdf.to_csv(os.path.join(exp_scen_dir, f"{g_prefix}{county_slug}.csv"), index=False)


def _compute_bill(exp_base: str, scenario: str, housing_type: str, counties: List[str]) -> Optional[str]:
    try:
        import experiments.solar_size_sweep as sss  # type: ignore
        return sss._compute_bill_for_fraction(exp_base, scenario, housing_type, counties)  # type: ignore
    except Exception:
        return None


def run_for_county(
    base_input_dir: str,
    scenario: str,
    housing_type: str,
    county: str,
    capacities_kwh: Iterable[float],
    *,
    options: BatterySweepOptions = BatterySweepOptions(),
    experiments_root: str = "data/experiments/battery_size_sweep",
) -> pd.DataFrame:
    county_slug = slugify_county_name(county)
    paths = _paths_for_county(base_input_dir, scenario, housing_type, county)
    if not os.path.exists(paths["weather"]) or not os.path.exists(paths["load"]):
        raise FileNotFoundError(f"Missing inputs for {county}: {paths}")

    # Load weather and load using Step 9 helper for alignment
    weather_df, load_profile = diy._prepare_weather_and_load(paths["weather"], paths["load"])  # type: ignore

    # PV baseline size: prefer Step14 summary; else compute via Step 9 anchor × PV_SIZE_FRACTION
    pvsum = _read_capital_summary_with_pv(base_input_dir, scenario, housing_type)
    system_kw: float
    if pvsum is not None and not pvsum.empty:
        sub = pvsum[pvsum['county_slug'].str.lower() == county_slug.lower()]
        system_kw = float(sub.iloc[0]['solar_kw']) if not sub.empty and 'solar_kw' in sub.columns else 0.0
    else:
        base_kw = diy._compute_system_capacity_kW(weather_df, load_profile)  # type: ignore
        system_kw = float(base_kw) * float(getattr(diy, 'PV_SIZE_FRACTION', 1.0))

    ledger = _read_capital_ledger(base_input_dir, scenario, housing_type)
    base_eac = _eac_baseline_components(ledger, scenario, county_slug)
    exp_county_dir = os.path.join(experiments_root, scenario, housing_type, county_slug)
    _ensure_dir(exp_county_dir)

    # PV cost components from Step14 if present; else zero
    pv_capex_base = 0.0
    pv_net = 0.0
    if pvsum is not None and not pvsum.empty:
        sub = pvsum[pvsum['county_slug'].str.lower() == county_slug.lower()]
        if not sub.empty:
            pv_capex_base = float(sub.iloc[0].get('pv_capex', 0.0) or 0.0)
            pv_inc_full = float(sub.iloc[0].get('pv_incentives_full', 0.0) or 0.0)
            pv_net = pv_capex_base - pv_inc_full
    crf_pv = _crf(0.07, LIFETIMES.get('solar', 25))

    rows: List[Dict] = []
    for cap_kwh in capacities_kwh:
        cap_kwh = float(cap_kwh)
        # PV AC series (fixed PV size for sweep)
        pv_series = diy._pv_timeseries_ac_kwh(weather_df, system_kw)  # type: ignore
        # Dispatch with temporary battery capacity
        with _temp_battery_capacity_kwh(cap_kwh):
            _, bc, bd, gtl, gtb, ptb, soc = diy._simple_battery_dispatch(  # type: ignore
                load_profile,
                pv_series,
            )
        m = _collect_metrics(load_profile, pv_series, bd, gtl, gtb, ptb)

        # Storage capex/net scaled linearly from BatteryStorageAppliance unit economics
        st = _battery_costs_for_kwh(cap_kwh)
        crf_st = _crf(0.07, LIFETIMES.get('storage', 15))
        capex_storage_annual = st['storage_net'] * crf_st
        capex_pv_annual = pv_net * crf_pv

        # Battery utilization metrics (relative to dispatch envelope)
        try:
            peak_hours = max(0, int(getattr(diy, 'DISCHARGE_END_HOUR', 21)) - int(getattr(diy, 'DISCHARGE_START_HOUR', 16)))
            daily_power_cap = float(getattr(diy, 'P_DISCHARGE_MAX_KW', 3.0)) * float(peak_hours)
            usable_energy_delivered = (
                float(getattr(diy, 'MAX_SOC_FRAC', 0.9)) - float(getattr(diy, 'MIN_SOC_FRAC', 0.2))
            ) * cap_kwh * float(getattr(diy, 'ETA_DISCHARGE', 0.98))
            daily_theoretical_max = float(min(daily_power_cap, usable_energy_delivered)) if usable_energy_delivered > 0 else 0.0
            annual_theoretical_max = daily_theoretical_max * 365.0
            actual_discharge_annual = float(sum(bd))
            battery_util_percent = (100.0 * actual_discharge_annual / annual_theoretical_max) if annual_theoretical_max > 0 else 0.0
            eq_full_cycles_per_year = (actual_discharge_annual / usable_energy_delivered) if usable_energy_delivered > 0 else 0.0
        except Exception:
            battery_util_percent = 0.0
            eq_full_cycles_per_year = 0.0

        row = {
            "battery_kwh": cap_kwh,
            "solar_kw": float(system_kw),
            **m,
            # annualized capex components
            "capex_pv_annual": float(capex_pv_annual),
            "capex_storage_annual": float(capex_storage_annual),
            # baseline components independent of capacity
            "capex_electric": base_eac.get("capex_electric", 0.0),
            "capex_gas": base_eac.get("capex_gas", 0.0),
            "vehicle_om": base_eac.get("vehicle_om", 0.0),
            # diagnostics
            "storage_capex_base": float(st['storage_capex']),
            "storage_net": float(st['storage_net']),
            "battery_util_percent": float(battery_util_percent),
            "battery_eq_full_cycles_per_year": float(eq_full_cycles_per_year),
        }
        # Optionally compute bills by writing hourly and running Steps 10/11/13 in exp tree
        if options.compute_bills:
            cap_tag = f"batt_{int(round(cap_kwh))}kwh"
            exp_scen_root = os.path.join(experiments_root, cap_tag)
            exp_scen_dir = os.path.join(exp_scen_root, scenario, housing_type, county_slug)
            _ensure_dir(exp_scen_dir)
            _write_hourly(exp_scen_dir, county_slug, load_profile, pv_series, bd, gtl, gtb, ptb, soc)
            _ensure_rate_inputs(exp_scen_dir, base_input_dir, scenario, housing_type, county_slug, pd.date_range(start="2018-01-01", periods=8760, freq="H"), load_profile)
            _compute_bill(exp_scen_root, scenario, housing_type, [county])
            # Try to read the bill back into row (totals and split E/G)
            try:
                from plot_scenario_comparison_helper import (
                    _latest_totals_csv,
                    _latest_electricity_csv,
                    _latest_gas_csv,
                    _read_first_numeric_for_row,
                )
                totals_csv = _latest_totals_csv(exp_scen_root, scenario, housing_type, county_slug)
                df = pd.read_csv(totals_csv, index_col="scenario")
                scen_key = f"{scenario}.solarstorage"
                if scen_key in df.index:
                    row["annual_bill_with_solar"] = float(df.loc[scen_key].iloc[0])
                else:
                    row["annual_bill_with_solar"] = float(df.iloc[0].iloc[0])
                # Split electricity/gas bills for stacked plotting
                e_csv = _latest_electricity_csv(exp_scen_root, scenario, housing_type, county_slug)
                g_csv = _latest_gas_csv(exp_scen_root, scenario, housing_type, county_slug)
                row["annual_bill_electric"] = _read_first_numeric_for_row(e_csv, scen_key)
                row["annual_bill_gas"] = _read_first_numeric_for_row(g_csv, scen_key)
            except Exception:
                row["annual_bill_with_solar"] = np.nan
                row["annual_bill_electric"] = np.nan
                row["annual_bill_gas"] = np.nan

        rows.append(row)

    out_df = pd.DataFrame(rows).sort_values("battery_kwh")
    out_df.to_csv(os.path.join(exp_county_dir, f"sweep_summary_battery_{county_slug}.csv"), index=False)
    _plot_flows(out_df, exp_county_dir, county_slug, scenario)
    _plot_eac(out_df, exp_county_dir, county_slug, scenario)
    return out_df


def run(
    base_input_dir: str,
    scenario: str,
    housing_type: str,
    counties: Optional[List[str]] = None,
    capacities_kwh: Optional[Iterable[float]] = None,
    *,
    options: BatterySweepOptions = BatterySweepOptions(),
    experiments_root: str = "data/experiments/battery_size_sweep",
) -> Dict[str, pd.DataFrame]:
    capacities = list(capacities_kwh) if capacities_kwh is not None else [0.1, 3.0, 5.0, 7.5, 10.0, 12.5, 15.0]
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
                capacities,
                options=options,
                experiments_root=experiments_root,
            )
            results[county] = df
        except Exception as e:
            print(f"Battery sweep failed for {county}: {e}")
    return results
