"""
Step 9 (DIY): PV + simple battery dispatch without PySAM

Implements the same battery outputs as step9_solar_storage_custom_dispatch.py,
but computes the PV AC generation time series directly from the weather CSV
instead of using Pvsamv1.

PV model (simplified PVWatts‑style):
- AC_kW[h] = system_capacity_kW * (GHI[h] / 1000) * PR_base * temp_derate[h]
- temp_derate[h] = 1 + gamma_pdc * (Tcell[h] − 25°C)
- Tcell[h] ≈ Tamb[h] + ((NOCT − 20) / 800) * GHI[h]
  where NOCT = 46°C, PR_base = 0.85, gamma_pdc = −0.00280 / °C
- Clip at zero; no inverter clipping modeled (kept simple to match DIY intent).

Battery dispatch:
- Capacity 13.5 kWh, round‑trip eff 96% as symmetric sqrt(RTE), 3 kW charge/discharge
- Min SOC 20%, max SOC 90%
- Classic strategy (default):
  • Discharge window 16:00–21:00 (up to residual load, subject to power/SOC). 
  • PV surplus can charge any hour (default ON).
  • Optional grid top‑up 14:00–16:00 (default OFF).
- Dynamic strategy (opt‑in via USE_DYNAMIC_DISPATCH=True):
  • PV‑only charging; at 16:00 if PV<load, discharge until min SOC or first hour PV≥load next day.

Outputs (identical columns used downstream by step10):
- "Load Profile", "System to Load", "Battery to Load", "Grid to Load",
  "Solar + Battery to Load", "Total Supply", "Difference",
  "System to Battery", "Grid to Battery", "Battery SOC"

Files:
- Reads weather: data/loadprofiles/<scenario>/<housing_type>/<county>/weather_TMY_<county>.csv
- Reads load:   data/loadprofiles/<scenario>/<housing_type>/<county>/combined_profiles_<scenario>_<county}.csv
- Writes:       data/loadprofiles/<scenario>/<housing_type>/<county>/sam_optimized_load_profiles_<county>.csv

"""

from __future__ import annotations

import os
import csv
from math import sqrt
from typing import Dict, List, Optional, Tuple
import contextlib

import pandas as pd
import subprocess

from helpers.main_helpers import (
    get_counties,
    get_scenario_path,
    log,
    format_load_profile,
    to_decimal_number,
    norcal_counties,
    central_counties,
    socal_counties,
    slugify_county_name,
)
from helpers import log_profiles
from helpers.step9_plotting_helper import plot_first_weeks


# I/O constants
LOADPROFILE_FILE_PREFIX = "combined_profiles"
TOTAL_LOAD_COLUMN_NAME = "electricity.real_and_simulated.for_typical_county_home.kwh"
OUTPUT_LOADPROFILE_FILE_PREFIX = "sam_optimized_load_profiles"
SOLAR_STORAGE_CAPACITY_PREFIX = "electrified_assets"
CAPITAL_COSTS_FOLDER_NAME = "CAPITAL_COSTS"

# Shared run identifiers for repeatable, versioned outputs

def _get_git_short_sha() -> str:
    try:
        sha = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            stderr=subprocess.DEVNULL,
        ).decode().strip()
        return sha or "nogit"
    except Exception:
        return "nogit"

GIT_SHORT_SHA = _get_git_short_sha()


# Battery + dispatch constants
# Dispatch strategy selector:
#   - False: classic windowed discharge (16–21), optional PV surplus charge, optional grid top-up
#   - True:  dynamic PV-only strategy (PV charges; discharge from 16:00 until PV≥load next day)
USE_DYNAMIC_DISPATCH = True

# Toggle: default PV→Battery surplus charging (applied when function arg is None)
ENABLE_PV_SURPLUS_TO_BATTERY = True
BATTERY_CAPACITY_KWH = 13.5
ROUND_TRIP_EFFICIENCY = 0.96
ETA_CHARGE = sqrt(ROUND_TRIP_EFFICIENCY)
ETA_DISCHARGE = sqrt(ROUND_TRIP_EFFICIENCY)
P_CHARGE_MAX_KW = 3.0
P_DISCHARGE_MAX_KW = 3.0
# Grid top‑up window (2–4pm local)
CHARGE_START_HOUR = 14
CHARGE_END_HOUR = 16
DISCHARGE_START_HOUR = 16
DISCHARGE_END_HOUR = 21
MIN_SOC_FRAC = 0.20
MAX_SOC_FRAC = 0.90

# Default grid-charging toggle (applied when function arg is None)
GRID_CHARGING_ENABLED = False

def _resolve_flag(user_value: Optional[bool], default_value: bool) -> bool:
    """Return a concrete boolean for tri-state toggles.

    If the caller passes None, fall back to the module-level default. Otherwise
    coerce the provided value to bool. Keeps all call sites consistent.
    """
    return default_value if user_value is None else bool(user_value)


# PV model constants (simple PVWatts‑like), aligned to PySAM preset assumptions
# Loss stack / PR approximates detailed model losses (soiling/mismatch/wiring/inverter/availability)
PR_BASE = 0.80               # base performance ratio
NOCT_C = 45.0                # Nominal Operating Cell Temp (°C)
G_REF = 1000.0               # reference irradiance (W/m^2)
G_NOCT = 800.0               # NOCT reference irradiance (W/m^2)
GAMMA_PDC = -0.00337         # DC power temp coeff per °C (−0.337%/°C)

# Weather alignment
WEATHER_SHIFT_HOURS = 8      # Fixed shift (hours) to align weather to local load
# 8 hours is the most correct timeshift for the custom solar / storage -- the sun really does go down before 4pm in January, and after 6pm in July. 

# Sizing fraction relative to the "annual-energy match" anchor (1.0 = match).
# Pipeline default: 0.5 (50% of annual-load match). Change this constant to adjust.
PV_SIZE_FRACTION = 1

# Optional: use EAC sweep (PV×Battery) "best" sizes per scenario/county.
# Deterministic behavior: when enabled, Step 9 reads only the dynamic‑dispatch
# integrated dashboard CSV to size PV and battery; if missing, the county run
# fails (no fallback to other sources or default sizing).
USE_EAC_OPTIMAL_SIZING = False

# Deterministic source root for min‑EAC results (integrated dashboard),
# keyed by the local dispatch mode.
DISPATCH_LABEL = "dispatch_dynamic" if USE_DYNAMIC_DISPATCH else "dispatch_classic"
EAC_DYNAMIC_RESULTS_ROOT = os.path.join(
    "data", "experiments", "integrated_dashboard", DISPATCH_LABEL, "combined"
)


def _find_header_row(path: str) -> int:
    """Find the zero‑based index of the header row containing 'Year' in NSRDB CSV."""
    with open(path, 'r', newline='') as f:
        for idx, line in enumerate(f):
            if 'Year' in line and ',' in line:
                return idx
    return 0


def _read_weather_csv(path: str) -> pd.DataFrame:
    """Read NSRDB CSV (TMY) and return a DataFrame with at least GHI and ambient temp."""
    header_idx = _find_header_row(path)
    df = pd.read_csv(path, skiprows=header_idx)
    # Normalize column names
    cols = {c: c.strip().lower() for c in df.columns}
    df.rename(columns=cols, inplace=True)

    # Candidate columns
    def get_col(*candidates: str) -> Optional[str]:
        for c in candidates:
            if c.lower() in df.columns:
                return c.lower()
        return None

    ghi_col = get_col('ghi', 'global horizontal irradiance', 'gh')
    temp_col = get_col('temp', 'temperature', 'tdry', 't_dry', 'ambient temperature', 'tamb')
    if not ghi_col:
        raise ValueError(f"Weather CSV missing GHI column: {path}")
    if not temp_col:
        # fallback: synthesize temp 20C if missing
        df['__temp_fallback'] = 20.0
        temp_col = '__temp_fallback'

    # Ensure numeric and length
    ghi = pd.to_numeric(df[ghi_col], errors='coerce').fillna(0.0)
    tamb = pd.to_numeric(df[temp_col], errors='coerce').fillna(20.0)
    out = pd.DataFrame({'ghi': ghi, 'tamb': tamb})

    # Keep exactly 8760 values
    if len(out) > 8760:
        out = out.iloc[:8760].reset_index(drop=True)
    elif len(out) < 8760:
        # tile if an exact divisor; else pad with zeros
        if 8760 % len(out) == 0 and len(out) > 0:
            reps = 8760 // len(out)
            out = pd.concat([out] * reps, ignore_index=True).iloc[:8760]
        else:
            pad = pd.DataFrame({'ghi': [0.0] * (8760 - len(out)), 'tamb': [20.0] * (8760 - len(out))})
            out = pd.concat([out, pad], ignore_index=True)
    return out


def _apply_weather_shift(df: pd.DataFrame) -> pd.DataFrame:
    """Rotate weather series by fixed WEATHER_SHIFT_HOURS constant."""
    shift = WEATHER_SHIFT_HOURS
    if shift % 8760 == 0:
        return df
    out = df.copy()
    for col in out.columns:
        vals = out[col].tolist()
        # left‑rotation by shift
        n = shift % len(vals)
        out[col] = vals[n:] + vals[:n]
    print(f"[Weather] Applied fixed shift={shift}h for weather (no tz override)")
    return out


def _aggregate_to_hourly(series: List[float], expected_length: int = 8760) -> List[float]:
    n = len(series)
    if n == expected_length:
        return list(series)
    if n % expected_length != 0 or n == 0:
        return list(series[:expected_length]) + [0.0] * max(0, expected_length - n)
    factor = n // expected_length
    hourly = []
    for i in range(expected_length):
        s = i * factor
        e = s + factor
        hourly.append(float(pd.Series(series[s:e]).mean()))
    return hourly


def _prepare_weather_and_load(weather_file: str, load_file: str) -> Tuple[pd.DataFrame, List[float]]:
    # Weather
    w = _read_weather_csv(weather_file)
    w = _apply_weather_shift(w)

    # Load profile and align to Jan 1 00:00 if timestamp present
    load_df = pd.read_csv(load_file)

    def _roll_left(vals: List[float], n: int) -> List[float]:
        if not vals:
            return vals
        n = n % len(vals)
        return vals[n:] + vals[:n]

    vals = load_df[TOTAL_LOAD_COLUMN_NAME].astype(float).tolist()
    ts_col_candidates = ["timestamp", "Timestamp", "datetime", "date", "time"]
    ts_col = next((c for c in ts_col_candidates if c in load_df.columns), None)
    shifted = False
    if ts_col is not None:
        try:
            ts = pd.to_datetime(load_df[ts_col], errors="coerce")
            midnight_idx = ts[(ts.dt.month == 1) & (ts.dt.day == 1) & (ts.dt.hour == 0)].index
            if len(midnight_idx) > 0:
                i0 = int(midnight_idx[0])
                if i0 != 0:
                    vals = _roll_left(vals, i0)
                    shifted = True
                    log(load_timezone_shift_hours=i0, load_timezone_shift_method="timestamp_detected_midnight")
        except Exception:
            pass
    if not shifted:
        env_shift = os.getenv("LOAD_TZ_SHIFT_HOURS")
        if env_shift:
            try:
                shift_h = int(env_shift)
                if shift_h != 0:
                    vals = _roll_left(vals, shift_h)
                    log(load_timezone_shift_hours=shift_h, load_timezone_shift_method="env_LOAD_TZ_SHIFT_HOURS")
            except Exception:
                pass
    if len(vals) != 8760:
        vals = _aggregate_to_hourly(vals, 8760)

    return w, vals


@contextlib.contextmanager
def _temp_battery_capacity_kwh(kwh: float):
    """Temporarily override BATTERY_CAPACITY_KWH within this module.

    This keeps the change scoped to a single county iteration without
    refactoring dispatch signatures. Restores the previous value on exit.
    """
    global BATTERY_CAPACITY_KWH
    prev = BATTERY_CAPACITY_KWH
    try:
        BATTERY_CAPACITY_KWH = float(kwh)
        yield
    finally:
        BATTERY_CAPACITY_KWH = prev


def _find_eac_min_sizes(
    scenario: str,
    housing_type: str,
    county_dir_name: str,
) -> Optional[Tuple[float, float]]:
    """Return (solar_kw, battery_kwh) at min EAC from dynamic‑dispatch integrated CSV.

    Deterministic: uses only EAC_DYNAMIC_RESULTS_ROOT. Raises if missing.
    """
    slug = slugify_county_name(county_dir_name)
    csv_path = os.path.join(
        EAC_DYNAMIC_RESULTS_ROOT,
        scenario,
        housing_type,
        slug,
        f"combined_sweep_{slug}.csv",
    )
    if not os.path.exists(csv_path):
        raise FileNotFoundError(
            f"EAC sweep CSV not found (dynamic dispatch): {csv_path}. "
            f"Run the integrated combined sweep first."
        )
    df = pd.read_csv(csv_path)
    if df.empty:
        raise ValueError(f"EAC sweep CSV is empty: {csv_path}")
    if 'eac_total' not in df.columns:
        comp_cols = [
            'capex_pv_annual', 'capex_storage_annual', 'capex_electric',
            'capex_gas', 'vehicle_om', 'annual_bill_with_solar'
        ]
        for c in comp_cols:
            if c not in df.columns:
                df[c] = 0.0
        eac = (
            pd.to_numeric(df['capex_pv_annual'], errors='coerce').fillna(0)
            + pd.to_numeric(df['capex_storage_annual'], errors='coerce').fillna(0)
            + pd.to_numeric(df['capex_electric'], errors='coerce').fillna(0)
            + pd.to_numeric(df['capex_gas'], errors='coerce').fillna(0)
            + pd.to_numeric(df['vehicle_om'], errors='coerce').fillna(0)
            + pd.to_numeric(df['annual_bill_with_solar'], errors='coerce').fillna(0)
        )
        df['eac_total'] = pd.to_numeric(eac, errors='coerce').fillna(0)
    row = df.loc[df['eac_total'].idxmin()]
    solar_kw = float(row.get('solar_kw', float('nan')))
    batt_kwh = float(row.get('battery_kwh', float('nan')))
    if pd.isna(solar_kw) or pd.isna(batt_kwh):
        raise ValueError(
            f"EAC CSV missing required columns (solar_kw, battery_kwh): {csv_path}"
        )
    return (float(solar_kw), float(batt_kwh))


def _compute_system_capacity_kW(weather_df: pd.DataFrame, load_profile: List[float]) -> float:
    # Sizing mirrors earlier heuristic: annual irradiance → energy per m^2 → DC capacity
    mean_ghi = float(weather_df['ghi'].mean())  # W/m²
    daily_irr_kwh_per_m2 = mean_ghi * 24.0 / 1000.0
    annual_irr_kwh_per_m2 = daily_irr_kwh_per_m2 * 365.0
    # Align sizing with PySAM step (efficiency and PR)
    pv_cell_eff = 0.206
    system_pr = PR_BASE   # 0.80
    annual_elec_per_m2 = annual_irr_kwh_per_m2 * pv_cell_eff * system_pr
    # Power density at STC ≈ 0.193 kW/m² used in the SAM-based step
    panel_power_density_kw_per_m2 = 0.193

    annual_load_kwh = sum(load_profile)
    required_panel_area_m2 = (annual_load_kwh / annual_elec_per_m2) if annual_elec_per_m2 > 0 else 0.0
    required_dc_capacity_kw = required_panel_area_m2 * panel_power_density_kw_per_m2
    log(debug_required_panel_area_m2=required_panel_area_m2, debug_required_dc_capacity_kW=required_dc_capacity_kw)
    return required_dc_capacity_kw


def _pv_timeseries_ac_kwh(weather_df: pd.DataFrame, system_capacity_kw: float) -> List[float]:
    """Compute hourly PV AC energy using simple PVWatts‑style model."""
    ghi = weather_df['ghi'].astype(float).values
    tamb = weather_df['tamb'].astype(float).values
    # Cell temperature estimate
    tcell = tamb + ((NOCT_C - 20.0) / G_NOCT) * ghi
    temp_derate = 1.0 + GAMMA_PDC * (tcell - 25.0)
    temp_derate = pd.Series(temp_derate).clip(lower=0.0, upper=1.5).values
    # AC power as hourly average power (kW), so equals kWh per hour
    pac = system_capacity_kw * (ghi / G_REF) * PR_BASE * temp_derate
    pac = pd.Series(pac).clip(lower=0.0).values
    # Ensure 8760 values
    if len(pac) != 8760:
        pac = _aggregate_to_hourly(list(map(float, pac)), 8760)
    else:
        pac = list(map(float, pac))
    return pac


# --- Battery dispatch implementations ---

def _battery_dispatch_classic(
    load_kwh: List[float],
    solar_kwh: List[float],
) -> Tuple[
    List[float], List[float], List[float], List[float], List[float], List[float], List[float]
]:
    """Classic windowed discharge (16–21), optional PV surplus charge, optional grid charge 14–16.
    Default grid charging is disabled via GRID_CHARGING_ENABLED.
    """
    assert len(load_kwh) == 8760 and len(solar_kwh) == 8760
    soc_kwh = BATTERY_CAPACITY_KWH * MIN_SOC_FRAC
    min_soc_kwh = BATTERY_CAPACITY_KWH * MIN_SOC_FRAC
    max_soc_kwh = BATTERY_CAPACITY_KWH * MAX_SOC_FRAC
    grid_demand = [0.0] * 8760
    batt_charge = [0.0] * 8760
    batt_discharge = [0.0] * 8760
    grid_to_load = [0.0] * 8760
    grid_to_batt = [0.0] * 8760
    # Explicit channels for PV→Battery and Grid→Battery
    pv_to_batt = [0.0] * 8760
    soc_percent = [0.0] * 8760

    # Resolve toggles: PV surplus via module constant; grid charging via module constant only
    pv_surplus_flag = ENABLE_PV_SURPLUS_TO_BATTERY
    grid_charge_flag = GRID_CHARGING_ENABLED

    for h in range(8760):
        hod = h % 24
        # Solar offsets household load immediately
        net_after_solar = max(load_kwh[h] - solar_kwh[h], 0.0)
        # PV surplus available after serving load
        pv_surplus = max(solar_kwh[h] - load_kwh[h], 0.0)

        # Discharge to cover peak window residual load
        if DISCHARGE_START_HOUR <= hod < DISCHARGE_END_HOUR and net_after_solar > 0 and soc_kwh > min_soc_kwh:
            desired_to_load = min(P_DISCHARGE_MAX_KW, net_after_solar)
            available_discharge_energy = max(soc_kwh - min_soc_kwh, 0.0)
            energy_from_batt = min(available_discharge_energy, desired_to_load / ETA_DISCHARGE)
            delivered = energy_from_batt * ETA_DISCHARGE
            soc_kwh -= energy_from_batt
            batt_discharge[h] = delivered
            net_after_solar -= delivered

        # First: charge from PV surplus (any hour), obeying power cap and headroom
        pv_input_energy_used = 0.0
        if pv_surplus_flag and pv_surplus > 0 and soc_kwh < max_soc_kwh:
            remaining_input_headroom = max((max_soc_kwh - soc_kwh) / ETA_CHARGE, 0.0)
            # Limit by battery charge power
            pv_input_energy = min(pv_surplus, P_CHARGE_MAX_KW, remaining_input_headroom)
            if pv_input_energy > 0:
                stored_pv = pv_input_energy * ETA_CHARGE
                soc_kwh += stored_pv
                batt_charge[h] += stored_pv
                pv_to_batt[h] = pv_input_energy
                pv_input_energy_used = pv_input_energy

        # Then: optionally top-up from grid during 14:00–16:00, obeying remaining power and headroom
        if grid_charge_flag and CHARGE_START_HOUR <= hod < CHARGE_END_HOUR and soc_kwh < max_soc_kwh:
            remaining_input_headroom = max((max_soc_kwh - soc_kwh) / ETA_CHARGE, 0.0)
            # Respect charge power cap; subtract PV portion already used this hour
            remaining_power_cap = max(P_CHARGE_MAX_KW - pv_input_energy_used, 0.0)
            max_grid_energy = min(remaining_power_cap, remaining_input_headroom)
            if max_grid_energy > 0:
                stored_grid = max_grid_energy * ETA_CHARGE
                soc_kwh += stored_grid
                batt_charge[h] += stored_grid
                grid_to_batt[h] = max_grid_energy

        grid_to_load[h] = max(net_after_solar, 0.0)
        grid_demand[h] = grid_to_load[h] + grid_to_batt[h]
        soc_percent[h] = (soc_kwh / BATTERY_CAPACITY_KWH) * 100.0

    return grid_demand, batt_charge, batt_discharge, grid_to_load, grid_to_batt, pv_to_batt, soc_percent


def _battery_dispatch_dynamic(
    load_kwh: List[float],
    solar_kwh: List[float],
) -> Tuple[
    List[float], List[float], List[float], List[float], List[float], List[float], List[float]
]:
    """Dynamic PV-only dispatch:
    - Charge from PV surplus only (no grid→battery), any hour.
    - At 16:00, if PV < load, enter discharge mode and continue discharging up to residual
      (respecting power/SOC limits) until min SOC or first hour PV ≥ load.
    """
    assert len(load_kwh) == 8760 and len(solar_kwh) == 8760
    soc_kwh = BATTERY_CAPACITY_KWH * MIN_SOC_FRAC
    min_soc_kwh = BATTERY_CAPACITY_KWH * MIN_SOC_FRAC
    max_soc_kwh = BATTERY_CAPACITY_KWH * MAX_SOC_FRAC
    grid_demand = [0.0] * 8760
    batt_charge = [0.0] * 8760
    batt_discharge = [0.0] * 8760
    grid_to_load = [0.0] * 8760
    grid_to_batt = [0.0] * 8760
    pv_to_batt = [0.0] * 8760
    soc_percent = [0.0] * 8760

    pv_surplus_flag = ENABLE_PV_SURPLUS_TO_BATTERY
    discharge_mode = False

    for h in range(8760):
        hod = h % 24
        load_h = float(load_kwh[h])
        pv_h = float(solar_kwh[h])
        net_after_pv = max(load_h - pv_h, 0.0)
        pv_surplus = max(pv_h - load_h, 0.0)

        if (hod >= DISCHARGE_START_HOUR or discharge_mode) and net_after_pv > 0.0: # decide whether we should be in discharge mode this hour
            discharge_mode = True
        if pv_surplus > 0.0: # stop discharging once PV >= load (first hour surplus)
            discharge_mode = False

        if discharge_mode and net_after_pv > 0.0 and soc_kwh > min_soc_kwh:
            desired = min(P_DISCHARGE_MAX_KW, net_after_pv)
            available_discharge_energy = max(soc_kwh - min_soc_kwh, 0.0)
            energy_from_batt = min(available_discharge_energy, desired / ETA_DISCHARGE)
            delivered = energy_from_batt * ETA_DISCHARGE
            if delivered > 0:
                soc_kwh -= energy_from_batt
                batt_discharge[h] = delivered
                net_after_pv -= delivered

        if pv_surplus_flag and pv_surplus > 0.0 and soc_kwh < max_soc_kwh:
            remaining_input_headroom = max((max_soc_kwh - soc_kwh) / ETA_CHARGE, 0.0)
            pv_input_energy = min(pv_surplus, P_CHARGE_MAX_KW, remaining_input_headroom)
            if pv_input_energy > 0:
                stored_pv = pv_input_energy * ETA_CHARGE
                soc_kwh += stored_pv
                batt_charge[h] += stored_pv
                pv_to_batt[h] = pv_input_energy

        grid_to_load[h] = max(net_after_pv, 0.0)
        grid_demand[h] = grid_to_load[h]
        soc_percent[h] = (soc_kwh / BATTERY_CAPACITY_KWH) * 100.0

    return grid_demand, batt_charge, batt_discharge, grid_to_load, grid_to_batt, pv_to_batt, soc_percent


def _simple_battery_dispatch(
    load_kwh: List[float],
    solar_kwh: List[float],
) -> Tuple[
    List[float], List[float], List[float], List[float], List[float], List[float], List[float]
]:
    """Dispatch wrapper that selects between classic and dynamic strategies.
    Toggle with USE_DYNAMIC_DISPATCH at the top of this file.
    """
    if USE_DYNAMIC_DISPATCH:
        return _battery_dispatch_dynamic(load_kwh, solar_kwh)
    return _battery_dispatch_classic(load_kwh, solar_kwh)


def _validate_lengths(*series_lists: List[List[float]]) -> None:
    for s in series_lists:
        for arr in s:
            if len(arr) != 8760:
                raise ValueError("All output series must be 8760 elements long.")


def process(
    base_input_dir: str,
    base_output_dir: str,
    scenario: str,
    housing_type: str,
    counties: Optional[List[str]] = None,
    years_of_analysis: int = 1,
    force_recompute: bool = False,
):
    scenario_path = get_scenario_path(base_input_dir, scenario, housing_type)
    counties_to_run = get_counties(scenario_path, counties)
    capacity_dict = {}

    for county in counties_to_run:
        try:
            log(county=county)
            weather_file = os.path.join(base_input_dir, scenario, housing_type, county, f"weather_TMY_{county}.csv")
            load_file = os.path.join(scenario_path, county, f"{LOADPROFILE_FILE_PREFIX}_{scenario}_{county}.csv")
            output_file = os.path.join(base_output_dir, scenario, housing_type, county, f"{OUTPUT_LOADPROFILE_FILE_PREFIX}_{county}.csv")

            if not os.path.exists(weather_file):
                print(f"Weather file not found: {weather_file}. Skipping...")
                continue
            if not os.path.exists(load_file):
                print(f"Load file not found: {load_file}. Skipping...")
                continue
            if not force_recompute and os.path.exists(output_file):
                print(f"Output exists: {output_file}. Skipping (force_recompute=True to rebuild)")
                continue

            # Weather + load
            weather_df, load_profile = _prepare_weather_and_load(weather_file, load_file)
            # Decide sizing approach
            base_capacity_kw = _compute_system_capacity_kW(weather_df, load_profile)
            system_capacity_kW = base_capacity_kw * PV_SIZE_FRACTION
            selected_batt_kwh: Optional[float] = None
            if USE_EAC_OPTIMAL_SIZING:
                opt_solar_kw, opt_batt_kwh = _find_eac_min_sizes(scenario, housing_type, county)
                system_capacity_kW = float(opt_solar_kw)
                selected_batt_kwh = float(opt_batt_kwh)
                log(eac_optimal_sizing_applied=True, solar_kw=system_capacity_kW, battery_kwh=selected_batt_kwh)

            # Record the sizing that will be used for this county
            used_batt_kwh = float(selected_batt_kwh) if selected_batt_kwh is not None else float(BATTERY_CAPACITY_KWH)
            log(at="step9_sizing", county=county, solar_capacity_kw_used=system_capacity_kW, battery_capacity_kwh_used=used_batt_kwh)

            # Compute PV hourly AC (kWh)
            solar_gen = _pv_timeseries_ac_kwh(weather_df, system_capacity_kW)

            # Battery (grid-only charge, PV immediate offset)
            if selected_batt_kwh is not None:
                with _temp_battery_capacity_kwh(selected_batt_kwh):
                    grid_demand, batt_charge, batt_discharge, grid_to_load, grid_to_batt, pv_to_batt, soc_percent = _simple_battery_dispatch(
                        load_profile, solar_gen
                    )
            else:
                grid_demand, batt_charge, batt_discharge, grid_to_load, grid_to_batt, pv_to_batt, soc_percent = _simple_battery_dispatch(
                    load_profile, solar_gen
                )
            _validate_lengths([solar_gen, grid_demand, batt_charge, batt_discharge, grid_to_load, grid_to_batt, pv_to_batt, soc_percent])

            # Human-readable summaries for verification
            log_profiles(
                {
                    "Household Load (kWh)": load_profile,
                    "Solar Generation (kWh)": solar_gen,
                    "Battery Charge (kWh)": batt_charge,
                    "Battery Discharge (kWh)": batt_discharge,
                    "Grid to Household Load (kWh)": grid_to_load,
                    "Grid to Battery (kWh)": grid_to_batt,
                    "Grid Demand (kWh)": grid_demand,
                },
                title=f"DIY Dispatch Profiles — {county}",
            )

            # Detailed diagnostics comparable to PySAM step
            try:
                total_load = float(sum(load_profile))
                total_pv_gen = float(sum(solar_gen))
                system_to_load = [min(s, l) for s, l in zip(solar_gen, load_profile)]
                pv_to_load_sum = float(sum(system_to_load))
                pv_to_batt_sum = float(sum(pv_to_batt))
                pv_to_grid_implied = max(0.0, total_pv_gen - (pv_to_load_sum + pv_to_batt_sum))
                batt_to_load_sum = float(sum(batt_discharge))
                grid_to_load_sum = float(sum(grid_to_load))
                grid_to_batt_sum = float(sum(grid_to_batt))
                soc_min = min(soc_percent) if soc_percent else 0.0
                soc_max = max(soc_percent) if soc_percent else 0.0
                soc_end = soc_percent[-1] if soc_percent else 0.0
                mean_ghi = float(weather_df['ghi'].mean())
                sum_ghi_kwhm2 = float(weather_df['ghi'].sum()) / 1000.0
                jan_len = 31 * 24
                jan_idx = int(pd.Series(solar_gen[:jan_len]).idxmax()) if total_pv_gen > 0 else -1
                jan_hod = jan_idx % 24 if jan_idx >= 0 else -1
                print("\n[DIY PV Diagnostics]", county)
                print(f"  WEATHER_SHIFT_HOURS       = {WEATHER_SHIFT_HOURS}")
                print(f"  PR_BASE / NOCT / gamma    = {PR_BASE} / {NOCT_C}C / {GAMMA_PDC}/C")
                print(f"  mean_GHI_Wm2              = {mean_ghi:.1f}")
                print(f"  sum_GHI_kWh_per_m2        = {sum_ghi_kwhm2:.1f}")
                print(f"  system_capacity_kW        = {system_capacity_kW:.3f}")
                print(f"  battery_capacity_kWh      = {used_batt_kwh:.2f}")
                print(f"  total_pv_gen_kWh          = {total_pv_gen:.1f}")
                print(f"  pv_to_load_kWh            = {pv_to_load_sum:.1f}")
                print(f"  pv_to_batt_kWh            = {pv_to_batt_sum:.1f}")
                print(f"  pv_to_grid_kWh(derived)   = {pv_to_grid_implied:.1f}")
                print(f"  batt_to_load_kWh          = {batt_to_load_sum:.1f}")
                print(f"  grid_to_load_kWh          = {grid_to_load_sum:.1f}")
                print(f"  grid_to_batt_kWh          = {grid_to_batt_sum:.1f}")
                print(f"  total_load_kWh            = {total_load:.1f}")
                print(f"  batt_SOC[%] min/max/end   = {soc_min:.1f}/{soc_max:.1f}/{soc_end:.1f}")
                print(f"  Jan peak hour-of-day      = {jan_hod}")
            except Exception:
                pass

            # Save per-county outputs in the standard schema used by step10
            os.makedirs(os.path.dirname(output_file), exist_ok=True)
            date_range = pd.date_range(start="2018-01-01", periods=8760, freq="H")
            system_to_load = [min(s, l) for s, l in zip(solar_gen, load_profile)]
            batt_to_load = batt_discharge
            # Derive PV→Grid from PV AC and on-site PV uses (PV→Load, PV→Battery).
            # Keep non-negative and consistent with energy balance.
            pv_to_grid = [
                max(0.0, float(s) - float(a) - float(b))
                for s, a, b in zip(solar_gen, system_to_load, pv_to_batt)
            ]

            df = pd.DataFrame({
                "Load Profile": load_profile,
                "System to Load": system_to_load,
                "Battery to Load": batt_to_load,
                "Grid to Load": grid_to_load,
                "Solar + Battery to Load": [a + b for a, b in zip(system_to_load, batt_to_load)],
                "Total Supply": [a + b + c for a, b, c in zip(system_to_load, batt_to_load, grid_to_load)],
                "Difference": [l - (a + b + c) for l, a, b, c in zip(load_profile, system_to_load, batt_to_load, grid_to_load)],
                "System to Battery": pv_to_batt,
                "Grid to Battery": grid_to_batt,
                "Battery SOC": soc_percent,
                # New columns to support NEM 3.0 accounting downstream
                "PV AC (kWh)": solar_gen,
                "PV to Grid (kWh)": pv_to_grid,
            }, index=date_range)
            df.to_csv(output_file)

            # Create and save Jan/Jul plots
            plots_path = os.path.join(
                base_output_dir,
                scenario,
                housing_type,
                county,
                f"step9_my_own_solar_storage_plots_{county}_g{GIT_SHORT_SHA}.png",
            )
            try:
                os.makedirs(os.path.dirname(plots_path), exist_ok=True)
                pv_used_series = [min(s, l) + pv for s, l, pv in zip(solar_gen, load_profile, pv_to_batt)]
                summary = {
                    "Solar size (kW)": float(system_capacity_kW),
                    "PV gross (kWh)": float(sum(solar_gen)),
                    "PV used (kWh)": float(sum(pv_used_series)),
                    "PV→Battery (kWh)": float(sum(pv_to_batt)),
                    "Battery→Load (kWh)": float(sum(batt_discharge)),
                    "Grid→Battery (kWh)": float(sum(grid_to_batt)),
                }
                plot_first_weeks(
                    load_kwh=load_profile,
                    pv_ac_kwh=solar_gen,
                    batt_to_load_kwh=batt_discharge,
                    grid_to_load_kwh=grid_to_load,
                    grid_to_batt_kwh=grid_to_batt,
                    pv_to_batt_kwh=pv_to_batt,
                    soc_percent=soc_percent,
                    pv_used_kwh=pv_used_series,
                    summary_stats=summary,
                    title=f"DIY Dispatch — {scenario} — {county}",
                    show=False,
                    save_path=plots_path,
                )
                print(f"Saved step9_my_own_solar_storage plots to: {plots_path}")
            except Exception as plot_err:
                print(f"Plotting failed for {county}: {plot_err}")

            # Track capacity for capital costs linkage
            capacity_dict[county] = {
                "Solar Capacity (kW)": to_decimal_number(system_capacity_kW),
                "Battery Capacity (kWh)": to_decimal_number(selected_batt_kwh if selected_batt_kwh is not None else BATTERY_CAPACITY_KWH),
            }

            # Compact log
            log(
                at="step9_my_own_solar_storage",
                solar_profile=format_load_profile(solar_gen),
                grid_to_load=format_load_profile(grid_to_load),
                batt_to_load=format_load_profile(batt_to_load),
                grid_to_batt=format_load_profile(grid_to_batt),
                saved_to=output_file,
            )

        except Exception as e:
            print(f"Error processing {county}: {e}")

    # Save capacity table
    capital_costs_folder = f"{base_input_dir}/{scenario}/{housing_type}/{CAPITAL_COSTS_FOLDER_NAME}"
    os.makedirs(capital_costs_folder, exist_ok=True)
    capacity_df = pd.DataFrame.from_dict(capacity_dict, orient="index").rename_axis("County")
    capacity_df.to_csv(f"{capital_costs_folder}/{SOLAR_STORAGE_CAPACITY_PREFIX}.csv")


# Example usage
scenario = "baseline"
housing_type = "single-family-detached"

if __name__ == "__main__":
    process(
        "data/loadprofiles",
        "data/loadprofiles",
        scenario,
        housing_type,
        ["Alameda County"], # norcal_counties, # + socal_counties + central_counties,
        force_recompute=True,
    )
