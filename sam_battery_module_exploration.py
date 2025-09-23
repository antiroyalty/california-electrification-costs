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

    def _set(key: str, val, required: bool = False):
        try:
            batt.value(key, val)
            return True
        except Exception as e:
            msg = f"Failed to set {key}: {e}"
            if required:
                raise RuntimeError(msg)
            print(f"DEBUG: {msg}")
            return False

    # Chemistry and initial SOC (use direct value() to avoid getters raising)
    _set("batt_chem", 1, required=False)  # 1 = Li-ion (if supported)
    _set("batt_initial_SOC", 50.0, required=False)

    # Core system efficiencies & topology
    _set("batt_meter_position", 0, required=False)  # 0=behind-the-meter
    _set("batt_ac_or_dc", 1, required=False)  # 1=AC-coupled (if supported)
    _set("batt_dc_dc_efficiency", 0.96, required=False)
    _set("batt_ac_dc_efficiency", 0.96, required=False)
    _set("batt_dc_ac_efficiency", 0.96, required=False)
    _set("batt_minimum_SOC", 20.0, required=False)
    _set("batt_maximum_SOC", 80.0, required=False)
    # Set explicit power limits (kW) on both DC and AC sides if supported
    _set("batt_power_charge_max_kwdc", 5.0, required=False)
    _set("batt_power_discharge_max_kwdc", 5.0, required=False)
    _set("batt_power_charge_max_kwac", 5.0, required=False)
    _set("batt_power_discharge_max_kwac", 5.0, required=False)
    # Enable battery if needed and provide computed bank placeholders expected by some builds
    _set("en_batt", 1, required=False)
    _set("batt_computed_series", 13, required=False)
    _set("batt_computed_strings", 107, required=False)
    _set("batt_computed_bank_capacity", 12.5, required=False)  # kWh approx
    # Simple battery sizing (if supported by this build)
    _set("batt_simple_enable", 1, required=False)
    _set("batt_simple_kwh", 13.5, required=False)
    _set("batt_simple_kw", 5.0, required=False)
    _set("batt_simple_chemistry", 1, required=False)  # 1 = Li-ion

    # Manual dispatch preferences
    _set("batt_dispatch_choice", 3, required=False)  # manual dispatch
    _set("batt_dispatch_auto_can_gridcharge", 0, required=False)
    _set("batt_dispatch_auto_can_charge", 1, required=False)
    _set("batt_dispatch_auto_btm_can_discharge_to_grid", 0, required=False)
    _set("dispatch_manual_system_charge_first", 1, required=False)
    # Manual-dispatch export policy across TOU periods (6 periods typical)
    _set("dispatch_manual_btm_discharge_to_grid", [0, 0, 0, 0, 0, 0], required=False)
    # Battery life model: avoid requiring batt_lifetime_matrix
    _set("batt_life_model", 1, required=False)

    # Lifetime (keep simple one-year)
    _set("analysis_period", 1, required=False)
    _set("system_use_lifetime_output", 0, required=False)

    return batt


def configure_standalone_mode(batt: BatteryMod.Battery, pv_ac: List[float], load_ac: List[float]) -> None:
    """
    Configure Battery module for stand‑alone operation with explicit forecasts
    and a 60‑minute timestep. Fails fast if the build does not support the
    required inputs.
    """
    def _set(name: str, val, required: bool = False):
        try:
            batt.value(name, val)
            return True
        except Exception as e:
            msg = f"Failed to set {name}: {e}"
            if required:
                raise RuntimeError(msg)
            print(f"DEBUG: {msg}")
            return False

    # Forecasts (required)
    _set("batt_pv_ac_forecast", pv_ac, required=True)
    _set("batt_load_ac_forecast", load_ac, required=True)

    # Timestep (required; try a few common keys)
    ok_ts = (
        _set("timestep_minutes", 60, required=False)
        or _set("timestep", 60, required=False)
        or _set("dt_hour", 1.0, required=False)
    )
    if not ok_ts:
        raise RuntimeError("Failed to set simulation timestep (tried timestep_minutes, timestep, dt_hour)")

    # Enable standalone battery mode (optional; some builds may not require)
    _set("en_standalone_batt", 1, required=False)


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

    # Safe setter via value(); fail fast on critical settings
    def _set(name: str, val, required: bool = False):
        try:
            batt.value(name, val)
            return True
        except Exception as e:
            msg = f"Failed to set {name}: {e}"
            if required:
                raise RuntimeError(msg)
            print(f"DEBUG: {msg}")
            return False

    # BatteryCell / BatterySystem SOC bounds
    _set("batt_initial_SOC", float(initial_soc), required=False)
    _set("batt_minimum_SOC", float(min_soc), required=False)
    _set("batt_maximum_SOC", float(max_soc), required=False)

    # BatteryDispatch settings (manual, PV‑first, no grid charge)
    # Manual dispatch mode and preferences
    _set("batt_dispatch_choice", 3, required=False)  # 3 = manual, 2 = custom
    _set("batt_dispatch_auto_can_gridcharge", 0, required=False)
    _set("batt_dispatch_auto_can_charge", 1, required=False)
    _set("batt_dispatch_auto_btm_can_discharge_to_grid", 0, required=False)
    _set("dispatch_manual_system_charge_first", 1, required=False)

    # Manual arrays (kW); if not supported, try percent arrays
    power_charge_ok = _set("dispatch_manual_charge", charge_kw.tolist(), required=False)
    power_discharge_ok = _set("dispatch_manual_discharge", discharge_kw.tolist(), required=False)
    _set("dispatch_manual_gridcharge", gridcharge_kw.tolist(), required=False)

    # Always define period mapping and percent arrays to satisfy prechecks.
    # Define schedule: period 1 for 16-20 hours, otherwise period 0 (weekday/weekend identical)
    day_sched = [0] * 24
    for h in range(16, 21):
        day_sched[h] = 1
    sched_mat = [list(day_sched) for _ in range(12)]  # 12x24 matrix

    pct_discharge_periods = [0, 100, 0, 0, 0, 0]
    pct_gridcharge_periods = [0, 0, 0, 0, 0, 0]
    pct_export_periods = [0, 0, 0, 0, 0, 0]

    # Prefer group assign to avoid getter side-effects
    try:
        batt.BatteryDispatch.assign({
            "dispatch_manual_sched": sched_mat,
            "dispatch_manual_sched_weekend": sched_mat,
            "dispatch_manual_percent_discharge": pct_discharge_periods,
            "dispatch_manual_percent_gridcharge": pct_gridcharge_periods,
            "dispatch_manual_btm_discharge_to_grid": pct_export_periods,
        })
    except Exception as e:
        raise RuntimeError(f"Failed to assign manual dispatch schedules/percents: {e}")


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

def main():
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

    # Configure stand‑alone mode (forecasts + timestep + standalone flag)
    try:
        configure_standalone_mode(batt, solar_profile, load_profile)
        print("DEBUG: Configured Battery stand‑alone mode (forecasts + timestep)")
    except RuntimeError as e:
        print(f"DEBUG: Stand‑alone configuration issue: {e}")
        # Continue without standalone mode; manual dispatch may still run depending on build

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

    # Debug: confirm key manual inputs are assigned before execution
    exp = batt.export()
    bd = exp.get("BatteryDispatch", {}) if isinstance(exp, dict) else {}
    dbg_keys = [
        "batt_dispatch_choice",
        "dispatch_manual_sched",
        "dispatch_manual_sched_weekend",
        "dispatch_manual_percent_discharge",
        "dispatch_manual_percent_gridcharge",
        "dispatch_manual_btm_discharge_to_grid",
    ]
    print("DEBUG: Manual dispatch config snapshot (before execute):")
    for k in dbg_keys:
        v = bd.get(k, None)
        if isinstance(v, (list, tuple)) and len(v) > 24:
            print(f"  {k}: len={len(v)} head={v[:5]} ... tail={v[-5:]}")
        else:
            print(f"  {k}: {v}")

    # Validate required manual dispatch inputs before execution (fail fast)
    precheck_errors = []
    # batt_dispatch_choice should be manual (3) or custom (2)
    if bd.get("batt_dispatch_choice", None) not in (2, 3):
        precheck_errors.append("batt_dispatch_choice must be 2 (custom) or 3 (manual)")

    # Period-based arrays must exist with acceptable shapes
    def _is_24_vector(x):
        return isinstance(x, (list, tuple)) and len(x) == 24
    def _is_12x24_matrix(x):
        return (
            isinstance(x, (list, tuple)) and len(x) == 12 and
            all(isinstance(r, (list, tuple)) and len(r) == 24 for r in x)
        )

    sched = bd.get("dispatch_manual_sched", None)
    if not (_is_24_vector(sched) or _is_12x24_matrix(sched)):
        precheck_errors.append("dispatch_manual_sched must be a 24-vector or 12x24 matrix")

    sched_wknd = bd.get("dispatch_manual_sched_weekend", None)
    if not (_is_24_vector(sched_wknd) or _is_12x24_matrix(sched_wknd)):
        precheck_errors.append("dispatch_manual_sched_weekend must be a 24-vector or 12x24 matrix")

    pct_dis = bd.get("dispatch_manual_percent_discharge", None)
    if not (isinstance(pct_dis, (list, tuple)) and len(pct_dis) == 6):
        precheck_errors.append("dispatch_manual_percent_discharge must be a 6-element list")

    pct_grid = bd.get("dispatch_manual_percent_gridcharge", None)
    if pct_grid is not None and not (isinstance(pct_grid, (list, tuple)) and len(pct_grid) == 6):
        precheck_errors.append("dispatch_manual_percent_gridcharge must be a 6-element list if provided")

    pct_export = bd.get("dispatch_manual_btm_discharge_to_grid", None)
    if pct_export is not None and not (isinstance(pct_export, (list, tuple)) and len(pct_export) == 6):
        precheck_errors.append("dispatch_manual_btm_discharge_to_grid must be a 6-element list if provided")

    if precheck_errors:
        print("ERROR: Manual dispatch configuration is incomplete:")
        for e in precheck_errors:
            print(f"  - {e}")
        print("Aborting before execute().")
        return

    # Execute the battery simulation
    batt.execute(0)

    # Diagnostics
    log_first_day(batt, day_index=0)
    plot_soc_one_day(batt, day_index=0)


if __name__ == "__main__":
    main()
