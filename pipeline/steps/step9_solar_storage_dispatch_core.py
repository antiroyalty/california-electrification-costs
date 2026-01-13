"""
Core PV + dynamic battery dispatch logic for Step 9 (no tariffs/NEM3).

Responsibilities:
- Read/align weather and load
- Size PV system (heuristic)
- Compute PV AC timeseries
- Dynamic dispatch (PV-only charging, evening discharge)

Exports:
- Functions used by step9_my_own_solar_storage.py to produce the base CSV
  and to assemble inputs for the exports-only CSV.
"""

from __future__ import annotations

from typing import List, Optional, Tuple
import contextlib

import os
import pandas as pd


# PV model constants (simple PVWatts‑like), aligned to PySAM preset assumptions
PR_BASE = 0.80               # base performance ratio
NOCT_C = 45.0                # Nominal Operating Cell Temp (°C)
G_REF = 1000.0               # reference irradiance (W/m^2)
G_NOCT = 800.0               # NOCT reference irradiance (W/m^2)
GAMMA_PDC = -0.00337         # DC power temp coeff per °C (−0.337%/°C)

# Weather alignment
WEATHER_SHIFT_HOURS = 8      # Fixed shift (hours) to align weather to local load

# Battery + dispatch constants (dynamic only; no grid charging)
from math import sqrt

ENABLE_PV_SURPLUS_TO_BATTERY = True
BATTERY_CAPACITY_KWH = 13.5
ROUND_TRIP_EFFICIENCY = 0.96
ETA_CHARGE = sqrt(ROUND_TRIP_EFFICIENCY)
ETA_DISCHARGE = sqrt(ROUND_TRIP_EFFICIENCY)
P_CHARGE_MAX_KW = 3.0
P_DISCHARGE_MAX_KW = 3.0
DISCHARGE_START_HOUR = 16
DISCHARGE_END_HOUR = 21
MIN_SOC_FRAC = 0.20
MAX_SOC_FRAC = 0.90


def _find_header_row(path: str) -> int:
    """Find the zero‑based index of the header row containing 'Year' in NSRDB CSV."""
    with open(path, 'r', newline='') as f:
        for idx, line in enumerate(f):
            if 'Year' in line and ',' in line:
                return idx
    return 0


def read_weather_csv(path: str) -> pd.DataFrame:
    """Read NSRDB CSV (TMY) and return a DataFrame with at least GHI and ambient temp."""
    header_idx = _find_header_row(path)
    df = pd.read_csv(path, skiprows=header_idx)
    cols = {c: c.strip().lower() for c in df.columns}
    df.rename(columns=cols, inplace=True)

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
        df['__temp_fallback'] = 20.0
        temp_col = '__temp_fallback'

    ghi = pd.to_numeric(df[ghi_col], errors='coerce').fillna(0.0)
    tamb = pd.to_numeric(df[temp_col], errors='coerce').fillna(20.0)
    out = pd.DataFrame({'ghi': ghi, 'tamb': tamb})

    # Ensure 8760 values
    if len(out) > 8760:
        out = out.iloc[:8760].reset_index(drop=True)
    elif len(out) < 8760:
        if 8760 % len(out) == 0 and len(out) > 0:
            reps = 8760 // len(out)
            out = pd.concat([out] * reps, ignore_index=True).iloc[:8760]
        else:
            pad = pd.DataFrame({'ghi': [0.0] * (8760 - len(out)), 'tamb': [20.0] * (8760 - len(out))})
            out = pd.concat([out, pad], ignore_index=True)
    return out


def apply_weather_shift(df: pd.DataFrame) -> pd.DataFrame:
    """Rotate weather series by fixed WEATHER_SHIFT_HOURS constant."""
    shift = WEATHER_SHIFT_HOURS
    if shift % 8760 == 0:
        return df
    out = df.copy()
    for col in out.columns:
        vals = out[col].tolist()
        n = shift % len(vals)
        out[col] = vals[n:] + vals[:n]
    return out


def aggregate_to_hourly(series: List[float], expected_length: int = 8760) -> List[float]:
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


def prepare_weather_and_load(weather_file: str, load_file: str, total_load_column_name: str) -> Tuple[pd.DataFrame, List[float]]:
    # Weather
    w = read_weather_csv(weather_file)
    w = apply_weather_shift(w)

    # Load profile and align to Jan 1 00:00 if timestamp present
    load_df = pd.read_csv(load_file)

    def _roll_left(vals: List[float], n: int) -> List[float]:
        if not vals:
            return vals
        n = n % len(vals)
        return vals[n:] + vals[:n]

    vals = load_df[total_load_column_name].astype(float).tolist()
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
        except Exception:
            pass
    if not shifted:
        env_shift = os.getenv("LOAD_TZ_SHIFT_HOURS")
        if env_shift:
            try:
                shift_h = int(env_shift)
                if shift_h != 0:
                    vals = _roll_left(vals, shift_h)
            except Exception:
                pass
    if len(vals) != 8760:
        vals = aggregate_to_hourly(vals, 8760)

    return w, vals


@contextlib.contextmanager
def temp_battery_capacity_kwh(kwh: float):
    """Temporarily override BATTERY_CAPACITY_KWH within this module."""
    global BATTERY_CAPACITY_KWH
    prev = BATTERY_CAPACITY_KWH
    try:
        BATTERY_CAPACITY_KWH = float(kwh)
        yield
    finally:
        BATTERY_CAPACITY_KWH = prev


def compute_system_capacity_kW(weather_df: pd.DataFrame, load_profile: List[float]) -> float:
    # Sizing mirrors earlier heuristic: annual irradiance → energy per m^2 → DC capacity
    mean_ghi = float(weather_df['ghi'].mean())  # W/m²
    daily_irr_kwh_per_m2 = mean_ghi * 24.0 / 1000.0
    annual_irr_kwh_per_m2 = daily_irr_kwh_per_m2 * 365.0
    pv_cell_eff = 0.206
    system_pr = PR_BASE
    annual_elec_per_m2 = annual_irr_kwh_per_m2 * pv_cell_eff * system_pr
    panel_power_density_kw_per_m2 = 0.193

    annual_load_kwh = sum(load_profile)
    required_panel_area_m2 = (annual_load_kwh / annual_elec_per_m2) if annual_elec_per_m2 > 0 else 0.0
    required_dc_capacity_kw = required_panel_area_m2 * panel_power_density_kw_per_m2
    return required_dc_capacity_kw


def pv_timeseries_ac_kwh(weather_df: pd.DataFrame, system_capacity_kw: float) -> List[float]:
    """Compute hourly PV AC energy using simple PVWatts‑style model."""
    ghi = weather_df['ghi'].astype(float).values
    tamb = weather_df['tamb'].astype(float).values
    tcell = tamb + ((NOCT_C - 20.0) / G_NOCT) * ghi
    temp_derate = 1.0 + GAMMA_PDC * (tcell - 25.0)
    temp_derate = pd.Series(temp_derate).clip(lower=0.0, upper=1.5).values
    pac = system_capacity_kw * (ghi / G_REF) * PR_BASE * temp_derate
    pac = pd.Series(pac).clip(lower=0.0).values
    if len(pac) != 8760:
        pac = aggregate_to_hourly(list(map(float, pac)), 8760)
    else:
        pac = list(map(float, pac))
    return pac


def battery_dispatch_dynamic(
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

        if (hod >= DISCHARGE_START_HOUR or discharge_mode) and net_after_pv > 0.0:
            discharge_mode = True
        if pv_surplus > 0.0:
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

