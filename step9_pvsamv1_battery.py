"""
Simple Pvsamv1 demo using presets from SAM_Detailed_PV_Battery.

What this script does
- Loads presets from JSON into PySAM.Pvsamv1.
- Ensures Manual Dispatch mode (and logs that it came from JSON).
- Requires and attaches a local weather CSV and the research load CSV, then executes.
- Logs, clearly:
  (1) Grid export settings (from JSON)
  (2) The load profile (kW)
  (3) Battery power caps and first‑day summaries
  (4) Solar generation profile (kW AC)

Notes
- Presets directory: SAM_Detailed_PV_Battery
- Default PV config file: untitled_pvsamv1.json
- Weather and the research load CSV are required; no JSON load fallback is used.

Run
  python3 pvsamv1_battery.py

Env overrides (optional)
- COUNTY_NAME: default "alameda"
- WEATHER_FILE: path to SAM CSV weather file
- LOAD_FILE: path to CSV with hourly load column
- LOAD_COL: column name in LOAD_FILE
- SAM_PRESET_DIR: default "SAM_Detailed_PV_Battery"
- PVSAMV1_JSON: default "untitled_pvsamv1.json"
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import traceback

import PySAM.Pvsamv1 as Pvsamv1
import PySAM.ResourceTools as ResourceTools
from step9_plotting_helper import plot_first_weeks

# Use project slug rules for county folder names
try:
    from main_helpers import slugify_county_name
except Exception:
    def slugify_county_name(name: str) -> str:
        return name.lower().replace("county", "").strip().replace(" ", "-")

MIN_SOC = 25
MAX_SOC = 90
INITIAL_SOC = 50
DISPATCH_MODE = 3 # Manual dispatch https://nrel-pysam.readthedocs.io/en/v7.1.0/modules/Pvsamv1.html#PySAM.Pvsamv1.Pvsamv1.BatteryDispatch.batt_dispatch_choice
GRID_INTERCONNECTION_LIMIT_KWAC = 0
CAN_EXPORT_TO_GRID = 0
ENABLE_PREDICTIVE_DISPATCH = True
BATTERY_EFFICIENCY = 5
PEAK_START_HOUR = 16
PEAK_END_HOUR = 21
BATTERY_CAPACITY_KWH = 13.5

# PV sizing/model alignment constants (match DIY step assumptions)
PV_SIZING_CELL_EFF = 0.206            # STC cell efficiency (fraction)
PV_SIZING_PR = 0.80                    # Performance ratio for sizing
PV_SIZING_POWER_DENSITY = 0.193        # kW/m² at STC
# DIY PV model constants for gross AC reconstruction from weather
NOCT_C = 45.0
G_NOCT = 800.0
G_REF = 1000.0
GAMMA_PDC = -0.00337

# Solar charging control defaults (exact SAM parameter values)
DISPATCH_MANUAL_SYSTEM_CHARGE_FIRST = 1         # dispatch_manual_system_charge_first
BATT_DISPATCH_AUTO_CAN_CHARGE = 1              # batt_dispatch_auto_can_charge
BATT_DISPATCH_CHARGE_ONLY_SYSTEM_EXCEEDS_LOAD = 0            # batt_dispatch_charge_only_system_exceeds_load
BATT_DISPATCH_DISCHARGE_ONLY_LOAD_EXCEEDS_SYSTEM = 0                 # batt_dispatch_discharge_only_load_exceeds_system
BATT_DISPATCH_AUTO_CAN_GRIDCHARGE = 1            # batt_dispatch_auto_can_gridcharge

# Efficiency defaults
BATT_DC_DC_EFFICIENCY = 96.0             # batt_dc_dc_efficiency

# Time window defaults (hours 0-23)
SOLAR_CHARGING_START_HOUR = 6       # Start of solar charging window
SOLAR_CHARGING_END_HOUR = 15        # End of solar charging window  
PEAK_DISCHARGE_START_HOUR = 16      # Start of peak discharge window
PEAK_DISCHARGE_END_HOUR = 21        # End of peak discharge window

@dataclass
class SimulationConfiguration:
    county_slug: str
    sam_preset_dir: str
    pvsamv1_json_name: str
    weather_file: str
    load_file: str
    load_col: str
    show_plots: bool = True
    weather_shift_hours: int = 8


@dataclass
class SamPresetFiles:
    photovoltaic_preset_values: Dict[str, Any]
    battery_preset_values: Optional[Dict[str, Any]] = None


@dataclass
class SamModules:
    photovoltaic_model: Pvsamv1.Pvsamv1
    battery_model: Optional[Any] = None


@dataclass
class SimulationSeries:
    load_series_kw: List[float]
    state_of_charge_series_percent: List[float]
    solar_ac_power_series_kw: List[float]
    solar_to_load_series_kw: List[float]
    battery_to_load_series_kw: List[float]
    grid_to_load_series_kw: List[float]


@dataclass
class ApplyReport:
    pv_applied_count: int
    pv_failed_keys: List[str]
    batt_applied_count: int
    batt_failed_keys: List[str]
    warnings: List[str]


@dataclass
class SocBounds:
    min_soc: Optional[float]
    max_soc: Optional[float]
    initial_soc: Optional[float]


@dataclass
class RuntimeOverrides:
    min_soc: Optional[float] = None
    max_soc: Optional[float] = None
    initial_soc: Optional[float] = None
    dispatch_mode: Optional[int] = None
    grid_interconnection_limit_kwac: Optional[float] = None
    can_export_to_grid: Optional[bool] = None
    # Predictive dispatch parameters
    enable_predictive_dispatch: Optional[bool] = None
    battery_efficiency: Optional[float] = None
    peak_start_hour: Optional[int] = None
    peak_end_hour: Optional[int] = None
    battery_capacity_kwh: Optional[float] = None
    
    # Solar charging control flags (exact SAM parameter values: 0 or 1)
    dispatch_manual_system_charge_first: Optional[int] = None               # dispatch_manual_system_charge_first
    batt_dispatch_auto_can_charge: Optional[int] = None                    # batt_dispatch_auto_can_charge
    batt_dispatch_charge_only_system_exceeds_load: Optional[int] = None                  # batt_dispatch_charge_only_system_exceeds_load
    batt_dispatch_discharge_only_load_exceeds_system: Optional[int] = None                       # batt_dispatch_discharge_only_load_exceeds_system
    batt_dispatch_auto_can_gridcharge: Optional[int] = None                  # batt_dispatch_auto_can_gridcharge
    
    # Efficiency parameters (hardware characteristics)
    batt_dc_dc_efficiency: Optional[float] = None                    # batt_dc_dc_efficiency
    
    # Time window configuration (static schedule parameters)
    solar_charging_start_hour: Optional[int] = None             # Start of solar charging window
    solar_charging_end_hour: Optional[int] = None               # End of solar charging window
    peak_discharge_start_hour: Optional[int] = None             # Start of peak discharge window
    peak_discharge_end_hour: Optional[int] = None               # End of peak discharge window


# ------------------------------
# Helpers: JSON, logging, loading
# ------------------------------

def calculate_peak_energy_requirements(load_forecast: List[float], day_index: int, battery_efficiency: float = 0.90) -> Dict[str, float]:
    """
    Calculate energy needed for 4-9pm peak period including efficiency losses.
    
    Args:
        load_forecast: 8760-hour load profile (kW)
        day_index: Day of year (0-364)
        battery_efficiency: Round-trip efficiency (default 0.90)
        
    Returns:
        Dictionary with peak_load_kwh, energy_to_store_kwh, efficiency_loss_kwh
    """
    # Peak period hours (4-9pm = hours 16-20)
    peak_start = 16
    peak_end = 21
    
    # Get load forecast for peak period
    peak_load_kwh = 0.0
    day_start_hour = day_index * 24
    
    for hour in range(peak_start, peak_end):
        hour_index = day_start_hour + hour
        if hour_index < len(load_forecast):
            peak_load_kwh += load_forecast[hour_index]
    
    # Account for round-trip efficiency losses
    # Energy needed to store = peak_load / efficiency
    energy_to_store_kwh = peak_load_kwh / battery_efficiency
    efficiency_loss_kwh = energy_to_store_kwh - peak_load_kwh
    
    return {
        'peak_load_kwh': peak_load_kwh,
        'energy_to_store_kwh': energy_to_store_kwh,
        'efficiency_loss_kwh': efficiency_loss_kwh
    }


def calculate_precharge_target_soc(peak_energy_req: Dict[str, float], battery_capacity_kwh: float = 13.5, min_soc: float = 20.0, max_soc: float = 90.0) -> Dict[str, float]:
    """
    Calculate target SOC needed by 4pm to serve peak load.
    
    Args:
        peak_energy_req: Result from calculate_peak_energy_requirements
        battery_capacity_kwh: Battery capacity (default 13.5 kWh for Tesla Powerwall)
        min_soc: Minimum SOC percentage (default 20.0)
        max_soc: Maximum SOC percentage (default 90.0)
        
    Returns:
        Dictionary with target_soc, target_energy_kwh, precharge_energy_kwh
    """
    # Energy available at minimum SOC
    min_energy_kwh = (min_soc / 100.0) * battery_capacity_kwh
    
    # Total energy needed = minimum energy + peak energy requirement
    target_energy_kwh = min_energy_kwh + peak_energy_req['energy_to_store_kwh']
    
    # Convert to SOC percentage, clamped to maximum
    target_soc = min(max_soc, (target_energy_kwh / battery_capacity_kwh) * 100.0)
    
    return {
        'target_soc': target_soc,
        'target_energy_kwh': target_energy_kwh,
        'precharge_energy_kwh': peak_energy_req['energy_to_store_kwh']
    }


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
      hour, hod, Load(kWh), PV(kWh), PV->Batt, PV->Load, PV->Grid, Batt->Load, Batt(kWh), Residual
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
    # Get total load profile from the model
    load_profile = _load_series(pv)
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

    nmax = max(gen_flows.size, sB.size, sL.size, sG.size, bL.size, batt_kwh.size, load_profile.size)
    if nmax == 0:
        print("No outputs available to build table.")
        return

    print("hour hod  Load(kWh)   PV(kWh)  PV->Batt  PV->Load  PV->Grid   Batt->Load  Batt(kWh)   Residual")
    for h in range(start, min(end, nmax)):
        hod = h % 24
        load = load_profile[h] if h < load_profile.size else 0.0
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
            f"{load:9.3f}  {g:8.3f}  {sb:8.3f}  {sl:8.3f}  {sg:8.3f}   {bl:11.3f}  {bk:10.3f}  {residual:9.3f}"
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


def _pv_ac_from_flows(pv: Pvsamv1.Pvsamv1) -> np.ndarray:
    out = pv.Outputs.export()
    def arr(k: str) -> np.ndarray:
        return np.asarray(out.get(k, []), dtype=float).ravel()
    return arr("system_to_batt") + arr("system_to_load") + arr("system_to_grid")


def _load_series(pv: Pvsamv1.Pvsamv1) -> np.ndarray:
    try:
        return np.asarray(pv.value("load"), dtype=float).ravel()
    except Exception:
        return np.array([], dtype=float)


def _soc_series(pv: Pvsamv1.Pvsamv1) -> np.ndarray:
    try:
        return np.asarray(pv.Outputs.batt_SOC, dtype=float).ravel()
    except Exception:
        return np.array([], dtype=float)

def _flow_series(pv: Pvsamv1.Pvsamv1) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    out = pv.Outputs.export()
    
    def arr(k: str) -> np.ndarray:
        raw_data = out.get(k, [])
        result = np.asarray(raw_data, dtype=float).ravel()
        # Verify expected hourly length
        if len(result) != 8760:
            print(f"Warning: {k} has {len(result)} elements (expected 8760)")
        return result
    
    system_to_load = arr("system_to_load")
    batt_to_load = arr("batt_to_load") 
    grid_to_load = arr("grid_to_load")
    
    return system_to_load, batt_to_load, grid_to_load

def _battery_charging_series(pv: Pvsamv1.Pvsamv1) -> Tuple[np.ndarray, np.ndarray]:
    out = pv.Outputs.export()
    
    def arr(k: str) -> np.ndarray:
        raw_data = out.get(k, [])
        result = np.asarray(raw_data, dtype=float).ravel()
        # Verify expected hourly length
        if len(result) != 8760:
            print(f"Warning: {k} has {len(result)} elements (expected 8760)")
        return result
    
    system_to_batt = arr("system_to_batt")
    grid_to_batt = arr("grid_to_batt")
    
    return system_to_batt, grid_to_batt


def _plot_eight_panel_weeks(
    load_ser: np.ndarray,
    soc_ser: np.ndarray,
    pv_ser: np.ndarray,
    pv_to_load: np.ndarray,
    batt_to_load: np.ndarray,
    grid_to_load: np.ndarray,
    pv_to_batt: np.ndarray,
    grid_to_batt: np.ndarray,
    min_soc_line: float | None,
    max_soc_line: float | None,
) -> None:
    """Create a single figure with 8 panels and highlight 4–9pm peak windows daily.
    Rows: Load, Battery SOC, Solar AC (PV), Battery Charging Sources. Col 1: First week of January. Col 2: First week of July.
    Adds light red shading for each day's 4–9pm (16–21) peak period across all panels.
    """
    week_len = 24 * 7
    first_week_start = 0
    july_start = 181 * 24  # Jan–Jun days = 181 (non-leap)
    peak_start_hour = 16
    peak_end_hour = 21

    def _slice(s: np.ndarray, start: int) -> tuple[np.ndarray, np.ndarray]:
        if s.size == 0:
            return np.array([]), np.array([])
        end = min(start + week_len, s.size)
        if start >= end:
            return np.array([]), np.array([])
        x = np.arange(end - start)
        y = s[start:end]
        return x, y

    fig, axes = plt.subplots(4, 2, figsize=(14, 12), sharex="col")

    # Top row: load breakdown by source (stacked area)
    for c, start, title in [
        (0, first_week_start, "Load Served by Source - First Week January"),
        (1, july_start, "Load Served by Source - First Week July"),
    ]:
        ax = axes[0, c]
        # Shade daily 4–9pm windows in the background
        for d in range(7):
            ax.axvspan(d * 24 + peak_start_hour, d * 24 + peak_end_hour, color="#d62728", alpha=0.10, zorder=0)
        xL, L = _slice(load_ser, start)
        xPV, PVL = _slice(pv_to_load, start)
        xBL, BL = _slice(batt_to_load, start)
        xGL, GL = _slice(grid_to_load, start)
        if L.size == 0 or PVL.size == 0 or BL.size == 0 or GL.size == 0:
            ax.text(0.5, 0.5, "No data", transform=ax.transAxes, ha="center", va="center")
            ax.set_title(title)
            ax.set_ylabel("kW")
            ax.grid(True, alpha=0.3)
            continue
        PVL = np.clip(PVL, 0.0, None)
        BL = np.clip(BL, 0.0, None)
        GL = np.clip(GL, 0.0, None)
        ax.stackplot(xL, PVL, BL, GL,
                     labels=["Solar→Load", "Battery→Load", "Grid→Load"],
                     colors=["#ff7f0e", "#2ca02c", "#7f7f7f"], alpha=0.8)
        ax.plot(xL, L, color="#000000", lw=1.2, label="Total Load")
        ax.set_title(title)
        ax.set_ylabel("kW")
        ax.grid(True, alpha=0.3)
        ax.legend(loc="upper right", fontsize=8, framealpha=0.8)

    # Middle row: SOC lines (with dashed min/max SOC) and peak shading
    for c, start, title in [
        (0, first_week_start, "Battery SOC - First Week January"),
        (1, july_start, "Battery SOC - First Week July"),
    ]:
        ax = axes[1, c]
        # Shade daily 4–9pm windows in the background
        for d in range(7):
            ax.axvspan(d * 24 + peak_start_hour, d * 24 + peak_end_hour, color="#d62728", alpha=0.10, zorder=0)
        x, y = _slice(soc_ser, start)
        if y.size == 0:
            ax.text(0.5, 0.5, "No data", transform=ax.transAxes, ha="center", va="center")
            ax.set_title(title)
            ax.set_ylabel("%")
            ax.grid(True, alpha=0.3)
            continue
        ax.plot(x, y, color="#1f77b4", lw=1.8)
        ax.set_title(title)
        ax.set_ylabel("%")
        ax.set_ylim(0, 100)
        ax.grid(True, alpha=0.3)
        # Add dashed min/max SOC lines if available
        if isinstance(min_soc_line, (int, float)):
            ax.axhline(float(min_soc_line), color="#d62728", ls="--", lw=1.2, alpha=0.9, label=f"Min SOC ({min_soc_line:g}%)")
        if isinstance(max_soc_line, (int, float)):
            ax.axhline(float(max_soc_line), color="#ff7f0e", ls="--", lw=1.2, alpha=0.9, label=f"Max SOC ({max_soc_line:g}%)")
        h, lab = ax.get_legend_handles_labels()
        if lab:
            ax.legend(loc="upper right", fontsize=8, framealpha=0.8)

    # Third row: PV AC lines with peak shading
    for c, start, title in [
        (0, first_week_start, "Solar AC (PV) - First Week January"),
        (1, july_start, "Solar AC (PV) - First Week July"),
    ]:
        ax = axes[2, c]
        # Shade daily 4–9pm windows in the background
        for d in range(7):
            ax.axvspan(d * 24 + peak_start_hour, d * 24 + peak_end_hour, color="#d62728", alpha=0.10, zorder=0)
        x, y = _slice(pv_ser, start)
        if y.size == 0:
            ax.text(0.5, 0.5, "No data", transform=ax.transAxes, ha="center", va="center")
            ax.set_title(title)
            ax.set_ylabel("kW")
            ax.grid(True, alpha=0.3)
            continue
        ax.plot(x, y, color="#ff7f0e", lw=1.8)
        ax.set_title(title)
        ax.set_ylabel("kW")
        ax.grid(True, alpha=0.3)

    # Bottom row: Battery charging sources (stacked area)
    for c, start, title in [
        (0, first_week_start, "Battery Charging Sources - First Week January"),
        (1, july_start, "Battery Charging Sources - First Week July"),
    ]:
        ax = axes[3, c]
        # Shade daily 4–9pm windows in the background
        for d in range(7):
            ax.axvspan(d * 24 + peak_start_hour, d * 24 + peak_end_hour, color="#d62728", alpha=0.10, zorder=0)
        xPVB, PVB = _slice(pv_to_batt, start)
        xGB, GB = _slice(grid_to_batt, start)
        if PVB.size == 0 or GB.size == 0:
            ax.text(0.5, 0.5, "No data", transform=ax.transAxes, ha="center", va="center")
            ax.set_title(title)
            ax.set_ylabel("kW")
            ax.grid(True, alpha=0.3)
            continue
        # Clip negative values to zero for stacked plot
        PVB = np.clip(PVB, 0.0, None)
        GB = np.clip(GB, 0.0, None)
        # Stack solar and grid charging
        ax.stackplot(xPVB, PVB, GB,
                     labels=["Solar→Battery", "Grid→Battery"],
                     colors=["#ff7f0e", "#1f77b4"], alpha=0.8)
        # Plot total charging as a line
        total_charging = PVB + GB
        ax.plot(xPVB, total_charging, color="#000000", lw=1.2, label="Total Charging")
        ax.set_title(title)
        ax.set_ylabel("kW")
        ax.grid(True, alpha=0.3)
        ax.legend(loc="upper right", fontsize=8, framealpha=0.8)

    axes[3, 0].set_xlabel("Hour")
    axes[3, 1].set_xlabel("Hour")
    fig.tight_layout()
    plt.show()


# =====================
# Configuration helpers
# =====================


def build_configuration_from_environment(scenario, county) -> SimulationConfiguration:
    # Clean county name for file paths (consistent slug)
    county_slug = slugify_county_name(county)
    
    preset_dir = os.environ.get("SAM_PRESET_DIR", "SAM_Detailed_PV_Battery")
    pvsam_json_name = os.environ.get("PVSAMV1_JSON", "untitled_pvsamv1.json")
    weather_file = os.environ.get(
        "WEATHER_FILE",
        f"data/loadprofiles/{scenario}/single-family-detached/{county_slug}/weather_TMY_{county_slug}.csv",
    )
    load_file = os.environ.get(
        "LOAD_FILE",
        f"data/loadprofiles/{scenario}/single-family-detached/{county_slug}/combined_profiles_{scenario}_{county_slug}.csv",
    )
    load_col = os.environ.get(
        "LOAD_COL",
        "electricity.real_and_simulated.for_typical_county_home.kwh",
    )
    show_plots = True
    try:
        # No time shifting - use weather data as-is to avoid timing issues
        weather_shift_hours = int(os.environ.get("WEATHER_SHIFT_HOURS", "0"))
    except Exception:
        weather_shift_hours = 0
    return SimulationConfiguration(
        county_slug=county_slug,
        sam_preset_dir=preset_dir,
        pvsamv1_json_name=pvsam_json_name,
        weather_file=weather_file,
        load_file=load_file,
        load_col=load_col,
        show_plots=show_plots,
        weather_shift_hours=weather_shift_hours,
    )


def validate_configuration(cfg: SimulationConfiguration) -> None:
    pvsam_json_path = os.path.join(cfg.sam_preset_dir, cfg.pvsamv1_json_name)
    if not os.path.exists(pvsam_json_path):
        raise FileNotFoundError(f"Pvsamv1 JSON not found: {pvsam_json_path}")
    if not os.path.exists(cfg.weather_file):
        raise FileNotFoundError(f"Weather file not found: {cfg.weather_file}")
    if not os.path.exists(cfg.load_file):
        raise FileNotFoundError(f"Research load CSV not found: {cfg.load_file}")


def configure(scenario: str = "baseline", county: str = "alameda") -> SimulationConfiguration:
    cfg = build_configuration_from_environment(scenario, county)
    validate_configuration(cfg)
    log_section("Effective Configuration")
    print(f"county_slug={cfg.county_slug}")
    print(f"preset_dir={cfg.sam_preset_dir}")
    print(f"pvsamv1_json_name={cfg.pvsamv1_json_name}")
    print(f"weather_file={cfg.weather_file}")
    print(f"load_file={cfg.load_file}")
    print(f"load_col={cfg.load_col}")
    print(f"weather_shift_hours={cfg.weather_shift_hours}")
    print(f"show_plots={cfg.show_plots}")
    return cfg


# ==============
# Preset loading
# ==============


def load_sam_presets_from_disk(cfg: SimulationConfiguration) -> SamPresetFiles:
    pvsam_json_path = os.path.join(cfg.sam_preset_dir, cfg.pvsamv1_json_name)
    return SamPresetFiles(photovoltaic_preset_values=load_json(pvsam_json_path))


def load_presets(cfg: SimulationConfiguration) -> SamPresetFiles:
    presets = load_sam_presets_from_disk(cfg)
    log_section("Preset Files Loaded")
    print(
        f"Pvsamv1 preset: {os.path.join(cfg.sam_preset_dir, cfg.pvsamv1_json_name)}  "
        f"(keys={len(presets.photovoltaic_preset_values)})"
    )
    return presets


def build_runtime_overrides(cfg: SimulationConfiguration) -> RuntimeOverrides:
    return RuntimeOverrides(
        min_soc=MIN_SOC,
        max_soc=MAX_SOC,
        initial_soc=INITIAL_SOC,
        dispatch_mode=DISPATCH_MODE,
        grid_interconnection_limit_kwac=GRID_INTERCONNECTION_LIMIT_KWAC,
        can_export_to_grid=CAN_EXPORT_TO_GRID,
        # Predictive dispatch parameters
        enable_predictive_dispatch=ENABLE_PREDICTIVE_DISPATCH,
        battery_efficiency=BATTERY_EFFICIENCY,
        peak_start_hour=PEAK_START_HOUR,
        peak_end_hour=PEAK_END_HOUR,
        battery_capacity_kwh=BATTERY_CAPACITY_KWH,
        
        # Solar charging control flags
        dispatch_manual_system_charge_first=DISPATCH_MANUAL_SYSTEM_CHARGE_FIRST,
        batt_dispatch_auto_can_charge=BATT_DISPATCH_AUTO_CAN_CHARGE,
        batt_dispatch_charge_only_system_exceeds_load=BATT_DISPATCH_CHARGE_ONLY_SYSTEM_EXCEEDS_LOAD,
        batt_dispatch_discharge_only_load_exceeds_system=BATT_DISPATCH_DISCHARGE_ONLY_LOAD_EXCEEDS_SYSTEM,
        batt_dispatch_auto_can_gridcharge=BATT_DISPATCH_AUTO_CAN_GRIDCHARGE,
        
        # Efficiency parameters
        batt_dc_dc_efficiency=BATT_DC_DC_EFFICIENCY,
        
        # Time window configuration
        solar_charging_start_hour=SOLAR_CHARGING_START_HOUR,
        solar_charging_end_hour=SOLAR_CHARGING_END_HOUR,
        peak_discharge_start_hour=PEAK_DISCHARGE_START_HOUR,
        peak_discharge_end_hour=PEAK_DISCHARGE_END_HOUR,
    )


# =================
# Module management
# =================


def create_sam_compute_modules(with_standalone_battery: bool = False) -> SamModules:
    pv = Pvsamv1.new()
    # Intentionally avoid creating a standalone Battery module in this path
    return SamModules(photovoltaic_model=pv, battery_model=None)


def initialize_modules() -> SamModules:
    return create_sam_compute_modules(with_standalone_battery=False)


def apply_preset_values_to_modules(modules: SamModules, presets: SamPresetFiles) -> ApplyReport:
    pv = modules.photovoltaic_model
    ap_pv, failed_pv = apply_json(pv, presets.photovoltaic_preset_values)
    # No standalone battery in this workflow
    return ApplyReport(
        pv_applied_count=ap_pv,
        pv_failed_keys=failed_pv,
        batt_applied_count=0,
        batt_failed_keys=[],
        warnings=[],
    )


def apply_runtime_overrides(pv: Pvsamv1.Pvsamv1, overrides: RuntimeOverrides) -> None:
    def set_if_present(key: str, value: Optional[Any]) -> None:
        if value is None:
            return
        try:
            pv.value(key, value)
        except Exception:
            pass

    # Basic battery configuration
    set_if_present("batt_minimum_SOC", overrides.min_soc)
    set_if_present("batt_maximum_SOC", overrides.max_soc)
    set_if_present("batt_initial_SOC", overrides.initial_soc)
    set_if_present("batt_dispatch_choice", overrides.dispatch_mode)
    set_if_present("grid_interconnection_limit_kwac", overrides.grid_interconnection_limit_kwac)
    set_if_present("batt_dispatch_auto_btm_can_discharge_to_grid", overrides.can_export_to_grid)
    
    # Solar charging control flags (direct SAM parameter values)
    set_if_present("en_standalone_batt", 0)
    set_if_present("dispatch_manual_system_charge_first", 1) # overrides.dispatch_manual_system_charge_first)
    set_if_present("batt_dispatch_auto_can_charge", 1) # overrides.batt_dispatch_auto_can_charge)
    set_if_present("batt_dispatch_auto_can_clipcharge", 1)
    set_if_present("batt_dispatch_charge_only_system_exceeds_load", 1) # overrides.batt_dispatch_charge_only_system_exceeds_load)
    set_if_present("batt_dispatch_discharge_only_load_exceeds_system", overrides.batt_dispatch_discharge_only_load_exceeds_system)
    set_if_present("batt_dispatch_auto_can_gridcharge", overrides.batt_dispatch_auto_can_gridcharge)
    
    # Efficiency parameters
    set_if_present("batt_dc_dc_efficiency", overrides.batt_dc_dc_efficiency)
    
    # Force single-year outputs instead of 25-year lifetime to prevent 219,000 element arrays
    set_if_present("analysis_period", 1)
    set_if_present("system_use_lifetime_output", 0)
    set_if_present("batt_replacement_option", 0)  # Disable battery replacements for single-year analysis
    print(f"✓ Forced single-year analysis: analysis_period=1, system_use_lifetime_output=0, batt_replacement_option=0")


def apply_dispatch_schedule(pv: Pvsamv1.Pvsamv1, dispatch_schedule: Dict[str, Any], 
                          overrides: RuntimeOverrides) -> None:
    """Apply the predictive dispatch schedule to the SAM model with comprehensive solar charging configuration."""
    
    log_section("Applying Dispatch Schedule Configuration")
    
    # Set manual dispatch mode (Mode 3: Manual Dispatch with period-based scheduling)
    pv.value('batt_dispatch_choice', 3)
    print(f"Set dispatch mode: 3 (Manual Dispatch)")
    
    # =======================
    # PERIOD-BASED SCHEDULING CONFIGURATION
    # =======================
    
    # Define daily time periods based on configured windows
    solar_start = overrides.solar_charging_start_hour or 6
    solar_end = overrides.solar_charging_end_hour or 17
    peak_start = overrides.peak_discharge_start_hour or 18
    peak_end = overrides.peak_discharge_end_hour or 23
    
    # Build dynamic schedule based on time windows:
    # Period 1: Night/off-peak hours - No action, preserve battery
    # Period 2: Solar charging window - Solar charging enabled
    # Period 3: Peak discharge window - Discharge to reduce grid usage
    daily_schedule = []
    for hour in range(24):
        if solar_start <= hour <= solar_end:
            daily_schedule.append(2)  # Solar charging period
        elif peak_start <= hour <= peak_end:
            daily_schedule.append(3)  # Peak discharge period
        else:
            daily_schedule.append(1)  # Off-peak period
    
    print(f"Time windows: Solar({solar_start}-{solar_end}), Peak({peak_start}-{peak_end})")
    schedule_matrix = [daily_schedule] * 12  # Same pattern for all 12 months
    # 1 means: off-peak / night hours
    # 2 means: solar charging window
    # 3 means: peak discharge window
    # 4 means: summer peak discharge
    
    schedule_matrix = [[1, 1, 1, 1, 1, 1, 2, 2, 2, 2, 2, 2, 2, 2, 2, 3, 3, 3, 3, 3, 3, 3, 1, 1], [1, 1, 1, 1, 1, 1, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 3, 3, 3, 3, 3, 3, 1, 1], [1, 1, 1, 1, 1, 1, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 3, 3, 3, 3, 3, 3, 1, 1], [1, 1, 1, 1, 1, 1, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 3, 3, 3, 3, 3, 3, 1, 1], [1, 1, 1, 1, 1, 1, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 3, 3, 3, 3, 3, 3, 1, 1], [1, 1, 1, 1, 1, 1, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 3, 3, 3, 3, 3, 3, 1, 1], [1, 1, 1, 1, 1, 1, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 3, 3, 3, 3, 3, 3, 1, 1], [1, 1, 1, 1, 1, 1, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 3, 3, 3, 3, 3, 3, 1, 1], [1, 1, 1, 1, 1, 1, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 3, 3, 3, 3, 3, 3, 1, 1], [1, 1, 1, 1, 1, 1, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 3, 3, 3, 3, 3, 3, 1, 1], [1, 1, 1, 1, 1, 1, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 3, 3, 3, 3, 3, 3, 1, 1], [1, 1, 1, 1, 1, 1, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 3, 3, 3, 3, 3, 3, 1, 1]]
    schedule_matrix_weekend = [[ 1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1 ], [ 1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1 ], [ 1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1 ], [ 1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1 ], [ 1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1 ], [ 1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1 ], [ 1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1 ], [ 1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1 ], [ 1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1 ], [ 1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1 ], [ 1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1 ], [ 1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1,  1 ]]
    
    pv.value('dispatch_manual_sched', schedule_matrix)
    pv.value('dispatch_manual_sched_weekend', schedule_matrix_weekend)
    print(f"Applied period schedule: Night(1), Solar(2), Peak(3)")

    # Configure period actions based on generated dispatch schedule
    grid_charge_max = max(dispatch_schedule.get('dispatch_manual_percent_gridcharge', [0]))
    discharge_max = max(dispatch_schedule.get('dispatch_manual_percent_discharge', [0]))
    
    # Period action configuration:
    # [Period1, Period2, Period3, Period4, Period5, Period6]
    pv.value('dispatch_manual_charge', [1, 1, 0, 0, 0, 0]) # Solar charge during all periods

    pv.value("dispatch_manual_discharge", [ 1, 1, 1, 1, 0, 0 ]) # Dispatch during periods 1, 2, 3 and 4
    pv.value('dispatch_manual_percent_discharge', [ 0, 0, 10, 10, 0, 0 ]) # Dispatch manually in periods 3 and 4 at a rate of 10%

    pv.value("dispatch_manual_btm_discharge_to_grid", [ 0, 0, 0, 0, 0, 0 ]) # No grid discharge ever

    pv.value("dispatch_manual_gridcharge", [ 1, 1, 0, 0, 0, 0 ]) # Grid charge during period 1
    pv.value("dispatch_manual_percent_gridcharge", [50, 50, 0, 0, 0, 0])

    
    # =======================
    # SOLAR CHARGING PRIORITY AND CONTROL FLAGS
    # =======================
    
    # Solar charging priority - critical for solar-first operation
    pv.value('dispatch_manual_system_charge_first', overrides.dispatch_manual_system_charge_first)
    print(f"✓ Solar charging priority: {overrides.dispatch_manual_system_charge_first}")
    
    # Master PV charging enable
    pv.value('batt_dispatch_auto_can_charge', overrides.batt_dispatch_auto_can_charge)
    print(f"✓ PV charging capability: {overrides.batt_dispatch_auto_can_charge}")
    
    # Smart solar charging - only charge when solar exceeds load
    pv.value('batt_dispatch_charge_only_system_exceeds_load', 0) # overrides.batt_dispatch_charge_only_system_exceeds_load)
    print(f"✓ Smart solar charging: {overrides.batt_dispatch_charge_only_system_exceeds_load}")
    
    # Smart discharge - only discharge when load exceeds solar
    pv.value('batt_dispatch_discharge_only_load_exceeds_system', overrides.batt_dispatch_discharge_only_load_exceeds_system)
    print(f"✓ Smart discharge: {overrides.batt_dispatch_discharge_only_load_exceeds_system}")
    
    # Grid charging control - allow schedule to dynamically override this setting
    grid_charging_enabled = 1 # if (grid_charge_max > 0 and overrides.batt_dispatch_auto_can_gridcharge == 1) else 0
    pv.value('batt_dispatch_auto_can_gridcharge', grid_charging_enabled)
    print(f"✓ Grid charging: {grid_charging_enabled} (schedule-driven)")
    
    # Grid export control
    pv.value('batt_dispatch_auto_btm_can_discharge_to_grid', overrides.can_export_to_grid)
    print(f"✓ Battery-to-grid export: {overrides.can_export_to_grid}")
    
    # =======================
    # EFFICIENCY AND CONVERSION PARAMETERS
    # =======================
    
    # DC-DC converter efficiency for solar-to-battery charging
    pv.value('batt_dc_dc_efficiency', overrides.batt_dc_dc_efficiency)
    print(f"✓ DC-DC converter efficiency: {overrides.batt_dc_dc_efficiency}%")
    
    # =======================
    # CAPACITY AND RATE LIMITS
    # =======================
    
    # Battery capacity configuration
    if overrides.battery_capacity_kwh:
        # Note: Battery capacity is typically set in the JSON preset files
        # These parameters may be read-only depending on the SAM configuration
        try:
            pv.value('batt_computed_bank_capacity', overrides.battery_capacity_kwh)
            print(f"✓ Battery capacity: {overrides.battery_capacity_kwh} kWh")
        except Exception:
            print(f"⚠ Battery capacity setting failed (may be preset-controlled)")
    
    # Grid interconnection limit
    if overrides.grid_interconnection_limit_kwac:
        pv.value('grid_interconnection_limit_kwac', overrides.grid_interconnection_limit_kwac)
        print(f"✓ Grid interconnection limit: {overrides.grid_interconnection_limit_kwac} kW")
    
    # =======================
    # VALIDATION AND REPORTING
    # =======================
    
    # Report dispatch schedule metrics
    metrics = dispatch_schedule.get('validation_metrics', {})
    if metrics:
        print(f"Schedule validation:")
        print(f"  Peak coverage: {metrics.get('peak_coverage_percentage', 0):.1f}%")
        print(f"  Annual grid charging: {metrics.get('annual_grid_charging_kwh', 0):.1f} kWh")
        print(f"  Annual efficiency losses: {metrics.get('annual_efficiency_losses_kwh', 0):.1f} kWh")
    
    # Verify critical settings were applied
    current_dispatch_mode = pv.value('batt_dispatch_choice')
    current_solar_priority = pv.value('dispatch_manual_system_charge_first')
    current_pv_charge = pv.value('batt_dispatch_auto_can_charge')
    
    print(f"Verification: dispatch_mode={current_dispatch_mode}, "
          f"solar_priority={current_solar_priority}, pv_charge={current_pv_charge}")
    
    if current_dispatch_mode != 3:
        print(f"⚠ WARNING: Dispatch mode is {current_dispatch_mode}, expected 3 (Manual)")


def report_apply_results(report: ApplyReport) -> None:
    print(
        f"Applied {report.pv_applied_count} parameters to Pvsamv1 "
        f"({len(report.pv_failed_keys)} failed)"
    )
    if report.pv_failed_keys:
        print(f"WARN: Pvsamv1 keys failed to apply: {sorted(report.pv_failed_keys)[:10]}" + (" ..." if len(report.pv_failed_keys) > 10 else ""))


def ensure_manual_dispatch_if_configured(pv: Pvsamv1.Pvsamv1, presets: SamPresetFiles) -> None:
    dispatch_from_json = presets.photovoltaic_preset_values.get("batt_dispatch_choice", None)
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


def read_soc_bounds(pv: Pvsamv1.Pvsamv1) -> SocBounds:
    def get_or_none(k: str) -> Optional[float]:
        try:
            return float(pv.value(k))
        except Exception:
            return None
    return SocBounds(
        min_soc=get_or_none("batt_minimum_SOC"),
        max_soc=get_or_none("batt_maximum_SOC"),
        initial_soc=get_or_none("batt_initial_SOC"),
    )


def report_soc_bounds(bounds: SocBounds) -> None:
    log_section("Battery SOC Settings (Pre-Execute)")
    print(
        f"min_SOC={bounds.min_soc}  max_SOC={bounds.max_soc}  initial_SOC={bounds.initial_soc}"
    )


def report_grid_export_settings(presets: SamPresetFiles) -> None:
    log_section("Grid Export Settings (from JSON)")
    pvj = presets.photovoltaic_preset_values
    print(
        f"batt_dispatch_auto_btm_can_discharge_to_grid = "
        f"{pvj.get('batt_dispatch_auto_btm_can_discharge_to_grid', None)}"
    )
    print(
        f"dispatch_manual_btm_discharge_to_grid        = "
        f"{pvj.get('dispatch_manual_btm_discharge_to_grid', None)}"
    )
    print(
        f"grid_interconnection_limit_kwac              = "
        f"{pvj.get('grid_interconnection_limit_kwac', None)}"
    )


def configure_modules(modules: SamModules, presets: SamPresetFiles, overrides: RuntimeOverrides) -> ApplyReport:
    report = apply_preset_values_to_modules(modules, presets)
    report_apply_results(report)
    apply_runtime_overrides(modules.photovoltaic_model, overrides)
    ensure_manual_dispatch_if_configured(modules.photovoltaic_model, presets)
    report_soc_bounds(read_soc_bounds(modules.photovoltaic_model))
    report_grid_export_settings(presets)
    return report


def attach_weather_resource_to_pvsam(pv: Pvsamv1.Pvsamv1, cfg: SimulationConfiguration) -> bool:
    if not os.path.exists(cfg.weather_file):
        print(f"ERROR: Required weather file not found: {cfg.weather_file}")
        raise FileNotFoundError(cfg.weather_file)

    srd = ResourceTools.SAM_CSV_to_solar_data(cfg.weather_file)

    # Use weather data as-is without time shifting to avoid timing issues
    shift_hours = cfg.weather_shift_hours
    if shift_hours != 0:
        hourly_keys = ["dn", "df", "gh", "tdry", "tdew", "rhum", "wdir", "wspd"]
        for key in hourly_keys:
            if key in srd and isinstance(srd[key], (list, tuple)) and len(srd[key]) == 8760:
                arr = list(srd[key])
                srd[key] = [arr[(i + shift_hours) % 8760] for i in range(8760)]
        print(f"Attached weather from: {cfg.weather_file} (shifted +{shift_hours}h; no tz override)")
    else:
        print(f"Attached weather from: {cfg.weather_file} (no time shifting applied)")

    # Debug: examine weather data before timezone changes
    current_tz = srd.get('tz', 'not specified')
    print(f"Weather timezone (original): {current_tz}")
    
    # Sample some weather data for debugging
    if 'gh' in srd and len(srd['gh']) >= 24:
        gh_sample = srd['gh'][:24]  # First 24 hours of global horizontal irradiance
        max_gh = max(gh_sample)
        max_gh_hour = gh_sample.index(max_gh)
        print(f"Weather sample: max irradiance {max_gh:.1f} W/m² at hour {max_gh_hour} (before tz change)")
    
    # CONFIGURABLE: Set timezone override or leave as-is
    # For testing, you can change this value or comment out the override
    # Try combining both timezone setting AND data shifting for UTC->Pacific Time conversion
    APPLY_TIMEZONE_OVERRIDE = True  # Disable timezone override for now
    APPLY_TIME_SHIFT = True  # Enable 8-hour time shift to convert UTC->Pacific
    SHIFT_HOURS = 8  # UTC to Pacific Time shift
    
    if APPLY_TIME_SHIFT and SHIFT_HOURS != 0:
        # Apply time shift to weather data arrays (UTC to Pacific Time)
        hourly_keys = ["dn", "df", "gh", "tdry", "tdew", "rhum", "wdir", "wspd"]
        for key in hourly_keys:
            if key in srd and isinstance(srd[key], (list, tuple)) and len(srd[key]) == 8760:
                arr = list(srd[key])
                # Store original GHI for comparison if this is the GHI key
                if key == "gh":
                    original_gh = arr[:24]  # First 24 hours before shift
                # Shift data: positive shift moves data earlier (UTC->PST needs +8 hour shift)
                srd[key] = [arr[(i + SHIFT_HOURS) % 8760] for i in range(8760)]
                # Print GHI comparison for specific counties
                if key == "gh":
                    shifted_gh = srd[key][:24]  # First 24 hours after shift
                    county_name = cfg.county_slug.replace('-', ' ').title()
                    if 'alameda' in cfg.county_slug.lower() or 'alpine' in cfg.county_slug.lower():
                        print(f"\n=== GHI ANALYSIS FOR {county_name.upper()} ===")
                        print(f"Original GHI (first 24h): {[round(x, 1) for x in original_gh]}")
                        print(f"Shifted GHI (first 24h):  {[round(x, 1) for x in shifted_gh]}")
                        max_orig = max(original_gh)
                        max_shift = max(shifted_gh)
                        max_orig_hour = original_gh.index(max_orig)
                        max_shift_hour = shifted_gh.index(max_shift)
                        print(f"Peak GHI: {max_orig:.1f} W/m² at hour {max_orig_hour} → {max_shift:.1f} W/m² at hour {max_shift_hour}")
        print(f"Applied {SHIFT_HOURS}h time shift to weather data (UTC->Pacific)")
    
    if APPLY_TIMEZONE_OVERRIDE:
        # Set timezone field (currently disabled)
        srd["tz"] = -8
        print(f"Weather timezone (override): -8 (Pacific Time)")
    else:
        print(f"Weather timezone (no override): using original {current_tz}")
    
    pv.SolarResource.solar_resource_data = srd
    return True


def align_load_profile_to_midnight(df: pd.DataFrame, load_col: str) -> List[float]:
    """
    Align the load profile to start at midnight (00:00:00) of January 1st.
    
    Args:
        df: DataFrame with timestamp and load columns
        load_col: Name of the load column
        
    Returns:
        List of load values aligned to start at midnight, maintaining 8760 hours
    """
    if 'timestamp' not in df.columns:
        print("WARNING: No timestamp column found, assuming data already starts at midnight")
        return df[load_col].astype(float).tolist()
    
    # Parse timestamps
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    
    # Find midnight of January 1st
    # Look for the first occurrence of hour 0 on January 1st
    january_first_mask = (df['timestamp'].dt.month == 1) & (df['timestamp'].dt.day == 1)
    midnight_mask = df['timestamp'].dt.hour == 0
    target_mask = january_first_mask & midnight_mask
    
    if not target_mask.any():
        print("WARNING: Could not find January 1st midnight, assuming data already starts at midnight")
        return df[load_col].astype(float).tolist()
    
    # Get the index of midnight January 1st
    midnight_index = df[target_mask].index[0]
    original_start_time = df['timestamp'].iloc[0]
    midnight_time = df['timestamp'].iloc[midnight_index]
    
    print(f"Original start time: {original_start_time}")
    print(f"Aligning to midnight: {midnight_time}")
    print(f"Shifting by {midnight_index} hours")
    
    # Extract load values and rotate to start at midnight
    load_values = df[load_col].astype(float).tolist()
    
    # Rotate the array: take from midnight_index to end, then from start to midnight_index
    aligned_load = load_values[midnight_index:] + load_values[:midnight_index]
    
    if len(aligned_load) != 8760:
        raise ValueError(f"Aligned load profile has {len(aligned_load)} hours, expected 8760")
    
    return aligned_load


def attach_load_profile_to_pvsam(pv: Pvsamv1.Pvsamv1, cfg: SimulationConfiguration) -> bool:
    if not os.path.exists(cfg.load_file):
        print(
            "ERROR: Required research load CSV not found: "
            f"{cfg.load_file} (no JSON fallback is allowed)"
        )
        raise FileNotFoundError(cfg.load_file)

    df = pd.read_csv(cfg.load_file)
    if cfg.load_col not in df.columns:
        raise KeyError(
            f"Column '{cfg.load_col}' not found in {cfg.load_file}. Available columns: {list(df.columns)}"
        )
    
    # Align load profile to start at midnight and get the aligned load values
    load = align_load_profile_to_midnight(df, cfg.load_col)
    
    if len(load) != 8760:
        raise ValueError(
            f"Research load series must be 8760 hours; got len={len(load)} at {cfg.load_file}"
        )

    pv.value("load", load)
    # Provide auxiliary arrays commonly required
    pv.value("crit_load", [0.0] * len(load))
    pv.value("batt_load_ac_forecast", load)
    print(
        f"Attached aligned load from CSV: {cfg.load_file} (len={len(load)}, sum={sum(load):.1f} kWh)"
    )
    return True


def attach_json_load_if_present(pv: Pvsamv1.Pvsamv1, presets: SamPresetFiles) -> bool:
    # For research reproducibility, we intentionally do not use the JSON 'load' in this workflow.
    if isinstance(presets.photovoltaic_preset_values.get("load"), list):
        print("INFO: JSON contains 'load', but research pipeline requires CSV load. Ignoring JSON 'load'.")
    return False


def attach_resources(pv: Pvsamv1.Pvsamv1, cfg: SimulationConfiguration, presets: SamPresetFiles) -> None:
    ok_weather = attach_weather_resource_to_pvsam(pv, cfg)
    ok_load = attach_load_profile_to_pvsam(pv, cfg)
    if not (ok_weather and ok_load):
        raise RuntimeError("Failed to attach required weather and research load resources.")


def _diy_pv_from_srd(pv: Pvsamv1.Pvsamv1, system_capacity_kw: float) -> list[float]:
    """Reconstruct a simple gross PV AC series from SAM's weather resource.

    Uses the same simplified model/parameters as the DIY step so that the
    "PV AC (kWh)" panel represents gross available PV (pre‑constraint).
    """
    try:
        srd = pv.SolarResource.solar_resource_data
        ghi = np.asarray(srd.get('gh') or srd.get('ghi') or [], dtype=float)
        tamb = np.asarray(srd.get('tdry') or srd.get('tamb') or [], dtype=float)
        if ghi.size == 0:
            return [0.0] * 8760
        if tamb.size == 0:
            tamb = np.full_like(ghi, 20.0)
        # Cell temperature and temp derate
        tcell = tamb + ((NOCT_C - 20.0) / G_NOCT) * ghi
        temp_derate = np.clip(1.0 + (GAMMA_PDC) * (tcell - 25.0), 0.0, 1.5)
        pac = system_capacity_kw * (ghi / G_REF) * PV_SIZING_PR * temp_derate
        pac = np.clip(pac, 0.0, None)
        if pac.size != 8760:
            out = np.zeros(8760)
            n = min(8760, pac.size)
            out[:n] = pac[:n]
            return out.tolist()
        return pac.tolist()
    except Exception:
        return [0.0] * 8760


def _compute_system_capacity_kW_from_pv_and_load(pv: Pvsamv1.Pvsamv1) -> float:
    """Size PV capacity from weather (GHI) and load, mirroring the DIY step.

    Uses:
    - mean GHI (W/m²) → annual kWh/m² via 24h and 365d
    - PV_SIZING_CELL_EFF and PV_SIZING_PR for electrical yield per m²
    - PV_SIZING_POWER_DENSITY (kW/m²) to convert area to DC capacity
    """
    try:
        srd = pv.SolarResource.solar_resource_data
        ghi = srd.get('gh') or srd.get('ghi')
        if not ghi or len(ghi) == 0:
            return 0.0
        mean_ghi = float(sum(ghi) / len(ghi))  # W/m²
        daily_irr_kwh_per_m2 = mean_ghi * 24.0 / 1000.0
        annual_irr_kwh_per_m2 = daily_irr_kwh_per_m2 * 365.0
        annual_elec_per_m2 = annual_irr_kwh_per_m2 * PV_SIZING_CELL_EFF * PV_SIZING_PR
        try:
            load = pv.value('load')
        except Exception:
            load = []
        annual_load_kwh = float(sum(load)) if load else 0.0
        required_panel_area_m2 = (annual_load_kwh / annual_elec_per_m2) if annual_elec_per_m2 > 0 else 0.0
        required_dc_capacity_kw = required_panel_area_m2 * PV_SIZING_POWER_DENSITY
        # guardrail
        return max(0.0, float(required_dc_capacity_kw))
    except Exception:
        return 0.0


# ==========
# Execution
# ==========


def execute_pvsam(pv: Pvsamv1.Pvsamv1, county_slug: str = "") -> bool:
    try:
        pv.execute(0)
        
        # ==== DIAGNOSTIC: Solar Generation Profile Analysis ====
        county_name = county_slug.replace('-', ' ').title() if county_slug else "Unknown"
        print(f"\n=== SOLAR GENERATION DIAGNOSTIC LOGGING - {county_name.upper()} ===")
        
        try:
            out = pv.Outputs.export()
            
            # Extract solar generation components
            system_to_batt = out.get("system_to_batt", [])
            system_to_load = out.get("system_to_load", [])
            system_to_grid = out.get("system_to_grid", [])
            
            if system_to_load and system_to_batt and system_to_grid:
                # Calculate total solar generation
                total_solar = [a + b + c for a, b, c in zip(system_to_load, system_to_batt, system_to_grid)]
                
                if len(total_solar) >= 24:
                    print(f"Solar Generation Analysis for {county_name}:")
                    print(f"  Profile length: {len(total_solar)} hours")
                    print(f"  Annual total: {sum(total_solar):.2f} kWh")
                    print(f"  Peak generation: {max(total_solar):.3f} kW")
                    print(f"  Average generation: {sum(total_solar)/len(total_solar):.3f} kW")
                    
                    # Special detailed output for Alameda and Alpine
                    if 'alameda' in county_slug.lower() or 'alpine' in county_slug.lower():
                        print(f"\n  *** DETAILED {county_name.upper()} SOLAR ANALYSIS ***")
                        print(f"  Annual solar kWh: {sum(total_solar):.1f}")
                        print(f"  First 24h solar (kW): {[round(x, 3) for x in total_solar[:24]]}")
                        print(f"  Midday hours 10-15 (kW): {[round(x, 3) for x in total_solar[10:16]]}")
                        print(f"  Evening hours 16-21 (kW): {[round(x, 3) for x in total_solar[16:22]]}")
                        
                        # Find daily peak pattern for first week
                        for day in range(7):
                            day_start = day * 24
                            day_end = day_start + 24
                            daily_solar = total_solar[day_start:day_end]
                            daily_peak = max(daily_solar)
                            peak_hour = daily_solar.index(daily_peak)
                            print(f"  Day {day+1} peak: {daily_peak:.3f} kW at hour {peak_hour}")
                        print(f"  *** END {county_name.upper()} DETAILS ***")
                    
                    # Find peak generation time
                    max_gen = max(total_solar)
                    peak_hour = total_solar.index(max_gen)
                    print(f"  Peak generation hour: {peak_hour} (hour of year)")
                    print(f"  Peak generation time of day: {peak_hour % 24}:00")
                    
                    # Show first 24 hours pattern
                    print(f"  First 24 hours: {[round(x, 3) for x in total_solar[:24]]}")
                    
                    # Show midday pattern (hours around solar noon)
                    noon_start = 10
                    noon_end = 16
                    noon_pattern = total_solar[noon_start:noon_end]
                    print(f"  Hours {noon_start}-{noon_end-1}: {[round(x, 3) for x in noon_pattern]}")
                    
                    # Count productive hours
                    productive_hours = len([x for x in total_solar if x > 0.1])  # >0.1 kW
                    print(f"  Productive hours (>0.1 kW): {productive_hours}")
                    
                    # Check for unusual patterns
                    if max_gen < 1.0:
                        print(f"  ⚠️  Low peak generation: {max_gen:.3f} kW")
                    if peak_hour % 24 < 10 or peak_hour % 24 > 16:
                        print(f"  ⚠️  Unusual peak time: {peak_hour % 24}:00")
                    
                else:
                    print(f"  Warning: Short solar profile ({len(total_solar)} hours)")
            else:
                print(f"  Warning: Missing solar generation components")
                print(f"  Available keys: {sorted(out.keys())}")
        
        except Exception as e:
            print(f"Error in solar diagnostic logging: {e}")
        
        print(f"=== END SOLAR DIAGNOSTIC LOGGING ===\n")
        # ==== END DIAGNOSTIC ====
        
        print("\nExecuted Pvsamv1 successfully.")
        return True
    except Exception as e:
        raise RuntimeError(f"Pvsamv1 execution failed: {e}")


def execute(pv: Pvsamv1.Pvsamv1, county_slug: str = "") -> None:
    execute_pvsam(pv, county_slug)


# ============
# Extraction
# ============


def solar_ac_power_series_from_flows(pv: Pvsamv1.Pvsamv1) -> List[float]:
    return _pv_ac_from_flows(pv).astype(float).ravel().tolist()


def load_series_kw_from_model(pv: Pvsamv1.Pvsamv1) -> List[float]:
    return _load_series(pv).astype(float).ravel().tolist()


def state_of_charge_series_percent_from_model(pv: Pvsamv1.Pvsamv1) -> List[float]:
    return _soc_series(pv).astype(float).ravel().tolist()


def per_source_load_series_kw_from_model(pv: Pvsamv1.Pvsamv1) -> Tuple[List[float], List[float], List[float]]:
    sL, bL, gL = _flow_series(pv)
    return sL.astype(float).ravel().tolist(), bL.astype(float).ravel().tolist(), gL.astype(float).ravel().tolist()


def collect_outputs(pv: Pvsamv1.Pvsamv1) -> SimulationSeries:
    return SimulationSeries(
        load_series_kw=load_series_kw_from_model(pv),
        state_of_charge_series_percent=state_of_charge_series_percent_from_model(pv),
        solar_ac_power_series_kw=solar_ac_power_series_from_flows(pv),
        solar_to_load_series_kw=per_source_load_series_kw_from_model(pv)[0],
        battery_to_load_series_kw=per_source_load_series_kw_from_model(pv)[1],
        grid_to_load_series_kw=per_source_load_series_kw_from_model(pv)[2],
    )


def extract(pv: Pvsamv1.Pvsamv1) -> SimulationSeries:
    return collect_outputs(pv)


# =========
# Reporting
# =========


def report_manual_dispatch_schedules(presets: SamPresetFiles) -> None:
    log_section("Manual Dispatch Schedules (from JSON)")
    pvsam = presets.photovoltaic_preset_values
    for key in (
        "dispatch_manual_sched",
        "dispatch_manual_sched_weekend",
        "dispatch_manual_percent_discharge",
        "dispatch_manual_percent_gridcharge",
        "dispatch_manual_btm_discharge_to_grid",
    ):
        val = pvsam.get(key)
        if isinstance(val, list) and len(val) > 24:
            print(f"{key}: len={len(val)} head={val[:5]} ... tail={val[-5:]}")
        else:
            print(f"{key}: {val}")

def calculate_daily_charging_schedule(day_start: int, target_energy_needed: float, load_forecast: List[float], 
                                    solar_forecast: Optional[List[float]], battery_capacity_kwh: float) -> Dict[str, float]:
    """
    Phase 1: Calculate charging schedule for 6am-4pm period (solar priority + grid backup).
    
    Args:
        day_start: Starting hour index for the day (day * 24)
        target_energy_needed: kWh needed to be stored (from calculate_peak_energy_requirements)
        load_forecast: 8760-hour load profile (kW)
        solar_forecast: 8760-hour solar generation forecast (kW), optional
        battery_capacity_kwh: Battery capacity
        
    Returns:
        Dictionary with cumulative_stored_kwh, grid_charging_kwh, grid_charge_hours
    """
    cumulative_stored_kwh = 0.0
    total_grid_charging_kwh = 0.0
    grid_charge_hours = []
    
    for hour in range(6, 16):  # 6am to 4pm
        hour_index = day_start + hour
        
        # Solar charging priority
        if solar_forecast and hour_index < len(solar_forecast):
            solar_gen = solar_forecast[hour_index]
            load = load_forecast[hour_index] if hour_index < len(load_forecast) else 0.0
            excess_solar = max(0.0, solar_gen - load)
            
            # Use available solar first
            energy_still_needed = target_energy_needed - cumulative_stored_kwh
            if energy_still_needed > 0 and excess_solar > 0:
                solar_charge_kwh = min(excess_solar, energy_still_needed)
                cumulative_stored_kwh += solar_charge_kwh
        
        # Grid backup charging if solar insufficient (after 10am)
        if hour >= 10:
            energy_still_needed = target_energy_needed - cumulative_stored_kwh
            if energy_still_needed > 0:
                max_hourly_charge = min(5.0, energy_still_needed)  # 5kW charge rate limit
                grid_charge_percent = min(100.0, (max_hourly_charge / battery_capacity_kwh) * 100.0)
                cumulative_stored_kwh += max_hourly_charge
                total_grid_charging_kwh += max_hourly_charge
                grid_charge_hours.append((hour_index, grid_charge_percent))
    
    return {
        'cumulative_stored_kwh': cumulative_stored_kwh,
        'grid_charging_kwh': total_grid_charging_kwh,
        'grid_charge_hours': grid_charge_hours
    }


def get_peak_period_loads(day_start: int, load_forecast: List[float], peak_start: int = 16, peak_end: int = 21) -> Dict[str, Any]:
    """
    Extract peak period load profile for proportional discharge calculation.
    
    Args:
        day_start: Starting hour index for the day (day * 24)
        load_forecast: 8760-hour load profile (kW)
        peak_start: Peak period start hour (default 16 = 4pm)
        peak_end: Peak period end hour (default 21 = 9pm)
        
    Returns:
        Dictionary with peak_loads, total_peak_load, peak_hour_indices
    """
    peak_loads = []
    peak_hour_indices = []
    total_peak_load = 0.0
    
    for hour in range(peak_start, peak_end):
        hour_index = day_start + hour
        load = load_forecast[hour_index] if hour_index < len(load_forecast) else 0.0
        peak_loads.append(load)
        peak_hour_indices.append(hour_index)
        total_peak_load += load
    
    return {
        'peak_loads': peak_loads,
        'total_peak_load': total_peak_load,
        'peak_hour_indices': peak_hour_indices
    }


def distribute_discharge_proportionally(peak_loads: List[float], total_peak_load: float, 
                                      available_discharge_energy: float, battery_capacity_kwh: float) -> List[Tuple[float, float]]:
    """
    Calculate proportional discharge percentages for peak period hours.
    
    Args:
        peak_loads: Load for each peak period hour (kW)
        total_peak_load: Sum of all peak period loads (kW)
        available_discharge_energy: Energy available for discharge (kWh)
        battery_capacity_kwh: Battery capacity for percentage calculation
        
    Returns:
        List of (desired_discharge_kwh, discharge_percent) tuples for each peak hour
    """
    discharge_schedule = []
    
    if total_peak_load > 0:
        for load in peak_loads:
            # Proportional discharge based on load profile
            load_fraction = load / total_peak_load
            desired_discharge_kwh = min(available_discharge_energy * load_fraction, load)
            
            # Convert to discharge percentage for SAM
            if desired_discharge_kwh > 0:
                discharge_percent = min(100.0, (desired_discharge_kwh / battery_capacity_kwh) * 100.0)
            else:
                discharge_percent = 0.0
                
            discharge_schedule.append((desired_discharge_kwh, discharge_percent))
    else:
        # No load during peak period
        discharge_schedule = [(0.0, 0.0)] * len(peak_loads)
    
    return discharge_schedule


def calculate_peak_discharge_schedule(day_start: int, target_soc: float, min_soc: float, 
                                    battery_capacity_kwh: float, load_forecast: List[float], 
                                    peak_start: int = 16, peak_end: int = 21) -> Dict[str, Any]:
    """
    Phase 2: Calculate discharge schedule for 4pm-9pm peak period.
    
    Args:
        day_start: Starting hour index for the day (day * 24)
        target_soc: Target SOC by 4pm (from calculate_precharge_target_soc)
        min_soc: Minimum SOC percentage
        battery_capacity_kwh: Battery capacity
        load_forecast: 8760-hour load profile (kW)
        peak_start: Peak period start hour (default 16 = 4pm)
        peak_end: Peak period end hour (default 21 = 9pm)
        
    Returns:
        Dictionary with discharge_hours, peak_coverage, total_discharge_kwh
    """
    # Available energy for discharge (from target SOC down to min SOC)
    available_discharge_energy = ((target_soc - min_soc) / 100.0) * battery_capacity_kwh
    
    # Get peak period loads
    peak_info = get_peak_period_loads(day_start, load_forecast, peak_start, peak_end)
    peak_loads = peak_info['peak_loads']
    total_peak_load = peak_info['total_peak_load']
    peak_hour_indices = peak_info['peak_hour_indices']
    
    # Calculate proportional discharge
    discharge_schedule = distribute_discharge_proportionally(
        peak_loads, total_peak_load, available_discharge_energy, battery_capacity_kwh
    )
    
    # Build output with hour indices and discharge percentages
    discharge_hours = []
    peak_coverage = 0.0
    total_discharge_kwh = 0.0
    
    for i, (discharge_kwh, discharge_percent) in enumerate(discharge_schedule):
        hour_index = peak_hour_indices[i]
        if discharge_percent > 0:
            discharge_hours.append((hour_index, discharge_percent))
        peak_coverage += min(discharge_kwh, peak_loads[i])
        total_discharge_kwh += discharge_kwh
    
    return {
        'discharge_hours': discharge_hours,
        'peak_coverage': peak_coverage,
        'total_discharge_kwh': total_discharge_kwh,
        'total_peak_load': total_peak_load
    }


def compose_battery_charge_schedule(load_forecast: List[float], solar_forecast: Optional[List[float]] = None, 
                                  battery_capacity_kwh: float = 13.5, battery_efficiency: float = 0.90,
                                  min_soc: float = 20.0, max_soc: float = 90.0) -> Dict[str, Any]:
    """
    Create predictive battery dispatch schedules optimized for California TOU rates.
    
    Uses existing helper functions:
    - calculate_peak_energy_requirements(): Predicts 4-9pm energy needs with efficiency losses
    - calculate_precharge_target_soc(): Calculates target SOC needed by 4pm
    
    And new modular helper functions:
    - calculate_daily_charging_schedule(): Phase 1 charging logic
    - calculate_peak_discharge_schedule(): Phase 2 discharge logic
    
    Args:
        load_forecast: 8760-hour load profile (kW)
        solar_forecast: 8760-hour solar generation forecast (kW), optional
        battery_capacity_kwh: Battery capacity (default 13.5 kWh)
        battery_efficiency: Round-trip efficiency (default 0.90)
        min_soc: Minimum SOC percentage (default 20.0)
        max_soc: Maximum SOC percentage (default 90.0)
        
    Returns:
        Dictionary with SAM-compatible schedules and validation metrics
    """
    if len(load_forecast) != 8760:
        raise ValueError(f"Load forecast must be 8760 hours, got {len(load_forecast)}")
    
    # Initialize annual schedules for SAM
    grid_charge_percent = [0.0] * 8760  # Grid charging percentages (0-100)
    discharge_percent = [0.0] * 8760    # Discharge percentages (0-100)
    
    # Validation tracking
    peak_coverage_days = 0
    total_grid_charging_kwh = 0.0
    total_efficiency_losses_kwh = 0.0
    
    for day in range(365):
        day_start = day * 24
        
        # Use existing helper: Calculate peak energy requirements
        peak_req = calculate_peak_energy_requirements(load_forecast, day, battery_efficiency)
        
        # Use existing helper: Calculate target SOC needed by 4pm
        target_info = calculate_precharge_target_soc(peak_req, battery_capacity_kwh, min_soc, max_soc)
        
        # Track efficiency losses
        total_efficiency_losses_kwh += peak_req['efficiency_loss_kwh']
        
        # Phase 1: Calculate charging schedule using helper function
        charging_result = calculate_daily_charging_schedule(
            day_start, peak_req['energy_to_store_kwh'], load_forecast, solar_forecast, battery_capacity_kwh
        )
        
        # Apply grid charging schedule
        for hour_index, charge_percent in charging_result['grid_charge_hours']:
            grid_charge_percent[hour_index] = charge_percent
        
        total_grid_charging_kwh += charging_result['grid_charging_kwh']
        
        # Phase 2: Calculate discharge schedule using helper function
        discharge_result = calculate_peak_discharge_schedule(
            day_start, target_info['target_soc'], min_soc, battery_capacity_kwh, load_forecast
        )
        
        # Apply discharge schedule
        for hour_index, discharge_pct in discharge_result['discharge_hours']:
            discharge_percent[hour_index] = discharge_pct
        
        # Track performance (80% coverage threshold)
        if discharge_result['peak_coverage'] >= discharge_result['total_peak_load'] * 0.8:
            peak_coverage_days += 1
    
    # Validation metrics
    validation_metrics = {
        'peak_coverage_percentage': (peak_coverage_days / 365) * 100,
        'annual_grid_charging_kwh': total_grid_charging_kwh,
        'annual_efficiency_losses_kwh': total_efficiency_losses_kwh,
        'days_processed': 365
    }
    
    return {
        'dispatch_manual_percent_gridcharge': grid_charge_percent,
        'dispatch_manual_percent_discharge': discharge_percent,
        'validation_metrics': validation_metrics
    }

def report(cfg: SimulationConfiguration, presets: SamPresetFiles, outputs: SimulationSeries, pv: Pvsamv1.Pvsamv1) -> None:
    # Load profile summary
    log_section("Load Profile (kW)")
    load = outputs.load_series_kw
    if load and len(load) == 8760:
        head, tail = safe_head_tail(load, n=24)
        print(
            f"len={len(load)}  sum={sum(load):.1f} kWh  min={min(load):.3f}  "
            f"max={max(load):.3f}  mean={np.mean(load):.3f}"
        )
        print(f"first 24 hours: {head}")
        if tail:
            print(f"last 24 hours : {tail}")
    else:
        print("No load profile available.")

    # PV generation summary (from flows)
    log_section("Solar Generation Profile (kW AC)")
    gen = outputs.solar_ac_power_series_kw
    if gen:
        head, tail = safe_head_tail(gen, n=24)
        print(
            f"len={len(gen)}  sum={sum(gen):.1f} kWh  max={max(gen):.3f} kW  "
            f"mean={np.mean(gen):.3f} kW"
        )
        print(f"first 24 hours: {head}")
        if tail:
            print(f"last 24 hours : {tail}")
    else:
        print("No PV generation available.")

    # Battery caps and power series
    log_section("Battery Power (kW)")
    pvsam = presets.photovoltaic_preset_values
    caps = {
        "batt_power_charge_max_kwac": pvsam.get("batt_power_charge_max_kwac"),
        "batt_power_discharge_max_kwac": pvsam.get("batt_power_discharge_max_kwac"),
        "batt_power_charge_max_kwdc": pvsam.get("batt_power_charge_max_kwdc"),
        "batt_power_discharge_max_kwdc": pvsam.get("batt_power_discharge_max_kwdc"),
    }
    for k, v in caps.items():
        print(f"{k} = {v}")

    # First‑day tables and plots
    print_first_day_flow_table(pv, day_index=0)
    print_first_day_soc_summary(pv, day_index=0)

    # Always save plots (do not depend on SHOW_PLOTS for saving) — show flag controls UI only
    try:
        print("[PlotDebug] Begin plot assembly for", cfg.county_slug)
        # Build series for unified helper: gross PV (DIY from weather) and used PV (flows)
        sL = outputs.solar_to_load_series_kw or []
        bL = outputs.battery_to_load_series_kw or []
        gL = outputs.grid_to_load_series_kw or []
        print("[PlotDebug] Series lengths (sL, bL, gL):", len(sL), len(bL), len(gL))
        pv_to_batt, grid_to_batt = _battery_charging_series(pv)
        print("[PlotDebug] Series lengths (pv_to_batt, grid_to_batt):", len(pv_to_batt), len(grid_to_batt))
        pv_used_series = (np.asarray(sL, dtype=float) + np.asarray(pv_to_batt, dtype=float)).tolist()
        solar_capacity, _ = get_system_capacities(pv)
        print(f"[PlotDebug] solar_capacity_kW={solar_capacity}")
        pv_gross_series = _diy_pv_from_srd(pv, float(solar_capacity))
        print("[PlotDebug] pv_gross_series len/sum:", len(pv_gross_series), sum(pv_gross_series) if pv_gross_series else 0)
        county_dir = os.path.dirname(cfg.weather_file)
        plots_path = os.path.join(county_dir, f"step9_pvsamv1_battery_plots_{cfg.county_slug}.png")
        print("[PlotDebug] plots_path:", plots_path)
        print("[PlotDebug] Calling plot_first_weeks …")
        summary = {
            "Solar size (kW)": float(solar_capacity),
            "PV gross (kWh)": float(sum(pv_gross_series)) if pv_gross_series else 0.0,
            "PV used (kWh)": float(sum(pv_used_series)),
            "Battery→Load (kWh)": float(sum(bL)),
            "Grid→Battery (kWh)": float(sum(grid_to_batt)),
        }
        plot_first_weeks(
            load_kwh=outputs.load_series_kw,
            pv_ac_kwh=pv_gross_series,
            batt_to_load_kwh=bL,
            grid_to_load_kwh=gL,
            grid_to_batt_kwh=grid_to_batt,
            pv_to_batt_kwh=pv_to_batt,
            soc_percent=outputs.state_of_charge_series_percent,
            pv_used_kwh=pv_used_series,
            summary_stats=summary,
            title=f"PySAM Dispatch — {cfg.county_slug}",
            show=False,
            save_path=plots_path,
        )
        print(f"Saved step9_pvsamv1_battery plots to: {plots_path}")
    except Exception as e:
        print(f"Plotting failed: {e}")
        traceback.print_exc()

    report_manual_dispatch_schedules(presets)


def print_first_24h_dispatch_table(dispatch_schedule: Dict[str, Any]) -> None:
    """Print the first 24 hours of the predictive dispatch schedule as a table.

    Columns:
      hour, hod, GridCharge(%) and Discharge(%).
    """
    log_section("Predictive Dispatch Schedule - First 24 Hours")
    grid = dispatch_schedule.get("dispatch_manual_percent_gridcharge", []) or []
    discharge = dispatch_schedule.get("dispatch_manual_percent_discharge", []) or []
    n = max(len(grid), len(discharge))
    if n == 0:
        print("No dispatch schedule data available.")
        return
    print("hour hod  GridCharge(%)  Discharge(%)")
    for h in range(0, min(24, n)):
        hod = h % 24
        g = grid[h] if h < len(grid) else 0
        d = discharge[h] if h < len(discharge) else 0
        try:
            g = float(g)
        except Exception:
            pass
        try:
            d = float(d)
        except Exception:
            pass
        print(f"{h:4d} {hod:3d}        {g:6.1f}         {d:6.1f}")

def save_sam_results(county: str, outputs: SimulationSeries, pv: Pvsamv1.Pvsamv1, output_file: str) -> None:
    """Save SAM simulation results in the format expected by downstream steps."""
    
    # Extract additional flow data needed for the output file
    pv_to_load, batt_to_load, grid_to_load = per_source_load_series_kw_from_model(pv)
    pv_to_batt, grid_to_batt = _battery_charging_series(pv)
    
    # Calculate derived series
    solar_battery_to_load = [s + b for s, b in zip(pv_to_load, batt_to_load)]
    total_supply = [s + b + g for s, b, g in zip(pv_to_load, batt_to_load, grid_to_load)]
    difference = [l - t for l, t in zip(outputs.load_series_kw, total_supply)]
    
    # Validate energy balance
    max_difference = max(abs(d) for d in difference)
    if max_difference > 1e-6:
        print(f"Warning: Energy balance discrepancy found in {county}. Max difference: {max_difference}")
    
    # Create output directory
    os.makedirs(os.path.dirname(output_file), exist_ok=True)
    
    # Create timestamp index
    date_range = pd.date_range(start='2018-01-01', periods=8760, freq='H')
    
    # Convert arrays to lists and validate lengths
    pv_to_batt_list = pv_to_batt.tolist() if hasattr(pv_to_batt, 'tolist') else list(pv_to_batt)
    grid_to_batt_list = grid_to_batt.tolist() if hasattr(grid_to_batt, 'tolist') else list(grid_to_batt)
    
    # Verify all arrays have correct length (8760 hours)
    data_arrays = [
        ('Load Profile', outputs.load_series_kw),
        ('System to Load', pv_to_load),
        ('Battery to Load', batt_to_load),
        ('Grid to Load', grid_to_load),
        ('System to Battery', pv_to_batt_list),
        ('Grid to Battery', grid_to_batt_list),
        ('Battery SOC', outputs.state_of_charge_series_percent),
    ]
    
    for name, data in data_arrays:
        if len(data) != 8760:
            raise ValueError(f"Data length mismatch in {county}: {name} has {len(data)} elements (expected 8760)")
    
    # Create DataFrame with the exact columns expected by step10
    df = pd.DataFrame({
        'Load Profile': outputs.load_series_kw,
        'System to Load': pv_to_load,
        'Battery to Load': batt_to_load,
        'Grid to Load': grid_to_load,
        'Solar + Battery to Load': solar_battery_to_load,
        'Total Supply': total_supply,
        'Difference': difference,
        'System to Battery': pv_to_batt_list,
        'Grid to Battery': grid_to_batt_list,
        'Battery SOC': outputs.state_of_charge_series_percent,
    }, index=date_range)
    
    # Summaries for diagnostics (helps compare with DIY PV)
    try:
        total_load = float(sum(outputs.load_series_kw))
        used_pv_gen = float(sum(outputs.solar_ac_power_series_kw))  # flows-based
        pv_to_load_sum = float(sum(pv_to_load))
        pv_to_batt_sum = float(sum(pv_to_batt_list))
        # Derive PV→Grid as remainder of PV gen after PV→Load and PV→Batt
        pv_to_grid_sum = max(0.0, used_pv_gen - (pv_to_load_sum + pv_to_batt_sum))
        batt_to_load_sum = float(sum(batt_to_load))
        grid_to_load_sum = float(sum(grid_to_load))
        grid_to_batt_sum = float(sum(grid_to_batt_list))
        # Battery SOC stats
        soc_series = outputs.state_of_charge_series_percent or []
        soc_min = min(soc_series) if soc_series else 0.0
        soc_max = max(soc_series) if soc_series else 0.0
        soc_end = soc_series[-1] if soc_series else 0.0
        # Capacities
        solar_capacity, battery_capacity = get_system_capacities(pv)
        # Gross PV AC energy from Outputs.gen if available
        try:
            out = pv.Outputs.export()
            gross_pv_gen = float(sum(out.get('gen', []))) if isinstance(out.get('gen'), list) else None
        except Exception:
            gross_pv_gen = None
        print("\n[PySAM PV Diagnostics]", county)
        print(f"  system_capacity_kW       = {solar_capacity:.3f}")
        if gross_pv_gen is not None:
            print(f"  gross_pv_gen_kWh         = {gross_pv_gen:.1f}")
        print(f"  used_pv_gen_kWh          = {used_pv_gen:.1f}")
        print(f"  pv_to_load_kWh           = {pv_to_load_sum:.1f}")
        print(f"  pv_to_batt_kWh           = {pv_to_batt_sum:.1f}")
        print(f"  pv_to_grid_kWh(derived)  = {pv_to_grid_sum:.1f}")
        print(f"  batt_to_load_kWh         = {batt_to_load_sum:.1f}")
        print(f"  grid_to_load_kWh         = {grid_to_load_sum:.1f}")
        print(f"  grid_to_batt_kWh         = {grid_to_batt_sum:.1f}")
        print(f"  total_load_kWh           = {total_load:.1f}")
        print(f"  batt_SOC[%]  min/ max/ end = {soc_min:.1f} / {soc_max:.1f} / {soc_end:.1f}")
        # Selected dispatch/export flags (best effort)
        def v(key, default=None):
            try:
                return pv.value(key)
            except Exception:
                return default
        print("  flags: export_to_grid?=", v('batt_dispatch_auto_btm_can_discharge_to_grid'))
        print("         grid_interconnection_limit_kwac=", v('grid_interconnection_limit_kwac'))
        print("         dc_ac_ratio=", v('dc_ac_ratio'))
    except Exception as _:
        pass

    # Save to CSV file
    df.to_csv(output_file)
    
    print(f"SAM results saved to: {output_file}")
    print(f"Columns written: {list(df.columns)}")


def get_system_capacities(pv: Pvsamv1.Pvsamv1) -> tuple:
    """Extract solar and battery capacities from the SAM model."""
    try:
        # Get solar capacity
        solar_capacity = float(pv.value("system_capacity"))
    except Exception:
        solar_capacity = 0.0
    
    try:
        # Get battery capacity
        battery_capacity = float(pv.value("batt_bank_installed_capacity"))
    except Exception:
        try:
            battery_capacity = float(pv.value("batt_computed_bank_capacity"))
        except Exception:
            battery_capacity = 0.0
    
    return solar_capacity, battery_capacity


def process_single_county(base_input_dir: str, base_output_dir: str, scenario: str, housing_type: str, county: str, force_recompute: bool = False) -> dict:
    """Process a single county with the PvSAMv1 battery model."""
    # Set environment variables for configuration
    county_slug = slugify_county_name(county)
    os.environ["COUNTY_NAME"] = county_slug
    # Compute canonical resource paths and set env overrides so configure() uses them
    weather_file_canon = f"{base_input_dir}/{scenario}/{housing_type}/{county_slug}/weather_TMY_{county_slug}.csv"
    load_file_canon = f"{base_input_dir}/{scenario}/{housing_type}/{county_slug}/combined_profiles_{scenario}_{county_slug}.csv"
    os.environ["WEATHER_FILE"] = weather_file_canon
    os.environ["LOAD_FILE"] = load_file_canon
    
    # Define output file path to match step10 expectations
    output_file = os.path.join(base_output_dir, scenario, housing_type, county_slug, f"sam_optimized_load_profiles_{county_slug}.csv")
    
    # Skip if output file already exists and force_recompute is False
    if not force_recompute and os.path.exists(output_file):
        print(f"Output file already exists: {output_file}. Skipping... (use force_recompute=True to rebuild)")
        # Still return capacity info if available
        try:
            # Try to extract capacity from existing results or return defaults
            return {
                "Solar Capacity (kW)": 0.0,
                "Battery Capacity (kWh)": 13.5  # Default Tesla Powerwall capacity
            }
        except Exception:
            return {"Solar Capacity (kW)": 0.0, "Battery Capacity (kWh)": 13.5}
    
    cfg = configure(scenario, county)                                 # Configuration phase
    # Log the exact files that will be used by this run
    print(f"  Using weather_file={cfg.weather_file}")
    print(f"  Using load_file={cfg.load_file}")
    presets = load_presets(cfg)                       # Presets phase
    overrides = build_runtime_overrides(cfg)          # Runtime overrides
    modules = initialize_modules()                    # Module lifecycle: create
    configure_modules(modules, presets, overrides)    # Apply + checks
    pv = modules.photovoltaic_model
    attach_resources(pv, cfg, presets)                # Weather + household load

    # Dynamically size PV capacity based on weather + load (aligned with DIY step)
    sized_capacity_kw = _compute_system_capacity_kW_from_pv_and_load(pv)
    if sized_capacity_kw > 0:
        try:
            # Set system capacity (DC) before any execution
            pv.SystemDesign.system_capacity = float(sized_capacity_kw)
            print(f"[Sizing] Set system_capacity_kW from weather+load: {sized_capacity_kw:.3f}")
        except Exception as e:
            print(f"[Sizing] Failed to set system_capacity_kW: {e}")

    # Get load forecast from attached load profile
    load_forecast = load_series_kw_from_model(pv)
    
    # Generate predictive battery dispatch schedule
    dispatch_schedule = compose_battery_charge_schedule(
        load_forecast=load_forecast,
        solar_forecast=None,  # Will be calculated after execution
        battery_capacity_kwh=overrides.battery_capacity_kwh or 13.5,
        battery_efficiency=overrides.battery_efficiency or 0.90,
        min_soc=overrides.min_soc or 20.0,
        max_soc=overrides.max_soc or 90.0
    )
    
    # Log dispatch schedule validation metrics
    log_section("Predictive Dispatch Schedule Results")
    metrics = dispatch_schedule['validation_metrics']
    print_first_24h_dispatch_table(dispatch_schedule)
    print(f"Peak coverage: {metrics['peak_coverage_percentage']:.1f}% of days")
    print(f"Annual grid charging: {metrics['annual_grid_charging_kwh']:.1f} kWh")
    print(f"Annual efficiency losses: {metrics['annual_efficiency_losses_kwh']:.1f} kWh")
    
    # Apply the dispatch schedule configuration to SAM model
    apply_dispatch_schedule(pv, dispatch_schedule, overrides)
    
    execute(pv, county_slug)                          # Execute model or raise
    outputs = extract(pv)                             # Collect outputs
    
    # Save results in format expected by step10
    save_sam_results(county, outputs, pv, output_file)
    
    # Extract system capacities for capacity tracking
    solar_capacity, battery_capacity = get_system_capacities(pv)
    
    report(cfg, presets, outputs, pv)                 # Reporting/visualization
    # Print the rendered plot path for convenience
    try:
        county_dir = os.path.dirname(cfg.weather_file)
        plots_path = os.path.join(county_dir, f"step9_pvsamv1_battery_plots_{cfg.county_slug}.png")
        if os.path.exists(plots_path):
            print(f"Saved step9_pvsamv1_battery plots to: {plots_path}")
        else:
            print(f"Plot not generated (check SHOW_PLOTS). Expected at: {plots_path}")
    except Exception:
        pass
    
    return {
        "Solar Capacity (kW)": round(solar_capacity, 2),
        "Battery Capacity (kWh)": round(battery_capacity, 2)
    }


def process(base_input_dir: str, base_output_dir: str, scenario: str, housing_type: str, counties=None, years_of_analysis: int = 1, force_recompute: bool = False):
    """
    Process PvSAMv1 battery simulation for multiple counties.
    
    This function matches the signature expected by cost_service.py.
    
    Args:
        base_input_dir: Base input directory path
        base_output_dir: Base output directory path
        scenario: Scenario name (e.g., "baseline", "heat_pump")
        housing_type: Housing type (e.g., "single-family-detached")
        counties: List of counties to process (if None, processes all available)
        years_of_analysis: Number of years to analyze (default 1)
        force_recompute: Whether to force recomputation of existing results
    """
    print(f"Running PvSAMv1 battery simulation for scenario: {scenario}")
    
    # Import required helpers to get county list if needed
    try:
        from main_helpers import get_counties, get_scenario_path
        
        # Get counties to process
        if counties is None:
            scenario_path = get_scenario_path(base_input_dir, scenario, housing_type)
            counties_to_run = get_counties(scenario_path, counties)
        else:
            counties_to_run = counties
            
    except ImportError:
        # Fallback if main_helpers not available
        if counties is None:
            print("Warning: main_helpers not available, using default county list")
            counties_to_run = ["alameda"]
        else:
            counties_to_run = counties
    
    successful_counties = []
    failed_counties = []
    capacity_dict = {}
    
    for county in counties_to_run:
        try:
            print(f"\nProcessing county: {county}")
            
            # Clean county name for file paths
            county_slug = slugify_county_name(county)
            
            # Check for required input files
            weather_file = f"{base_input_dir}/{scenario}/{housing_type}/{county_slug}/weather_TMY_{county_slug}.csv"
            load_file = f"{base_input_dir}/{scenario}/{housing_type}/{county_slug}/combined_profiles_{scenario}_{county_slug}.csv"
            print(f"  Weather: {weather_file}  exists={os.path.exists(weather_file)}")
            print(f"  Load:    {load_file}     exists={os.path.exists(load_file)}")
            
            if not os.path.exists(weather_file):
                print(f"Weather file not found: {weather_file}. Skipping...")
                failed_counties.append(county)
                continue
                
            if not os.path.exists(load_file):
                print(f"Load file not found: {load_file}. Skipping...")
                failed_counties.append(county)
                continue
            
            # Process this county and collect capacity data
            capacity_data = process_single_county(base_input_dir, base_output_dir, scenario, housing_type, county, force_recompute)
            # Store capacities keyed by slug so downstream maps (which use slugs) find them
            capacity_dict[county_slug] = capacity_data
            successful_counties.append(county)
            
        except Exception as e:
            print(f"Error processing {county}: {e}")
            failed_counties.append(county)
    
    # Save capacity data to CSV file (matching original step9 behavior)
    if capacity_dict:
        capital_costs_folder = f"{base_input_dir}/{scenario}/{housing_type}/CAPITAL_COSTS"
        os.makedirs(capital_costs_folder, exist_ok=True)
        
        capacity_df = pd.DataFrame.from_dict(capacity_dict, orient='index').rename_axis('County')
        output_csv_path = f"{capital_costs_folder}/electrified_assets.csv"
        capacity_df.to_csv(output_csv_path)
        print(f"\nCapacity data saved to: {output_csv_path}")
    else:
        print("\nNo capacity data to save.")
    
    # Summary report
    print(f"\n{'='*60}")
    print(f"PvSAMv1 Battery Simulation Summary")
    print(f"{'='*60}")
    print(f"Scenario: {scenario}")
    print(f"Housing type: {housing_type}")
    print(f"Successfully processed: {len(successful_counties)} counties")
    print(f"Failed: {len(failed_counties)} counties")
    
    if successful_counties:
        print(f"Successful counties: {', '.join(successful_counties)}")
    if failed_counties:
        print(f"Failed counties: {', '.join(failed_counties)}")
    
    return successful_counties


scenario = "baseline"
housing_type = "single-family-detached"

if __name__ == '__main__':
    # Default configuration for standalone execution
    scenario = "baseline"
    county = "alameda"
    housing_type = "single-family-detached"
    base_input_dir = "data/loadprofiles"
    base_output_dir = "data/loadprofiles"
    
    print(f"Running PvSAMv1 battery simulation for {county} county, {scenario} scenario")
    
    # Run the main processing pipeline for single county
    process_single_county(base_input_dir, base_output_dir, scenario, housing_type, county, force_recompute=True)
