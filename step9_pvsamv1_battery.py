"""
Step 9: Run SAM Model for Solar Storage using Pvsamv1 battery implementation

This is a drop-in replacement for step9_run_sam_model_for_solar_storage.py that uses
the pvsamv1_battery implementation instead of the legacy PvWatts + BattWatts approach.

Key differences:
- Uses PySAM.Pvsamv1 with integrated battery modeling
- Implements manual dispatch with predictive scheduling
- Uses exact parameters from pvsamv1_battery.py demonstration script
"""

import os
import json
import pandas as pd
import statistics
from typing import List, Dict, Any, Optional, Tuple

import PySAM.Pvsamv1 as Pvsamv1
import PySAM.ResourceTools as ResourceTools

from main_helpers import get_counties, get_scenario_path, log, format_load_profile, to_decimal_number, norcal_counties, central_counties, socal_counties

# Constants from original step9
LOADPROFILE_FILE_PREFIX = "combined_profiles"
TOTAL_LOAD_COLUMN_NAME = "electricity.real_and_simulated.for_typical_county_home.kwh"
OUTPUT_LOADPROFILE_FILE_PREFIX = "sam_optimized_load_profiles"
SOLAR_STORAGE_CAPACITY_PREFIX = "electrified_assets"
CAPITAL_COSTS_FOLDER_NAME = "CAPITAL_COSTS"

# Constants from pvsamv1_battery.py
MIN_SOC = 25
MAX_SOC = 90
INITIAL_SOC = 50
DISPATCH_MODE = 3  # Manual dispatch
GRID_INTERCONNECTION_LIMIT_KWAC = 0
CAN_EXPORT_TO_GRID = 0
ENABLE_PREDICTIVE_DISPATCH = True
BATTERY_EFFICIENCY = 5
PEAK_START_HOUR = 16
PEAK_END_HOUR = 21
BATTERY_CAPACITY_KWH = 13.5

# Solar charging control defaults (exact SAM parameter values)
DISPATCH_MANUAL_SYSTEM_CHARGE_FIRST = 1
BATT_DISPATCH_AUTO_CAN_CHARGE = 1
BATT_DISPATCH_CHARGE_ONLY_SYSTEM_EXCEEDS_LOAD = 0
BATT_DISPATCH_DISCHARGE_ONLY_LOAD_EXCEEDS_SYSTEM = 0
BATT_DISPATCH_AUTO_CAN_GRIDCHARGE = 1

# Efficiency defaults
BATT_DC_DC_EFFICIENCY = 96.0

# Time window defaults (hours 0-23)
SOLAR_CHARGING_START_HOUR = 6
SOLAR_CHARGING_END_HOUR = 15
PEAK_DISCHARGE_START_HOUR = 16
PEAK_DISCHARGE_END_HOUR = 21


def calculate_peak_energy_requirements(load_forecast: List[float], day_index: int, battery_efficiency: float = 0.90) -> Dict[str, float]:
    """Calculate energy needed for 4-9pm peak period including efficiency losses."""
    peak_start = 16
    peak_end = 21
    
    peak_load_kwh = 0.0
    day_start_hour = day_index * 24
    
    for hour in range(peak_start, peak_end):
        hour_index = day_start_hour + hour
        if hour_index < len(load_forecast):
            peak_load_kwh += load_forecast[hour_index]
    
    energy_to_store_kwh = peak_load_kwh / battery_efficiency
    efficiency_loss_kwh = energy_to_store_kwh - peak_load_kwh
    
    return {
        'peak_load_kwh': peak_load_kwh,
        'energy_to_store_kwh': energy_to_store_kwh,
        'efficiency_loss_kwh': efficiency_loss_kwh
    }


def calculate_precharge_target_soc(peak_energy_req: Dict[str, float], battery_capacity_kwh: float = 13.5, min_soc: float = 20.0, max_soc: float = 90.0) -> Dict[str, float]:
    """Calculate target SOC needed by 4pm to serve peak load."""
    min_energy_kwh = (min_soc / 100.0) * battery_capacity_kwh
    target_energy_kwh = min_energy_kwh + peak_energy_req['energy_to_store_kwh']
    target_soc = min(max_soc, (target_energy_kwh / battery_capacity_kwh) * 100.0)
    
    return {
        'target_soc': target_soc,
        'target_energy_kwh': target_energy_kwh,
        'precharge_energy_kwh': peak_energy_req['energy_to_store_kwh']
    }


def compose_battery_charge_schedule(load_forecast: List[float], solar_forecast: Optional[List[float]] = None, 
                                  battery_capacity_kwh: float = 13.5, battery_efficiency: float = 0.90,
                                  min_soc: float = 20.0, max_soc: float = 90.0) -> Dict[str, Any]:
    """Create predictive battery dispatch schedules optimized for California TOU rates."""
    if len(load_forecast) != 8760:
        raise ValueError(f"Load forecast must be 8760 hours, got {len(load_forecast)}")
    
    grid_charge_percent = [0.0] * 8760
    discharge_percent = [0.0] * 8760
    
    peak_coverage_days = 0
    total_grid_charging_kwh = 0.0
    total_efficiency_losses_kwh = 0.0
    
    for day in range(365):
        day_start = day * 24
        
        peak_req = calculate_peak_energy_requirements(load_forecast, day, battery_efficiency)
        target_info = calculate_precharge_target_soc(peak_req, battery_capacity_kwh, min_soc, max_soc)
        
        total_efficiency_losses_kwh += peak_req['efficiency_loss_kwh']
        
        # Charging schedule (6am-4pm)
        cumulative_stored_kwh = 0.0
        for hour in range(6, 16):
            hour_index = day_start + hour
            
            # Solar charging priority
            if solar_forecast and hour_index < len(solar_forecast):
                solar_gen = solar_forecast[hour_index]
                load = load_forecast[hour_index] if hour_index < len(load_forecast) else 0.0
                excess_solar = max(0.0, solar_gen - load)
                
                energy_still_needed = peak_req['energy_to_store_kwh'] - cumulative_stored_kwh
                if energy_still_needed > 0 and excess_solar > 0:
                    solar_charge_kwh = min(excess_solar, energy_still_needed)
                    cumulative_stored_kwh += solar_charge_kwh
            
            # Grid backup charging if solar insufficient (after 10am)
            if hour >= 10:
                energy_still_needed = peak_req['energy_to_store_kwh'] - cumulative_stored_kwh
                if energy_still_needed > 0:
                    max_hourly_charge = min(5.0, energy_still_needed)
                    grid_charge_percent[hour_index] = min(100.0, (max_hourly_charge / battery_capacity_kwh) * 100.0)
                    cumulative_stored_kwh += max_hourly_charge
                    total_grid_charging_kwh += max_hourly_charge
        
        # Discharge schedule (4pm-9pm)
        available_discharge_energy = ((target_info['target_soc'] - min_soc) / 100.0) * battery_capacity_kwh
        peak_loads = []
        for hour in range(16, 21):
            hour_index = day_start + hour
            load = load_forecast[hour_index] if hour_index < len(load_forecast) else 0.0
            peak_loads.append(load)
        
        total_peak_load = sum(peak_loads)
        peak_coverage = 0.0
        
        if total_peak_load > 0:
            for i, load in enumerate(peak_loads):
                hour_index = day_start + 16 + i
                load_fraction = load / total_peak_load
                desired_discharge_kwh = min(available_discharge_energy * load_fraction, load)
                
                if desired_discharge_kwh > 0:
                    discharge_percent[hour_index] = min(100.0, (desired_discharge_kwh / battery_capacity_kwh) * 100.0)
                    peak_coverage += min(desired_discharge_kwh, load)
        
        if peak_coverage >= total_peak_load * 0.8:
            peak_coverage_days += 1
    
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


def prepare_data_and_compute_system_capacity(weather_file: str, load_file: str, years_of_analysis: int):
    """Prepare weather and load data, compute system capacity using simplified approach."""
    # Load weather data from NREL API
    solar_resource_data = ResourceTools.SAM_CSV_to_solar_data(weather_file)
    
    # Convert weather data from UTC to Pacific Time (8-hour shift)
    weather_arrays = ['dn', 'df', 'gh', 'tdry', 'tdew', 'rhum', 'wdir', 'wspd']
    utc_to_pst_shift = 8
    
    for array_name in weather_arrays:
        if array_name in solar_resource_data:
            original_array = solar_resource_data[array_name]
            solar_resource_data[array_name] = [original_array[(i + utc_to_pst_shift) % 8760] for i in range(8760)]
    
    # Load profile
    load_data = pd.read_csv(load_file)
    load_profile = load_data[TOTAL_LOAD_COLUMN_NAME].tolist()
    annual_load_kWh = sum(load_profile)
    
    log(
        debug_load_profile_sample=load_profile[:10],
        debug_load_profile_min=min(load_profile),
        debug_load_profile_max=max(load_profile),
        debug_load_profile_mean=statistics.mean(load_profile),
        debug_annual_load_kWh=annual_load_kWh,
    )
    
    # Solar irradiance analysis
    gh_w_per_m2 = solar_resource_data["gh"]
    mean_gh_w_per_m2 = statistics.mean(gh_w_per_m2)
    daily_irradiance_kWh_per_m2_per_day = mean_gh_w_per_m2 * 24 / 1000
    
    log(
        debug_mean_irradiance_w_per_m2=mean_gh_w_per_m2,
        debug_daily_irradiance_kWh_per_m2=daily_irradiance_kWh_per_m2_per_day,
    )
    
    # Simplified system sizing based on annual load
    # Use similar logic to original but simplified
    annual_irradiance_kWh_per_m2 = daily_irradiance_kWh_per_m2_per_day * 365
    pv_cell_efficiency = 0.206
    system_performance_ratio = 0.80
    annual_energy_production_kWh_per_m2 = (annual_irradiance_kWh_per_m2 * 
                                          pv_cell_efficiency * 
                                          system_performance_ratio)
    
    panel_nameplate_power_density_kW_per_m2 = 0.193
    required_panel_area_m2 = annual_load_kWh / annual_energy_production_kWh_per_m2
    required_dc_capacity_kW = required_panel_area_m2 * panel_nameplate_power_density_kW_per_m2
    
    log(
        debug_required_panel_area_m2=required_panel_area_m2,
        debug_required_dc_capacity_kW=required_dc_capacity_kW,
    )
    
    return solar_resource_data, load_profile, required_dc_capacity_kW


def create_pvsamv1_model(solar_resource_data: Dict, load_profile: List[float], system_capacity: float, years_of_analysis: int) -> Pvsamv1.Pvsamv1:
    """Create and configure PySAM Pvsamv1 model with battery integration."""
    pv = Pvsamv1.new()
    
    # Load configuration from SAM_Detailed_PV_Battery preset
    dir_path = "./SAM_Detailed_PV_Battery/"
    json_file = "untitled_pvsamv1.json"
    
    with open(os.path.join(dir_path, json_file), 'r') as file:
        data = json.load(file)
        for k, v in data.items():
            if k != "number_inputs":
                try:
                    pv.value(k, v)
                except Exception:
                    pass  # Skip failed parameters
    
    # Override with specific configuration
    pv.SolarResource.solar_resource_data = solar_resource_data
    pv.value("load", load_profile)
    pv.value("crit_load", [0.0] * len(load_profile))
    pv.value("batt_load_ac_forecast", load_profile)
    
    # System sizing
    pv.SystemDesign.system_capacity = system_capacity
    pv.Lifetime.dc_degradation = [0.5] * years_of_analysis
    
    # Battery configuration from pvsamv1_battery constants
    pv.value("batt_minimum_SOC", MIN_SOC)
    pv.value("batt_maximum_SOC", MAX_SOC)
    pv.value("batt_initial_SOC", INITIAL_SOC)
    pv.value("batt_dispatch_choice", DISPATCH_MODE)
    pv.value("grid_interconnection_limit_kwac", GRID_INTERCONNECTION_LIMIT_KWAC)
    pv.value("batt_dispatch_auto_btm_can_discharge_to_grid", CAN_EXPORT_TO_GRID)
    
    # Solar charging control flags
    pv.value("en_standalone_batt", 0)
    pv.value("dispatch_manual_system_charge_first", DISPATCH_MANUAL_SYSTEM_CHARGE_FIRST)
    pv.value("batt_dispatch_auto_can_charge", BATT_DISPATCH_AUTO_CAN_CHARGE)
    pv.value("batt_dispatch_auto_can_clipcharge", 1)
    pv.value("batt_dispatch_charge_only_system_exceeds_load", BATT_DISPATCH_CHARGE_ONLY_SYSTEM_EXCEEDS_LOAD)
    pv.value("batt_dispatch_discharge_only_load_exceeds_system", BATT_DISPATCH_DISCHARGE_ONLY_LOAD_EXCEEDS_SYSTEM)
    pv.value("batt_dispatch_auto_can_gridcharge", BATT_DISPATCH_AUTO_CAN_GRIDCHARGE)
    
    # Efficiency parameters
    pv.value("batt_dc_dc_efficiency", BATT_DC_DC_EFFICIENCY)
    
    log(solar_system_capacity=system_capacity)
    
    return pv


def apply_dispatch_schedule(pv: Pvsamv1.Pvsamv1, dispatch_schedule: Dict[str, Any]) -> None:
    """Apply the predictive dispatch schedule to the SAM model."""
    log_section_title = "Applying Dispatch Schedule Configuration"
    print(f"\n{'=' * 80}\n{log_section_title}\n{'=' * 80}")
    
    # Set manual dispatch mode
    pv.value('batt_dispatch_choice', 3)
    print(f"Set dispatch mode: 3 (Manual Dispatch)")
    
    # Define daily schedule matrix based on time windows
    schedule_matrix = [
        [1, 1, 1, 1, 1, 1, 2, 2, 2, 2, 2, 2, 2, 2, 2, 3, 3, 3, 3, 3, 3, 3, 1, 1]
    ] * 12  # Same pattern for all 12 months
    
    schedule_matrix_weekend = [
        [1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1]
    ] * 12  # Off-peak for weekends
    
    pv.value('dispatch_manual_sched', schedule_matrix)
    pv.value('dispatch_manual_sched_weekend', schedule_matrix_weekend)
    print(f"Applied period schedule: Night(1), Solar(2), Peak(3)")
    
    # Period action configuration
    pv.value('dispatch_manual_charge', [1, 1, 0, 0, 0, 0])
    pv.value("dispatch_manual_discharge", [1, 1, 1, 1, 0, 0])
    pv.value('dispatch_manual_percent_discharge', [0, 0, 10, 10, 0, 0])
    pv.value("dispatch_manual_btm_discharge_to_grid", [0, 0, 0, 0, 0, 0])
    pv.value("dispatch_manual_gridcharge", [1, 1, 0, 0, 0, 0])
    pv.value("dispatch_manual_percent_gridcharge", [100, 100, 0, 0, 0, 0])
    
    # Apply the calculated dispatch schedules
    grid_charge = dispatch_schedule.get('dispatch_manual_percent_gridcharge', [])
    discharge = dispatch_schedule.get('dispatch_manual_percent_discharge', [])
    
    if grid_charge:
        # Override with predictive schedule
        pv.value("dispatch_manual_percent_gridcharge", grid_charge)
    
    if discharge:
        # Override with predictive schedule  
        pv.value("dispatch_manual_percent_discharge", discharge)
    
    # Report dispatch schedule metrics
    metrics = dispatch_schedule.get('validation_metrics', {})
    if metrics:
        print(f"Schedule validation:")
        print(f"  Peak coverage: {metrics.get('peak_coverage_percentage', 0):.1f}%")
        print(f"  Annual grid charging: {metrics.get('annual_grid_charging_kwh', 0):.1f} kWh")
        print(f"  Annual efficiency losses: {metrics.get('annual_efficiency_losses_kwh', 0):.1f} kWh")


def run_model_and_extract_outputs(pv: Pvsamv1.Pvsamv1, load_profile: List[float]) -> Tuple:
    """Execute PvSamv1 model and extract outputs in format compatible with original step9."""
    pv.execute(0)
    
    outputs = pv.Outputs.export()
    
    # Extract power flows
    system_to_load = outputs.get('system_to_load', [])
    batt_to_load = outputs.get('batt_to_load', [])
    grid_to_load = outputs.get('grid_to_load', [])
    grid_to_batt = outputs.get('grid_to_batt', [])
    system_to_batt = outputs.get('system_to_batt', [])
    system_to_batt_dc = outputs.get('system_to_batt_dc', [])
    system_to_grid = outputs.get('system_to_grid', [])
    battery_soc = outputs.get('batt_SOC', [])
    
    # Handle sub-hourly timesteps by aggregating to hourly
    def aggregate_to_hourly(data, expected_length=8760, is_power_flow=True):
        """Convert sub-hourly data to hourly by summing (for power flows) or averaging (for SOC)."""
        if not data or len(data) == expected_length:
            return list(data)
        
        if len(data) % expected_length != 0:
            print(f"Warning: Data length {len(data)} not evenly divisible by {expected_length}")
            # Truncate to nearest multiple
            data = data[:len(data) - (len(data) % expected_length)]
        
        # Calculate aggregation factor
        factor = len(data) // expected_length
        print(f"Aggregating sub-hourly data: {len(data)} points -> {expected_length} hourly (factor: {factor})")
        
        # Sum sub-hourly values for power flows (to get total energy per hour)
        # Average for state variables like SOC
        hourly_data = []
        for i in range(expected_length):
            start_idx = i * factor
            end_idx = start_idx + factor
            if is_power_flow:
                # Sum power flows to get total energy per hour
                hourly_value = sum(data[start_idx:end_idx])
            else:
                # Average state variables like SOC
                hourly_value = sum(data[start_idx:end_idx]) / factor
            hourly_data.append(hourly_value)
        
        return hourly_data
    
    # Aggregate all power flow arrays to hourly (sum sub-hourly values)
    system_to_load = aggregate_to_hourly(system_to_load, is_power_flow=True)
    batt_to_load = aggregate_to_hourly(batt_to_load, is_power_flow=True)
    grid_to_load = aggregate_to_hourly(grid_to_load, is_power_flow=True)
    grid_to_batt = aggregate_to_hourly(grid_to_batt, is_power_flow=True)
    system_to_batt = aggregate_to_hourly(system_to_batt, is_power_flow=True)
    system_to_batt_dc = aggregate_to_hourly(system_to_batt_dc, is_power_flow=True)
    system_to_grid = aggregate_to_hourly(system_to_grid, is_power_flow=True)
    
    # Average SOC values (state variable, not power flow)
    battery_soc = aggregate_to_hourly(battery_soc, is_power_flow=False)
    
    # Calculate combined flows
    solar_battery_to_load = [s + b for s, b in zip(system_to_load, batt_to_load)]
    total_supply = [s + b + g for s, b, g in zip(system_to_load, batt_to_load, grid_to_load)]
    difference = [l - t for l, t in zip(load_profile, total_supply)]
    
    # Get capacities
    try:
        solar_capacity = pv.value("system_capacity")
    except:
        solar_capacity = pv.SystemDesign.system_capacity
    
    try:
        battery_capacity = outputs.get('batt_bank_installed_capacity', BATTERY_CAPACITY_KWH)
    except:
        battery_capacity = BATTERY_CAPACITY_KWH
    
    return (system_to_load, batt_to_load, grid_to_load, solar_battery_to_load, total_supply, difference,
            grid_to_batt, system_to_batt, system_to_batt_dc, system_to_grid, load_profile, battery_soc,
            solar_capacity, battery_capacity)


def log_first_day_power_allocation(county: str, load_profile: List[float], system_to_load: List[float],
                                  batt_to_load: List[float], system_to_batt: List[float], 
                                  system_to_grid: List[float], battery_soc: List[float]) -> None:
    """Log the first-day power allocation table showing hour-by-hour energy flows."""
    print(f"\n{'=' * 80}")
    print(f"First-Day Power Allocation Table - {county}")
    print(f"{'=' * 80}")
    print(f"{'hour':>4} {'hod':>3}  {'Load(kWh)':>9}   {'PV(kWh)':>8}  {'PV->Batt':>8}  {'PV->Load':>8}  {'PV->Grid':>8}   {'Batt->Load':>9}  {'Batt(kWh)':>9}   {'Residual':>8}")
    
    # Calculate derived values for first 24 hours
    for hour in range(24):
        if hour >= len(load_profile):
            break
            
        load = load_profile[hour]
        pv_total = system_to_load[hour] + system_to_batt[hour] + system_to_grid[hour]
        pv_to_batt = system_to_batt[hour] 
        pv_to_load = system_to_load[hour]
        pv_to_grid = system_to_grid[hour]
        batt_to_load_val = batt_to_load[hour]
        batt_energy = battery_soc[hour] * BATTERY_CAPACITY_KWH / 100.0  # Convert SOC% to kWh
        
        # Calculate residual (unmet load from grid)
        residual = max(0, load - pv_to_load - batt_to_load_val)
        
        # Hour of day (hod) is just the hour within the day
        hod = hour
        
        print(f"{hour:4d} {hod:3d}      {load:5.3f}     {pv_total:5.3f}     {pv_to_batt:5.3f}     {pv_to_load:5.3f}     {pv_to_grid:5.3f}         {batt_to_load_val:5.3f}       {batt_energy:5.3f}      {residual:5.3f}")


def validate_and_save_results(county: str, load_profile: List[float], system_to_load: List[float], 
                            batt_to_load: List[float], grid_to_load: List[float], 
                            solar_battery_to_load: List[float], total_supply: List[float], 
                            difference: List[float], output_file: str, grid_to_batt: List[float], 
                            system_to_batt: List[float], system_to_batt_dc: List[float], 
                            system_to_grid: List[float], load: List[float], battery_soc: List[float]) -> None:
    """Validate results and save to CSV file (same format as original step9)."""
    max_difference = max(abs(d) for d in difference)
    
    if max_difference > 1e-6:
        print(f"Warning: Discrepancy found in {county}. Max difference: {max_difference}")
    
    os.makedirs(os.path.dirname(output_file), exist_ok=True)
    date_range = pd.date_range(start='2018-01-01', periods=8760, freq='H')
    
    df = pd.DataFrame({
        'Load Profile': load_profile,
        'System to Load': system_to_load,
        'Battery to Load': batt_to_load,
        'Grid to Load': grid_to_load,
        'Solar + Battery to Load': solar_battery_to_load,
        'Total Supply': total_supply,
        'Difference': difference,
        'System to Battery': system_to_batt,
        'Grid to Battery': grid_to_batt,
        'Battery SOC': battery_soc,
    }, index=date_range)
    
    log(
        at="step9_pvsamv1_battery",
        load_profile=format_load_profile(load_profile),
        solar_to_load=format_load_profile(system_to_load),
        battery_to_load=format_load_profile(batt_to_load),
        grid_to_load=format_load_profile(grid_to_load),
        solar_battery_to_load=format_load_profile(solar_battery_to_load),
        total_supply=format_load_profile(total_supply),
        difference=format_load_profile(difference),
        grid_to_batt=format_load_profile(grid_to_batt),
        system_to_batt=format_load_profile(system_to_batt),
        system_to_batt_dc=format_load_profile(system_to_batt_dc),
        system_to_grid=format_load_profile(system_to_grid),
        load=format_load_profile(load),
        saved_to=output_file,
    )
    
    df.to_csv(output_file)


def process(base_input_dir: str, base_output_dir: str, scenario: str, housing_type: str, 
           counties: Optional[List[str]] = None, years_of_analysis: int = 1, force_recompute: bool = False):
    """Main processing function - drop-in replacement for original step9 process function."""
    scenario_path = get_scenario_path(base_input_dir, scenario, housing_type)
    counties_to_run = get_counties(scenario_path, counties)
    capacity_dict = {}
    
    for county in counties_to_run:
        try:
            log(county=county)
            
            weather_file = os.path.join(base_input_dir, scenario, housing_type, county, f"weather_TMY_{county}.csv")
            load_file = os.path.join(scenario_path, county, f"{LOADPROFILE_FILE_PREFIX}_{scenario}_{county}.csv")
            output_file = os.path.join(base_output_dir, scenario, housing_type, county, f"{OUTPUT_LOADPROFILE_FILE_PREFIX}_{county}.csv")
            
            # Skip if output file already exists and force_recompute is False
            if not force_recompute and os.path.exists(output_file):
                print(f"Output file already exists: {output_file}. Skipping... (use force_recompute=True to rebuild)")
                continue
            
            if not os.path.exists(weather_file):
                print(f"Weather file not found: {weather_file}. Skipping...")
                continue
            if not os.path.exists(load_file):
                print(f"Load file not found: {load_file}. Skipping...")
                continue
            
            # Prepare data and compute system capacity
            solar_resource_data, load_profile, system_capacity = prepare_data_and_compute_system_capacity(
                weather_file, load_file, years_of_analysis)
            
            # Create PvSamv1 model with battery
            pv = create_pvsamv1_model(solar_resource_data, load_profile, system_capacity, years_of_analysis)
            
            # Generate predictive dispatch schedule
            dispatch_schedule = compose_battery_charge_schedule(
                load_forecast=load_profile,
                solar_forecast=None,  # Will be calculated after execution
                battery_capacity_kwh=BATTERY_CAPACITY_KWH,
                battery_efficiency=0.90,
                min_soc=MIN_SOC,
                max_soc=MAX_SOC
            )
            
            # Apply dispatch schedule
            apply_dispatch_schedule(pv, dispatch_schedule)
            
            # Run model and extract outputs
            (system_to_load, batt_to_load, grid_to_load, solar_battery_to_load, total_supply, difference,
             grid_to_batt, system_to_batt, system_to_batt_dc, system_to_grid, load, battery_soc,
             solar_capacity, battery_capacity) = run_model_and_extract_outputs(pv, load_profile)
            
            capacity_dict[county] = {
                "Solar Capacity (kW)": to_decimal_number(solar_capacity),
                "Battery Capacity (kWh)": to_decimal_number(battery_capacity)
            }
            
            # Log first-day power allocation table
            log_first_day_power_allocation(county, load_profile, system_to_load, batt_to_load, 
                                         system_to_batt, system_to_grid, battery_soc)
            
            validate_and_save_results(county, load_profile, system_to_load, batt_to_load, grid_to_load,
                                    solar_battery_to_load, total_supply, difference, output_file,
                                    grid_to_batt, system_to_batt, system_to_batt_dc, system_to_grid,
                                    load, battery_soc)
                                    
        except Exception as e:
            print(f"Error processing {county}: {e}")
            import traceback
            traceback.print_exc()
    
    # Save capacity data
    capital_costs_folder = f"{base_input_dir}/{scenario}/{housing_type}/{CAPITAL_COSTS_FOLDER_NAME}"
    os.makedirs(capital_costs_folder, exist_ok=True)
    
    capacity_df = pd.DataFrame.from_dict(capacity_dict, orient='index').rename_axis('County')
    output_csv_path = f"{capital_costs_folder}/{SOLAR_STORAGE_CAPACITY_PREFIX}.csv"
    capacity_df.to_csv(output_csv_path)


# Example usage
scenario = "heat_pump"
housing_type = "single-family-detached"

if __name__ == '__main__':
    process("data/loadprofiles", "data/loadprofiles", scenario, housing_type, 
           ["Alameda County"], force_recompute=True)