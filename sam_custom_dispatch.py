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
        Generate SAM custom dispatch schedule arrays
        Returns: (charge_schedule, discharge_schedule, gridcharge_schedule)
        """
        hours = len(load_profile)
        hourly_rates = self.get_hourly_rates()
        
        # Initialize dispatch arrays (0 = no action, values 0-1 represent fraction of max power)
        charge_schedule = np.zeros(hours)      # Battery charging from excess solar
        discharge_schedule = np.zeros(hours)   # Battery discharging to load
        gridcharge_schedule = np.zeros(hours)  # Battery charging from grid
        
        # Simulate battery SOC to inform dispatch decisions
        current_soc = 50.0  # Start at 50% SOC
        battery_kwh = current_soc / 100 * self.battery_capacity
        
        # Track hourly decisions for analysis
        dispatch_log = []
        
        for h in range(hours):
            load = load_profile[h]
            solar = solar_profile[h] if solar_profile else 0
            rate = hourly_rates[h]
            net_load = load - solar  # Positive = need more energy, Negative = excess solar
            
            # Decision variables
            charge_action = 0.0
            discharge_action = 0.0
            gridcharge_action = 0.0
            
            # Strategy 1: Handle excess solar (charge battery when possible)
            if net_load < 0 and current_soc < self.max_soc:
                excess_energy = abs(net_load)
                battery_capacity_available = (self.max_soc - current_soc) / 100 * self.battery_capacity
                
                if battery_capacity_available > 0:
                    # Charge from excess solar (prioritize this over grid charging)
                    charge_amount = min(excess_energy, battery_capacity_available, 5.0)  # 5kW max charge rate
                    charge_action = charge_amount / 5.0  # Normalize to 0-1
                    battery_kwh += charge_amount
                    current_soc = (battery_kwh / self.battery_capacity) * 100
            
            # Strategy 2: Discharge during high-rate periods when economically justified
            elif net_load > 0 and current_soc > self.min_soc:
                battery_available = battery_kwh - (self.min_soc / 100 * self.battery_capacity)
                
                if battery_available > 0 and rate > self.cycle_cost:
                    # Economic discharge: rate exceeds battery degradation cost
                    discharge_amount = min(net_load, battery_available, 5.0)  # 5kW max discharge rate
                    discharge_action = discharge_amount / 5.0  # Normalize to 0-1
                    battery_kwh -= discharge_amount
                    current_soc = (battery_kwh / self.battery_capacity) * 100
            
            # Strategy 3: Grid charging during very low-rate periods
            if rate < self.cycle_cost * 0.6 and current_soc < 90:  # Very cheap electricity
                battery_capacity_available = (90 - current_soc) / 100 * self.battery_capacity  # Don't charge to 100%
                
                if battery_capacity_available > 0:
                    # Charge from grid during super off-peak
                    gridcharge_amount = min(battery_capacity_available, 2.0)  # 2kW grid charging
                    gridcharge_action = gridcharge_amount / 5.0  # Normalize to 0-1 scale
                    battery_kwh += gridcharge_amount
                    current_soc = (battery_kwh / self.battery_capacity) * 100
            
            # Store dispatch decisions
            charge_schedule[h] = charge_action
            discharge_schedule[h] = discharge_action
            gridcharge_schedule[h] = gridcharge_action
            
            # Log for analysis
            dispatch_log.append({
                'hour': h,
                'rate': rate,
                'soc': current_soc,
                'load': load,
                'solar': solar,
                'net_load': net_load,
                'charge': charge_action,
                'discharge': discharge_action,
                'gridcharge': gridcharge_action
            })
        
        self.dispatch_log = pd.DataFrame(dispatch_log)
        
        return charge_schedule, discharge_schedule, gridcharge_schedule
    
    def analyze_dispatch_strategy(self):
        """Analyze the generated dispatch strategy"""
        if not hasattr(self, 'dispatch_log'):
            print("No dispatch log available. Run generate_custom_dispatch_schedule first.")
            return
        
        log = self.dispatch_log
        
        # Calculate statistics
        total_charge_events = (log['charge'] > 0).sum()
        total_discharge_events = (log['discharge'] > 0).sum()
        total_gridcharge_events = (log['gridcharge'] > 0).sum()
        
        avg_discharge_rate = log[log['discharge'] > 0]['rate'].mean()
        avg_gridcharge_rate = log[log['gridcharge'] > 0]['rate'].mean()
        
        min_soc = log['soc'].min()
        max_soc = log['soc'].max()
        avg_soc = log['soc'].mean()
        
        print("Custom Dispatch Strategy Analysis")
        print("=" * 45)
        print(f"Charge events (solar):        {total_charge_events:,} hours")
        print(f"Discharge events:             {total_discharge_events:,} hours")
        print(f"Grid charge events:           {total_gridcharge_events:,} hours")
        print()
        print(f"Avg discharge rate:           ${avg_discharge_rate:.3f}/kWh" if not np.isnan(avg_discharge_rate) else "Avg discharge rate:           N/A")
        print(f"Avg grid charge rate:         ${avg_gridcharge_rate:.3f}/kWh" if not np.isnan(avg_gridcharge_rate) else "Avg grid charge rate:         N/A")
        print(f"Battery cycle cost:           ${self.cycle_cost:.3f}/kWh")
        print()
        print(f"SOC range: {min_soc:.1f}% - {max_soc:.1f}% (avg: {avg_soc:.1f}%)")
        
        return {
            'charge_events': total_charge_events,
            'discharge_events': total_discharge_events,
            'gridcharge_events': total_gridcharge_events,
            'avg_discharge_rate': avg_discharge_rate,
            'avg_gridcharge_rate': avg_gridcharge_rate,
            'min_soc': min_soc,
            'max_soc': max_soc,
            'avg_soc': avg_soc
        }


def initialize_solar(weather_file, load_profile, charge_schedule, discharge_schedule, gridcharge_schedule):
    """Initialize SAM solar model with configuration"""
    print("DEBUG: Starting SAM configuration...")
        
    # Load solar resource data
    print("DEBUG: Loading solar resource data...")
    solar_resource_data = tools.SAM_CSV_to_solar_data(weather_file)
    print(f"DEBUG: Solar resource data loaded, keys: {list(solar_resource_data.keys())[:5]}...")
    
    # Calculate system capacity (simplified)
    annual_load_kwh = sum(load_profile)
    system_capacity = annual_load_kwh / 1200  # Rough sizing: 1200 kWh/kW annually
    
    print(f"SAM Configuration:")
    print(f"  Annual load: {annual_load_kwh:,.0f} kWh")
    print(f"  Solar system size: {system_capacity:.1f} kW")
    
    # === Solar Model Setup ===
    print("DEBUG: Initializing solar model...")
    solar = pvwatts.new()
    print(f"DEBUG: Solar model created: {type(solar)}")
    
    # Load SAM solar configuration with debugging
    print("DEBUG: Loading solar configuration with custom dispatch...")
    solar_config_file = "SAM_configuration_with_battery_custom_dispatch/untitled__1__pvwattsv8.json"
    
    if not os.path.exists(solar_config_file):
        print(f"DEBUG: Solar config file not found: {solar_config_file}")
        return None
    
    with open(solar_config_file, 'r') as file:
        solar_config = json.load(file)
        print(f"DEBUG: Solar config loaded, {len(solar_config)} parameters")
        
        # Apply configuration with error checking
        print("DEBUG: Applying solar configuration...")
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
                print(f"DEBUG: Failed to set solar parameter '{k}': {e}")
                skipped_params.append(k)
        
        print(f"DEBUG: Applied {len(applied_params)} solar parameters")
        if skipped_params:
            print(f"DEBUG: Skipped {len(skipped_params)} solar parameters")

    # Set solar parameters with debugging
    print("DEBUG: Setting solar resource data...")
    try:
        solar.SolarResource.solar_resource_data = solar_resource_data
        print("DEBUG: Solar resource data set")
    except Exception as e:
        print(f"DEBUG: Failed to set solar resource data: {e}")
        return None
    
    print("DEBUG: Setting system capacity...")
    try:
        solar.SystemDesign.system_capacity = system_capacity
        print(f"DEBUG: System capacity set to {system_capacity:.1f} kW")
    except Exception as e:
        print(f"DEBUG: Failed to set system capacity: {e}")
        return None
    
    print("DEBUG: Setting degradation...")
    try:
        solar.Lifetime.dc_degradation = [0.5]  # 0.5% annual degradation
        print("DEBUG: Degradation set")
    except Exception as e:
        print(f"DEBUG: Failed to set degradation: {e}")
        return None
    
    return solar


def initialize_storage(weather_file, load_profile, charge_schedule, discharge_schedule, gridcharge_schedule, solar):
    """Initialize SAM battery storage model"""
    # === Battery Model Setup ===
    print("DEBUG: Creating battery model...")
    try:
        battery = battery_model.from_existing(solar)
        print(f"DEBUG: Battery model created: {type(battery)}")
    except Exception as e:
        print(f"DEBUG: Failed to create battery model: {e}")
        return None
    
    # Load SAM battery configuration with debugging
    print("DEBUG: Loading battery configuration...")
    battery_config_file = "SAM_configuration_with_battery_custom_dispatch/untitled__1__battwatts.json"
    
    if not os.path.exists(battery_config_file):
        print(f"DEBUG: Battery config file not found: {battery_config_file}")
        return None
        
    with open(battery_config_file, 'r') as file:
        battery_config = json.load(file)
        print(f"DEBUG: Battery config loaded, {len(battery_config)} parameters")
        
        # Apply configuration with error checking
        print("DEBUG: Applying battery configuration...")
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
                print(f"DEBUG: Failed to set battery parameter '{k}': {e}")
                skipped_battery_params.append(k)
        
        print(f"DEBUG: Applied {len(applied_battery_params)} battery parameters")
        if skipped_battery_params:
            print(f"DEBUG: Skipped {len(skipped_battery_params)} battery parameters")
    
    # Set load profile with debugging
    print("DEBUG: Setting load profile...")
    try:
        battery.Battery.assign({'load': load_profile})
        print(f"DEBUG: Load profile set, {len(load_profile)} hours")
    except Exception as e:
        print(f"DEBUG: Failed to set load profile: {e}")
        return None
    
    return battery


def initialize_custom_dispatch(solar, battery, load_profile, charge_schedule, discharge_schedule, gridcharge_schedule):
    """Configure SAM with custom dispatch schedules"""
    # === Configure Custom Dispatch ===
    print("DEBUG: Configuring custom dispatch...")
    
    # Load battery config for reference
    battery_config_file = "SAM_configuration_with_battery_custom_dispatch/untitled__1__battwatts.json"
    with open(battery_config_file, 'r') as file:
        battery_config = json.load(file)
    
    # Validate schedule lengths
    print(f"DEBUG: Validating schedule lengths...")
    print(f"  Load profile: {len(load_profile)} hours")
    print(f"  Charge schedule: {len(charge_schedule)} hours")
    print(f"  Discharge schedule: {len(discharge_schedule)} hours")
    print(f"  Grid charge schedule: {len(gridcharge_schedule)} hours")
    
    if not all(len(s) == len(load_profile) for s in [charge_schedule, discharge_schedule, gridcharge_schedule]):
        print("DEBUG: Schedule length mismatch!")
        return None

    # Set custom dispatch schedules
    print("DEBUG: Setting custom dispatch schedules...")
    try:
        # Convert schedules to lists if they're numpy arrays
        discharge_list = discharge_schedule.tolist() if hasattr(discharge_schedule, 'tolist') else list(discharge_schedule)
        charge_list = charge_schedule.tolist() if hasattr(charge_schedule, 'tolist') else list(charge_schedule)
        gridcharge_list = gridcharge_schedule.tolist() if hasattr(gridcharge_schedule, 'tolist') else list(gridcharge_schedule)
        
        # Try different formats for custom dispatch
        custom_dispatch_formats = [
            # Format 1: List of lists (most common)
            [discharge_list, charge_list, gridcharge_list],
            # Format 2: Flattened approach
            discharge_list + charge_list + gridcharge_list,
            # Format 3: Transposed (hour-by-hour)
            [[d, c, g] for d, c, g in zip(discharge_list, charge_list, gridcharge_list)]
        ]
        
        success = False
        for i, custom_dispatch_array in enumerate(custom_dispatch_formats):
            try:
                print(f"DEBUG: Trying custom dispatch format {i+1}...")
                battery.Battery.batt_custom_dispatch = custom_dispatch_array
                
                # Verify it was set
                check_dispatch = battery.Battery.batt_custom_dispatch
                print(f"DEBUG: Custom dispatch format {i+1} successful!")
                print(f"  Array shape: {len(custom_dispatch_array)} x {len(custom_dispatch_array[0]) if isinstance(custom_dispatch_array[0], list) else 'flat'}")
                success = True
                break
                
            except Exception as e:
                print(f"DEBUG: Format {i+1} failed: {e}")
                continue
        
        if not success:
            print("DEBUG: All custom dispatch formats failed")
            return None
            
    except Exception as e:
        print(f"DEBUG: Failed to set custom dispatch schedules: {e}")
        print(f"  Error type: {type(e)}")
        print(f"  Error details: {str(e)}")
        return None
    
    # Try to enable advanced dispatch options through config
    print("DEBUG: Setting additional dispatch parameters...")
    
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
                print(f"DEBUG: Set {param} = {value}")
        except Exception as e:
            print(f"DEBUG: Failed to set {param}: {e}")
    
    print(f"DEBUG: Custom dispatch configuration complete")


def run_sam_simulation(solar, battery):
    """Execute SAM simulation and extract results"""
    # === Run SAM Simulation ===
    print("\nRunning SAM simulation...")
    
    print("DEBUG: Executing solar model...")
    try:
        solar.execute(0)
        print("DEBUG: Solar execution completed")
    except Exception as e:
        print(f"DEBUG: Solar execution failed: {e}")
        return None
    
    print("DEBUG: Executing battery model...")
    try:
        battery.execute(0)
        print("DEBUG: Battery execution completed")
    except Exception as e:
        print(f"DEBUG: Battery execution failed: {e}")
        print(f"  Error type: {type(e)}")
        print(f"  Error details: {str(e)}")
        import traceback
        traceback.print_exc()
        return None
    
    print("SAM simulation completed")
    
    # === Extract Results ===
    print("DEBUG: Extracting results...")
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
        
        print(f"DEBUG: Results extracted successfully")
        print(f"  Solar capacity: {results['solar_capacity']:.1f} kW")
        print(f"  Battery capacity: {results['battery_capacity']:.1f} kWh")
        print(f"  Load profile length: {len(results['load_profile'])}")
        print(f"  SOC range: {min(results['battery_soc']):.1f}% - {max(results['battery_soc']):.1f}%")
        
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


def compare_dispatch_results(reference_data, custom_data, dispatch_log):
    """
    Compare reference SAM results with custom dispatch results
    """
    if reference_data is None or custom_data is None:
        print("Cannot compare results - missing data")
        return
    
    print("Dispatch Results Comparison")
    print("=" * 50)
    
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
    print(f"SOC utilization improvement: {ref_stats['avg_soc'] - custom_stats['avg_soc']:.1f} percentage points")
    
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
    
    print("Economic Analysis: Custom Dispatch")
    print("=" * 45)
    print(f"Annual electricity cost (custom):  ${custom_annual_cost:,.2f}")
    if ref_annual_cost:
        print(f"Annual electricity cost (reference): ${ref_annual_cost:,.2f}")
        print(f"Annual savings:                    ${annual_savings:,.2f}")
        print(f"Savings percentage:                {annual_savings/ref_annual_cost*100:.1f}%")
    
    print("\nDispatch Strategy Analysis:")
    print(f"Discharge events:                  {total_discharge_events:,} hours")
    print(f"Avg discharge rate:                ${avg_discharge_rate:.3f}/kWh" if not pd.isna(avg_discharge_rate) else "Avg discharge rate:                N/A")
    
    print(f"Grid charge events:                {total_gridcharge_events:,} hours")
    print(f"Avg grid charge rate:              ${avg_gridcharge_rate:.3f}/kWh" if not pd.isna(avg_gridcharge_rate) else "Avg grid charge rate:              N/A")
    
    if rate_spread > 0:
        print(f"Rate arbitrage spread:             ${rate_spread:.3f}/kWh")
        print(f"Cycle cost threshold:              ${generator.cycle_cost:.3f}/kWh")
        
        if avg_discharge_rate > generator.cycle_cost:
            print("Discharge strategy is economically justified")
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


def plot_custom_dispatch_analysis(custom_results, dispatch_log, reference_data=None):
    """
    Create comprehensive visualization of custom dispatch behavior
    """
    if custom_results is None:
        print("Cannot create plots without custom dispatch results")
        return
    
    # Use first week of January for detailed view
    week_hours = 168
    hours = range(week_hours)
    
    # Extract first week data
    custom_week = {
        'load': custom_results['load_profile'][:week_hours],
        'solar': custom_results['system_to_load'][:week_hours],
        'battery_soc': custom_results['battery_soc'][:week_hours],
        'battery_discharge': custom_results['battery_to_load'][:week_hours],
        'grid_usage': custom_results['grid_to_load'][:week_hours],
        'grid_to_battery': custom_results['grid_to_batt'][:week_hours]
    }
    
    dispatch_week = dispatch_log.iloc[:week_hours]
    
    # Create subplots
    fig, axes = plt.subplots(3, 2, figsize=(16, 14))
    fig.suptitle('SAM Custom Dispatch Analysis: First Week of January', fontsize=16, fontweight='bold')
    
    # 1. Battery SOC with dispatch signals
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
    
    ax1.axhline(y=10, color='red', linestyle='--', alpha=0.7, label='Min SOC (10%)')
    ax1.set_title('Battery SOC with Dispatch Events', fontweight='bold')
    ax1.set_ylabel('SOC (%)')
    ax1.legend()
    ax1.grid(True, alpha=0.3)
    
    plt.tight_layout()
    plt.show()


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
    print("=" * 30)
    
    # Load reference data
    reference_sam_data = None
    if os.path.exists(sam_file):
        reference_sam_data = pd.read_csv(sam_file, index_col=0, parse_dates=True)
        print(f"✓ Loaded reference SAM data for {county_name}")
    else:
        print(f"⚠ Reference SAM data not found: {sam_file}")
    
    # Load load profile
    load_profile = None
    if os.path.exists(load_file):
        load_data = pd.read_csv(load_file)
        load_profile = load_data["electricity.real_and_simulated.for_typical_county_home.kwh"].tolist()
        annual_load_kwh = sum(load_profile)
        print(f"✓ Loaded load profile: {len(load_profile)} hours, {annual_load_kwh:.0f} kWh/year")
    else:
        print(f"⚠ Load file not found: {load_file}")
        return
    
    # Check weather file
    if not os.path.exists(weather_file):
        print(f"⚠ Weather file not found: {weather_file}")
        return
    else:
        print(f"✓ Weather file found")
    
    # Initialize dispatch generator
    pge_rate_plan = PGE_RATE_PLANS["E-TOU-C"]
    dispatch_generator = CustomDispatchScheduleGenerator(pge_rate_plan)
    
    print(f"\n✓ Custom dispatch generator initialized:")
    print(f"  Battery capacity: {dispatch_generator.battery_capacity} kWh")
    print(f"  Cycle cost threshold: ${dispatch_generator.cycle_cost:.3f}/kWh")
    print(f"  SOC operating range: {dispatch_generator.min_soc}% - {dispatch_generator.max_soc}%")
    
    # Get solar profile
    if reference_sam_data is not None:
        solar_profile = reference_sam_data['System to Load'].tolist()
        print(f"✓ Using solar profile from reference SAM data")
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
        print(f"⚠ Using synthetic solar profile for demo")
    
    # Generate custom dispatch schedules
    print("\n🔄 Generating custom dispatch schedules...")
    charge_schedule, discharge_schedule, gridcharge_schedule = dispatch_generator.generate_custom_dispatch_schedule(
        load_profile, solar_profile
    )
    
    # Analyze the strategy
    print("\n📊 Analyzing dispatch strategy...")
    analysis = dispatch_generator.analyze_dispatch_strategy()
    
    # Run SAM with custom dispatch
    print("\n🚀 Running SAM simulation with custom dispatch...")
    custom_sam_results = run_sam_with_custom_dispatch(
        weather_file, load_profile, charge_schedule, discharge_schedule, gridcharge_schedule
    )
    
    if custom_sam_results is None:
        print("❌ SAM simulation failed")
        return
    
    # Compare results
    if reference_sam_data is not None:
        print("\n⚖️ Comparing results...")
        comparison_results = compare_dispatch_results(
            reference_sam_data, 
            custom_sam_results, 
            dispatch_generator.dispatch_log
        )
    
    # Economic analysis
    print("\n💰 Calculating economic benefits...")
    economic_analysis = calculate_economic_benefits(
        custom_sam_results,
        reference_sam_data,
        dispatch_generator.dispatch_log,
        pge_rate_plan
    )
    
    # Generate plots
    print("\n📈 Generating visualization plots...")
    plot_custom_dispatch_analysis(
        custom_sam_results, 
        dispatch_generator.dispatch_log, 
        reference_sam_data
    )
    
    print("\n✅ Custom dispatch demo completed successfully!")
    print("Check the displayed plots for detailed analysis.")


if __name__ == "__main__":
    main()