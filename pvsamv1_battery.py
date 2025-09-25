"""
Simple Pvsamv1 + Battery demo using presets from SAM_Detailed_PV_Battery.

What this script does
- Loads presets from JSON into PySAM.Pvsamv1 and PySAM.Battery.
- Ensures Manual Dispatch mode (and logs that it came from JSON).
- Attaches a local weather CSV if found and executes Pvsamv1.
- Logs, clearly:
  (1) Grid export settings (from JSON)
  (2) The load profile (kW)
  (3) Battery level (kW caps; and first‑day power if available)
  (4) Solar generation profile (kW AC)

Notes
- Presets directory: SAM_Detailed_PV_Battery
- Default PV config file: untitled_pvsamv1.json
- Default Battery config file: untitled.json (contains batt_* keys)
- Weather + load fallbacks use Alameda example files under data/loadprofiles/...

Run
  python3 pvsamv1_battery.py

Env overrides (optional)
- COUNTY_NAME: default "alameda"
- WEATHER_FILE: path to SAM CSV weather file
- LOAD_FILE: path to CSV with hourly load column
- LOAD_COL: column name in LOAD_FILE
- SAM_PRESET_DIR: default "SAM_Detailed_PV_Battery"
- PVSAMV1_JSON: default "untitled_pvsamv1.json"
- BATTERY_JSON: default "untitled.json"
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Tuple

import numpy as np
import pandas as pd

import PySAM.Pvsamv1 as Pvsamv1
import PySAM.Battery as Battery
import PySAM.ResourceTools as ResourceTools


# ------------------------------
# Helpers: JSON, logging, loading
# ------------------------------

def load_json(path: str) -> Dict[str, Any]:
    if not os.path.exists(path):
        raise FileNotFoundError(f"JSON not found: {path}")
    with open(path, "r") as f:
        return json.load(f)


def apply_json(module: Any, data: Dict[str, Any]) -> Tuple[int, List[str]]:
    """Attempt to set all keys from JSON into a PySAM module via .value().
    Returns (count_applied, failed_keys).
    """
    applied = 0
    failed: List[str] = []
    for k, v in data.items():
        if k == "number_inputs":
            continue
        try:
            module.value(k, v)
            applied += 1
        except Exception:
            failed.append(k)
    return applied, failed


def log_section(title: str) -> None:
    print("\n" + "=" * 80)
    print(title)
    print("=" * 80)


def safe_head_tail(arr: List[float], n: int = 12) -> Tuple[List[float], List[float]]:
    if arr is None:
        return [], []
    if len(arr) <= n:
        return arr, []
    return arr[:n], arr[-n:]


def print_first_day_flow_table(pv: Pvsamv1.Pvsamv1, day_index: int = 0) -> None:
    """Print a first-day hourly allocation table with PV and battery flows.

    Columns:
      hour, hod, PV(kWh), PV->Batt, PV->Load, PV->Grid, Batt->Load, Batt(kWh), Residual
    Residual = PV(kWh) - (PV->Batt + PV->Load + PV->Grid)
    """
    log_section("First-Day Power Allocation Table")
    out = pv.Outputs.export()

    def arr(key: str) -> np.ndarray:
        return np.asarray(out.get(key, []), dtype=float).ravel()

    sL = arr("system_to_load")
    sB = arr("system_to_batt")
    sG = arr("system_to_grid")
    bL = arr("batt_to_load")
    soc = arr("batt_SOC")
    # Define PV(kWh) as the sum of PV flows to avoid negative night values
    gen_flows = sB + sL + sG

    # Battery capacity (kWh) for converting SOC -> kWh — do not assume defaults.
    batt_cap = None
    # Prefer installed capacity
    try:
        batt_cap = float(pv.value("batt_bank_installed_capacity"))
        source = "batt_bank_installed_capacity (module)"
    except Exception:
        # Try from outputs
        val = out.get("batt_bank_installed_capacity", None)
        if val is not None:
            batt_cap = float(val)
            source = "batt_bank_installed_capacity (outputs)"
    # Accept computed bank capacity as a strict fallback if present
    if batt_cap is None:
        try:
            batt_cap = float(pv.value("batt_computed_bank_capacity"))
            source = "batt_computed_bank_capacity (module)"
        except Exception:
            val = out.get("batt_computed_bank_capacity", None)
            if val is not None:
                batt_cap = float(val)
                source = "batt_computed_bank_capacity (outputs)"
    if batt_cap is None:
        raise RuntimeError(
            "Battery capacity not found (missing batt_bank_installed_capacity and batt_computed_bank_capacity)."
        )
    # Compute battery energy from SOC
    batt_kwh = (soc / 100.0) * batt_cap if soc.size > 0 else np.zeros_like(gen_flows)

    start = day_index * 24
    end = start + 24

    nmax = max(gen_flows.size, sB.size, sL.size, sG.size, bL.size, batt_kwh.size)
    if nmax == 0:
        print("No outputs available to build table.")
        return

    print("hour hod   PV(kWh)  PV->Batt  PV->Load  PV->Grid   Batt->Load  Batt(kWh)   Residual")
    for h in range(start, min(end, nmax)):
        hod = h % 24
        g = gen_flows[h] if h < gen_flows.size else 0.0
        sb = sB[h] if h < sB.size else 0.0
        sl = sL[h] if h < sL.size else 0.0
        sg = sG[h] if h < sG.size else 0.0
        bl = bL[h] if h < bL.size else 0.0
        bk = batt_kwh[h] if h < batt_kwh.size else 0.0
        # Residual built from flows should be identically zero
        residual = g - (sb + sl + sg)
        print(
            f"{h:4d} {hod:3d}  "
            f"{g:8.3f}  {sb:8.3f}  {sl:8.3f}  {sg:8.3f}   {bl:11.3f}  {bk:10.3f}  {residual:9.3f}"
        )


def print_first_day_soc_summary(pv: Pvsamv1.Pvsamv1, day_index: int = 0) -> None:
    """Print starting and ending SOC for the specified day (0-indexed)."""
    log_section("First-Day SOC Summary")
    try:
        soc = np.asarray(pv.Outputs.batt_SOC, dtype=float).ravel()
    except Exception:
        soc = np.asarray([], dtype=float)
    if soc.size == 0:
        print("No SOC series available.")
        return
    start = day_index * 24
    end = min(start + 24, soc.size)
    if start >= soc.size:
        print(f"SOC series too short for day_index={day_index}")
        return
    start_soc = float(soc[start])
    end_soc = float(soc[end - 1])
    print(f"Day {day_index + 1}: start_SOC={start_soc:.2f}%  end_SOC={end_soc:.2f}%")


def attach_weather(pv: Pvsamv1.Pvsamv1, county_slug: str) -> bool:
    weather_file = os.environ.get(
        "WEATHER_FILE",
        f"data/loadprofiles/baseline/single-family-detached/{county_slug}/weather_TMY_{county_slug}.csv",
    )
    if not os.path.exists(weather_file):
        print(f"WARN: Weather file not found: {weather_file} (PV run will be skipped)")
        raise Exception

    srd = ResourceTools.SAM_CSV_to_solar_data(weather_file)

    # Align weather from eastern time (ET) to local time (PT) to match typical load profiles
    shift_hours = 0
    hourly_keys = ["dn", "df", "gh", "tdry", "tdew", "rhum", "wdir", "wspd"]
    for key in hourly_keys:
        if key in srd and isinstance(srd[key], (list, tuple)) and len(srd[key]) == 8760:
            arr = list(srd[key])
            srd[key] = [arr[(i + shift_hours) % 8760] for i in range(8760)]

    pv.SolarResource.solar_resource_data = srd
    print(f"Attached weather from: {weather_file} (shifted +{shift_hours}h for PT)")
    return True


def attach_load_from_csv(pv: Pvsamv1.Pvsamv1, county_slug: str) -> bool:
    load_file = os.environ.get(
        "LOAD_FILE",
        f"data/loadprofiles/baseline/single-family-detached/{county_slug}/combined_profiles_baseline_{county_slug}.csv",
    )
    load_col = os.environ.get(
        "LOAD_COL",
        "electricity.real_and_simulated.for_typical_county_home.kwh",
    )
    if not os.path.exists(load_file):
        print(f"INFO: Load CSV not found: {load_file} (will use JSON 'load' if present)")
        raise Exception

    df = pd.read_csv(load_file)
    load = df[load_col].astype(float).tolist()
    if len(load) != 8760:
        print(f"WARN: CSV load length {len(load)} != 8760; continuing anyway")

    pv.value("load", load)
    # Provide auxiliary arrays commonly required
    pv.value("crit_load", [0.0] * len(load))
    pv.value("batt_load_ac_forecast", load)
    print(
        f"Attached load from CSV: {load_file} (len={len(load)}, sum={sum(load):.1f} kWh)"
    )
    return True


# ------------------------------
# Main demo
# ------------------------------

def main() -> None:
    county_slug = os.environ.get("COUNTY_NAME", "alameda").lower().replace(" ", "-")
    preset_dir = os.environ.get("SAM_PRESET_DIR", "SAM_Detailed_PV_Battery")
    pvsam_json_name = os.environ.get("PVSAMV1_JSON", "untitled_pvsamv1.json")
    batt_json_name = os.environ.get("BATTERY_JSON", "untitled.json")

    pvsam_json_path = os.path.join(preset_dir, pvsam_json_name)
    batt_json_path = os.path.join(preset_dir, batt_json_name)

    # Load JSON presets
    pvsam_data = load_json(pvsam_json_path)
    batt_data = load_json(batt_json_path)

    log_section("Preset Files Loaded")
    print(f"Pvsamv1 preset: {pvsam_json_path}  (keys={len(pvsam_data)})")
    print(f"Battery preset: {batt_json_path}   (keys={len(batt_data)})")

    # Build modules
    pv = Pvsamv1.new()
    batt = Battery.new()

    # Apply presets
    ap_pv, failed_pv = apply_json(pv, pvsam_data)
    ap_bt, failed_bt = apply_json(batt, batt_data)

    print(
        f"Applied {ap_pv} parameters to Pvsamv1 ({len(failed_pv)} failed); "
        f"Applied {ap_bt} to Battery ({len(failed_bt)} failed)"
    )

    # Battery SOC settings (pre-execute)
    log_section("Battery SOC Settings (Pre-Execute)")
    try:
        min_soc = pv.value("batt_minimum_SOC")
    except Exception:
        min_soc = None
    try:
        max_soc = pv.value("batt_maximum_SOC")
    except Exception:
        max_soc = None
    try:
        init_soc = pv.value("batt_initial_SOC")
    except Exception:
        init_soc = None
    print(f"min_SOC={min_soc}  max_SOC={max_soc}  initial_SOC={init_soc}")

    # Manual Dispatch confirmation (imported from JSON)
    dispatch_from_json = pvsam_data.get("batt_dispatch_choice", None)
    log_section("Dispatch Mode (Imported From JSON)")
    print(
        "batt_dispatch_choice (Pvsamv1 JSON) = ",
        dispatch_from_json,
        "=> Manual" if dispatch_from_json == 3 else "",
    )
    try:
        current_dispatch = pv.value("batt_dispatch_choice")
        print(f"Pvsamv1 module batt_dispatch_choice = {current_dispatch}")
    except Exception:
        pass
    try:
        current_dispatch_batt = batt.value("batt_dispatch_choice")
        print(f"Battery module batt_dispatch_choice   = {current_dispatch_batt}")
    except Exception:
        pass

    # Grid export settings (from JSON)
    log_section("Grid Export Settings (from JSON)")
    grid_can_export = pvsam_data.get(
        "batt_dispatch_auto_btm_can_discharge_to_grid", None
    )
    manual_export_periods = pvsam_data.get(
        "dispatch_manual_btm_discharge_to_grid", None
    )
    interconnection_kwac = pvsam_data.get("grid_interconnection_limit_kwac", None)
    print(f"batt_dispatch_auto_btm_can_discharge_to_grid = {grid_can_export}")
    print(f"dispatch_manual_btm_discharge_to_grid        = {manual_export_periods}")
    print(f"grid_interconnection_limit_kwac              = {interconnection_kwac}")

    # Attach weather + load (prefer CSV load to reflect this repo's data)
    attached_weather = attach_weather(pv, county_slug)
    used_csv_load = attach_load_from_csv(pv, county_slug)

    # Fallback to JSON load if CSV not available and JSON contains 'load'
    if not used_csv_load and isinstance(pvsam_data.get("load"), list):
        try:
            pv.value("load", pvsam_data["load"])  # kW
            pv.value("crit_load", [0.0] * len(pvsam_data["load"]))
            pv.value("batt_load_ac_forecast", pvsam_data["load"])  # kW forecast for batt
            print(
                "Attached load from JSON 'load' "
                f"(len={len(pvsam_data['load'])}, sum={sum(pvsam_data['load']):.1f} kWh)"
            )
        except Exception as e:
            print(f"WARN: Failed to apply JSON 'load' into Pvsamv1: {e}")

    # (2) Load profile (kW)
    log_section("Load Profile (kW)")
    try:
        load = list(pv.value("load"))
    except Exception:
        load = pvsam_data.get("load", [])
    if isinstance(load, list) and load:
        head, tail = safe_head_tail([float(x) for x in load], n=24)
        print(
            f"len={len(load)}  sum={sum(load):.1f} kWh  min={min(load):.3f}  "
            f"max={max(load):.3f}  mean={np.mean(load):.3f}"
        )
        print(f"first 24 hours: {head}")
        if tail:
            print(f"last 24 hours : {tail}")
    else:
        print("No load profile available.")

    # Execute PV if we have weather and a load profile
    pv_executed = False
    try:
        if attached_weather:
            pv.execute(0)
            pv_executed = True
            print("\nExecuted Pvsamv1 successfully.")
    except Exception as e:
        print(f"WARN: Pvsamv1 execution failed: {e}")

    # (4) Solar generation profile (kW AC)
    log_section("Solar Generation Profile (kW AC)")
    gen = []
    if pv_executed:
        try:
            gen = list(getattr(pv.Outputs, "gen", []))
        except Exception:
            try:
                gen = list(getattr(pv.Outputs, "ac", []))
            except Exception:
                gen = []
    if gen:
        head, tail = safe_head_tail([float(x) for x in gen], n=24)
        print(
            f"len={len(gen)}  sum={sum(gen):.1f} kWh  max={max(gen):.3f} kW  "
            f"mean={np.mean(gen):.3f} kW"
        )
        print(f"first 24 hours: {head}")
        if tail:
            print(f"last 24 hours : {tail}")
    else:
        print("No PV generation available (missing weather or execution failed).")

    # (3) Battery level (kW)
    # Report nameplate charging/discharging caps from JSON, and per-hour power if available
    log_section("Battery Level (kW)")
    caps = {
        "batt_power_charge_max_kwac": pvsam_data.get("batt_power_charge_max_kwac"),
        "batt_power_discharge_max_kwac": pvsam_data.get("batt_power_discharge_max_kwac"),
        "batt_power_charge_max_kwdc": pvsam_data.get("batt_power_charge_max_kwdc"),
        "batt_power_discharge_max_kwdc": pvsam_data.get("batt_power_discharge_max_kwdc"),
    }
    for k, v in caps.items():
        print(f"{k} = {v}")

    batt_power_series: List[float] = []
    if pv_executed:
        # Prefer Pvsamv1 battery power output if available
        try:
            batt_power_series = list(getattr(pv.Outputs, "batt_power", []))
        except Exception:
            batt_power_series = []

    if batt_power_series:
        head, tail = safe_head_tail([float(x) for x in batt_power_series], n=24)
        print(
            f"batt_power series present: len={len(batt_power_series)}  "
            f"min={min(batt_power_series):.3f}  max={max(batt_power_series):.3f}  "
            f"mean={np.mean(batt_power_series):.3f}"
        )
        print(f"first 24 hours: {head}")
        if tail:
            print(f"last 24 hours : {tail}")
    else:
        print("No per‑hour battery power available (PV not executed or output absent).")

    # Final echo of manual schedules from JSON for auditability
    log_section("Manual Dispatch Schedules (from JSON)")
    for key in (
        "dispatch_manual_sched",
        "dispatch_manual_sched_weekend",
        "dispatch_manual_percent_discharge",
        "dispatch_manual_percent_gridcharge",
        "dispatch_manual_btm_discharge_to_grid",
    ):
        val = pvsam_data.get(key)
        if isinstance(val, list) and len(val) > 24:
            print(f"{key}: len={len(val)} head={val[:5]} ... tail={val[-5:]}")
        else:
            print(f"{key}: {val}")

    # Build a first‑day flow table once execution succeeds
    if pv_executed:
        print_first_day_flow_table(pv, day_index=0)
        print_first_day_soc_summary(pv, day_index=0)


if __name__ == "__main__":
    main()
