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

import PySAM.Pvsamv1 as Pvsamv1
import PySAM.ResourceTools as ResourceTools


# ==========================
# Data models and structures
# ==========================


# ==========================
# Predictive dispatch functions
# ==========================

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
        return np.asarray(out.get(k, []), dtype=float).ravel()
    return arr("system_to_load"), arr("batt_to_load"), arr("grid_to_load")


def _plot_six_panel_weeks(
    load_ser: np.ndarray,
    soc_ser: np.ndarray,
    pv_ser: np.ndarray,
    pv_to_load: np.ndarray,
    batt_to_load: np.ndarray,
    grid_to_load: np.ndarray,
    min_soc_line: float | None,
    max_soc_line: float | None,
) -> None:
    """Create a single figure with 6 panels:
    Rows: Load, Battery SOC, Solar AC (PV). Col 1: First week of January. Col 2: First week of July.
    """
    week_len = 24 * 7
    first_week_start = 0
    july_start = 181 * 24  # Jan–Jun days = 181 (non-leap)

    def _slice(s: np.ndarray, start: int) -> tuple[np.ndarray, np.ndarray]:
        if s.size == 0:
            return np.array([]), np.array([])
        end = min(start + week_len, s.size)
        if start >= end:
            return np.array([]), np.array([])
        x = np.arange(end - start)
        y = s[start:end]
        return x, y

    fig, axes = plt.subplots(3, 2, figsize=(14, 9), sharex="col")

    # Top row: load breakdown by source (stacked area)
    for c, start, title in [
        (0, first_week_start, "Load Served by Source - First Week January"),
        (1, july_start, "Load Served by Source - First Week July"),
    ]:
        ax = axes[0, c]
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

    # Middle row: SOC lines (with dashed min/max SOC)
    for c, start, title in [
        (0, first_week_start, "Battery SOC - First Week January"),
        (1, july_start, "Battery SOC - First Week July"),
    ]:
        ax = axes[1, c]
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

    # Bottom row: PV AC lines
    for c, start, title in [
        (0, first_week_start, "Solar AC (PV) - First Week January"),
        (1, july_start, "Solar AC (PV) - First Week July"),
    ]:
        ax = axes[2, c]
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
    axes[2, 0].set_xlabel("Hour")
    axes[2, 1].set_xlabel("Hour")
    fig.tight_layout()
    plt.show()


# =====================
# Configuration helpers
# =====================


def build_configuration_from_environment() -> SimulationConfiguration:
    county_slug = os.environ.get("COUNTY_NAME", "alameda").lower().replace(" ", "-")
    preset_dir = os.environ.get("SAM_PRESET_DIR", "SAM_Detailed_PV_Battery")
    pvsam_json_name = os.environ.get("PVSAMV1_JSON", "untitled_pvsamv1.json")
    weather_file = os.environ.get(
        "WEATHER_FILE",
        f"data/loadprofiles/baseline/single-family-detached/{county_slug}/weather_TMY_{county_slug}.csv",
    )
    load_file = os.environ.get(
        "LOAD_FILE",
        f"data/loadprofiles/baseline/single-family-detached/{county_slug}/combined_profiles_baseline_{county_slug}.csv",
    )
    load_col = os.environ.get(
        "LOAD_COL",
        "electricity.real_and_simulated.for_typical_county_home.kwh",
    )
    show_plots = os.environ.get("SHOW_PLOTS", "1").strip() not in {"0", "false", "False"}
    try:
        weather_shift_hours = int(os.environ.get("WEATHER_SHIFT_HOURS", "8"))
    except Exception:
        weather_shift_hours = 8
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


def configure() -> SimulationConfiguration:
    cfg = build_configuration_from_environment()
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
    def parse_float(env_key: str) -> Optional[float]:
        v = os.environ.get(env_key)
        if v is None or v == "":
            return None
        try:
            return float(v)
        except Exception:
            return None

    def parse_int(env_key: str) -> Optional[int]:
        v = os.environ.get(env_key)
        if v is None or v == "":
            return None
        try:
            return int(v)
        except Exception:
            return None

    def parse_bool(env_key: str) -> Optional[bool]:
        v = os.environ.get(env_key)
        if v is None or v == "":
            return None
        return v.lower() in {"1", "true", "yes", "y"}

    return RuntimeOverrides(
        min_soc=parse_float("MIN_SOC"),
        max_soc=parse_float("MAX_SOC"),
        initial_soc=parse_float("INITIAL_SOC"),
        dispatch_mode=parse_int("DISPATCH_MODE"),
        grid_interconnection_limit_kwac=parse_float("GRID_INTERCONNECTION_LIMIT_KWAC"),
        can_export_to_grid=parse_bool("CAN_EXPORT_TO_GRID"),
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

    set_if_present("batt_minimum_SOC", overrides.min_soc)
    set_if_present("batt_maximum_SOC", overrides.max_soc)
    set_if_present("batt_initial_SOC", overrides.initial_soc)
    set_if_present("batt_dispatch_choice", overrides.dispatch_mode)
    set_if_present("grid_interconnection_limit_kwac", overrides.grid_interconnection_limit_kwac)
    set_if_present("batt_dispatch_auto_btm_can_discharge_to_grid", overrides.can_export_to_grid)


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

    # Align weather from eastern time (ET) to local time (PT) to match typical load profiles
    shift_hours = cfg.weather_shift_hours
    hourly_keys = ["dn", "df", "gh", "tdry", "tdew", "rhum", "wdir", "wspd"]
    for key in hourly_keys:
        if key in srd and isinstance(srd[key], (list, tuple)) and len(srd[key]) == 8760:
            arr = list(srd[key])
            srd[key] = [arr[(i + shift_hours) % 8760] for i in range(8760)]

    pv.SolarResource.solar_resource_data = srd
    print(f"Attached weather from: {cfg.weather_file} (shifted +{shift_hours}h for PT)")
    return True


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
    load = df[cfg.load_col].astype(float).tolist()
    if len(load) != 8760:
        raise ValueError(
            f"Research load series must be 8760 hours; got len={len(load)} at {cfg.load_file}"
        )

    pv.value("load", load)
    # Provide auxiliary arrays commonly required
    pv.value("crit_load", [0.0] * len(load))
    pv.value("batt_load_ac_forecast", load)
    print(
        f"Attached load from CSV: {cfg.load_file} (len={len(load)}, sum={sum(load):.1f} kWh)"
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


# ==========
# Execution
# ==========


def execute_pvsam(pv: Pvsamv1.Pvsamv1) -> bool:
    try:
        pv.execute(0)
        print("\nExecuted Pvsamv1 successfully.")
        return True
    except Exception as e:
        raise RuntimeError(f"Pvsamv1 execution failed: {e}")


def execute(pv: Pvsamv1.Pvsamv1) -> None:
    execute_pvsam(pv)


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

    if cfg.show_plots:
        # Build series for stacked source load and SOC/PV panels
        sL = outputs.solar_to_load_series_kw
        bL = outputs.battery_to_load_series_kw
        gL = outputs.grid_to_load_series_kw
        min_soc = read_soc_bounds(pv).min_soc
        max_soc = read_soc_bounds(pv).max_soc
        _plot_six_panel_weeks(
            np.array(outputs.load_series_kw, dtype=float),
            np.array(outputs.state_of_charge_series_percent, dtype=float),
            np.array(outputs.solar_ac_power_series_kw, dtype=float),
            np.array(sL, dtype=float),
            np.array(bL, dtype=float),
            np.array(gL, dtype=float),
            min_soc,
            max_soc,
        )

    report_manual_dispatch_schedules(presets)

def main() -> None:
    cfg = configure()                                 # Configuration phase
    presets = load_presets(cfg)                       # Presets phase
    overrides = build_runtime_overrides(cfg)          # Runtime overrides
    modules = initialize_modules()                    # Module lifecycle: create
    configure_modules(modules, presets, overrides)    # Apply + checks
    pv = modules.photovoltaic_model
    attach_resources(pv, cfg, presets)                # Weather + research load
    execute(pv)                                       # Execute model or raise
    outputs = extract(pv)                             # Collect outputs
    report(cfg, presets, outputs, pv)                 # Reporting/visualization


if __name__ == "__main__":
    main()
