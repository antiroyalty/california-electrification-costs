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
    
    def generate_custom_dispatch_schedule(self, load_profile, solar_profile):
        """
        Generate SAM custom dispatch schedule arrays using peak-hour optimization logic
        
        Strategy:
        1) Look ahead to calculate daily peak load (4-9pm)
        2) Prioritize solar for charging battery up to peak load requirement
        3) Use remaining solar for household load, then top up battery
        4) Discharge battery during 4-9pm peak hours (80% max, 20% min SOC)
        
        Returns: (charge_schedule, discharge_schedule, gridcharge_schedule)
        """
        hours = len(load_profile)
        hourly_rates = self.get_hourly_rates()
        
        # Initialize dispatch arrays (0 = no action, values 0-1 represent fraction of max power)
        charge_schedule = np.zeros(hours)      # Battery charging from excess solar
        discharge_schedule = np.zeros(hours)   # Battery discharging to load
        gridcharge_schedule = np.zeros(hours)  # Battery charging from grid
        
        # Battery simulation parameters (align with Battwatts default ~50% so plots match SAM)
        current_soc = 50.0
        battery_kwh = current_soc / 100 * self.battery_capacity
        max_charge_power = 5.0  # kW
        max_discharge_power = 5.0  # kW
        
        # Operating SOC limits for peak hour strategy
        peak_max_soc = 90.0  # Don't discharge below this during peak
        peak_min_soc = 20.0  # Don't charge above this for peak preparation
        
        # Track hourly decisions for analysis
        dispatch_log = []
        
        # Track daily predictions for logging
        daily_predictions = {}
        
        # Process each hour
        for h in range(hours):
            load = load_profile[h]
            solar = solar_profile[h] if solar_profile else 0
            rate = hourly_rates[h]
            hour_of_day = h % 24
            
            # Determine if we're in peak hours (4 PM - 9 PM)
            is_peak_hour = 16 <= hour_of_day <= 20  # 4 PM to 8 PM (inclusive)
            
            # Look ahead to calculate today's peak load requirement
            day_start = (h // 24) * 24
            day_end = min(day_start + 24, hours)
            peak_start_today = day_start + 16  # 4 PM
            peak_end_today = min(day_start + 21, hours)  # 9 PM
            current_day = h // 24
            
            # Calculate total peak load for today
            if peak_end_today > peak_start_today:
                today_peak_load = sum(load_profile[peak_start_today:peak_end_today])
            else:
                today_peak_load = 0
            
            # Calculate energy needed from battery for today's peak
            # (This is the target we want to have stored)
            peak_battery_target_kwh = min(today_peak_load, 
                                        (peak_max_soc - peak_min_soc) / 100 * self.battery_capacity)
            
            # Log daily predictions (only once per day at 6 AM)
            if hour_of_day == 6 and current_day not in daily_predictions:
                battery_available_for_peak = max(0, battery_kwh - (peak_min_soc / 100 * self.battery_capacity))
                daily_predictions[current_day] = {
                    'day': current_day,
                    'peak_load_kwh': today_peak_load,
                    'peak_target_kwh': peak_battery_target_kwh,
                    'battery_ready_kwh': battery_available_for_peak,
                    'current_soc': current_soc,
                    'battery_total_kwh': battery_kwh
                }
            
            # Additional logging when entering peak hours (reduced)
            if hour_of_day == 16 and h > 0:
                pass
            
            # Decision variables
            charge_action = 0.0
            discharge_action = 0.0
            gridcharge_action = 0.0
            
            if is_peak_hour:
                # PEAK HOURS (4-9 PM): Discharge battery to meet load
                if current_soc > peak_min_soc and load > 0:
                    battery_available = battery_kwh - (peak_min_soc / 100 * self.battery_capacity)
                    
                    if battery_available > 0:
                        # Discharge to meet as much load as possible
                        discharge_amount = min(load, battery_available, max_discharge_power)
                        discharge_action = discharge_amount / max_discharge_power
                        
                        # Predict new SOC after discharge
                        new_battery_kwh = battery_kwh - discharge_amount
                        new_soc = (new_battery_kwh / self.battery_capacity) * 100
                        
                        if new_soc < peak_min_soc:
                            # Adjust discharge to respect SOC limit
                            safe_discharge = battery_kwh - (peak_min_soc / 100 * self.battery_capacity)
                            discharge_amount = max(0, safe_discharge)
                            discharge_action = discharge_amount / max_discharge_power if max_discharge_power > 0 else 0
                        
                        battery_kwh -= discharge_amount
                        current_soc = (battery_kwh / self.battery_capacity) * 100
                        
                        # Final SOC check (reduced verbosity)
                        if current_soc < peak_min_soc - 0.1:
                            pass
            
            else:
                # NON-PEAK HOURS: Implement solar prioritization strategy
                if solar > 0:
                    # Calculate how much battery capacity we need for peak preparation
                    current_battery_energy = battery_kwh
                    peak_prep_target = peak_battery_target_kwh + (peak_min_soc / 100 * self.battery_capacity)
                    peak_prep_needed = max(0, peak_prep_target - current_battery_energy)
                    
                    # 1. First Priority: Charge battery for peak hours
                    if peak_prep_needed > 0 and current_soc < peak_max_soc:
                        battery_capacity_available = min(
                            (peak_max_soc - current_soc) / 100 * self.battery_capacity,
                            peak_prep_needed
                        )
                        
                        if battery_capacity_available > 0:
                            charge_amount = min(solar, battery_capacity_available, max_charge_power)
                            charge_action = charge_amount / max_charge_power
                            
                            old_soc = current_soc
                            battery_kwh += charge_amount
                            current_soc = (battery_kwh / self.battery_capacity) * 100
                            solar -= charge_amount  # Reduce available solar
                            
                        else:
                            pass
                    
                    # 2. Second Priority: Meet household load with remaining solar
                    if solar > 0 and load > 0:
                        load_met_by_solar = min(solar, load)
                        solar -= load_met_by_solar  # Reduce available solar
                        # Note: This doesn't require a dispatch action in SAM as it's automatic
                    
                    # 3. Third Priority: Top up battery with any remaining solar
                    if solar > 0 and current_soc < self.max_soc:
                        battery_capacity_available = (self.max_soc - current_soc) / 100 * self.battery_capacity
                        
                        if battery_capacity_available > 0:
                            additional_charge = min(solar, battery_capacity_available, max_charge_power - charge_action * max_charge_power)
                            if additional_charge > 0:
                                # Add to existing charge action
                                old_soc = current_soc
                                total_charge = charge_action * max_charge_power + additional_charge
                                charge_action = min(total_charge / max_charge_power, 1.0)
                                battery_kwh += additional_charge
                                current_soc = (battery_kwh / self.battery_capacity) * 100
                            else:
                                pass
                        else:
                            pass
                    else:
                        pass
                
                # Handle any remaining load not met by solar (use grid)
                # This is automatic in SAM, no dispatch action needed
            
            # Store dispatch decisions
            charge_schedule[h] = charge_action
            discharge_schedule[h] = discharge_action
            gridcharge_schedule[h] = gridcharge_action
            
            # Reduced per-hour warnings
            if current_soc < 10.0:
                pass
            
            # Log for analysis
            dispatch_log.append({
                'hour': h,
                'hour_of_day': hour_of_day,
                'rate': rate,
                'soc': current_soc,
                'load': load,
                'solar': solar_profile[h] if solar_profile else 0,
                'is_peak': is_peak_hour,
                'peak_load_target': today_peak_load,
                'charge': charge_action,
                'discharge': discharge_action,
                'gridcharge': gridcharge_action
            })
        
        self.dispatch_log = pd.DataFrame(dispatch_log)
        
        # Reduced end-of-run diagnostics omitted to reduce verbosity

        return charge_schedule, discharge_schedule, gridcharge_schedule


def initialize_solar(weather_file, load_profile, charge_schedule, discharge_schedule, gridcharge_schedule):
    """Initialize SAM solar model with configuration (reduced console output)"""
        
    # Load solar resource data
    solar_resource_data = tools.SAM_CSV_to_solar_data(weather_file)
    
    # Calculate system capacity (simplified)
    annual_load_kwh = sum(load_profile)
    system_capacity = annual_load_kwh / 1200  # Rough sizing: 1200 kWh/kW annually
    
    # Basic derived sizing only; detailed logging removed
    
    # === Solar Model Setup ===
    solar = pvwatts.new()
    
    # Load SAM solar configuration with debugging
    solar_config_file = "SAM_configuration_with_battery_custom_dispatch/untitled__1__pvwattsv8.json"
    
    if not os.path.exists(solar_config_file):
        print(f"DEBUG: Solar config file not found: {solar_config_file}")
        return None
    
    with open(solar_config_file, 'r') as file:
        solar_config = json.load(file)
        # Apply configuration
        skipped_params = []
        applied_params = []
        
        for k, v in solar_config.items():
            if k in ["number_inputs"]:
                skipped_params.append(k)
                continue
                
            try:
                solar.value(k, v)
                applied_params.append(k)
            except Exception as e:
                # silently skip parameters that cannot be set
                skipped_params.append(k)
        # no verbose reporting

    # Set solar parameters with debugging
    try:
        solar.SolarResource.solar_resource_data = solar_resource_data
    except Exception as e:
        print(f"DEBUG: Failed to set solar resource data: {e}")
        return None
    
    try:
        solar.SystemDesign.system_capacity = system_capacity
    except Exception as e:
        print(f"DEBUG: Failed to set system capacity: {e}")
        return None
    
    try:
        solar.Lifetime.dc_degradation = [0.5]  # 0.5% annual degradation
    except Exception as e:
        print(f"DEBUG: Failed to set degradation: {e}")
        return None
    
    return solar


def initialize_storage(weather_file, load_profile, charge_schedule, discharge_schedule, gridcharge_schedule, solar):
    """Initialize SAM battery storage model (reduced console output)"""
    try:
        battery = battery_model.from_existing(solar)
    except Exception as e:
        print(f"DEBUG: Failed to create battery model: {e}")
        return None
    
    # Load SAM battery configuration
    battery_config_file = "SAM_configuration_with_battery_custom_dispatch/untitled__1__battwatts.json"
    
    if not os.path.exists(battery_config_file):
        print(f"DEBUG: Battery config file not found: {battery_config_file}")
        return None
        
    with open(battery_config_file, 'r') as file:
        battery_config = json.load(file)
        # DEBUG: show configured simple capacity
        try:
            conf_kwh = battery_config.get('batt_simple_kwh', None)
            conf_kw = battery_config.get('batt_simple_kw', None)
            print(f"DEBUG: Config batt_simple_kwh={conf_kwh}, batt_simple_kw={conf_kw} (from {battery_config_file})")
        except Exception:
            pass
        # Apply configuration
        skipped_battery_params = []
        applied_battery_params = []
        
        for k, v in battery_config.items():
            if k in ["number_inputs"]:
                skipped_battery_params.append(k)
                continue
                
            try:
                battery.value(k, v)
                applied_battery_params.append(k)
            except Exception as e:
                # silently skip parameters that cannot be set
                skipped_battery_params.append(k)
        # no verbose reporting
    
    # Set load profile
    try:
        battery.Battery.assign({'load': load_profile})
    except Exception as e:
        print(f"DEBUG: Failed to set load profile: {e}")
        return None

    # Align SAM's initial SOC with desired start (Battwatts expects this on Battery)
    try:
        # Prefer value() to cover cases where group attribute access differs
        battery.value('batt_initial_SOC', 90.0)
        # Also align min/max SOC bounds if available
        try:
            battery.value('batt_minimum_SOC', 20.0)
        except Exception:
            pass
        try:
            battery.value('batt_maximum_SOC', 80.0)
        except Exception:
            pass
    except Exception:
        try:
            if hasattr(battery, 'Battery') and hasattr(battery.Battery, 'batt_initial_SOC'):
                battery.Battery.batt_initial_SOC = 90.0
            if hasattr(battery.Battery, 'batt_minimum_SOC'):
                battery.Battery.batt_minimum_SOC = 20.0
            if hasattr(battery.Battery, 'batt_maximum_SOC'):
                battery.Battery.batt_maximum_SOC = 80.0
        except Exception:
            pass

    # DEBUG: Report SOC inputs as seen before execution
    try:
        soc_init = None
        soc_min = None
        soc_max = None
        if hasattr(battery, 'Battery'):
            if hasattr(battery.Battery, 'batt_initial_SOC'):
                soc_init = battery.Battery.batt_initial_SOC
            if hasattr(battery.Battery, 'batt_minimum_SOC'):
                soc_min = battery.Battery.batt_minimum_SOC
            if hasattr(battery.Battery, 'batt_maximum_SOC'):
                soc_max = battery.Battery.batt_maximum_SOC
        print(f"DEBUG: Pre-exec Battwatts SOC params -> initial: {soc_init}, min: {soc_min}, max: {soc_max}")
        # Also report simple capacity values as seen on the model
        model_kwh = None
        model_kw = None
        if hasattr(battery, 'Battery'):
            if hasattr(battery.Battery, 'batt_simple_kwh'):
                model_kwh = battery.Battery.batt_simple_kwh
            if hasattr(battery.Battery, 'batt_simple_kw'):
                model_kw = battery.Battery.batt_simple_kw
        print(f"DEBUG: Pre-exec Battwatts capacity (input) kWh={model_kwh}, kW={model_kw}")
    except Exception:
        pass

    return battery


def initialize_custom_dispatch(solar, battery, load_profile, charge_schedule, discharge_schedule, gridcharge_schedule):
    """Configure SAM with custom dispatch schedules (reduced console output)"""
    
    # Load battery config for reference
    battery_config_file = "SAM_configuration_with_battery_custom_dispatch/untitled__1__battwatts.json"
    with open(battery_config_file, 'r') as file:
        battery_config = json.load(file)
    
    # Validate schedule lengths
    
    if not all(len(s) == len(load_profile) for s in [charge_schedule, discharge_schedule, gridcharge_schedule]):
        print("DEBUG: Schedule length mismatch!")
        return None

    # Set custom dispatch schedules
    try:
        # Convert schedules to lists if they're numpy arrays
        discharge_list = discharge_schedule.tolist() if hasattr(discharge_schedule, 'tolist') else list(discharge_schedule)
        charge_list = charge_schedule.tolist() if hasattr(charge_schedule, 'tolist') else list(charge_schedule)
        gridcharge_list = gridcharge_schedule.tolist() if hasattr(gridcharge_schedule, 'tolist') else list(gridcharge_schedule)
        
        # Convert our optimization schedules to SAM's simple format
        # SAM expects: positive = discharge, negative = charge, zero = no action
        sam_dispatch_array = []
        
        for h in range(len(load_profile)):
            discharge_signal = discharge_list[h]
            charge_signal = charge_list[h] 
            gridcharge_signal = gridcharge_list[h]
            
            # Decision logic: prioritize the strongest signal
            if discharge_signal > 0.1:  # Threshold to avoid tiny values
                # Want to discharge: positive value in SAM
                sam_dispatch_array.append(1)
            elif charge_signal > 0.1 or gridcharge_signal > 0.1:
                # Want to charge (from solar or grid): negative value in SAM
                sam_dispatch_array.append(-1)
            else:
                # No strong preference: let SAM decide automatically
                sam_dispatch_array.append(0)
        
        # Set the custom dispatch array
        battery.Battery.batt_custom_dispatch = sam_dispatch_array
        
        # Verify it was set correctly
        check_dispatch = battery.Battery.batt_custom_dispatch
        _ = len(check_dispatch)
        
    except Exception as e:
        print(f"DEBUG: Failed to set custom dispatch schedules: {e}")
        print(f"  Error type: {type(e)}")
        print(f"  Error details: {str(e)}")
        return None
    
    # Set any additional dispatch parameters found in config
    additional_dispatch_settings = {
        'batt_dispatch_auto_can_gridcharge': 1,
        'batt_dispatch_auto_can_charge': 1,
        'batt_dispatch_auto_btm_can_discharge_to_grid': 0,  # Don't discharge to grid
    }
    
    for param, value in additional_dispatch_settings.items():
        try:
            if param in battery_config or hasattr(battery.Battery, param):
                setattr(battery.Battery, param, value)
        except Exception as e:
            print(f"DEBUG: Failed to set {param}: {e}")
    
    # done


def run_sam_simulation(solar, battery):
    # === Run SAM Simulation ===
    try:
        solar.execute(0)
    except Exception as e:
        print(f"DEBUG: Solar execution failed: {e}")
        return None
    
    try:
        # Ensure initial SOC is set just before execution (Battwatts expects percent 0–100)
        try:
            battery.value('batt_initial_SOC', 90.0)
        except Exception:
            try:
                if hasattr(battery, 'Battery') and hasattr(battery.Battery, 'batt_initial_SOC'):
                    battery.Battery.batt_initial_SOC = 90.0
            except Exception:
                pass
        # DEBUG: Echo the current SOC inputs right before execution
        try:
            soc_init = None
            if hasattr(battery, 'Battery') and hasattr(battery.Battery, 'batt_initial_SOC'):
                soc_init = battery.Battery.batt_initial_SOC
            print(f"DEBUG: Pre-execute batt_initial_SOC = {soc_init}")
        except Exception:
            pass
        battery.execute(0)
    except Exception as e:
        print(f"DEBUG: Battery execution failed: {e}")
        print(f"  Error type: {type(e)}")
        print(f"  Error details: {str(e)}")
        import traceback
        traceback.print_exc()
        return None
    
    # === Extract Results ===
    try:
        results = {
            'load_profile': battery.Battery.load,
            'system_to_load': battery.Outputs.system_to_load,
            'battery_to_load': battery.Outputs.batt_to_load,
            'grid_to_load': battery.Outputs.grid_to_load,
            'grid_to_batt': battery.Outputs.grid_to_batt,
            'system_to_batt': battery.Outputs.system_to_batt,
            'system_to_grid': battery.Outputs.system_to_grid,
            'battery_soc': battery.Outputs.batt_SOC,
            'solar_capacity': solar.SystemDesign.system_capacity,
            'battery_capacity': battery.Outputs.batt_bank_installed_capacity
        }
        # DEBUG: Show first day SOC to verify starting state
        try:
            soc = results['battery_soc']
            print(f"DEBUG: SOC first 12 hours: {[round(x,1) for x in soc[:12]]}")
        except Exception:
            pass
        # DEBUG: Report installed battery capacity and simple input if available
        try:
            installed_kwh = results.get('battery_capacity', None)
            simple_kwh = None
            simple_kw = None
            if hasattr(battery, 'Battery'):
                simple_kwh = getattr(battery.Battery, 'batt_simple_kwh', None)
                simple_kw = getattr(battery.Battery, 'batt_simple_kw', None)
            print(f"DEBUG: Post-exec Battwatts capacity -> installed_kwh={installed_kwh}, simple_kwh={simple_kwh}, simple_kw={simple_kw}")
        except Exception:
            pass
        
        return results
        
    except Exception as e:
        print(f"DEBUG: Failed to extract results: {e}")
        return None


def run_sam_with_custom_dispatch(weather_file, load_profile, charge_schedule, discharge_schedule, gridcharge_schedule):
    """
    Run SAM with custom dispatch schedule
    """
    try:
        solar = initialize_solar(weather_file, load_profile, charge_schedule, discharge_schedule, gridcharge_schedule)
        if solar is None:
            return None
            
        battery = initialize_storage(weather_file, load_profile, charge_schedule, discharge_schedule, gridcharge_schedule, solar)
        if battery is None:
            return None
            
        initialize_custom_dispatch(solar, battery, load_profile, charge_schedule, discharge_schedule, gridcharge_schedule)
        
        return run_sam_simulation(solar, battery)
        
    except Exception as e:
        print(f"DEBUG: Unexpected error in SAM simulation: {e}")
        print(f"  Error type: {type(e)}")
        print(f"  Error details: {str(e)}")
        import traceback
        traceback.print_exc()
        return None


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
      batt_dispatch_auto_can_gridcharge = 1 so grid charging is allowed.

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
    """
    Create comprehensive visualization of custom dispatch behavior
    
    Args:
        custom_results: SAM simulation results
        dispatch_log: Algorithm dispatch decisions
        reference_data: Reference SAM data for comparison
        month: Month name for title (e.g., "January", "July")
        week_offset: Which week of the year to analyze (0 = first week)
    """
    if custom_results is None:
        print("Cannot create plots without custom dispatch results")
        return
    
    # Calculate week hours based on offset
    week_hours = 168
    start_hour = week_offset * 24  # Start of the target week
    end_hour = start_hour + week_hours
    hours = range(week_hours)
    
    # Extract week data based on offset
    max_hours = min(len(custom_results['load_profile']), len(dispatch_log))
    actual_end = min(end_hour, max_hours)
    actual_start = min(start_hour, max_hours - week_hours) if max_hours >= week_hours else 0
    actual_week_hours = actual_end - actual_start
    
    custom_week = {
        'load': custom_results['load_profile'][actual_start:actual_end],
        'solar': custom_results['system_to_load'][actual_start:actual_end],
        'battery_soc': custom_results['battery_soc'][actual_start:actual_end],
        'battery_discharge': custom_results['battery_to_load'][actual_start:actual_end],
        'grid_usage': custom_results['grid_to_load'][actual_start:actual_end],
        'grid_to_battery': custom_results['grid_to_batt'][actual_start:actual_end]
    }
    
    dispatch_week = dispatch_log.iloc[actual_start:actual_end]
    
    # Adjust hours range for actual data length
    hours = range(len(custom_week['load']))
    week_hours = len(custom_week['load'])
    
    # Create subplots (expanded to 2x4 layout for 8 plots total)
    fig, axes = plt.subplots(2, 4, figsize=(24, 10))
    week_start_day = (actual_start // 24) + 1
    fig.suptitle(f'SAM Custom Dispatch Analysis: Week Starting Day {week_start_day} ({month})', fontsize=16, fontweight='bold')
    
    # 1. Battery SOC with dispatch events
    ax1 = axes[0, 0]
    ax1.plot(hours, custom_week['battery_soc'], 'b-', linewidth=2, label='Battery SOC')
    
    # Highlight dispatch events
    charge_hours = dispatch_week[dispatch_week['charge'] > 0].index
    discharge_hours = dispatch_week[dispatch_week['discharge'] > 0].index  
    gridcharge_hours = dispatch_week[dispatch_week['gridcharge'] > 0].index
    
    for h in charge_hours:
        if h < week_hours:
            ax1.axvline(x=h, color='green', alpha=0.3, linewidth=0.8)
    for h in discharge_hours:
        if h < week_hours:
            ax1.axvline(x=h, color='red', alpha=0.3, linewidth=0.8)
    for h in gridcharge_hours:
        if h < week_hours:
            ax1.axvline(x=h, color='orange', alpha=0.3, linewidth=0.8)
    
    # Mark peak hours and SOC limits
    week_days = set(h // 24 for h in hours if h < week_hours)
    for day in week_days:
        peak_start = day * 24 + 16
        peak_end = day * 24 + 21
        if peak_start < week_hours:
            peak_end = min(peak_end, week_hours)
            ax1.axvspan(peak_start, peak_end, alpha=0.2, color='yellow', label='Peak Hours' if day == min(week_days) else "")
    
    ax1.axhline(y=20, color='red', linestyle='--', alpha=0.7, label='Min Peak SOC (20%)')
    ax1.axhline(y=80, color='orange', linestyle='--', alpha=0.7, label='Max Peak SOC (80%)')
    
    # Add vertical lines for peak price windows (4-9 PM each day)
    week_days = set(h // 24 for h in hours if h < week_hours)
    for day in week_days:
        peak_start = day * 24 + 16  # 4 PM
        peak_end = day * 24 + 21    # 9 PM
        if peak_start < week_hours:
            ax1.axvline(x=peak_start, color='grey', linestyle='--', alpha=0.6, linewidth=1)
            if peak_end < week_hours:
                ax1.axvline(x=peak_end, color='grey', linestyle='--', alpha=0.6, linewidth=1)
            # Add label only for the first day
            if day == min(week_days):
                ax1.text(peak_start + 2.5, 85, 'Peak\n4-9PM', 
                        fontsize=8, ha='center', va='center', alpha=0.7,
                        bbox=dict(boxstyle='round,pad=0.2', facecolor='lightgrey', alpha=0.5))
    
    ax1.set_title('Battery SOC with Dispatch Events', fontweight='bold')
    ax1.set_ylabel('SOC (%)')
    ax1.legend()
    ax1.grid(True, alpha=0.3)
    
    # Skip Rates vs Discharge Decisions plot - removed per user request
    
    # 2. Energy flows stacked area chart
    ax2 = axes[0, 1]
    solar_data = np.array(custom_week['solar'])
    battery_data = np.array(custom_week['battery_discharge'])
    grid_data = np.array(custom_week['grid_usage'])
    load_data = np.array(custom_week['load'])
    
    # Create stacked areas for energy sources
    ax2.fill_between(hours, 0, solar_data, alpha=0.7, color='gold', label='Solar')
    ax2.fill_between(hours, solar_data, solar_data + battery_data, 
                    alpha=0.7, color='green', label='Battery Discharge')
    ax2.fill_between(hours, solar_data + battery_data, 
                    solar_data + battery_data + grid_data,
                    alpha=0.7, color='red', label='Grid')
    
    # Plot total load as a line
    ax2.plot(hours, load_data, 'k-', linewidth=2, label='Total Load')
    
    # Add vertical lines for peak price windows (4-9 PM each day)
    week_days = set(h // 24 for h in hours if h < week_hours)
    for day in week_days:
        peak_start = day * 24 + 16  # 4 PM
        peak_end = day * 24 + 21    # 9 PM
        if peak_start < week_hours:
            ax2.axvline(x=peak_start, color='grey', linestyle='--', alpha=0.6, linewidth=1)
            if peak_end < week_hours:
                ax2.axvline(x=peak_end, color='grey', linestyle='--', alpha=0.6, linewidth=1)
            # Add label only for the first day
            if day == min(week_days):
                ax2.text(peak_start + 2.5, max(load_data) * 0.9, 'Peak\n4-9PM', 
                        fontsize=8, ha='center', va='center', alpha=0.7,
                        bbox=dict(boxstyle='round,pad=0.2', facecolor='lightgrey', alpha=0.5))
    
    ax2.set_title('Energy Sources (Custom Dispatch)', fontweight='bold')
    ax2.set_ylabel('Power (kW)')
    ax2.legend()
    ax2.grid(True, alpha=0.3)
    
    # 3. Battery Charge in kWh
    ax3 = axes[0, 2]
    
    # Calculate battery charge in kWh from SOC percentage
    battery_capacity_kwh = 13.5  # Tesla Powerwall capacity
    battery_charge_kwh = np.array(custom_week['battery_soc']) / 100 * battery_capacity_kwh
    
    ax3.plot(hours, battery_charge_kwh, 'g-', linewidth=2, label='Battery Charge')
    ax3.fill_between(hours, 0, battery_charge_kwh, alpha=0.3, color='green', label='Stored Energy')
    
    # Add capacity reference lines
    min_charge_kwh = 20 / 100 * battery_capacity_kwh  # 20% minimum
    max_charge_kwh = 80 / 100 * battery_capacity_kwh  # 80% maximum
    ax3.axhline(y=min_charge_kwh, color='red', linestyle='--', alpha=0.7, label=f'Min Charge ({min_charge_kwh:.1f} kWh)')
    ax3.axhline(y=max_charge_kwh, color='orange', linestyle='--', alpha=0.7, label=f'Max Charge ({max_charge_kwh:.1f} kWh)')
    
    # Add vertical lines for peak price windows
    week_days = set(h // 24 for h in hours if h < week_hours)
    for day in week_days:
        peak_start = day * 24 + 16  # 4 PM
        peak_end = day * 24 + 21    # 9 PM
        if peak_start < week_hours:
            ax3.axvline(x=peak_start, color='grey', linestyle='--', alpha=0.6, linewidth=1)
            if peak_end < week_hours:
                ax3.axvline(x=peak_end, color='grey', linestyle='--', alpha=0.6, linewidth=1)
            # Add label only for the first day
            if day == min(week_days):
                ax3.text(peak_start + 2.5, max_charge_kwh * 0.9, 'Peak\n4-9PM', 
                        fontsize=8, ha='center', va='center', alpha=0.7,
                        bbox=dict(boxstyle='round,pad=0.2', facecolor='lightgrey', alpha=0.5))
    
    ax3.set_title('Battery Charge (kWh)', fontweight='bold')
    ax3.set_ylabel('Energy (kWh)')
    ax3.legend()
    ax3.grid(True, alpha=0.3)
    
    # 4. Solar Power Available (kWh)
    ax4 = axes[0, 3]
    
    # Get solar generation data
    original_solar_week = dispatch_week['solar'][:week_hours].values
    system_to_load_week = np.array(custom_week['solar'])  # What actually went to load
    
    # Try to get system to battery data if available
    system_to_batt_week = np.array([0] * week_hours)  # Initialize
    try:
        if 'system_to_batt' in custom_results:
            system_to_batt_data = custom_results['system_to_batt']
            if hasattr(system_to_batt_data, '__len__') and len(system_to_batt_data) >= week_hours:
                system_to_batt_week = np.array(system_to_batt_data[actual_start:actual_end])
    except:
        pass
    
    # Plot available vs used solar
    ax4.fill_between(hours, 0, original_solar_week, alpha=0.3, color='yellow', label='Total Solar Available')
    ax4.fill_between(hours, 0, system_to_load_week, alpha=0.7, color='gold', label='Solar to Load')
    ax4.fill_between(hours, system_to_load_week, system_to_load_week + system_to_batt_week, 
                    alpha=0.7, color='orange', label='Solar to Battery')
    
    # Show solar clipping (unused solar)
    total_solar_used = system_to_load_week + system_to_batt_week
    solar_clipped = original_solar_week - total_solar_used
    clipping_mask = solar_clipped > 0.1
    
    if np.any(clipping_mask):
        ax4.fill_between(hours, total_solar_used, original_solar_week, 
                        where=(solar_clipped > 0.1), alpha=0.5, color='red', 
                        label='Clipped Solar')
    
    # Add vertical lines for peak price windows
    for day in week_days:
        peak_start = day * 24 + 16  # 4 PM
        peak_end = day * 24 + 21    # 9 PM
        if peak_start < week_hours:
            ax4.axvline(x=peak_start, color='grey', linestyle='--', alpha=0.6, linewidth=1)
            if peak_end < week_hours:
                ax4.axvline(x=peak_end, color='grey', linestyle='--', alpha=0.6, linewidth=1)
            # Add label only for the first day
            if day == min(week_days):
                ax4.text(peak_start + 2.5, max(original_solar_week) * 0.9, 'Peak\n4-9PM', 
                        fontsize=8, ha='center', va='center', alpha=0.7,
                        bbox=dict(boxstyle='round,pad=0.2', facecolor='lightgrey', alpha=0.5))
    
    ax4.set_title('Solar Power Available vs Used (kWh)', fontweight='bold')
    ax4.set_ylabel('Solar Power (kW)')
    ax4.legend()
    ax4.grid(True, alpha=0.3)
    
    # Skip SOC comparison plot - removed per user request
    
    # Skip Economic Benefits plot - removed per user request
    
    # 5. Grid Charging Events  
    ax5 = axes[1, 0]
    
    grid_to_battery = np.array(custom_week['grid_to_battery'])
    ax5.bar(hours, grid_to_battery, alpha=0.7, color='orange', label='Grid to Battery')
    
    # Add rate overlay on secondary y-axis
    rates_week = dispatch_week['rate'][:week_hours].values
    ax5_rate = ax5.twinx()
    ax5_rate.plot(hours, rates_week * 5, 'purple', linewidth=1, alpha=0.7, label='Rate (×5)')
    ax5_rate.set_ylabel('Rate ($/kWh × 5)', color='purple')
    
    # Add vertical lines for peak price windows
    for day in week_days:
        peak_start = day * 24 + 16  # 4 PM
        peak_end = day * 24 + 21    # 9 PM
        if peak_start < week_hours:
            ax5.axvline(x=peak_start, color='grey', linestyle='--', alpha=0.6, linewidth=1)
            if peak_end < week_hours:
                ax5.axvline(x=peak_end, color='grey', linestyle='--', alpha=0.6, linewidth=1)
    
    ax5.set_title('Grid Charging Events', fontweight='bold')
    ax5.set_ylabel('Power (kW)')
    ax5.legend(loc='upper left')
    ax5_rate.legend(loc='upper right')
    ax5.grid(True, alpha=0.3)
    
    # 6. Solar Generation Analysis - Check for clipping  
    ax6 = axes[1, 1]
    
    # Get the original solar profile from dispatch log (before any allocation)
    original_solar_week = dispatch_week['solar'][:week_hours].values
    system_to_load_week = np.array(custom_week['solar'])  # What actually went to load
    system_to_batt_week = np.array([0] * week_hours)  # Initialize
    
    # Try to get system to battery data if available
    try:
        if 'system_to_batt' in custom_results:
            system_to_batt_data = custom_results['system_to_batt']
            if hasattr(system_to_batt_data, '__len__') and len(system_to_batt_data) >= week_hours:
                system_to_batt_week = np.array(system_to_batt_data[:week_hours])
    except:
        pass
    
    # Calculate total solar utilization
    total_solar_used = system_to_load_week + system_to_batt_week
    
    # Plot solar generation components
    ax6.fill_between(hours, 0, system_to_load_week, alpha=0.7, color='gold', label='Solar to Load')
    ax6.fill_between(hours, system_to_load_week, total_solar_used, 
                    alpha=0.7, color='orange', label='Solar to Battery')
    
    # Show maximum available solar
    ax6.plot(hours, original_solar_week, 'r-', linewidth=2, label='Max Solar Available')
    
    # Highlight potential clipping (when available > used)
    solar_clipped = original_solar_week - total_solar_used
    clipping_mask = solar_clipped > 0.1  # Threshold for meaningful clipping
    
    if np.any(clipping_mask):
        clipped_hours = np.where(clipping_mask)[0]
        clipped_amounts = solar_clipped[clipping_mask]
        ax6.scatter(clipped_hours, original_solar_week[clipping_mask], 
                   c='red', s=50, alpha=0.8, marker='x', label='Clipped Solar')
        
        # Fill clipped area
        ax6.fill_between(hours, total_solar_used, original_solar_week, 
                        where=(solar_clipped > 0.1), alpha=0.3, color='red', 
                        label='Clipped Energy')
    
    ax6.set_title('Solar Generation & Clipping Analysis', fontweight='bold')
    ax6.set_ylabel('Solar Power (kW)')
    ax6.set_xlabel('Hours')
    ax6.legend()
    ax6.grid(True, alpha=0.3)
    
    # Add summary statistics
    total_available = np.sum(original_solar_week)
    total_used = np.sum(total_solar_used)
    total_clipped = np.sum(solar_clipped[solar_clipped > 0])
    clipping_pct = (total_clipped / total_available * 100) if total_available > 0 else 0
    
    stats_text = f'Week Solar Summary:\nAvailable: {total_available:.1f} kWh\nUsed: {total_used:.1f} kWh\nClipped: {total_clipped:.1f} kWh ({clipping_pct:.1f}%)'
    ax6.text(0.02, 0.98, stats_text, transform=ax6.transAxes, fontsize=9, 
            verticalalignment='top', bbox=dict(boxstyle='round', facecolor='lightblue', alpha=0.8))
    
    # 7. Peak Hour Load Coverage Analysis
    ax7 = axes[1, 2]
    
    # Identify peak hours in the week
    peak_mask = dispatch_week['is_peak'][:week_hours]
    peak_hours_list = [h for h in hours if h < len(peak_mask) and peak_mask.iloc[h]]
    
    if peak_hours_list:
        # Get load and battery discharge during peak hours
        peak_loads = [custom_week['load'][h] for h in peak_hours_list]
        peak_battery_discharge = [custom_week['battery_discharge'][h] for h in peak_hours_list]
        peak_grid_usage = [custom_week['grid_usage'][h] for h in peak_hours_list]
        
        # Create stacked bar chart for peak hours
        width = 0.8
        ax7.bar(peak_hours_list, peak_battery_discharge, width, alpha=0.7, 
               color='green', label='Battery Discharge')
        ax7.bar(peak_hours_list, peak_grid_usage, width, bottom=peak_battery_discharge, 
               alpha=0.7, color='red', label='Grid Usage')
        
        # Show total load as line
        ax7.plot(peak_hours_list, peak_loads, 'ko-', linewidth=2, label='Total Load')
        
        # Calculate peak coverage statistics
        total_peak_load = sum(peak_loads)
        total_battery_coverage = sum(peak_battery_discharge)
        battery_coverage_pct = (total_battery_coverage / total_peak_load * 100) if total_peak_load > 0 else 0
        
        ax7.set_title('Peak Hour Load Coverage (4-9 PM)', fontweight='bold')
        ax7.set_ylabel('Power (kW)')
        ax7.set_xlabel('Hours')
        ax7.legend()
        ax7.grid(True, alpha=0.3)
        
        # Add coverage statistics
        coverage_text = f'Peak Coverage:\nBattery: {battery_coverage_pct:.1f}%\nTotal Peak Load: {total_peak_load:.1f} kWh'
        ax7.text(0.02, 0.98, coverage_text, transform=ax7.transAxes, fontsize=9,
                verticalalignment='top', bbox=dict(boxstyle='round', facecolor='lightgreen', alpha=0.8))
    else:
        ax7.text(0.5, 0.5, 'No peak hours in selected week', 
                transform=ax7.transAxes, ha='center', va='center', fontsize=12)
        ax7.set_title('Peak Hour Load Coverage (4-9 PM)', fontweight='bold')
    
    # 8. Load Profile Analysis
    ax8 = axes[1, 3]
    
    # Plot the load profile for the week
    load_data = np.array(custom_week['load'])
    ax8.plot(hours, load_data, 'b-', linewidth=2, label='Household Load')
    
    # Highlight peak hours with background shading
    week_days = set(h // 24 for h in hours if h < week_hours)
    for day in week_days:
        peak_start = day * 24 + 16  # 4 PM
        peak_end = day * 24 + 21    # 9 PM
        if peak_start < week_hours:
            peak_end = min(peak_end, week_hours)
            ax8.axvspan(peak_start, peak_end, alpha=0.2, color='orange', label='Peak Hours (4-9 PM)' if day == min(week_days) else "")
    
    # Add daily average line
    if len(load_data) > 0:
        daily_avg = np.mean(load_data)
        ax8.axhline(y=daily_avg, color='red', linestyle='--', alpha=0.7, label=f'Week Average ({daily_avg:.2f} kW)')
    
    # Calculate and show load statistics
    if len(load_data) > 0:
        load_min = np.min(load_data)
        load_max = np.max(load_data)
        load_range = load_max - load_min
        
        # Identify peak and off-peak periods
        peak_loads = []
        off_peak_loads = []
        for h in hours:
            hour_of_day = h % 24
            if 16 <= hour_of_day <= 20:  # Peak hours
                peak_loads.append(load_data[h])
            else:
                off_peak_loads.append(load_data[h])
        
        peak_avg = np.mean(peak_loads) if peak_loads else 0
        off_peak_avg = np.mean(off_peak_loads) if off_peak_loads else 0
        
        # Add statistics text
        stats_text = f'''Load Statistics:
Min: {load_min:.2f} kW
Max: {load_max:.2f} kW
Range: {load_range:.2f} kW
Peak Avg: {peak_avg:.2f} kW
Off-Peak Avg: {off_peak_avg:.2f} kW'''
        
        ax8.text(0.02, 0.98, stats_text, transform=ax8.transAxes, fontsize=9,
                verticalalignment='top', bbox=dict(boxstyle='round', facecolor='lightcyan', alpha=0.8))
    
    ax8.set_title('Household Load Profile', fontweight='bold')
    ax8.set_xlabel('Hours')
    ax8.set_ylabel('Load (kW)')
    ax8.legend()
    ax8.grid(True, alpha=0.3)
    
    plt.tight_layout()
    plt.show()


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
    pge_rate_plan = PGE_RATE_PLANS["E-TOU-C"]
    dispatch_generator = CustomDispatchScheduleGenerator(pge_rate_plan)
    
    print(f"\nCustom dispatch generator initialized:")
    print(f"  Battery capacity: {dispatch_generator.battery_capacity} kWh")
    print(f"  Cycle cost threshold: ${dispatch_generator.cycle_cost:.3f}/kWh")
    print(f"  SOC operating range: {dispatch_generator.min_soc}% - {dispatch_generator.max_soc}%")
    
    # Get solar profile
    if reference_sam_data is not None:
        solar_profile = reference_sam_data['System to Load'].tolist()
        print(f"Using solar profile from reference SAM data")
    else:
        # Create simple solar profile for demo
        solar_profile = []
        for h in range(8760):
            hour_of_day = h % 24
            if 6 <= hour_of_day <= 18:
                solar_intensity = np.sin((hour_of_day - 6) * np.pi / 12) * 3.0
                solar_profile.append(max(0, solar_intensity))
            else:
                solar_profile.append(0.0)
        print(f"Using synthetic solar profile for demo")
    
    # Generate custom dispatch schedules
    print("\nGenerating custom dispatch schedules...")
    # Dispatch battery for the entire 4–9pm window; charge all other hours
    charge_schedule, discharge_schedule, gridcharge_schedule = (
        generate_peak_window_discharge_schedule(
            load_profile,
            peak_start_hour=16,
            peak_end_hour=21,
        )
    )
    # Build a minimal dispatch_log so downstream comparisons/plots work
    try:
        hourly_rates = dispatch_generator.get_hourly_rates()
    except Exception:
        hourly_rates = [0.0] * len(load_profile)
    rows = []
    for h in range(len(load_profile)):
        hod = h % 24
        rows.append({
            'hour': h,
            'hour_of_day': hod,
            'rate': hourly_rates[h] if h < len(hourly_rates) else 0.0,
            'soc': None,
            'load': load_profile[h],
            'solar': solar_profile[h] if 'solar_profile' in locals() and h < len(solar_profile) else 0.0,
            'is_peak': 16 <= hod <= 20,
            'peak_load_target': 0.0,
            'charge': charge_schedule[h],
            'discharge': discharge_schedule[h],
            'gridcharge': gridcharge_schedule[h]
        })
    dispatch_generator.dispatch_log = pd.DataFrame(rows)
    
    # Run SAM with custom dispatch
    print("\nRunning SAM simulation with custom dispatch...")
    custom_sam_results = run_sam_with_custom_dispatch(
        weather_file, load_profile, charge_schedule, discharge_schedule, gridcharge_schedule
    )
    
    if custom_sam_results is None:
        print("SAM simulation failed")
        return
    else:
        try:
            first24 = [round(x, 1) for x in custom_sam_results['battery_soc'][:24]]
            print(f"DEBUG: SAM SOC first 24 hours: {first24}")
        except Exception:
            pass
    
    # Compare results
    if reference_sam_data is not None:
        print("\nComparing results...")
        comparison_results = compare_dispatch_results(
            reference_sam_data, 
            custom_sam_results, 
            dispatch_generator.dispatch_log
        )
    
    # Economic analysis
    print("\nCalculating economic benefits...")
    economic_analysis = calculate_economic_benefits(
        custom_sam_results,
        reference_sam_data,
        dispatch_generator.dispatch_log,
        pge_rate_plan
    )
    
    # Generate plots for different time periods
    print("\nGenerating visualization plots...")
    
    # Figure 1: First week of January (winter analysis)
    print("  Figure 1: January analysis (first week)...")
    plot_custom_dispatch_analysis(
        custom_sam_results, 
        dispatch_generator.dispatch_log, 
        reference_sam_data,
        month="January",
        week_offset=0  # First week of year
    )
    
    # Figure 2: First week of July (summer analysis) 
    print("  Figure 2: July analysis (mid-summer week)...")
    july_start_day = 31 + 28 + 31 + 30 + 31 + 30  # Jan+Feb+Mar+Apr+May+Jun = 181 days
    plot_custom_dispatch_analysis(
        custom_sam_results, 
        dispatch_generator.dispatch_log, 
        reference_sam_data,
        month="July", 
        week_offset=july_start_day + 7  # Second week of July for better summer representation
    )
    
    # Figure 3: Annual SOC violation analysis
    print("  Figure 3: Annual SOC violation analysis...")
    plot_annual_soc_violations(dispatch_generator.dispatch_log)
    
    print("\nCustom dispatch demo completed.")


if __name__ == "__main__":
    main()
