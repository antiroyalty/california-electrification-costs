"""
Experimental PV size sweep helper (does not alter the main pipeline).

Given a scenario, housing type, and counties, sweeps PV size as a fraction of the
"annual-energy match" size (e.g., 10%..200%) and records:
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
import shutil

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from mpl_toolkits.axes_grid1 import make_axes_locatable

from helpers.main_helpers import slugify_county_name, get_scenario_path, get_counties

# Reuse PV + dispatch implementation from Step 9 DIY
import step9_my_own_solar_storage as diy
from helpers.capital_cost_map_builder import LIFETIMES
from step15_payback_periods import vehicle_annual_adders_from_ledger
from evaluations.eac import crf as _crf


@dataclass
class SweepOptions:
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


def _ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def _plot_summaries(df: pd.DataFrame, out_dir: str, county_slug: str, scenario: Optional[str] = None) -> None:
    # Plot flows vs PV size (kW)
    fig, ax = plt.subplots(figsize=(8.5, 4.8))
    x = df["solar_kw"].values
    # Determine x-axis span dynamically based on kW values
    try:
        x_min = float(np.nanmin(np.asarray(x, dtype=float))) if len(x) else 0.0
        x_max = float(np.nanmax(np.asarray(x, dtype=float))) if len(x) else 1.0
    except Exception:
        x_min, x_max = 0.0, 1.0
    for col, color, label in [
        ("pv_to_load_kwh", "#ff7f0e", "PV→Load"),
        ("pv_to_battery_kwh", "#9467bd", "PV→Battery"),
        ("battery_to_load_kwh", "#2ca02c", "Battery→Load"),
        ("grid_to_load_kwh", "#7f7f7f", "Grid→Load"),
    ]:
        ax.plot(x, df[col].values, marker="o", color=color, label=label)
    ax.set_xlabel("PV size (kW)")
    ax.set_ylabel("Annual energy (kWh)")
    scen_suffix = f" — {scenario}" if scenario else ""
    ax.set_title(f"Flows vs PV size — {county_slug}{scen_suffix}")
    ax.grid(True, axis="y", alpha=0.3, linestyle=":")
    # Dynamic x-axis using actual kW range and unique PV sizes as ticks
    pad = max(0.01 * (x_max - x_min), 0.02)
    ax.set_xlim(x_min - pad, x_max + pad)
    try:
        xticks = sorted(np.unique(np.asarray(x, dtype=float)))
        ax.set_xticks(xticks)
    except Exception:
        pass
    ax.legend(loc="best", fontsize=8)
    fig.tight_layout()
    flows_path = os.path.join(out_dir, f"sweep_flows_vs_fraction_{county_slug}.png")
    fig.savefig(flows_path, dpi=130)
    print(f"Saved flows-vs-fraction plot: {os.path.abspath(flows_path)}")
    plt.close(fig)


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

def _plot_eac(
    df: pd.DataFrame,
    out_dir: str,
    county_slug: str,
    scenario: Optional[str] = None,
    *,
    bar_width: Optional[float] = None,
) -> None:
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

    x = df['solar_kw'].values
    bottoms = np.zeros_like(x, dtype=float)
    fig, ax = plt.subplots(figsize=(11.2, 5.0))

    xf = np.asarray(x, dtype=float)
    if bar_width is not None:
        try:
            width = float(bar_width)
        except Exception:
            width = 0.2
    else:
        if xf.size > 1:
            dx_vals = np.diff(np.sort(np.unique(xf)))
            dx = float(dx_vals.min()) if dx_vals.size > 0 else 1.0
        else:
            dx = 1.0
        # Choose a width relative to spacing; keep sensible bounds
        width = max(0.2, min(0.8 * dx, 1.2))

    for key, color, label in comps:
        vals = pd.to_numeric(df.get(key, pd.Series([0.0] * len(df))), errors='coerce').fillna(0.0).values
        btm = bottoms.copy()
        ax.bar(x, vals, width=width, bottom=bottoms, color=color, label=label)
        for xi, v, b in zip(x, vals, btm):
            v_float = float(v) if np.isfinite(v) else 0.0
            if v_float > 0:
                ax.text(float(xi), float(b + v_float / 2.0), f"{v_float:.0f}",
                        ha='center', va='center', fontsize=7, color='black')
        bottoms += vals

    totals = np.asarray(bottoms, dtype=float)
    if totals.size > 0 and np.isfinite(totals).any():
        ymax = float(np.nanmax(totals))
        if ymax > 0:
            ax.set_ylim(0.0, ymax * 1.08)
        yoff = max(1.0, 0.02 * ymax) if ymax > 0 else 1.0
        for xi, tot in zip(x, totals):
            tval = float(tot) if np.isfinite(tot) else 0.0
            if tval > 0:
                ax.text(float(xi), tval + yoff, f"{tval:.0f}",
                        ha='center', va='bottom', fontsize=8, color='black')

    ax.set_xlabel('PV size (kW)')
    ax.set_ylabel('$ per year')
    scen_suffix = f" — {scenario}" if scenario else ""
    ax.set_title(f'EAC components vs PV size — {county_slug}{scen_suffix}')
    ax.grid(True, axis='y', linestyle=':', alpha=0.4)

    xmin = float(np.nanmin(xf)) if xf.size > 0 else 0.0
    xmax = float(np.nanmax(xf)) if xf.size > 0 else 1.0
    xpad = max(0.02, width * 0.55)
    ax.set_xlim(xmin - xpad, xmax + xpad)
    ax.margins(x=0.0)
    try:
        xticks = sorted(np.unique(np.asarray(xf, dtype=float)))
        ax.set_xticks(xticks)
    except Exception:
        pass

    h, l = ax.get_legend_handles_labels()
    ax.legend(h, l, loc='center left', bbox_to_anchor=(1.02, 0.5),
              frameon=False, fontsize=8, borderaxespad=0.)

    eac_path = os.path.join(out_dir, f"sweep_eac_vs_fraction_{county_slug}.png")
    fig.savefig(eac_path, dpi=130, bbox_inches='tight')
    print(f"Saved EAC-vs-fraction plot: {os.path.abspath(eac_path)}")
    plt.close(fig)

def _plot_two_days_deployment(
    out_dir: str,
    county_slug: str,
    scenario: str,
    system_kw: float,
    load_profile: List[float],
    pv_series: List[float],
    batt_to_load: List[float],
    grid_to_load: List[float],
) -> None:
    """Plot 24h slices for one January day and one July day showing Load, PV, Battery→Load, Grid→Load.

    The PV size corresponds to the 1.0 annual-match fraction.
    """
    try:
        idx = pd.date_range(start="2018-01-01", periods=8760, freq="H")
        df = pd.DataFrame({
            "Load": load_profile,
            "PV": pv_series,
            "Battery→Load": batt_to_load,
            "Grid→Load": grid_to_load,
        }, index=idx)

        days = [pd.Timestamp("2018-01-15"), pd.Timestamp("2018-07-15")]
        titles = ["January 15", "July 15"]

        fig, axes = plt.subplots(nrows=2, ncols=1, figsize=(10.5, 6.2), sharex=False)
        for ax, day, title in zip(axes, days, titles):
            mask = (df.index.date == day.date())
            d = df.loc[mask]
            if d.empty:
                continue
            hours = range(0, len(d))
            ax.plot(hours, d["Load"].values, color="black", label="Load")
            ax.plot(hours, d["PV"].values, color="#ff7f0e", label="Solar (PV)")
            ax.plot(hours, d["Battery→Load"].values, color="#2ca02c", label="Battery→Load")
            ax.plot(hours, d["Grid→Load"].values, color="#7f7f7f", label="Grid→Load")
            ax.set_ylabel("kW (per hour)")
            ax.set_title(f"{title}")
            ax.grid(True, axis="y", linestyle=":", alpha=0.4)
            ax.set_xlim(0, 23)
            ax.set_xticks([0, 4, 8, 12, 16, 20, 23])
            # Add an in-axes legend so colors are clearly labeled
            ax.legend(loc='upper right', fontsize=8, frameon=False)
        axes[-1].set_xlabel("Hour of day")
        fig.suptitle(f"PV fraction 1.0 — Solar capacity: {system_kw:.2f} kW — {county_slug} — {scenario}")
        fig.tight_layout(rect=[0, 0, 1, 0.95])
        out_path = os.path.join(out_dir, f"two_days_deployment_f100_{county_slug}.png")
        fig.savefig(out_path, dpi=130)
        plt.close(fig)
        print(f"Saved two-days deployment plot: {os.path.abspath(out_path)}")
    except Exception as e:
        print(f"Two-days deployment plot failed for {county_slug}: {e}")


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
    df.to_csv(os.path.join(out_dir, f"solar_storage_dispatch_profiles_{county_slug}.csv"))


def _ensure_rate_inputs_for_fraction(
    exp_scen_dir: str,
    base_input_dir: str,
    scenario: str,
    housing_type: str,
    county_slug: str,
    timestamps: pd.DatetimeIndex,
    load_profile: List[float],
) -> None:
    """Create/copy the files Step 10 expects in the experiment tree, honoring scenario mappings.

    Electricity default:
      experiments.../{file_prefix}{county}.csv with columns ['timestamp', <column_name>]
    Gas default:
      copy canonical gas file if present; else create zeros with mapped column name.
    """
    try:
        import step10_get_loads_for_rates as Step10
        mapping = Step10.SCENARIO_DATA_MAP.get(scenario, {})
        default_e = mapping.get("default", {}).get("electricity", {})
        default_g = mapping.get("default", {}).get("gas", {})
        e_prefix = default_e.get("file_prefix", "electricity_loads_")
        e_column = default_e.get("column", "total_load")
        g_prefix = default_g.get("file_prefix", "gas_loads_")
        g_column = default_g.get("column", "load.gas.building_avg.therms")
    except Exception:
        # Fallbacks
        e_prefix, e_column = "electricity_loads_", "total_load"
        g_prefix, g_column = "gas_loads_", "load.gas.building_avg.therms"

    # Electricity default loads
    elec_default_path = os.path.join(exp_scen_dir, f"{e_prefix}{county_slug}.csv")
    edf = pd.DataFrame({
        "timestamp": timestamps,
        e_column: load_profile,
    })
    edf.to_csv(elec_default_path, index=False)

    # Gas default loads
    canon_dir = get_scenario_path(base_input_dir, scenario, housing_type)
    canon_gas = os.path.join(canon_dir, county_slug, f"{g_prefix}{county_slug}.csv")
    exp_gas = os.path.join(exp_scen_dir, f"{g_prefix}{county_slug}.csv")
    if os.path.exists(canon_gas):
        try:
            shutil.copyfile(canon_gas, exp_gas)
        except Exception:
            pass
    else:
        # Create zeros file with proper column name if canonical gas is missing
        gdf = pd.DataFrame({
            "timestamp": timestamps,
            g_column: [0.0] * len(timestamps),
        })
        gdf.to_csv(exp_gas, index=False)


def _compute_bill_for_fraction(exp_base: str, scenario: str, housing_type: str, counties: List[str]) -> Optional[str]:
    """Run Steps 10/11/13 into the experiment tree and return totals CSV dir path."""
    try:
        import step10_get_loads_for_rates as Step10
        import step12_evaluate_electricity_rates as Step12
        import step11_evaluate_gas_rates as Step11
        import step13_combine_total_annual_costs as Step13
    except Exception:
        return None

    # Electricity: both input and output under the experiment tree
    Step10.process(exp_base, exp_base, scenario, [housing_type], counties)
    # Electricity rates into experiments tree
    Step12.process(exp_base, exp_base, scenario, housing_type, counties)
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
    bar_width: Optional[float] = None,
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

    # Load Step 14 PV/storage summary row for this county (scaling reference)
    pvsum = _read_capital_summary_with_pv(base_input_dir, scenario, housing_type)
    pv_row = None
    if pvsum is not None and not pvsum.empty:
        sub = pvsum[pvsum['county_slug'].str.lower() == county_slug.lower()]
        if not sub.empty:
            pv_row = sub.iloc[0]
    if pv_row is None:
        print(f"[Sweep] Warning: Step14 PV summary not found for {county_slug}; PV capex will be zero.")
        pv_row = pd.Series({
            'solar_kw': 0.0,
            'pv_capex': 0.0,
            'storage_capex': 0.0,
            'pv_incentives_full': 0.0,
            'storage_incentives_full': 0.0,
        })

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
        )
        m = _collect_metrics(load_profile, pv_series, bc, bd, gtl, gtb, ptb)
        # Battery utilization metrics
        try:
            peak_hours = max(0, int(getattr(diy, 'DISCHARGE_END_HOUR', 21)) - int(getattr(diy, 'DISCHARGE_START_HOUR', 16)))
            daily_power_cap = float(getattr(diy, 'P_DISCHARGE_MAX_KW', 3.0)) * float(peak_hours)
            usable_energy_delivered = (
                float(getattr(diy, 'MAX_SOC_FRAC', 0.9)) - float(getattr(diy, 'MIN_SOC_FRAC', 0.2))
            ) * float(getattr(diy, 'BATTERY_CAPACITY_KWH', 13.5)) * float(getattr(diy, 'ETA_DISCHARGE', 0.98))
            daily_theoretical_max = float(min(daily_power_cap, usable_energy_delivered)) if usable_energy_delivered > 0 else 0.0
            annual_theoretical_max = daily_theoretical_max * 365.0
            actual_discharge_annual = float(sum(bd))
            battery_util_percent = (100.0 * actual_discharge_annual / annual_theoretical_max) if annual_theoretical_max > 0 else 0.0
            eq_full_cycles_per_year = (actual_discharge_annual / usable_energy_delivered) if usable_energy_delivered > 0 else 0.0
        except Exception:
            battery_util_percent = 0.0
            eq_full_cycles_per_year = 0.0
        # Scale PV capex/incentives linearly from Step14 base values; keep storage constant
        base_solar_kw = float(pv_row.get('solar_kw', 0.0) or 0.0)
        ratio = (system_kw / base_solar_kw) if base_solar_kw > 0 else 0.0
        pv_capex = float(pv_row.get('pv_capex', 0.0) or 0.0) * ratio
        pv_inc   = float(pv_row.get('pv_incentives_full', 0.0) or 0.0) * ratio
        pv_net   = pv_capex - pv_inc
        st_capex = float(pv_row.get('storage_capex', 0.0) or 0.0)
        st_inc   = float(pv_row.get('storage_incentives_full', 0.0) or 0.0)
        st_net   = st_capex - st_inc
        pvst_capex = pv_capex + st_capex
        pvst_net   = pv_net + st_net
        # Annualized PV & storage capex per fraction
        crf_pv = _crf(0.07, LIFETIMES.get('solar', 25))
        crf_st = _crf(0.07, LIFETIMES.get('storage', 15))
        capex_pv_annual = pv_net * crf_pv
        capex_storage_annual = st_net * crf_st

        row = {
            "fraction": f,
            "solar_kw": float(system_kw),
            **m,
            # capex (scaled to fraction)
            "pv_capex_base": float(pv_capex),
            "pv_capex_net": float(pv_net),
            "pvst_capex_base": float(pvst_capex),
            "pvst_capex_net": float(pvst_net),
            "capex_pv_annual": float(capex_pv_annual),
            "capex_storage_annual": float(capex_storage_annual),
            # battery utilization diagnostics
            "battery_util_percent": float(battery_util_percent),
            "battery_eq_full_cycles_per_year": float(eq_full_cycles_per_year),
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
            # Ensure Step 10 input files exist in the experiment tree
            _ensure_rate_inputs_for_fraction(
                exp_scen_dir,
                base_input_dir,
                scenario,
                housing_type,
                county_slug,
                pd.date_range(start="2018-01-01", periods=8760, freq="H"),
                load_profile,
            )
            totals_base = _compute_bill_for_fraction(exp_scen_root, scenario, housing_type, [county])
            # Read back the total annual bill if available
            try:
                from helpers.plot_scenario_comparison_helper import (
                    _latest_totals_csv,
                    _latest_electricity_csv,
                    _latest_gas_csv,
                    _read_first_numeric_for_row,
                )
                totals_csv = _latest_totals_csv(exp_scen_root, scenario, housing_type, county_slug)
                df = pd.read_csv(totals_csv, index_col="scenario")
                # scenario with solarstorage row usually named f"{scenario}.solarstorage"
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

        # For 1.0 fraction, also render a focused two-day (Jan/Jul) deployment view
        try:
            if abs(f - 1.0) < 1e-9:
                _plot_two_days_deployment(
                    exp_county_dir,
                    county_slug,
                    scenario,
                    system_kw,
                    load_profile,
                    pv_series,
                    bd,
                    gtl,
                )
        except Exception as _two_day_err:
            print(f"Two-day deployment plotting skipped for {county_slug}: {_two_day_err}")

    out_df = pd.DataFrame(rows).sort_values("fraction")
    # Save county summary and plots
    out_df.to_csv(os.path.join(exp_county_dir, f"sweep_summary_{county_slug}.csv"), index=False)
    _plot_summaries(out_df, exp_county_dir, county_slug, scenario)
    # Save EAC plot if bills present or even without (bills column may be NaN)
    _plot_eac(out_df, exp_county_dir, county_slug, scenario, bar_width=bar_width)
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
    bar_width: Optional[float] = None,
) -> Dict[str, pd.DataFrame]:
    """Run the PV-size sweep for one or more counties and return per-county DataFrames."""
    # Default sweep: 0.1 .. 2.0 in 0.1 steps (supports 200% oversizing)
    fractions = fractions or [i/10.0 for i in range(1, 21)]
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
                bar_width=bar_width,
            )
            results[county] = df
        except Exception as e:
            print(f"Sweep failed for {county}: {e}")
    return results
