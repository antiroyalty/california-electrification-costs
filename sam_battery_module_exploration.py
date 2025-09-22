"""
SAM Battery Module Exploration (PySAM.Battery)

Goal
- Demonstrate a custom dispatch schedule using the System Advisor Model
  Battery (SCC) compute module that:
  - Respects SOC boundaries (default: 20% min, 80% max)
  - Charges mid‑day (PV‑driven) to prepare for the 4–9pm peak window
  - Discharges over the full 4–9pm peak window to serve household load
  - Disallows grid charging (PV‑only charging)
  - Produces clear per‑day SOC and first‑day power‑flow logs

Notes
- This script uses the Battery compute module (PySAM.Battery) with manual
  dispatch arrays. It requires a valid Battery JSON (inputs) for your system.
  See "CONFIGURATION" below for details.

Configuration
- Provide a Battery JSON config file exported from SAM for a battery model
  (not Battwatts). Place it at, for example:
    SAM_configuration/battery_module_default.json
  Then set BATTERY_CONFIG_FILE accordingly.

What this script does
1) Builds a PV profile with PVWatts from the local weather CSV (same as
   sam_custom_dispatch.py).
2) Loads a Battery module JSON. Sets key dispatch properties:
   - Manual dispatch arrays (charge/discharge/gridcharge)
   - Disable grid charging; prioritize PV‑first charging
   - SOC bounds and initial SOC
3) Runs Battery.execute(0) (stand‑alone battery with PV/load forecasts).
4) Logs first‑day power flows + produces a single‑day SOC plot.

Limitations
- The Battery compute module focuses on battery state/power flows and may not
  provide grid/PV allocation at the same fidelity as an integrated model like
  Pvsamv1. This script surfaces the most relevant flows available from Battery
  (battery power, SOC) and uses PV/Load forecasts to drive manual dispatch.
"""

from __future__ import annotations

import json
import os
from typing import List, Tuple

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

import PySAM.Pvwattsv8 as Pvwatts
import PySAM.ResourceTools as ResourceTools
import PySAM.Battery as BatteryMod


# Defaults / Paths
PV_CONFIG_FILE = "SAM_configuration/untitled__1__pvwattsv8.json"


# ------------------------------
# Helpers: PV + Load + Schedules
# ------------------------------

def get_raw_solar_profile(weather_file: str, hours_hint: int | None = None) -> List[float]:
    """
    Generate PV AC output via PVWatts for the provided weather file.
    System size is heuristically scaled if hours_hint is passed (annual load proxy).
    """
    solar_resource_data = ResourceTools.SAM_CSV_to_solar_data(weather_file)

    pv = Pvwatts.new()
    with open(PV_CONFIG_FILE, "r") as f:
        cfg = json.load(f)
    for k, v in cfg.items():
        if k == "number_inputs":
            continue
        try:
            pv.value(k, v)
        except Exception:
            pass

    # Heuristic sizing (optional)
    if hours_hint is not None:
        # 1200 kWh/kW/yr typical
        pv.SystemDesign.system_capacity = max(0.1, hours_hint / 1200.0)

    pv.SolarResource.solar_resource_data = solar_resource_data
    pv.execute(0)
    ac = np.asarray(pv.Outputs.ac, dtype=float).ravel().tolist()
    return ac


def get_daily_peak_window_energy(
    load_profile: List[float], day_index: int, peak_start_hour: int = 16, peak_end_hour: int = 21
) -> float:
    """Total kWh for one day in the 4–9pm peak window (end exclusive)."""
    n = len(load_profile)
    start = day_index * 24 + peak_start_hour
    end = day_index * 24 + peak_end_hour
    if start >= n:
        return 0.0
    return float(np.sum(load_profile[start : min(end, n)]))


def get_all_daily_peak_window_energy(
    load_profile: List[float], peak_start_hour: int = 16, peak_end_hour: int = 21
) -> List[float]:
    n_days = (len(load_profile) + 23) // 24
    return [
        get_daily_peak_window_energy(load_profile, d, peak_start_hour, peak_end_hour) for d in range(n_days)
    ]


def generate_full_peak_discharge_and_pv_charge_schedule(
    load_profile: List[float],
    solar_profile: List[float],
    peak_start_hour: int = 16,
    peak_end_hour: int = 21,
    max_charge_kw: float = 5.0,
    max_discharge_kw: float = 5.0,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    Create hour-by-hour manual dispatch (kW) arrays for the Battery module:
    - Charge from PV during daylight (PV priority), cap at max_charge_kw
    - Discharge during the full peak window (4–9pm), cap at max_discharge_kw
    - No grid charging (gridcharge array kept at 0)

    Returns (charge_kW, discharge_kW, gridcharge_kW)
    """
    hours = len(load_profile)
    assert len(solar_profile) == hours

    charge = np.zeros(hours)
    discharge = np.zeros(hours)
    gridcharge = np.zeros(hours)

    for h in range(hours):
        hod = h % 24
        if peak_start_hour <= hod < peak_end_hour:
            discharge[h] = max_discharge_kw
        elif 6 <= hod < 18:
            # PV‑first charging: request up to max_charge_kw. Battery module will enforce
            # SOC/power caps. We use PV availability here as an upper bound.
            charge[h] = min(max_charge_kw, max(0.0, solar_profile[h]))
        else:
            # Overnight: no grid charging
            charge[h] = 0.0
            gridcharge[h] = 0.0

    return charge, discharge, gridcharge


# --------------------------------------------
# Battery model (PySAM.Battery) initialization
# --------------------------------------------

def create_default_battery_module() -> BatteryMod.Battery:
    """
    Create and configure a Battery compute module instance with reasonable defaults
    suitable for manual dispatch exploration without requiring a JSON export.

    This sets:
      - Lithium-ion chemistry, initial SOC
      - Basic efficiencies and meter position
      - Manual dispatch mode and PV-first charging preference
      - Disallow grid charging and export
    """
    batt = BatteryMod.new()

    # Chemistry and initial SOC
    if hasattr(batt, "BatteryCell"):
        if hasattr(batt.BatteryCell, "batt_chem"):
            batt.BatteryCell.batt_chem = 1  # 1 = Li-ion
        if hasattr(batt.BatteryCell, "batt_initial_SOC"):
            batt.BatteryCell.batt_initial_SOC = 50.0

    # Core system efficiencies & topology (set if available)
    if hasattr(batt, "Battery"):
        for name, val in {
            "batt_meter_position": 0,  # 0=behind-the-meter
            "batt_ac_or_dc": 1,  # 1=AC-coupled (if supported)
            "batt_dc_dc_efficiency": 0.96,
            "batt_ac_dc_efficiency": 0.96,
            "batt_dc_ac_efficiency": 0.96,
            "batt_minimum_SOC": 20.0,
            "batt_maximum_SOC": 80.0,
        }.items():
            if hasattr(batt.Battery, name):
                setattr(batt.Battery, name, val)

    # Manual dispatch preferences
    if hasattr(batt, "BatteryDispatch"):
        if hasattr(batt.BatteryDispatch, "batt_dispatch_choice"):
            batt.BatteryDispatch.batt_dispatch_choice = 3  # manual dispatch
        # Disallow grid charge and export, allow charging
        for name, val in {
            "batt_dispatch_auto_can_gridcharge": 0,
            "batt_dispatch_auto_can_charge": 1,
            "batt_dispatch_auto_btm_can_discharge_to_grid": 0,
            "dispatch_manual_system_charge_first": 1,
        }.items():
            if hasattr(batt.BatteryDispatch, name):
                setattr(batt.BatteryDispatch, name, val)

    # Lifetime (keep simple one-year)
    if hasattr(batt, "Lifetime"):
        if hasattr(batt.Lifetime, "analysis_period"):
            batt.Lifetime.analysis_period = 1
        if hasattr(batt.Lifetime, "system_use_lifetime_output"):
            batt.Lifetime.system_use_lifetime_output = 0

    return batt


def configure_battery_dispatch(
    batt: BatteryMod.Battery,
    charge_kw: np.ndarray,
    discharge_kw: np.ndarray,
    gridcharge_kw: np.ndarray,
    min_soc: float = 20.0,
    max_soc: float = 80.0,
    initial_soc: float = 50.0,
) -> None:
    """
    Configure manual (custom) dispatch for the Battery module with magnitudes.

    - Disallow grid charging
    - PV‑first charging
    - Manual power arrays for charge/discharge/gridcharge
    - SOC bounds (min/max/initial)
    """
    n = len(charge_kw)
    assert len(discharge_kw) == n and len(gridcharge_kw) == n

    # BatteryCell / BatterySystem SOC bounds
    if hasattr(batt, "BatteryCell"):
        batt.BatteryCell.batt_initial_SOC = float(initial_soc)
    if hasattr(batt, "Battery"):
        # Some builds expose these on Battery group
        if hasattr(batt.Battery, "batt_minimum_SOC"):
            batt.Battery.batt_minimum_SOC = float(min_soc)
        if hasattr(batt.Battery, "batt_maximum_SOC"):
            batt.Battery.batt_maximum_SOC = float(max_soc)

    # BatteryDispatch settings (manual, PV‑first, no grid charge)
    if hasattr(batt, "BatteryDispatch"):
        # Manual dispatch mode
        if hasattr(batt.BatteryDispatch, "batt_dispatch_choice"):
            # 3 (Manual) or 2 (Custom) depending on SAM version; manual arrays below are respected
            batt.BatteryDispatch.batt_dispatch_choice = 3

        # Disallow grid charging; allow charging and disallow export
        if hasattr(batt.BatteryDispatch, "batt_dispatch_auto_can_gridcharge"):
            batt.BatteryDispatch.batt_dispatch_auto_can_gridcharge = 0
        if hasattr(batt.BatteryDispatch, "batt_dispatch_auto_can_charge"):
            batt.BatteryDispatch.batt_dispatch_auto_can_charge = 1
        if hasattr(batt.BatteryDispatch, "batt_dispatch_auto_btm_can_discharge_to_grid"):
            batt.BatteryDispatch.batt_dispatch_auto_btm_can_discharge_to_grid = 0

        # PV‑first preference for manual schedules
        if hasattr(batt.BatteryDispatch, "dispatch_manual_system_charge_first"):
            batt.BatteryDispatch.dispatch_manual_system_charge_first = 1

        # Manual arrays (kW). Some builds accept percent arrays instead (0–100% of max).
        # We set power arrays when available; otherwise fall back to percent arrays.
        if hasattr(batt.BatteryDispatch, "dispatch_manual_charge"):
            batt.BatteryDispatch.dispatch_manual_charge = charge_kw.tolist()
        if hasattr(batt.BatteryDispatch, "dispatch_manual_discharge"):
            batt.BatteryDispatch.dispatch_manual_discharge = discharge_kw.tolist()
        if hasattr(batt.BatteryDispatch, "dispatch_manual_gridcharge"):
            batt.BatteryDispatch.dispatch_manual_gridcharge = gridcharge_kw.tolist()

        # If only percent arrays are available
        if hasattr(batt.BatteryDispatch, "dispatch_manual_percent_discharge") and not hasattr(
            batt.BatteryDispatch, "dispatch_manual_discharge"
        ):
            batt.BatteryDispatch.dispatch_manual_percent_discharge = (
                np.clip(100.0 * (discharge_kw / np.max(discharge_kw) if np.max(discharge_kw) > 0 else 0), 0, 100)
            ).tolist()
        if hasattr(batt.BatteryDispatch, "dispatch_manual_percent_gridcharge") and not hasattr(
            batt.BatteryDispatch, "dispatch_manual_gridcharge"
        ):
            batt.BatteryDispatch.dispatch_manual_percent_gridcharge = (
                np.zeros_like(gridcharge_kw)
            ).tolist()


# -----------------
# Diagnostics + Plots
# -----------------

def log_first_day(batt: BatteryMod.Battery, day_index: int = 0) -> None:
    start = day_index * 24
    end = min(start + 24, len(batt.Outputs.batt_SOC))
    soc = np.asarray(batt.Outputs.batt_SOC, dtype=float).ravel()
    p_dc = (
        np.asarray(getattr(batt.Outputs, "batt_power", np.zeros_like(soc)), dtype=float).ravel()
        if hasattr(batt.Outputs, "batt_power")
        else np.zeros_like(soc)
    )
    print("\nDEBUG: Battery first 24 hours (SOC %, batt_power kW if available):")
    for h in range(start, end):
        print(f"  h={h:04d} hod={h%24:02d}  SOC={soc[h]:6.2f}  batt_power={p_dc[h]:7.3f}")


def plot_soc_one_day(batt: BatteryMod.Battery, day_index: int = 0, title: str = "Battery SOC (Day)") -> None:
    start = day_index * 24
    soc = np.asarray(batt.Outputs.batt_SOC, dtype=float).ravel()
    end = min(start + 24, len(soc))
    hours = np.arange(end - start)
    plt.figure(figsize=(12, 4))
    plt.title(f"{title} {day_index + 1}")
    plt.plot(hours, soc[start:end], "b-", lw=2)
    plt.axhline(20, color="red", ls="--", alpha=0.5)
    plt.axhline(80, color="orange", ls="--", alpha=0.5)
    # Peak window shading
    plt.axvspan(16, min(21, end - start), color="yellow", alpha=0.2)
    plt.xlabel("Hour")
    plt.ylabel("SOC (%)")
    plt.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.show()


# -----
# Main
# -----

def main():
    # Inputs (example paths based on repo layout)
    county_name = "alameda"
    weather_file = f"data/loadprofiles/baseline/single-family-detached/{county_name}/weather_TMY_{county_name}.csv"
    load_file = f"data/loadprofiles/baseline/single-family-detached/{county_name}/combined_profiles_baseline_{county_name}.csv"

    if not os.path.exists(load_file) or not os.path.exists(weather_file):
        print("Load or weather file not found. Please adjust paths in main().")
        return

    # Load hourly household load (kW)
    load_df = pd.read_csv(load_file)
    load_profile = load_df["electricity.real_and_simulated.for_typical_county_home.kwh"].tolist()
    print(f"Loaded load profile: {len(load_profile)} hours, {sum(load_profile):.0f} kWh/yr")

    # Build PV profile (kW AC)
    solar_profile = get_raw_solar_profile(weather_file, hours_hint=sum(load_profile))
    print(
        f"PVWatts solar: {len(solar_profile)} hours, annual AC {sum(solar_profile):.0f} kWh, "
        f"peak {max(solar_profile):.2f} kW"
    )

    # Generate schedules (kW)
    charge_kw, discharge_kw, gridcharge_kw = generate_full_peak_discharge_and_pv_charge_schedule(
        load_profile, solar_profile, peak_start_hour=16, peak_end_hour=21, max_charge_kw=5.0, max_discharge_kw=5.0
    )

    # Initialize Battery module
    batt = create_default_battery_module()

    # Provide PV/load forecasts to the Battery module if available
    if hasattr(batt, "BatteryDispatch"):
        if hasattr(batt.BatteryDispatch, "batt_pv_ac_forecast"):
            batt.BatteryDispatch.batt_pv_ac_forecast = solar_profile
        if hasattr(batt.BatteryDispatch, "batt_load_ac_forecast"):
            batt.BatteryDispatch.batt_load_ac_forecast = load_profile

    # Configure manual dispatch and SOC bounds
    configure_battery_dispatch(
        batt,
        charge_kw,
        discharge_kw,
        gridcharge_kw,
        min_soc=20.0,
        max_soc=80.0,
        initial_soc=50.0,
    )

    # Execute the battery simulation
    batt.execute(0)

    # Diagnostics
    log_first_day(batt, day_index=0)
    plot_soc_one_day(batt, day_index=0)


if __name__ == "__main__":
    main()
