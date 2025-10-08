"""
SAM Custom Dispatch Module: Economically Optimal Battery Dispatch

This module implements custom dispatch schedules for SAM's Custom Dispatch mode (mode 3)
to maximize battery utilization based on Time-of-Use electricity rates.

Key Features:
- Economic optimization based on utility rates
- Rate-based scheduling using TOU electricity rates
- Battery degradation cost considerations
- Integration with SAM PySAM models

Usage:
    from sam_custom_dispatch import CustomDispatchScheduleGenerator
    from electricity_rate_helpers import PGE_RATE_PLANS
    
    generator = CustomDispatchScheduleGenerator(PGE_RATE_PLANS['E-TOU-C'])
    charge_sched, discharge_sched, gridcharge_sched = generator.generate_custom_dispatch_schedule(
        load_profile, solar_profile
    )
"""

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from datetime import datetime, timedelta
import os
import sys
import json

# SAM Python API
import PySAM.Pvwattsv8 as pvwatts
import PySAM.Battwatts as battery_model
import PySAM.ResourceTools as tools

# Add helpers to path
sys.path.append('helpers')
from electricity_rate_helpers import PGE_RATE_PLANS


class SAMConfiguration:
    """Centralized SAM model configuration management"""
    
    def __init__(self, config_dir="SAM_configuration_with_battery_custom_dispatch"):
        self.config_dir = config_dir
        self.solar_config_file = f"{config_dir}/untitled__1__pvwattsv8.json"
        self.battery_config_file = f"{config_dir}/untitled__1__battwatts.json"
        
    def load_solar_config(self):
        """Load solar configuration from JSON file"""
        if not os.path.exists(self.solar_config_file):
            raise FileNotFoundError(f"Solar config file not found: {self.solar_config_file}")
        
        with open(self.solar_config_file, 'r') as file:
            return json.load(file)
    
    def load_battery_config(self):
        """Load battery configuration from JSON file"""
        if not os.path.exists(self.battery_config_file):
            raise FileNotFoundError(f"Battery config file not found: {self.battery_config_file}")
        
        with open(self.battery_config_file, 'r') as file:
            return json.load(file)
    
    def apply_solar_config(self, solar_model, config=None):
        """Apply solar configuration to SAM solar model"""
        if config is None:
            config = self.load_solar_config()
        
        for k, v in config.items():
            if k in ["number_inputs"]:
                continue
            solar_model.value(k, v)
    
    def apply_battery_config(self, battery_model, config=None):
        """Apply battery configuration to SAM battery model"""
        if config is None:
            config = self.load_battery_config()
        
        # Optional: print configured capacity for visibility
        conf_kwh = config.get('batt_simple_kwh', None)
        conf_kw = config.get('batt_simple_kw', None)
        print(f"DEBUG: Config batt_simple_kwh={conf_kwh}, batt_simple_kw={conf_kw}")
        
        for k, v in config.items():
            if k in ["number_inputs"]:
                continue
            battery_model.value(k, v)


class DispatchVisualizer:
    """Handles visualization of battery dispatch analysis"""
    
    def __init__(self, custom_results, dispatch_log, reference_data=None):
        self.custom_results = custom_results
        self.dispatch_log = dispatch_log
        self.reference_data = reference_data
    
    def extract_week_data(self, week_offset=0, week_hours=168):
        """Extract week data for visualization"""
        start_hour = week_offset * 24
        end_hour = start_hour + week_hours
        max_hours = min(len(self.custom_results['load_profile']), len(self.dispatch_log))
        actual_end = min(end_hour, max_hours)
        actual_start = min(start_hour, max_hours - week_hours) if max_hours >= week_hours else 0
        
        custom_week = {
            'load': self.custom_results['load_profile'][actual_start:actual_end],
            'solar': self.custom_results['system_to_load'][actual_start:actual_end],
            'battery_soc': self.custom_results['battery_soc'][actual_start:actual_end],
            'battery_discharge': self.custom_results['battery_to_load'][actual_start:actual_end],
            'grid_usage': self.custom_results['grid_to_load'][actual_start:actual_end],
            'grid_to_battery': self.custom_results['grid_to_batt'][actual_start:actual_end]
        }
        
        dispatch_week = self.dispatch_log.iloc[actual_start:actual_end]
        return custom_week, dispatch_week, actual_start
    
    def plot_soc_analysis(self, ax, custom_week, dispatch_week):
        """Plot battery SOC with dispatch events"""
        hours = range(len(custom_week['battery_soc']))
        ax.plot(hours, custom_week['battery_soc'], 'b-', linewidth=2, label='Battery SOC')
        
        # Highlight dispatch events
        charge_hours = dispatch_week[dispatch_week['charge'] > 0].index
        discharge_hours = dispatch_week[dispatch_week['discharge'] > 0].index  
        gridcharge_hours = dispatch_week[dispatch_week['gridcharge'] > 0].index
        
        if not charge_hours.empty:
            relative_charge_hours = [h - dispatch_week.index[0] for h in charge_hours]
            ax.scatter(relative_charge_hours, [custom_week['battery_soc'][h] for h in relative_charge_hours], 
                      color='green', s=20, alpha=0.7, label='Solar Charging')
        
        if not discharge_hours.empty:
            relative_discharge_hours = [h - dispatch_week.index[0] for h in discharge_hours]
            ax.scatter(relative_discharge_hours, [custom_week['battery_soc'][h] for h in relative_discharge_hours], 
                      color='red', s=20, alpha=0.7, label='Discharging')
        
        # Add SOC limits
        ax.axhline(y=20, color='red', linestyle='--', alpha=0.5, label='Min SOC (20%)')
        ax.axhline(y=80, color='orange', linestyle='--', alpha=0.5, label='Target Max SOC (80%)')
        
        ax.set_title('Battery State of Charge with Dispatch Events')
        ax.set_ylabel('SOC (%)')
        ax.set_ylim(0, 100)
        ax.legend(fontsize=8)
        ax.grid(True, alpha=0.3)
    
    def plot_energy_flows(self, ax, custom_week):
        """Plot energy flows (load, solar, battery, grid)"""
        hours = range(len(custom_week['load']))
        ax.plot(hours, custom_week['load'], 'purple', linewidth=2, label='Household Load')
        ax.plot(hours, custom_week['solar'], 'orange', linewidth=1.5, label='Solar to Load')
        ax.plot(hours, custom_week['battery_discharge'], 'red', linewidth=1.5, label='Battery to Load')
        ax.plot(hours, custom_week['grid_usage'], 'gray', linewidth=1, alpha=0.7, label='Grid to Load')
        
        ax.set_title('Energy Flows to Meet Household Load')
        ax.set_ylabel('Power (kW)')
        ax.legend(fontsize=8)
        ax.grid(True, alpha=0.3)
    
    def plot_peak_hour_analysis(self, ax, custom_week, dispatch_week):
        """Plot peak hour performance analysis"""
        hours = range(len(custom_week['load']))
        ax.plot(hours, custom_week['load'], 'purple', linewidth=2, label='Load')
        ax.plot(hours, custom_week['battery_discharge'], 'red', linewidth=2, label='Battery Output')
        
        # Highlight peak hours (4-9 PM each day)
        for day in range(len(hours) // 24 + 1):
            peak_start = day * 24 + 16
            peak_end = day * 24 + 21
            if peak_start < len(hours):
                actual_peak_end = min(peak_end, len(hours))
                ax.axvspan(peak_start, actual_peak_end, alpha=0.2, color='yellow', label='Peak Hours (4-9pm)' if day == 0 else "")
        
        ax.set_title('Peak Hour Battery Performance')
        ax.set_ylabel('Power (kW)')
        ax.legend(fontsize=8)
        ax.grid(True, alpha=0.3)
    
    def plot_dispatch_rates(self, ax, dispatch_week):
        """Plot electricity rates and dispatch decisions"""
        hours = range(len(dispatch_week))
        ax.plot(hours, dispatch_week['rate'], 'green', linewidth=1.5, label='Electricity Rate')
        
        # Show dispatch decisions as bar overlays
        charge_mask = dispatch_week['charge'] > 0
        discharge_mask = dispatch_week['discharge'] > 0
        
        if charge_mask.any():
            ax.bar(hours, dispatch_week['charge'] * 0.1, alpha=0.3, color='blue', label='Charge Decision')
        if discharge_mask.any():
            ax.bar(hours, dispatch_week['discharge'] * 0.1, alpha=0.3, color='red', label='Discharge Decision')
        
        ax.set_title('Electricity Rates and Dispatch Decisions')
        ax.set_ylabel('Rate ($/kWh)')
        ax.legend(fontsize=8)
        ax.grid(True, alpha=0.3)
    
    def create_comprehensive_analysis(self, month="January", week_offset=0):
        """Create comprehensive 8-panel visualization"""
        if self.custom_results is None:
            print("Cannot create plots without custom dispatch results")
            return
        
        custom_week, dispatch_week, actual_start = self.extract_week_data(week_offset)
        
        # Create 2x4 subplot layout
        fig, axes = plt.subplots(2, 4, figsize=(24, 10))
        week_start_day = (actual_start // 24) + 1
        fig.suptitle(f'SAM Custom Dispatch Analysis: Week Starting Day {week_start_day} ({month})', fontsize=16, fontweight='bold')
        
        # Plot 1: SOC Analysis
        self.plot_soc_analysis(axes[0, 0], custom_week, dispatch_week)
        
        # Plot 2: Energy Flows
        self.plot_energy_flows(axes[0, 1], custom_week)
        
        # Plot 3: Peak Hour Analysis  
        self.plot_peak_hour_analysis(axes[0, 2], custom_week, dispatch_week)
        
        # Plot 4: Dispatch Rates
        self.plot_dispatch_rates(axes[0, 3], dispatch_week)
        
        # Plot 5-8: Additional plots can be added here
        # For now, create simplified placeholder plots
        for i, ax in enumerate([axes[1, 0], axes[1, 1], axes[1, 2], axes[1, 3]]):
            ax.text(0.5, 0.5, f'Additional Analysis Plot {i+5}', 
                   ha='center', va='center', transform=ax.transAxes)
            ax.set_title(f'Analysis Plot {i+5}')
        
        plt.tight_layout()
        plt.show()
        
        return fig


class CustomDispatchScheduleGenerator:
    """
    Generate SAM custom dispatch schedules based on utility rates and economic optimization
    """
    
    def __init__(self, rate_plan, battery_capacity_kwh=13.5, cycle_cost_per_kwh=0.185):
        self.rate_plan = rate_plan
        self.battery_capacity = battery_capacity_kwh
        self.cycle_cost = cycle_cost_per_kwh
        self.min_soc = 10.0  # Minimum SOC (%)
        self.max_soc = 95.0  # Maximum SOC (%) - Tesla Powerwall practical max
        
    def get_hourly_rates(self, year=2018):
        """Generate 8760 hourly electricity rates for the year"""
        rates = []
        start_date = datetime(year, 1, 1)
        
        for hour in range(8760):
            timestamp = start_date + timedelta(hours=hour)
            rate = self._get_rate_for_hour(timestamp)
            rates.append(rate)
            
        return rates
    
    def _get_rate_for_hour(self, timestamp):
        """Get electricity rate for specific hour"""
        month = timestamp.month
        hour = timestamp.hour
        weekday = timestamp.weekday() < 5  # Monday=0, Sunday=6
        
        # Determine season (PG&E: Summer = May-Oct, Winter = Nov-Apr)
        is_summer = month in [5, 6, 7, 8, 9, 10]
        season = 'summer' if is_summer else 'winter'
        
        # Use weekday rates (weekend rates could be added later)
        rates = self.rate_plan[season]['weekdays']
        
        # Check if peak hours (4 PM - 9 PM)
        if hour in rates['peakHours']:
            return rates['peak']
        else:
            return rates['offPeak']
    


def _load_weather_resource_pt(weather_file: str, shift_hours: int = 8):
    """Load SAM weather resource and shift hourly arrays from UTC to PT.

    Mirrors the approach in step9_run_sam_model_for_solar_storage.py by rolling
    key hourly arrays by +8 hours (UTC -> Pacific Time) to align with local-time loads.
    """
    srd = tools.SAM_CSV_to_solar_data(weather_file)
    weather_arrays = ['dn', 'df', 'gh', 'tdry', 'tdew', 'rhum', 'wdir', 'wspd']
    for key in weather_arrays:
        if key in srd and isinstance(srd[key], (list, tuple)) and len(srd[key]) == 8760:
            arr = list(srd[key])
            srd[key] = [arr[(i + shift_hours) % 8760] for i in range(8760)]
    return srd


def initialize_solar(weather_file, load_profile, charge_schedule, discharge_schedule, gridcharge_schedule):
    """Initialize SAM solar model with configuration."""
    # Load solar resource data and shift from UTC to PT to align with local loads
    solar_resource_data = _load_weather_resource_pt(weather_file)

    # Calculate system capacity (simplified sizing heuristic)
    annual_load_kwh = sum(load_profile)
    system_capacity = annual_load_kwh / 1200  # Rough sizing: 1200 kWh/kW annually

    # === Solar Model Setup ===
    solar = pvwatts.new()
    
    # Use centralized configuration management
    sam_config = SAMConfiguration()
    sam_config.apply_solar_config(solar)

    # Set solar parameters (strict)
    solar.SolarResource.solar_resource_data = solar_resource_data
    solar.SystemDesign.system_capacity = system_capacity
    solar.Lifetime.dc_degradation = [0.5]  # 0.5% annual degradation

    return solar


def initialize_storage(weather_file, load_profile, charge_schedule, discharge_schedule, gridcharge_schedule, solar):
    """Initialize SAM battery storage model with centralized configuration."""
    battery = battery_model.from_existing(solar)

    # Use centralized configuration management
    sam_config = SAMConfiguration()
    sam_config.apply_battery_config(battery)

    # Set load profile (must exist on Battery group)
    battery.Battery.assign({'load': load_profile})

    # Ensure simple battery model is enabled so SOC and flows are computed
    try:
        battery.value('batt_simple_enable', 1)
    except Exception:
        pass

    print("DEBUG: Battwatts simple model enabled (batt_simple_enable=1)")

    # Configure a single-year analysis period explicitly for Battwatts Lifetime
    # Keep lifetime outputs disabled (single-year repeated), but set analysis_period=1
    battery.value('system_use_lifetime_output', 0)
    battery.value('analysis_period', 1)
    model_kwh = getattr(battery.Battery, 'batt_simple_kwh', None)
    model_kw = getattr(battery.Battery, 'batt_simple_kw', None)
    print(f"DEBUG: Pre-exec Battwatts capacity (input) kWh={model_kwh}, kW={model_kw}")

    return battery

def set_custom_dispatch_schedule(battery, load_profile, charge_schedule, discharge_schedule, gridcharge_schedule):
    """
    Configure custom/manual dispatch schedules with proper PV charging support.

    Implements both:
    - Manual arrays: `dispatch_manual_charge`, `dispatch_manual_discharge`,
      `dispatch_manual_gridcharge` (kW), with PV-first policy
    - Fallback `batt_custom_dispatch` (kW): positive=discharge, negative=charge

    If an input schedule looks like 0/1 flags, it is scaled by the battery's
    `batt_simple_kw` rating. If it already contains kW magnitudes (>1), the
    values are used as-is (clipped to max power if available).
    """
    # Convert schedules to plain Python lists
    discharge_list = discharge_schedule.tolist() if hasattr(discharge_schedule, 'tolist') else list(discharge_schedule)
    charge_list = charge_schedule.tolist() if hasattr(charge_schedule, 'tolist') else list(charge_schedule)
    gridcharge_list = gridcharge_schedule.tolist() if hasattr(gridcharge_schedule, 'tolist') else list(gridcharge_schedule)

    # Battery power limit (kW), if exposed by the simple model
    max_kw = None
    if hasattr(battery, 'Battery') and hasattr(battery.Battery, 'batt_simple_kw'):
        try:
            max_kw = float(battery.Battery.batt_simple_kw)
        except Exception:
            max_kw = None

    def to_kw(seq):
        vals = [float(x) if x is not None else 0.0 for x in seq]
        if not vals:
            return []
        mx = max(abs(v) for v in vals)
        # Treat as 0/1 flags if all values are within [0,1]
        if max_kw is not None and mx <= 1.0 + 1e-9:
            vals = [v * max_kw for v in vals]
        # Enforce non-negative magnitudes for manual arrays
        vals = [max(0.0, v) for v in vals]
        # Clip to max power if provided
        if max_kw is not None:
            vals = [min(max_kw, v) for v in vals]
        return vals

    n = len(load_profile)
    charge_kw = to_kw(charge_list)[:n]
    discharge_kw = to_kw(discharge_list)[:n]
    gridcharge_kw = to_kw(gridcharge_list)[:n]

    # Assign manual arrays where supported (Battwatts exposes BatteryDispatch group)
    _set_batt_param(battery, 'dispatch_manual_charge', charge_kw)
    _set_batt_param(battery, 'dispatch_manual_discharge', discharge_kw)
    _set_batt_param(battery, 'dispatch_manual_gridcharge', gridcharge_kw)
    print(f"DEBUG: manual dispatch arrays set (len={n}) | charge/discharge/gridcharge kW (first 24):\n"
          f"  charge    -> {[round(x,3) for x in charge_kw[:24]]}\n"
          f"  discharge -> {[round(x,3) for x in discharge_kw[:24]]}\n"
          f"  gridchg   -> {[round(x,3) for x in gridcharge_kw[:24]]}")

    # PV-first charging preference in manual mode
    _set_batt_param(battery, 'dispatch_manual_system_charge_first', 1)

    # Build a fallback `batt_custom_dispatch` array for simple custom mode
    sam_dispatch_array = []
    for h in range(n):
        d = discharge_kw[h] if h < len(discharge_kw) else 0.0
        c = charge_kw[h] if h < len(charge_kw) else 0.0
        g = gridcharge_kw[h] if h < len(gridcharge_kw) else 0.0
        power = d - (c + g)  # + = discharge, - = charge
        if max_kw is not None and power != 0.0:
            power = max(-max_kw, min(max_kw, power))
        sam_dispatch_array.append(power)

    # Assign fallback schedule on the Battery group when available
    if hasattr(battery, 'Battery') and hasattr(battery.Battery, 'batt_custom_dispatch'):
        battery.Battery.batt_custom_dispatch = sam_dispatch_array
        preview = sam_dispatch_array[:24]
        print(f"DEBUG: batt_custom_dispatch first 24h: {[round(x,3) for x in preview]}")

def _set_batt_param(battery, name, value):
    """Set a battery dispatch parameter if it exists on known groups.

    Returns True if set, False if the parameter was not found.
    """
    if hasattr(battery, 'Battery') and hasattr(battery.Battery, name):
        setattr(battery.Battery, name, value)
        return True
    if hasattr(battery, 'BatteryDispatch') and hasattr(battery.BatteryDispatch, name):
        setattr(battery.BatteryDispatch, name, value)
        return True
    return False


def initialize_custom_dispatch(battery, load_profile, charge_schedule, discharge_schedule, gridcharge_schedule):
    """
    Configure SAM with custom dispatch schedules (reduced console output)
    
    Solar Priority Logic Implementation:
    - charge_schedule = 1 during daylight hours signals SAM to prioritize battery charging
    - SAM's internal logic will use available solar first for battery, then for load
    - This overrides the default solar priority of load-first
    """
    # Load battery config for reference
    battery_config_file = "SAM_configuration_with_battery_custom_dispatch/untitled__1__battwatts.json"
    with open(battery_config_file, 'r') as file:
        battery_config = json.load(file)
    
    # Validate schedule lengths
    
    if not all(len(s) == len(load_profile) for s in [charge_schedule, discharge_schedule, gridcharge_schedule]):
        raise ValueError(
            "Schedule length mismatch: charge, discharge, and gridcharge schedules must "
            f"all match load_profile length ({len(load_profile)})."
        )

    print("--------------")
    cs0 = charge_schedule[:24]
    ds0 = discharge_schedule[:24]
    gs0 = gridcharge_schedule[:24]
    print("First-day schedules (hours 0–23):")
    print(f"  charge_schedule:     {[int(x) if x in (0,1) else round(float(x),3) for x in cs0]}")
    print(f"  discharge_schedule:  {[int(x) if x in (0,1) else round(float(x),3) for x in ds0]}")
    print(f"  gridcharge_schedule: {[int(x) if x in (0,1) else round(float(x),3) for x in gs0]}")
    print("--------------")
    set_custom_dispatch_schedule(battery, load_profile, charge_schedule, discharge_schedule, gridcharge_schedule)
    
    # Enable manual dispatch controls and PV-first policy per BattWatts docs
    # Prefer manual mode if supported; otherwise fall back to simple custom dispatch
    try:
        # 3 = manual dispatch (uses dispatch_manual_* arrays)
        battery.value('batt_dispatch_choice', 3)
    except Exception:
        pass
    try:
        # For Battwatts simple model: 2 = custom power commands (batt_custom_dispatch)
        battery.value('batt_simple_dispatch', 2)
    except Exception:
        pass

    # Optional flags: apply only if present on this model
    optional_flags = {
        # Allow PV charging; prevent unintended auto grid charging
        'batt_dispatch_auto_can_gridcharge': 0,
        'batt_dispatch_auto_can_charge': 1,
        'batt_dispatch_auto_btm_can_discharge_to_grid': 0,
        # Allow battery to charge from PV even if PV does not exceed load (PV-first behavior)
        'batt_dispatch_charge_only_system_exceeds_load': 0,
        # Only discharge when load exceeds PV system power
        'batt_dispatch_discharge_only_load_exceeds_system': 1,
        # In manual mode, take PV before grid for charging
        'dispatch_manual_system_charge_first': 1,
    }
    for param, val in optional_flags.items():
        _set_batt_param(battery, param, val)

    # Prefer behind-the-meter topology if supported (ensure PV can directly feed battery)
    _set_batt_param(battery, 'batt_meter_position', 0)

    # Echo effective flag values (if readable)
    def _get(name):
        if hasattr(battery, 'Battery') and hasattr(battery.Battery, name):
            return getattr(battery.Battery, name)
        if hasattr(battery, 'BatteryDispatch') and hasattr(battery.BatteryDispatch, name):
            return getattr(battery.BatteryDispatch, name)
        return None
    print("DEBUG: Dispatch flags -> "
          f"can_gridcharge={_get('batt_dispatch_auto_can_gridcharge')}, "
          f"can_charge={_get('batt_dispatch_auto_can_charge')}, "
          f"btm_discharge_to_grid={_get('batt_dispatch_auto_btm_can_discharge_to_grid')}, "
          f"charge_only_if_pv_exceeds_load={_get('batt_dispatch_charge_only_system_exceeds_load')}, "
          f"discharge_only_if_load_exceeds_system={_get('batt_dispatch_discharge_only_load_exceeds_system')}, "
          f"system_charge_first={_get('dispatch_manual_system_charge_first')}, "
          f"simple_dispatch_mode={_get('batt_simple_dispatch')}")
    
    # done


def _solar_execute_and_export(solar):
    """Execute PVWatts model and return useful outputs (strict).

    Requires 'ac' and 'ac_annual' to be present in Outputs; no silent fallbacks.
    """
    solar.execute(0)
    solar_outputs = solar.Outputs.export()

    if 'ac' not in solar_outputs or 'ac_annual' not in solar_outputs:
        available = sorted(list(solar_outputs.keys()))
        raise KeyError(
            "PVWatts outputs missing required keys 'ac' and/or 'ac_annual'. "
            f"Available keys: {available}"
        )

    solar_ac = solar_outputs['ac']
    solar_ac_annual = solar_outputs['ac_annual']

    first24 = [round(float(x), 3) for x in (solar_ac[:24] if hasattr(solar_ac, '__len__') else [])]

    print("DEBUG: Solar model outputs available:")
    print(f"  keys={sorted(list(solar_outputs.keys()))}")
    print(f"  ac_annual={solar_ac_annual}")
    if first24:
        print(f"  solar_ac first 24 hours: {first24}")

    return solar_outputs, solar_ac, solar_ac_annual


def _export_battery_inputs(batt):
    """Export battery inputs as a nested dict, excluding the Outputs group."""
    data = batt.export()
    return {k: v for k, v in data.items() if k != 'Outputs'}


def _pretty_val(v, max_len=40):
    """Format lists/arrays compactly for console printing."""
    def is_seq(x):
        return isinstance(x, (list, tuple))

    try:
        vv = np.asarray(v).tolist()
    except Exception:
        vv = list(v) if is_seq(v) else v

    if is_seq(vv) and len(vv) > max_len:
        return f"list(len={len(vv)}) head={vv[:5]} ... tail={vv[-5:]}"
    return vv


def _print_battery_props(label, props):
    """Pretty-print nested battery properties (inputs only)."""
    print(f"DEBUG: {label}")
    for grp in sorted(props.keys()):
        print(f"  [{grp}]")
        for k in sorted(props[grp].keys()):
            print(f"    {k}: {_pretty_val(props[grp][k])}")


def _diff_battery_props(before, after, rtol=1e-9, atol=1e-12):
    """Return list of (group, key, before, after) for changed input properties."""
    diffs = []
    all_grps = sorted(set(before.keys()) | set(after.keys()))
    for grp in all_grps:
        b = before.get(grp, {})
        a = after.get(grp, {})
        keys = sorted(set(b.keys()) | set(a.keys()))
        for k in keys:
            bv = b.get(k, None)
            av = a.get(k, None)
            if bv is None and av is None:
                continue
            b_arr = np.asarray(bv) if bv is not None else None
            a_arr = np.asarray(av) if av is not None else None
            if (b_arr is not None) and (a_arr is not None):
                try:
                    equal = np.array_equal(b_arr, a_arr) or np.allclose(b_arr, a_arr, rtol=rtol, atol=atol)
                except Exception:
                    equal = (bv == av)
            else:
                equal = (bv == av)
            if not equal:
                diffs.append((grp, k, _pretty_val(bv), _pretty_val(av)))
    return diffs


def _execute_battery_quiet(battery):
    """Execute battery model without verbose before/after logs."""
    battery.execute(0)


def _to_hourly_kwh(solar_ac, annual_kwh=None):
    """Return hourly PV energy in kWh from PVWatts AC output (auto-units).

    Heuristic: choose scale 1.0 or 1/1000 so that sum matches annual_kwh
    when provided; otherwise, use 1/1000 if p95(ac) > 100 (likely Wh/W).
    """
    arr = np.asarray(solar_ac, dtype=float).ravel()
    if arr.size == 0:
        return arr
    cands = [1.0, 1.0 / 1000.0]
    if annual_kwh is not None:
        try:
            annual_kwh = float(annual_kwh)
        except Exception:
            annual_kwh = None
    if annual_kwh is not None and np.isfinite(annual_kwh) and annual_kwh > 0:
        sums = [float(np.nansum(arr * s)) for s in cands]
        errs = [abs(s - annual_kwh) for s in sums]
        scale = cands[int(np.argmin(errs))]
        return arr * scale
    # Fallback heuristic
    try:
        p95 = float(np.nanpercentile(arr, 95))
    except Exception:
        p95 = np.nan
    scale = 1.0 / 1000.0 if (np.isfinite(p95) and p95 > 100.0) else 1.0
    return arr * scale


def _log_hour_of_day_solar_breakdown(solar_ac, solar_ac_annual, battery):
    """Print average kWh by hour-of-day for solar and its allocation.

    Columns per hour-of-day (0..23):
    - Solar_kWh: average PV AC per hour-of-day
    - PV->Batt, PV->Load, PV->Grid: average allocations
    - BattFraction: PV->Batt / Solar_kWh (0 if Solar_kWh==0)
    """
    # Normalize PV AC to kWh to align with battery flow units
    ac = _to_hourly_kwh(solar_ac, solar_ac_annual)
    try:
        bout = battery.Outputs.export()
    except Exception:
        bout = {}
    s2b = np.asarray(bout.get('system_to_batt', []), dtype=float).ravel()
    s2l = np.asarray(bout.get('system_to_load', []), dtype=float).ravel()
    s2g = np.asarray(bout.get('system_to_grid', []), dtype=float).ravel()

    n = min(ac.size if ac.size else 0, s2b.size if s2b.size else 0, s2l.size if s2l.size else 0, s2g.size if s2g.size else 0)
    if n == 0:
        print("DEBUG: Hour-of-day solar breakdown unavailable (missing arrays).")
        return
    # Attempt to include hourly load (kW average over the hour)
    try:
        load_series = np.asarray(getattr(battery.Battery, 'load', []), dtype=float).ravel()
    except Exception:
        load_series = np.array([])

    # Constrain all arrays to a common length, including load if present
    if load_series.size:
        n = min(n, load_series.size)
    ac = ac[:n]; s2b = s2b[:n]; s2l = s2l[:n]; s2g = s2g[:n]
    if load_series.size:
        load_series = load_series[:n]

    idx = np.arange(n)

    def hod_avg(arr):
        return np.array([float(np.mean(arr[idx % 24 == h])) if np.any(idx % 24 == h) else 0.0 for h in range(24)])

    ac_h = hod_avg(ac)
    s2b_h = hod_avg(s2b)
    s2l_h = hod_avg(s2l)
    s2g_h = hod_avg(s2g)
    load_h = hod_avg(load_series) if load_series.size else np.zeros(24)

    print("\nDEBUG: Hour-of-day solar breakdown (average kWh per hour across the year):")
    # Note: Load is reported as average kW for the hour (kWh/h)
    print("hod  Solar_kWh  Load_kW  PV->Batt  PV->Load  PV->Grid  BattFraction")
    for h in range(24):
        solar = ac_h[h]
        load_kw = load_h[h]
        batt = s2b_h[h]
        pvload = s2l_h[h]
        grid = s2g_h[h]
        frac = (batt / solar) if solar > 1e-12 else 0.0
        print(f"{h:3d}  {solar:9.3f}  {load_kw:8.3f}  {batt:8.3f}  {pvload:8.3f}  {grid:8.3f}  {frac:12.3f}")

    resid = ac_h - (s2b_h + s2l_h + s2g_h)
    print(f"DEBUG: Avg identity residual |solar - (PV->Batt+PV->Load+PV->Grid)|: mean={np.mean(np.abs(resid)):.4f} kWh")


def _log_first_day_pv_allocation(solar_ac, solar_ac_annual, battery, day_index=0):
    """Print first 24 hours of PV vs allocation to Batt/Load/Grid.

    Shows a direct, hour-by-hour table for the selected day to validate
    that PV is being consumed by battery charging (and/or load), and how
    much, if any, is exported to grid.
    """
    # Normalize PV AC to kWh for hour-by-hour comparison
    ac = _to_hourly_kwh(solar_ac, solar_ac_annual)
    try:
        bout = battery.Outputs.export()
    except Exception:
        bout = {}
    s2b = np.asarray(bout.get('system_to_batt', []), dtype=float).ravel()
    s2l = np.asarray(bout.get('system_to_load', []), dtype=float).ravel()
    s2g = np.asarray(bout.get('system_to_grid', []), dtype=float).ravel()

    n = min(ac.size if ac.size else 0, s2b.size if s2b.size else 0, s2l.size if s2l.size else 0, s2g.size if s2g.size else 0)
    if n == 0:
        print("DEBUG: First-day PV allocation table unavailable (missing arrays).")
        return

    start = day_index * 24
    end = min(start + 24, n)
    print("\nDEBUG: First 24-hour PV allocation (kWh per hour):")
    print("hour hod   PV(kWh)  PV->Batt  PV->Load  PV->Grid   Residual")
    for h in range(start, end):
        hod = h % 24
        pv = ac[h]
        to_batt = s2b[h]
        to_load = s2l[h]
        to_grid = s2g[h]
        resid = pv - (to_batt + to_load + to_grid)
        print(f"{h:4d} {hod:3d}  {pv:8.3f}  {to_batt:8.3f}  {to_load:8.3f}  {to_grid:8.3f}  {resid:9.3f}")


def run_sam_simulation(solar, battery):
    """Run PVWatts and Battwatts, log key debug info, and return results.

    Returns a dict with hourly flows, SOC, capacities, and solar outputs.
    """
    # 1) Execute solar and capture outputs
    solar_outputs, solar_ac, solar_ac_annual = _solar_execute_and_export(solar)
    solar_ac_kwh = _to_hourly_kwh(solar_ac, solar_ac_annual)

    # 2) Execute battery quietly (no verbose input dumps)
    _execute_battery_quiet(battery)

    # 3) Build results payload strictly from what's actually present
    batt_out = battery.Outputs.export()
    print(f"DEBUG: Battery outputs available keys: {sorted(list(batt_out.keys()))}")

    # Ensure load profile attribute exists
    if not hasattr(battery, 'Battery') or not hasattr(battery.Battery, 'load'):
        raise AttributeError("Battery.Battery.load is not set; load profile missing from model inputs")

    results = {
        'load_profile': battery.Battery.load,
        'solar_capacity': solar.SystemDesign.system_capacity,
        'solar_outputs': solar_outputs,
        'solar_ac': solar_ac,
        'solar_ac_annual': solar_ac_annual,
        'solar_ac_kwh': solar_ac_kwh,
    }

    # Include flows only if Battwatts provided them
    flow_keys = ['system_to_load', 'batt_to_load', 'grid_to_load', 'grid_to_batt', 'system_to_batt', 'system_to_grid']
    flows_available = all(k in batt_out for k in flow_keys)
    results['flows_available'] = bool(flows_available)
    if flows_available:
        for k in flow_keys:
            results[
                'battery_to_load' if k == 'batt_to_load' else k
            ] = batt_out[k]

    # Include SOC and capacity if present
    if 'batt_SOC' in batt_out:
        results['battery_soc'] = batt_out['batt_SOC']
    if 'batt_bank_installed_capacity' in batt_out:
        results['battery_capacity'] = batt_out['batt_bank_installed_capacity']

    # 4) Solar utilization diagnostics
    #    a) Hour-of-day averages (yearwide)
    _log_hour_of_day_solar_breakdown(solar_ac, solar_ac_annual, battery)
    #    b) First-day hour-by-hour PV vs allocation
    _log_first_day_pv_allocation(solar_ac, solar_ac_annual, battery, day_index=0)

    # Optional: quick preview of first day's PV in kWh
    first24_kwh = [round(float(x), 3) for x in (solar_ac_kwh[:24] if hasattr(solar_ac_kwh, '__len__') else [])]
    print(f"DEBUG: solar_ac first 24 hours (kWh): {first24_kwh}")

    return results


def run_sam_with_custom_dispatch(weather_file, load_profile, charge_schedule, discharge_schedule, gridcharge_schedule):
    """
    Run SAM with custom dispatch schedule (strict).

    Any missing attributes or configuration errors will raise exceptions.
    """
    solar = initialize_solar(weather_file, load_profile, charge_schedule, discharge_schedule, gridcharge_schedule)
    battery = initialize_storage(weather_file, load_profile, charge_schedule, discharge_schedule, gridcharge_schedule, solar)
    initialize_custom_dispatch(battery, load_profile, charge_schedule, discharge_schedule, gridcharge_schedule)
    return run_sam_simulation(solar, battery)


def _estimate_soc_series(charge_kw, discharge_kw, gridcharge_kw, capacity_kwh, initial_soc=50.0,
                         charge_eff=0.95, discharge_eff=0.95):
    """Estimate SOC series from dispatch schedules and battery capacity.

    This is a deterministic estimate based on commanded charge/discharge magnitudes and does
    not represent SAM's internal physics. Use only when SAM does not expose batt_SOC.
    """
    n = len(discharge_kw)
    soc = np.zeros(n)
    energy = max(0.0, min(capacity_kwh, (initial_soc / 100.0) * capacity_kwh))
    for h in range(n):
        ch = float(charge_kw[h]) if h < len(charge_kw) else 0.0
        dc = float(discharge_kw[h]) if h < len(discharge_kw) else 0.0
        gc = float(gridcharge_kw[h]) if h < len(gridcharge_kw) else 0.0
        # kWh added/removed in this hour (assuming 1h timestep)
        energy += (ch + gc) * charge_eff
        energy -= (dc / max(discharge_eff, 1e-6))
        energy = max(0.0, min(capacity_kwh, energy))
        soc[h] = 100.0 * (energy / capacity_kwh) if capacity_kwh > 0 else 0.0
    return soc


def plot_estimated_soc_one_day(charge_schedule, discharge_schedule, gridcharge_schedule,
                               capacity_kwh, day_index=0,
                               title_prefix="Estimated Battery SOC (from schedules) - Day"):
    start = day_index * 24
    end = start + 24
    soc_series = _estimate_soc_series(charge_schedule, discharge_schedule, gridcharge_schedule,
                                      capacity_kwh=capacity_kwh, initial_soc=50.0)
    soc_day = soc_series[start:end]
    hours = range(len(soc_day))
    plt.figure(figsize=(10, 4))
    plt.plot(hours, soc_day, 'b-', linewidth=2)
    plt.title(f"{title_prefix} {day_index + 1}")
    plt.ylabel('SOC (%)')
    plt.xlabel('Hour')
    plt.grid(True, alpha=0.3)
    plt.tight_layout()


## PVSAMv1 helper functions removed to avoid confusion; this module uses Battwatts.


def log_first_day_power_flows(custom_results, charge_schedule, discharge_schedule, gridcharge_schedule, day_index=0):
    """
    Print a concise, hour-by-hour power flow summary for the first 24 hours
    of the selected day to trace how energy moves among PV, battery, grid, and load.
    """
    start = day_index * 24
    end = min(start + 24, len(custom_results['battery_soc']))
    print("\nDEBUG: First 24-hour power flow breakdown (kW where applicable):")
    print("hour hod  cmdC cmdD cmdG   Load   PV->Load  PV->Batt  Grid->Load  Grid->Batt  Batt->Load  SOC(%)")
    for h in range(start, end):
        hod = h % 24
        cmdC = charge_schedule[h] if h < len(charge_schedule) else 0
        cmdD = discharge_schedule[h] if h < len(discharge_schedule) else 0
        cmdG = gridcharge_schedule[h] if h < len(gridcharge_schedule) else 0
        load_val = float(custom_results['load_profile'][h]) if h < len(custom_results['load_profile']) else 0.0
        pv_to_load = float(custom_results['system_to_load'][h]) if h < len(custom_results['system_to_load']) else 0.0
        pv_to_batt = float(custom_results['system_to_batt'][h]) if h < len(custom_results['system_to_batt']) else 0.0
        grid_to_load = float(custom_results['grid_to_load'][h]) if h < len(custom_results['grid_to_load']) else 0.0
        grid_to_batt = float(custom_results['grid_to_batt'][h]) if h < len(custom_results['grid_to_batt']) else 0.0
        batt_to_load = float(custom_results['battery_to_load'][h]) if h < len(custom_results['battery_to_load']) else 0.0
        soc = float(custom_results['battery_soc'][h]) if h < len(custom_results['battery_soc']) else 0.0
        print(f"{h:4d} {hod:3d}  {cmdC:4.2f} {cmdD:4.2f} {cmdG:4.2f}  {load_val:7.3f}  {pv_to_load:7.3f}  {pv_to_batt:7.3f}  {grid_to_load:9.3f}  {grid_to_batt:9.3f}  {batt_to_load:9.3f}  {soc:6.3f}")


def plot_soc_one_day(custom_results, dispatch_log, day_index=0, title_prefix="Battery SOC with Dispatch Events - Day"):
    """
    Plot a single 24-hour period for SOC with dispatch event markers (charge/discharge) and peak shading.
    """
    start = day_index * 24
    end = min(start + 24, len(custom_results['battery_soc']))
    hours = range(end - start)

    soc = custom_results['battery_soc'][start:end]
    sublog = dispatch_log.iloc[start:end]

    plt.figure(figsize=(14, 4))
    plt.title(f"{title_prefix} {day_index + 1}")
    plt.plot(hours, soc, 'b-', linewidth=2, label='Battery SOC')

    # Mark charge/discharge events
    charge_hours = [i for i, v in enumerate(sublog['charge']) if v > 0]
    discharge_hours = [i for i, v in enumerate(sublog['discharge']) if v > 0]
    for h in charge_hours:
        plt.axvline(x=h, color='green', alpha=0.25, linewidth=0.8)
    for h in discharge_hours:
        plt.axvline(x=h, color='red', alpha=0.25, linewidth=0.8)

    # Peak window shading (4–9pm)
    peak_start = 16
    peak_end = 21
    if peak_start < (end - start):
        plt.axvspan(peak_start, min(peak_end, end - start), alpha=0.2, color='yellow', label='Peak 4–9pm')

    plt.axhline(y=20, color='red', linestyle='--', alpha=0.5, label='Min SOC 20%')
    plt.axhline(y=80, color='orange', linestyle='--', alpha=0.5, label='Max SOC 80%')
    plt.ylabel('SOC (%)')
    plt.xlabel('Hour of Day')
    plt.xlim(0, end - start - 1)
    plt.legend()
    plt.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.show()


def generate_simple_precharge_schedule(load_profile, precharge_hours=24, target_soc=90.0):
    """
    Build a very simple custom dispatch schedule that forces charging for a given
    number of hours (default: first 24 hours). Intended for diagnostics to see if
    SOC can reach a high value (e.g., 90%).

    Notes:
    - SAM's Battwatts honors SOC limits; to reach `target_soc`, ensure the model's
      maximum SOC is >= target_soc (e.g., set batt_maximum_SOC to 90 or 100).
    - With custom dispatch in simple mode, SAM will source charging from PV and/or
      grid (if grid charging is enabled). Our initializer sets
      batt_dispatch_auto_can_gridcharge = 0 so grid charging is not allowed.

    Returns:
      (charge_schedule, discharge_schedule, gridcharge_schedule) as arrays of 0/1.
    """
    hours = len(load_profile)
    charge_schedule = np.zeros(hours)
    discharge_schedule = np.zeros(hours)
    gridcharge_schedule = np.zeros(hours)

    # Force charge for the first `precharge_hours` (cap to available hours)
    end = min(precharge_hours, hours)
    charge_schedule[:end] = 1.0
    gridcharge_schedule[:end] = 1.0  # Redundant for our converter, but explicit

    return charge_schedule, discharge_schedule, gridcharge_schedule


def get_daily_peak_window_energy(load_profile, day_index, peak_start_hour=16, peak_end_hour=21):
    """
    Compute total kWh load for a given day within the peak window.

    Args:
        load_profile: Sequence of hourly load (kWh) values (length ~8760).
        day_index: Zero-based day index (0=Jan 1).
        peak_start_hour: Start hour (0-23) of the peak window (inclusive). Default 16 (4 PM).
        peak_end_hour: End hour (0-24) of the peak window (exclusive). Default 21 (9 PM).

    Returns:
        Float total kWh for the specified day's peak window. Handles partial last day safely.
    """
    hours = len(load_profile)
    day_start = day_index * 24
    if day_start >= hours:
        return 0.0
    start = min(day_start + peak_start_hour, hours)
    end = min(day_start + peak_end_hour, hours)
    if start >= end:
        return 0.0
    return float(np.sum(load_profile[start:end]))


def get_all_daily_peak_window_energy(load_profile, peak_start_hour=16, peak_end_hour=21):
    """
    Compute total kWh load for every day within the peak window.

    Args:
        load_profile: Sequence of hourly load (kWh) values (length ~8760).
        peak_start_hour: Start hour (0-23) inclusive. Default 16.
        peak_end_hour: End hour (0-24) exclusive. Default 21.

    Returns:
        List of daily totals (float) for each day present in the load_profile.
    """
    hours = len(load_profile)
    n_days = (hours + 23) // 24
    return [get_daily_peak_window_energy(load_profile, d, peak_start_hour, peak_end_hour) for d in range(n_days)]


def generate_peak_window_discharge_schedule(load_profile, peak_start_hour=16, peak_end_hour=21):
    """
    Generate a simple schedule that:
    - Discharges during the daily peak window (default 4–9pm)
    - Charges from grid during all other hours

    This is intended to test whether the battery can meet daily peak-window
    energy needs when allowed to charge the rest of the day.

    Returns:
      (charge_schedule, discharge_schedule, gridcharge_schedule)
    """
    hours = len(load_profile)
    charge = np.zeros(hours)
    discharge = np.zeros(hours)
    gridcharge = np.zeros(hours)

    for h in range(hours):
        hod = h % 24
        if peak_start_hour <= hod < peak_end_hour:
            discharge[h] = 1.0
        else:
            charge[h] = 1.0
            gridcharge[h] = 1.0

    return charge, discharge, gridcharge


## Note: Removed previously experimental solar-to-battery-first load manipulation
## to preserve fidelity of the load profile.


def generate_solar_priority_battery_schedule(load_profile, solar_profile, peak_start_hour=16, peak_end_hour=21):
    """
    Generate a schedule using clear time-based priorities:
    - Peak hours (4-9 PM): Discharge household load from battery (priority)
    - Daylight hours (6 AM - 6 PM, excluding peak): Charge from solar (PV-first), even if PV <= load
      This may shift some mid‑day load to the grid to prepare for peak discharge.
    - Overnight hours: No battery activity (grid charging disabled)
    
    Logic:
    1. Peak period discharge takes absolute priority over charging
    2. During non-peak daylight: charge with (solar - household_load) 
    3. Overnight: battery idle (grid charging disabled)
    4. Battery relies entirely on solar for replenishment
    
    Args:
        load_profile: Hourly household electricity demand (kW)
        solar_profile: Hourly solar generation available (kW)
        
    Returns:
      (charge_schedule, discharge_schedule, gridcharge_schedule)
    """
    hours = len(load_profile)
    charge = np.zeros(hours)
    discharge = np.zeros(hours)
    gridcharge = np.zeros(hours)
    
    # Validate that we have real solar data matching load data length
    if len(solar_profile) != hours:
        raise ValueError(f"Solar profile length ({len(solar_profile)}) must match load profile length ({hours}).")
    
    for h in range(hours):
        hod = h % 24
        household_load = load_profile[h]
        solar_available = solar_profile[h]
        
        if peak_start_hour <= hod < peak_end_hour:
            # Peak hours: discharge takes priority - serve household load from battery
            discharge[h] = household_load
            
        elif 6 <= hod < 18:  # Daylight hours (6 AM - 6 PM), excluding peak hours
            # PV-first charging: request charging during solar hours regardless of "excess" status.
            # Magnitude is treated as a flag; will be scaled to battery kW elsewhere.
            charge[h] = 1.0
            
        else:
            # Overnight hours: no grid charging allowed
            charge[h] = 0.0  # No charging during overnight
            gridcharge[h] = 0.0  # Grid charging disabled
    
    return charge, discharge, gridcharge


def generate_targeted_daily_peak_discharge_schedule(
    load_profile,
    peak_start_hour=16,
    peak_end_hour=21,
    max_discharge_kw=5.0,
    return_targets=False,
):
    """
    Generate a schedule that attempts to discharge only enough hours within
    the daily peak window to meet that day's 4–9pm energy needs, assuming
    a maximum discharge power (kW) constraint.

    Behavior:
    - For each day, compute total peak-window kWh via
      get_daily_peak_window_energy (4–9pm by default).
    - Compute required discharge hours = ceil(peak_kwh / max_discharge_kw).
    - Mark only the first `required hours` within the window as discharge (1),
      leave remaining peak-window hours neutral (0). Outside the window, charge
      from grid (1) to prepare for the next day.

    Notes:
    - This is an approximation; Battwatts simple custom dispatch uses on/off
      signals, and SAM enforces battery power and SOC constraints during execution.
    - Ensure SOC limits and capacity allow meeting the target.

    Args:
      load_profile: hourly kWh loads
      peak_start_hour: inclusive start of peak window (default 16)
      peak_end_hour: exclusive end of peak window (default 21)
      max_discharge_kw: assumed battery discharge power limit per hour
      return_targets: if True, also return list of peak-window energy targets

    Returns:
      (charge_schedule, discharge_schedule, gridcharge_schedule[, daily_targets])
    """
    hours = len(load_profile)
    charge = np.zeros(hours)
    discharge = np.zeros(hours)
    gridcharge = np.zeros(hours)

    daily_targets = get_all_daily_peak_window_energy(
        load_profile, peak_start_hour=peak_start_hour, peak_end_hour=peak_end_hour
    )

    n_days = (hours + 23) // 24
    window_len = max(0, peak_end_hour - peak_start_hour)

    for day in range(n_days):
        day_start = day * 24
        if day_start >= hours:
            break
        # Non-peak hours: charge from grid
        for h in range(day_start, min(day_start + 24, hours)):
            hod = h % 24
            if not (peak_start_hour <= hod < peak_end_hour):
                charge[h] = 1.0
                gridcharge[h] = 1.0

        # Peak window: select minimal number of hours to cover target energy
        peak_target_kwh = daily_targets[day] if day < len(daily_targets) else 0.0
        req_hours = window_len if max_discharge_kw <= 0 else int(np.ceil(peak_target_kwh / max_discharge_kw))
        req_hours = max(0, min(req_hours, window_len))

        peak_start = min(day_start + peak_start_hour, hours)
        peak_end = min(day_start + peak_end_hour, hours)
        # Choose the earliest hours in the window; change policy if desired
        for h in range(peak_start, min(peak_start + req_hours, peak_end)):
            discharge[h] = 1.0

    if return_targets:
        return charge, discharge, gridcharge, daily_targets
    return charge, discharge, gridcharge


def compare_dispatch_results(reference_data, custom_data, dispatch_log):
    """
    Compare reference SAM results with custom dispatch results
    """
    if reference_data is None or custom_data is None:
        print("Cannot compare results - missing data")
        return
    
    # Reduced verbosity; concise table still printed below
    
    # Convert custom results to series for easier analysis
    def safe_convert_to_list(data):
        """Safely convert data to list for analysis"""
        if isinstance(data, (list, tuple)):
            return list(data)
        elif hasattr(data, 'tolist'):
            return data.tolist()
        elif hasattr(data, '__iter__'):
            return list(data)
        else:
            return [data] * 8760  # Fallback for scalar values
    
    custom_df = pd.DataFrame({
        'Load Profile': safe_convert_to_list(custom_data['load_profile']),
        'System to Load': safe_convert_to_list(custom_data['system_to_load']),
        'Battery to Load': safe_convert_to_list(custom_data['battery_to_load']),
        'Grid to Load': safe_convert_to_list(custom_data['grid_to_load']),
        'Battery SOC': safe_convert_to_list(custom_data['battery_soc']),
        'Grid to Battery': safe_convert_to_list(custom_data['grid_to_batt'])
    })
    
    # Annual summaries
    ref_stats = {
        'grid_kwh': reference_data['Grid to Load'].sum(),
        'battery_discharge_kwh': reference_data['Battery to Load'].sum(),
        'battery_charge_kwh': (reference_data['System to Battery'] + reference_data['Grid to Battery']).sum(),
        'min_soc': reference_data['Battery SOC'].min(),
        'avg_soc': reference_data['Battery SOC'].mean(),
        'solar_kwh': reference_data['System to Load'].sum()
    }
    
    # Safely calculate custom stats
    try:
        system_to_batt_data = safe_convert_to_list(custom_data['system_to_batt'])
        custom_battery_charge = custom_df['Grid to Battery'].sum() + sum(system_to_batt_data)
    except Exception as e:
        print(f"DEBUG: Error calculating battery charge: {e}")
        custom_battery_charge = custom_df['Grid to Battery'].sum()
    
    custom_stats = {
        'grid_kwh': custom_df['Grid to Load'].sum(),
        'battery_discharge_kwh': custom_df['Battery to Load'].sum(),
        'battery_charge_kwh': custom_battery_charge,
        'min_soc': custom_df['Battery SOC'].min(),
        'avg_soc': custom_df['Battery SOC'].mean(),
        'solar_kwh': custom_df['System to Load'].sum()
    }
    
    print(f"{'Metric':<25} {'Reference':<15} {'Custom':<15} {'Difference':<15}")
    print("-" * 70)
    
    metrics = [
        ('Grid Usage (kWh)', 'grid_kwh'),
        ('Battery Discharge (kWh)', 'battery_discharge_kwh'),
        ('Battery Charge (kWh)', 'battery_charge_kwh'),
        ('Min SOC (%)', 'min_soc'),
        ('Avg SOC (%)', 'avg_soc'),
        ('Solar Production (kWh)', 'solar_kwh')
    ]
    
    for label, key in metrics:
        ref_val = ref_stats[key]
        custom_val = custom_stats[key]
        diff = custom_val - ref_val
        
        if 'kwh' in key.lower():
            print(f"{label:<25} {ref_val:<15.0f} {custom_val:<15.0f} {diff:<15.0f}")
        else:
            print(f"{label:<25} {ref_val:<15.1f} {custom_val:<15.1f} {diff:<15.1f}")
    
    # Calculate percentage improvements (with safety checks)
    grid_reduction_pct = 0
    battery_increase_pct = 0
    
    try:
        if ref_stats['grid_kwh'] > 0:
            grid_reduction_pct = (ref_stats['grid_kwh'] - custom_stats['grid_kwh']) / ref_stats['grid_kwh'] * 100
        
        if ref_stats['battery_discharge_kwh'] > 0:
            battery_increase_pct = (custom_stats['battery_discharge_kwh'] - ref_stats['battery_discharge_kwh']) / ref_stats['battery_discharge_kwh'] * 100
    except Exception as e:
        print(f"DEBUG: Error calculating percentages: {e}")
    
    print("\nKey Improvements:")
    print(f"Grid usage reduction: {grid_reduction_pct:.1f}%")
    print(f"Battery utilization increase: {battery_increase_pct:.1f}%")
    
    return {
        'reference_stats': ref_stats,
        'custom_stats': custom_stats,
        'grid_reduction_pct': grid_reduction_pct,
        'battery_increase_pct': battery_increase_pct
    }


def calculate_economic_benefits(custom_results, reference_data, dispatch_log, rate_plan):
    """
    Calculate economic benefits of custom dispatch vs reference
    """
    if custom_results is None:
        print("Cannot calculate benefits without custom results")
        return None
    
    # Initialize generator to get hourly rates
    generator = CustomDispatchScheduleGenerator(rate_plan)
    hourly_rates = generator.get_hourly_rates()
    
    # Calculate costs for custom dispatch
    custom_grid_usage = custom_results['grid_to_load']
    custom_annual_cost = sum(grid * rate for grid, rate in zip(custom_grid_usage, hourly_rates))
    
    # Calculate costs for reference (if available)
    if reference_data is not None:
        ref_grid_usage = reference_data['Grid to Load'].values
        ref_annual_cost = sum(grid * rate for grid, rate in zip(ref_grid_usage, hourly_rates))
        annual_savings = ref_annual_cost - custom_annual_cost
    else:
        ref_annual_cost = None
        annual_savings = None
    
    # Calculate dispatch efficiency metrics
    total_discharge_events = (dispatch_log['discharge'] > 0).sum()
    avg_discharge_rate = dispatch_log[dispatch_log['discharge'] > 0]['rate'].mean()
    
    total_gridcharge_events = (dispatch_log['gridcharge'] > 0).sum()
    avg_gridcharge_rate = dispatch_log[dispatch_log['gridcharge'] > 0]['rate'].mean()
    
    # Rate arbitrage opportunities
    if not pd.isna(avg_discharge_rate) and not pd.isna(avg_gridcharge_rate):
        rate_spread = avg_discharge_rate - avg_gridcharge_rate
    else:
        rate_spread = 0
    
    # Reduced verbosity; keep headline numbers
    print("Economic Analysis: Custom Dispatch")
    print(f"Annual electricity cost (custom):  ${custom_annual_cost:,.2f}")
    if ref_annual_cost:
        print(f"Annual electricity cost (reference): ${ref_annual_cost:,.2f}")
        print(f"Annual savings:                    ${annual_savings:,.2f}")
        print(f"Savings percentage:                {annual_savings/ref_annual_cost*100:.1f}%")
    
    # Condensed dispatch strategy summary
    print("\nDispatch Strategy Summary:")
    print(f"Discharge hours: {total_discharge_events:,}")
    if not pd.isna(avg_discharge_rate):
        print(f"Avg discharge rate: ${avg_discharge_rate:.3f}/kWh")
    print(f"Grid charge hours: {total_gridcharge_events:,}")
    if not pd.isna(avg_gridcharge_rate):
        print(f"Avg grid charge rate: ${avg_gridcharge_rate:.3f}/kWh")
    
    if rate_spread > 0:
        print(f"Rate arbitrage spread:             ${rate_spread:.3f}/kWh")
        print(f"Cycle cost threshold:              ${generator.cycle_cost:.3f}/kWh")
        
        if avg_discharge_rate > generator.cycle_cost:
            print("Discharge strategy economically justified")
        else:
            print("Discharge rate below cycle cost threshold")
    
    return {
        'custom_annual_cost': custom_annual_cost,
        'ref_annual_cost': ref_annual_cost,
        'annual_savings': annual_savings,
        'discharge_events': total_discharge_events,
        'gridcharge_events': total_gridcharge_events,
        'avg_discharge_rate': avg_discharge_rate,
        'avg_gridcharge_rate': avg_gridcharge_rate,
        'rate_spread': rate_spread
    }


def plot_custom_dispatch_analysis(custom_results, dispatch_log, reference_data=None, month="January", week_offset=0):
    """Create comprehensive visualization using the DispatchVisualizer class"""
    visualizer = DispatchVisualizer(custom_results, dispatch_log, reference_data)
    return visualizer.create_comprehensive_analysis(month, week_offset)


# Legacy function removed - large 400+ line function replaced with DispatchVisualizer class



def plot_annual_soc_violations(dispatch_log):
    """
    Create a separate figure showing SOC violations across the full year
    """
    if dispatch_log is None or len(dispatch_log) == 0:
        print("No dispatch log available for SOC violation analysis")
        return
    
    
    # Create figure for annual analysis
    fig, axes = plt.subplots(3, 1, figsize=(16, 12))
    fig.suptitle('Annual Battery SOC Analysis: Violations & Performance', fontsize=16, fontweight='bold')
    
    # Convert hour index to day of year
    hours = len(dispatch_log)
    days = [h // 24 for h in range(hours)]
    unique_days = sorted(set(days))
    
    # 1. Daily Minimum SOC
    ax1 = axes[0]
    daily_min_soc = []
    daily_max_soc = []
    violation_days = []
    critical_days = []
    
    for day in unique_days:
        day_start = day * 24
        day_end = min((day + 1) * 24, hours)
        day_data = dispatch_log.iloc[day_start:day_end]
        
        if len(day_data) > 0:
            min_soc = day_data['soc'].min()
            max_soc = day_data['soc'].max()
            daily_min_soc.append(min_soc)
            daily_max_soc.append(max_soc)
            
            # Track violation days
            if min_soc < 15.0:
                violation_days.append(day)
            if min_soc < 10.0:
                critical_days.append(day)
        else:
            daily_min_soc.append(50.0)
            daily_max_soc.append(50.0)
    
    # Plot daily SOC range
    ax1.fill_between(unique_days, daily_min_soc, daily_max_soc, alpha=0.3, color='blue', label='Daily SOC Range')
    ax1.plot(unique_days, daily_min_soc, 'b-', linewidth=1, label='Daily Minimum SOC')
    
    # Mark violation days
    if violation_days:
        violation_min_soc = [daily_min_soc[day] for day in violation_days]
        ax1.scatter(violation_days, violation_min_soc, c='orange', s=30, alpha=0.8, label=f'Low SOC Days (<15%): {len(violation_days)}')
    
    if critical_days:
        critical_min_soc = [daily_min_soc[day] for day in critical_days]
        ax1.scatter(critical_days, critical_min_soc, c='red', s=50, alpha=0.9, label=f'Critical SOC Days (<10%): {len(critical_days)}')
    
    # Reference lines
    ax1.axhline(y=20, color='red', linestyle='--', alpha=0.7, label='Target Min SOC (20%)')
    ax1.axhline(y=15, color='orange', linestyle='--', alpha=0.5, label='Warning Level (15%)')
    ax1.axhline(y=10, color='red', linestyle='--', alpha=0.5, label='Critical Level (10%)')
    ax1.axhline(y=80, color='green', linestyle='--', alpha=0.7, label='Target Max SOC (80%)')
    
    ax1.set_title('Daily SOC Range & Violations Throughout Year', fontweight='bold')
    ax1.set_ylabel('SOC (%)')
    ax1.set_ylim(0, 100)
    ax1.legend(bbox_to_anchor=(1.05, 1), loc='upper left')
    ax1.grid(True, alpha=0.3)
    
    # 2. Monthly Violation Summary
    ax2 = axes[1]
    
    # Group violations by month
    monthly_violations = {month: {'low': 0, 'critical': 0, 'total_days': 0} for month in range(1, 13)}
    
    for day in unique_days:
        # Approximate month (assuming 365-day year)
        month = min(12, ((day * 12) // 365) + 1)
        monthly_violations[month]['total_days'] += 1
        
        if day < len(daily_min_soc):
            if daily_min_soc[day] < 15.0:
                monthly_violations[month]['low'] += 1
            if daily_min_soc[day] < 10.0:
                monthly_violations[month]['critical'] += 1
    
    months = list(monthly_violations.keys())
    low_violations = [monthly_violations[m]['low'] for m in months]
    critical_violations = [monthly_violations[m]['critical'] for m in months]
    
    width = 0.35
    x_pos = np.arange(len(months))
    
    bars1 = ax2.bar(x_pos - width/2, low_violations, width, alpha=0.7, color='orange', label='Low SOC Days (<15%)')
    bars2 = ax2.bar(x_pos + width/2, critical_violations, width, alpha=0.7, color='red', label='Critical SOC Days (<10%)')
    
    ax2.set_title('Monthly SOC Violations', fontweight='bold')
    ax2.set_xlabel('Month')
    ax2.set_ylabel('Number of Days')
    ax2.set_xticks(x_pos)
    ax2.set_xticklabels(['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
                        'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'])
    ax2.legend()
    ax2.grid(True, alpha=0.3, axis='y')
    
    # Add value labels on bars
    for bar, value in zip(bars1, low_violations):
        if value > 0:
            ax2.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.1, 
                    str(value), ha='center', va='bottom', fontsize=9)
    
    for bar, value in zip(bars2, critical_violations):
        if value > 0:
            ax2.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.1, 
                    str(value), ha='center', va='bottom', fontsize=9)
    
    # 3. SOC Distribution Histogram
    ax3 = axes[2]
    
    all_soc_values = dispatch_log['soc'].values
    
    # Create histogram
    bins = np.arange(0, 101, 5)  # 5% bins
    counts, _, patches = ax3.hist(all_soc_values, bins=bins, alpha=0.7, color='skyblue', edgecolor='black')
    
    # Color code bins by safety level
    for i, patch in enumerate(patches):
        bin_center = (bins[i] + bins[i+1]) / 2
        if bin_center < 10:
            patch.set_facecolor('red')
        elif bin_center < 15:
            patch.set_facecolor('orange')
        elif bin_center < 20:
            patch.set_facecolor('yellow')
        else:
            patch.set_facecolor('lightgreen')
    
    # Add reference lines
    ax3.axvline(x=10, color='red', linestyle='--', alpha=0.8, label='Critical (10%)')
    ax3.axvline(x=15, color='orange', linestyle='--', alpha=0.8, label='Warning (15%)')
    ax3.axvline(x=20, color='green', linestyle='--', alpha=0.8, label='Target Min (20%)')
    ax3.axvline(x=80, color='blue', linestyle='--', alpha=0.8, label='Target Max (80%)')
    
    ax3.set_title('SOC Distribution Throughout Year', fontweight='bold')
    ax3.set_xlabel('State of Charge (%)')
    ax3.set_ylabel('Hours')
    ax3.legend()
    ax3.grid(True, alpha=0.3, axis='y')
    
    # Add statistics text
    stats_text = f'''Annual SOC Statistics:
Min SOC: {all_soc_values.min():.1f}%
Max SOC: {all_soc_values.max():.1f}%
Avg SOC: {all_soc_values.mean():.1f}%
Hours <10%: {sum(1 for x in all_soc_values if x < 10)} ({sum(1 for x in all_soc_values if x < 10)/len(all_soc_values)*100:.1f}%)
Hours <15%: {sum(1 for x in all_soc_values if x < 15)} ({sum(1 for x in all_soc_values if x < 15)/len(all_soc_values)*100:.1f}%)'''
    
    ax3.text(0.98, 0.98, stats_text, transform=ax3.transAxes, fontsize=9,
            verticalalignment='top', horizontalalignment='right',
            bbox=dict(boxstyle='round', facecolor='white', alpha=0.8))
    
    plt.tight_layout()
    plt.show()
    
    # Print summary
    print(f"\nSOC Violation Summary:")
    print(f"Days <15% SOC: {len(violation_days)}/{len(unique_days)}")
    print(f"Days <10% SOC: {len(critical_days)}/{len(unique_days)}")
    
    return {
        'violation_days': violation_days,
        'critical_days': critical_days,
        'monthly_violations': monthly_violations,
        'daily_min_soc': daily_min_soc
    }

def get_raw_solar_profile(weather_file, load_profile):
    """
    Generate raw solar profile using the same method as step8_run_sam_model_for_solar_storage.py
    
    Args:
        weather_file: Path to TMY weather data file
        load_profile: Hourly load profile for system sizing
        
    Returns:
        list: Hourly solar generation profile (kW AC)
    """
    print(f"Generating raw solar profile from weather data...")
    
    try:
        import PySAM.Pvwattsv8 as pvwatts
        import PySAM.ResourceTools as tools
        
        # Load solar resource data from weather file and shift to PT to match loads
        solar_resource_data = _load_weather_resource_pt(weather_file)
        
        # Create solar model
        solar_model = pvwatts.new()
        
        # Load solar configuration
        solar_config_file = "SAM_configuration_with_battery_custom_dispatch/untitled__1__pvwattsv8.json"
        with open(solar_config_file, 'r') as file:
            solar_config = json.load(file)
            for k, v in solar_config.items():
                if k not in ["number_inputs"]:
                    try:
                        solar_model.value(k, v)
                    except:
                        pass
        
        # Set solar resource data
        solar_model.SolarResource.solar_resource_data = solar_resource_data
        
        # Calculate system capacity using proper physics-based method (same as step9)
        annual_load_kwh = sum(load_profile)
        
        # Extract global horizontal irradiance data
        gh_w_per_m2 = solar_resource_data["gh"]
        mean_gh_w_per_m2 = sum(gh_w_per_m2) / len(gh_w_per_m2)
        
        # Convert to daily energy [kWh/m²/day]
        daily_irradiance_kWh_per_m2_per_day = mean_gh_w_per_m2 * 24 / 1000
        annual_irradiance_kWh_per_m2 = daily_irradiance_kWh_per_m2_per_day * 365
        
        # Apply PV physics parameters (matching step9)
        oversizing_factor = 1.0
        panel_nameplate_power_density_kW_per_m2 = 0.193  # Tesla panels: 420W/2.171m²
        system_performance_ratio = 0.80  # 80% efficiency after losses
        pv_cell_efficiency = 0.206  # 20.6% Tesla panel efficiency
        
        # Calculate energy production per square meter
        annual_energy_production_kWh_per_m2 = (annual_irradiance_kWh_per_m2 * 
                                               pv_cell_efficiency * 
                                               system_performance_ratio)
        
        # Calculate required panel area and DC capacity
        required_panel_area_m2 = (annual_load_kwh * oversizing_factor) / annual_energy_production_kWh_per_m2
        system_capacity = required_panel_area_m2 * panel_nameplate_power_density_kW_per_m2
        solar_model.SystemDesign.system_capacity = system_capacity
        print(f"solar system capacity: {system_capacity}")
        
        # Execute solar model to get raw generation
        solar_model.execute(0)
        
        # Get the raw solar generation (AC output in Watts)
        ac_output = solar_model.Outputs.ac
        # Convert to a flat Python list and convert from Watts to kW
        solar_profile_watts = np.asarray(ac_output, dtype=float).ravel().tolist()
        solar_profile = [w / 1000.0 for w in solar_profile_watts]  # Convert W to kW
        
        print(f"  Raw solar profile generated: {len(solar_profile)} hours")
        print(f"  Annual solar generation: {sum(solar_profile):.0f} kWh/year")
        print(f"  System capacity: {system_capacity:.2f} kW")
        print(f"  Peak solar output: {max(solar_profile):.2f} kW")
        
        return solar_profile
        
    except Exception as e:
        print(f"Error generating solar profile: {e}")
        raise Exception(f"Failed to generate raw solar profile: {e}")


def main():
    """
    Main execution function to run the custom dispatch demo
    """
    # Configure matplotlib for interactive display
    plt.style.use('default')
    plt.rcParams['figure.figsize'] = (14, 8)
    plt.rcParams['font.size'] = 10
    
    # Load existing data
    county_name = "alameda"
    sam_file = f"data/loadprofiles/baseline/single-family-detached/{county_name}/sam_optimized_load_profiles_{county_name}.csv"
    weather_file = f"data/loadprofiles/baseline/single-family-detached/{county_name}/weather_TMY_{county_name}.csv"
    load_file = f"data/loadprofiles/baseline/single-family-detached/{county_name}/combined_profiles_baseline_{county_name}.csv"
    
    print("SAM Custom Dispatch Demo")
    
    # Load reference data
    reference_sam_data = None
    if os.path.exists(sam_file):
        reference_sam_data = pd.read_csv(sam_file, index_col=0, parse_dates=True)
        print(f"Loaded reference SAM data for {county_name}")
    else:
        print(f"Reference SAM data not found: {sam_file}")
    
    # Load load profile
    load_profile = None
    if os.path.exists(load_file):
        load_data = pd.read_csv(load_file)
        load_profile = load_data["electricity.real_and_simulated.for_typical_county_home.kwh"].tolist()
        annual_load_kwh = sum(load_profile)
        print(f"Loaded load profile: {len(load_profile)} hours, {annual_load_kwh:.0f} kWh/year")
    else:
        print(f"Load file not found: {load_file}")
        return
    
    # Check weather file
    if not os.path.exists(weather_file):
        print(f"Weather file not found: {weather_file}")
        return
    else:
        print(f"Weather file found")
    
    # Initialize dispatch generator
    pge_rate_plan = PGE_RATE_PLANS["E-TOU-D"]
    dispatch_generator = CustomDispatchScheduleGenerator(pge_rate_plan)
    
    print(f"\nCustom dispatch generator initialized:")
    print(f"  Battery capacity: {dispatch_generator.battery_capacity} kWh")
    print(f"  Cycle cost threshold: ${dispatch_generator.cycle_cost:.3f}/kWh")
    print(f"  SOC operating range: {dispatch_generator.min_soc}% - {dispatch_generator.max_soc}%")
    
    solar_profile = get_raw_solar_profile(weather_file, load_profile)
    
    # Generate custom dispatch schedules
    print("\nGenerating custom dispatch schedules...")
    # Use solar-priority schedule: prioritize battery replenishment during daylight hours
    print("Using solar-only battery charging strategy...")
    print("  Solar Priority: Battery Charging → Load → Grid Export")
    print("  Daylight hours (6 AM - 4 PM): Charge with excess solar only")
    print("  Peak hours (4-9 PM): Discharge battery")
    print("  Overnight hours: No battery activity (grid charging disabled)")
    
    charge_schedule, discharge_schedule, gridcharge_schedule = generate_solar_priority_battery_schedule(
        load_profile,
        solar_profile,
        peak_start_hour=16,
        peak_end_hour=21
    )

    # Print first-day (0-23) schedule values for quick inspection
    cs0 = charge_schedule[:24]
    ds0 = discharge_schedule[:24]
    gs0 = gridcharge_schedule[:24]
    print("First-day schedules (hours 0–23):")
    print(f"  charge_schedule:     {[int(x) if x in (0,1) else round(float(x),3) for x in cs0]}")
    print(f"  discharge_schedule:  {[int(x) if x in (0,1) else round(float(x),3) for x in ds0]}")
    print(f"  gridcharge_schedule: {[int(x) if x in (0,1) else round(float(x),3) for x in gs0]}")
    
    # Show schedule statistics
    total_charge_energy = np.sum(charge_schedule)
    total_discharge_energy = np.sum(discharge_schedule) 
    total_gridcharge_energy = np.sum(gridcharge_schedule)
    daylight_charge_energy = sum(charge_schedule[h] for h in range(len(charge_schedule)) 
                                if charge_schedule[h] > 0 and 6 <= (h % 24) < 18)
    peak_discharge_energy = sum(discharge_schedule[h] for h in range(len(discharge_schedule))
                               if 16 <= (h % 24) < 21)
    
    print(f"  Schedule Summary:")
    print(f"    Total charge energy: {total_charge_energy:,.1f} kWh")
    print(f"    Daylight solar charge: {daylight_charge_energy:,.1f} kWh")
    print(f"    Peak discharge energy: {peak_discharge_energy:,.1f} kWh")
    print(f"    Grid charge energy: {total_gridcharge_energy:,.1f} kWh")
    # Build a minimal dispatch_log so downstream comparisons/plots work
    try:
        hourly_rates = dispatch_generator.get_hourly_rates()
    except Exception:
        hourly_rates = [0.0] * len(load_profile)
    rows = []
    for h in range(len(load_profile)):
        hod = h % 24
        # Determine solar intensity for synthetic profile if needed
        if h < len(solar_profile):
            solar_val = solar_profile[h]
        else:
            if 6 <= hod <= 18:
                solar_intensity = np.sin((hod - 6) * np.pi / 12) * 3.0
                solar_val = max(0, solar_intensity)
            else:
                solar_val = 0.0
            
        rows.append({
            'hour': h,
            'hour_of_day': hod,
            'rate': hourly_rates[h] if h < len(hourly_rates) else 0.0,
            'soc': None,
            'load': load_profile[h],
            'solar': solar_val,
            'is_peak': 16 <= hod <= 20,
            'peak_load_target': 5.0,  # Default peak target for compatibility
            'charge': charge_schedule[h],
            'discharge': discharge_schedule[h],
            'gridcharge': gridcharge_schedule[h]
        })
    dispatch_generator.dispatch_log = pd.DataFrame(rows)
    
    # Note: Removed experimental solar-to-battery-first load manipulation to ensure
    # the load profile remains accurate and unmodified.
    
    # Run SAM with custom dispatch
    print("\nRunning SAM simulation with custom dispatch (Battwatts)...")
    custom_sam_results = run_sam_with_custom_dispatch(
        weather_file, load_profile, charge_schedule, discharge_schedule, gridcharge_schedule
    )
    
    if custom_sam_results is None:
        print("SAM simulation failed")
        raise Exception
    else:
        if 'battery_soc' in custom_sam_results:
            first24 = [round(float(x), 3) for x in custom_sam_results['battery_soc'][:24]]
            print(f"DEBUG: SAM SOC first 24 hours: {first24}")
        else:
            print("DEBUG: battery_soc not available from Battwatts outputs.")
    
    # Compare results
    # Comparison requires disaggregated flows; skip if not available
    if reference_sam_data is not None and custom_sam_results.get('flows_available'):
        print("\nComparing results...")
        comparison_results = compare_dispatch_results(
            reference_sam_data, 
            custom_sam_results, 
            dispatch_generator.dispatch_log
        )
    else:
        print("\nSkipping comparison: disaggregated flow outputs not available with Battwatts.")
    
    # Economic analysis requires disaggregated grid_to_load flows; skip if unavailable
    if custom_sam_results.get('flows_available'):
        print("\nCalculating economic benefits...")
        economic_analysis = calculate_economic_benefits(
            custom_sam_results,
            reference_sam_data,
            dispatch_generator.dispatch_log,
            pge_rate_plan
        )
    else:
        print("\nSkipping economic analysis: disaggregated flow outputs not available with Battwatts.")
        economic_analysis = None
    
    # Generate plots (single-day SOC view)
    print("\nGenerating visualization plots...")
    # Always show SOC if available; otherwise, plot an estimated SOC from schedules for visibility
    if 'battery_soc' in custom_sam_results:
        print("  Figure: Battery SOC with Dispatch Events (Day 1)...")
        plot_soc_one_day(custom_sam_results, dispatch_generator.dispatch_log, day_index=0)
    else:
        print("  SAM did not expose battery_soc; plotting an estimated SOC from schedules (labelled as Estimated).")
        est_capacity = getattr(dispatch_generator, 'battery_capacity', 13.5)
        plot_estimated_soc_one_day(charge_schedule, discharge_schedule, gridcharge_schedule,
                                   capacity_kwh=est_capacity, day_index=0)

    # Weekly analysis requires flow breakdown; skip if not available
    if custom_sam_results.get('flows_available'):
        plot_custom_dispatch_analysis(custom_sam_results, dispatch_generator.dispatch_log, reference_sam_data, month="January", week_offset=0)
        july_start_day = 31 + 28 + 31 + 30 + 31 + 30
        plot_custom_dispatch_analysis(custom_sam_results, dispatch_generator.dispatch_log, reference_sam_data, month="July", week_offset=july_start_day + 7)
        plot_annual_soc_violations(dispatch_generator.dispatch_log)
    else:
        print("  Skipping weekly/annual flow plots: flows not available from Battwatts.")
    
    print("\nCustom dispatch demo completed.")


if __name__ == "__main__":
    main()
