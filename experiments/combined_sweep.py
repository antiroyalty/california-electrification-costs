"""
Experimental combined PV fraction × Battery capacity sweep (non-intrusive).

Sweeps:
  - PV size fraction of annual-match (e.g., 0.1..2.0), and
  - Battery capacity (kWh) (e.g., 3..15),
reusing Step 9 DIY PV and dispatch logic so behavior matches the main pipeline.

Outputs per county under data/experiments/combined_size_sweep/...:
  - CSV: combined_sweep_<county_slug>.csv (one row per (fraction, battery_kwh))
  - Heatmaps: EAC vs (fraction, kWh) and Battery Utilization vs (fraction, kWh)
"""

from __future__ import annotations

import contextlib
import os
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

from helpers.main_helpers import slugify_county_name, get_scenario_path, get_counties

# Reuse Step 9 (DIY) PV + dispatch implementation
import step9_my_own_solar_storage as diy
from capital_cost_map_builder import LIFETIMES
from appliances.battery_storage import BatteryStorageAppliance
from appliances.electric_base import IncentiveScenario
from step15_payback_periods import vehicle_annual_adders_from_ledger


@dataclass
class CombinedSweepOptions:
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
    unit = BatteryStorageAppliance(num_units=1, lifetime_years=LIFETIMES.get('storage', 15))
    per_kwh_capex = float(unit.base_cost) / float(unit.capacity_kwh)
    per_kwh_net = float(unit.get_net_cost(IncentiveScenario.FULL_INCENTIVES)) / float(unit.capacity_kwh)
    return {
        "storage_capex": per_kwh_capex * float(kwh),
        "storage_net": per_kwh_net * float(kwh),
    }


def _plot_heatmap(df: pd.DataFrame, x_key: str, y_key: str, z_key: str, out_path: str, title: str, xlabel: str, ylabel: str) -> None:
    # Pivot grid: rows = y, cols = x
    try:
        piv = df.pivot(index=y_key, columns=x_key, values=z_key)
        x_vals = sorted(df[x_key].unique())
        y_vals = sorted(df[y_key].unique())
        Z = piv.values
        fig, ax = plt.subplots(figsize=(10.5, 6.0))
        im = ax.imshow(Z, aspect='auto', origin='lower', interpolation='nearest', cmap='viridis')
        ax.set_xticks(range(len(x_vals)))
        ax.set_xticklabels([f"{v:g}" for v in x_vals])
        ax.set_yticks(range(len(y_vals)))
        ax.set_yticklabels([f"{v:g}" for v in y_vals])
        ax.set_xlabel(xlabel)
        ax.set_ylabel(ylabel)
        ax.set_title(title)
        fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
        # Annotate min value with (x, y) coordinates
        try:
            min_idx = np.unravel_index(np.nanargmin(Z), Z.shape)
            jx, iy = int(min_idx[1]), int(min_idx[0])
            x_min = x_vals[jx] if 0 <= jx < len(x_vals) else None
            y_min = y_vals[iy] if 0 <= iy < len(y_vals) else None
            ax.scatter(jx, iy, s=48, c='red', marker='o', label='Min')
            if x_min is not None and y_min is not None:
                label = f"PV={x_min:g}, kWh={y_min:g}"
                ax.text(
                    jx, iy,
                    label,
                    ha='left', va='bottom', fontsize=8, color='black',
                    bbox=dict(facecolor='white', alpha=0.75, edgecolor='none', boxstyle='round,pad=0.15')
                )
            ax.legend(loc='upper right', fontsize=8)
        except Exception:
            pass
        fig.tight_layout()
        fig.savefig(out_path, dpi=130)
        plt.close(fig)
        print(f"Saved heatmap: {os.path.abspath(out_path)}")
    except Exception as e:
        print(f"Heatmap failed for {out_path}: {e}")


def run_for_county(
    base_input_dir: str,
    scenario: str,
    housing_type: str,
    county: str,
    fractions: Iterable[float],
    capacities_kwh: Iterable[float],
    *,
    options: CombinedSweepOptions = CombinedSweepOptions(),
    experiments_root: str = "data/experiments/combined_size_sweep",
) -> pd.DataFrame:
    county_slug = slugify_county_name(county)
    paths = _paths_for_county(base_input_dir, scenario, housing_type, county)
    if not os.path.exists(paths["weather"]) or not os.path.exists(paths["load"]):
        raise FileNotFoundError(f"Missing inputs for {county}: {paths}")

    # Weather + load
    weather_df, load_profile = diy._prepare_weather_and_load(paths["weather"], paths["load"])  # type: ignore
    base_kw = diy._compute_system_capacity_kW(weather_df, load_profile)  # type: ignore

    ledger = _read_capital_ledger(base_input_dir, scenario, housing_type)
    base_eac = _eac_baseline_components(ledger, scenario, county_slug)
    exp_county_dir = os.path.join(experiments_root, scenario, housing_type, county_slug)
    _ensure_dir(exp_county_dir)

    # PV costs from Step14 summary row if present
    pvsum = _read_capital_summary_with_pv(base_input_dir, scenario, housing_type)
    pv_row = None
    if pvsum is not None and not pvsum.empty:
        sub = pvsum[pvsum['county_slug'].str.lower() == county_slug.lower()]
        if not sub.empty:
            pv_row = sub.iloc[0]
    if pv_row is None:
        pv_row = pd.Series({'solar_kw': 0.0, 'pv_capex': 0.0, 'pv_incentives_full': 0.0})
    crf_pv = _crf(0.07, LIFETIMES.get('solar', 25))
    crf_st = _crf(0.07, LIFETIMES.get('storage', 15))

    rows: List[Dict] = []
    for f in fractions:
        f = float(f)
        f = max(0.0, f)
        system_kw = base_kw * f
        pv_series = diy._pv_timeseries_ac_kwh(weather_df, system_kw)  # type: ignore

        # PV capex scaled linearly from Step14 base values
        base_solar_kw = float(pv_row.get('solar_kw', 0.0) or 0.0)
        ratio = (system_kw / base_solar_kw) if base_solar_kw > 0 else 0.0
        pv_capex = float(pv_row.get('pv_capex', 0.0) or 0.0) * ratio
        pv_inc   = float(pv_row.get('pv_incentives_full', 0.0) or 0.0) * ratio
        pv_net   = pv_capex - pv_inc
        capex_pv_annual = pv_net * crf_pv

        for cap_kwh in capacities_kwh:
            cap_kwh = float(cap_kwh)
            with _temp_battery_capacity_kwh(cap_kwh):
                _, bc, bd, gtl, gtb, ptb, soc = diy._simple_battery_dispatch(  # type: ignore
                    load_profile,
                    pv_series,
                )
            m = _collect_metrics(load_profile, pv_series, bd, gtl, gtb, ptb)

            # Storage capex/net scaled via BatteryStorageAppliance per‑kWh economics
            st = _battery_costs_for_kwh(cap_kwh)
            capex_storage_annual = st['storage_net'] * crf_st

            # Battery utilization metrics
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

            row: Dict = {
                "fraction": f,
                "battery_kwh": cap_kwh,
                "solar_kw": float(system_kw),
                **m,
                # annualized capex components
                "capex_pv_annual": float(capex_pv_annual),
                "capex_storage_annual": float(capex_storage_annual),
                # baseline components independent of PV/batt sizes
                "capex_electric": base_eac.get("capex_electric", 0.0),
                "capex_gas": base_eac.get("capex_gas", 0.0),
                "vehicle_om": base_eac.get("vehicle_om", 0.0),
                # diagnostics
                "storage_capex_base": float(st['storage_capex']),
                "storage_net": float(st['storage_net']),
                "battery_util_percent": float(battery_util_percent),
                "battery_eq_full_cycles_per_year": float(eq_full_cycles_per_year),
            }

            if options.compute_bills:
                # Use helpers from solar sweep to write inputs and compute bills for this pair
                try:
                    import experiments.solar_size_sweep as sss  # type: ignore
                    tag = f"pv_{int(round(f*100))}pct_batt_{int(round(cap_kwh))}kwh"
                    exp_scen_root = os.path.join(experiments_root, tag)
                    exp_scen_dir = os.path.join(exp_scen_root, scenario, housing_type, county_slug)
                    _ensure_dir(exp_scen_dir)
                    # Write hourly
                    idx = pd.date_range(start="2018-01-01", periods=8760, freq="H")
                    system_to_load = [min(s, l) for s, l in zip(pv_series, load_profile)]
                    dfh = pd.DataFrame({
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
                    dfh.to_csv(os.path.join(exp_scen_dir, f"sam_optimized_load_profiles_{county_slug}.csv"))
                    # Ensure Step 10 inputs and compute bills
                    sss._ensure_rate_inputs_for_fraction(exp_scen_dir, base_input_dir, scenario, housing_type, county_slug, idx, load_profile)  # type: ignore
                    sss._compute_bill_for_fraction(exp_scen_root, scenario, housing_type, [county])  # type: ignore
                    # Read back total annual bill
                    try:
                        from helpers.plot_scenario_comparison_helper import _latest_totals_csv
                        totals_csv = _latest_totals_csv(exp_scen_root, scenario, housing_type, county_slug)
                        df = pd.read_csv(totals_csv, index_col="scenario")
                        scen_key = f"{scenario}.solarstorage"
                        if scen_key in df.index:
                            row["annual_bill_with_solar"] = float(df.loc[scen_key].iloc[0])
                        else:
                            row["annual_bill_with_solar"] = float(df.iloc[0].iloc[0])
                    except Exception:
                        row["annual_bill_with_solar"] = np.nan
                except Exception:
                    row["annual_bill_with_solar"] = np.nan

            rows.append(row)

    out_df = pd.DataFrame(rows).sort_values(["battery_kwh", "fraction"]) if rows else pd.DataFrame()
    out_csv = os.path.join(exp_county_dir, f"combined_sweep_{county_slug}.csv")
    out_df.to_csv(out_csv, index=False)
    print(f"Saved combined sweep CSV: {os.path.abspath(out_csv)}")

    # Derive total EAC (treat missing annual bill as 0.0 if not computed)
    try:
        eac = (
            out_df.get('capex_pv_annual', 0.0)
            + out_df.get('capex_storage_annual', 0.0)
            + out_df.get('capex_electric', 0.0)
            + out_df.get('capex_gas', 0.0)
            + out_df.get('vehicle_om', 0.0)
            + out_df.get('annual_bill_with_solar', 0.0).fillna(0.0)
        )
        out_df['eac_total'] = pd.to_numeric(eac, errors='coerce').fillna(0.0)
    except Exception:
        out_df['eac_total'] = 0.0

    # Heatmaps
    # Include scenario in filenames for easier side-by-side comparison
    eac_path = os.path.join(exp_county_dir, f"combined_eac_heatmap_{scenario}_{county_slug}.png")
    util_path = os.path.join(exp_county_dir, f"combined_utilization_heatmap_{scenario}_{county_slug}.png")
    _plot_heatmap(out_df, 'solar_kw', 'battery_kwh', 'eac_total', eac_path, f"EAC heatmap — {county_slug} — {scenario}", "PV size (kW)", "Battery (kWh)")
    _plot_heatmap(out_df, 'solar_kw', 'battery_kwh', 'battery_util_percent', util_path, f"Battery utilization heatmap — {county_slug} — {scenario}", "PV size (kW)", "Battery (kWh)")
    return out_df


def run(
    base_input_dir: str,
    scenario: str,
    housing_type: str,
    counties: Optional[List[str]] = None,
    fractions: Optional[Iterable[float]] = None,
    capacities_kwh: Optional[Iterable[float]] = None,
    *,
    options: CombinedSweepOptions = CombinedSweepOptions(),
    experiments_root: str = "data/experiments/combined_size_sweep",
) -> Dict[str, pd.DataFrame]:
    fracs = list(fractions) if fractions is not None else [i / 10.0 for i in range(1, 21)]  # 0.1..2.0
    caps = list(capacities_kwh) if capacities_kwh is not None else [3.0, 5.0, 7.5, 10.0, 12.5, 15.0]
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
                fracs,
                caps,
                options=options,
                experiments_root=experiments_root,
            )
            results[county] = df
        except Exception as e:
            print(f"Combined sweep failed for {county}: {e}")
    return results
