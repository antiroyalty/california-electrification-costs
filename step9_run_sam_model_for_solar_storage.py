import os
import PySAM.Pvwattsv8 as pvwatts # https://nrel-pysam.readthedocs.io/en/main/modules/Pvwattsv8.html
import PySAM.Battwatts as battery_model # https://nrel-pysam.readthedocs.io/en/main/modules/Battery.html
import PySAM.ResourceTools as tools
import pandas as pd
import statistics
import json

from main_helpers import get_counties, get_scenario_path, log, format_load_profile, to_decimal_number, norcal_counties, central_counties, socal_counties

# LOADPROFILE_FILE_PREFIX = "electricity_loads"
LOADPROFILE_FILE_PREFIX = "combined_profiles"
TOTAL_LOAD_COLUMN_NAME = "electricity.real_and_simulated.for_typical_county_home.kwh"
OUTPUT_LOADPROFILE_FILE_PREFIX = "sam_optimized_load_profiles"
SOLAR_STORAGE_CAPACITY_PREFIX = "electrified_assets"
CAPITAL_COSTS_FOLDER_NAME = "CAPITAL_COSTS"

def prepare_data_and_compute_system_capacity(weather_file, load_file, years_of_analysis):
    solar_resource_data = tools.SAM_CSV_to_solar_data(weather_file)
    load_data = pd.read_csv(load_file)
    load_profile = load_data[TOTAL_LOAD_COLUMN_NAME].tolist()
    # TEMP CONSTANT LOAD
    # load_profile = [1.0] * 8760 # [kW] constant load example
    annual_load_kWh = sum(load_profile)

    # ========== DEBUGGING: Load Profile Analysis ==========
    log(
        debug_load_profile_sample=load_profile[:10],  # First 10 values
        debug_load_profile_min=min(load_profile),
        debug_load_profile_max=max(load_profile),
        debug_load_profile_mean=statistics.mean(load_profile),
        debug_annual_load_kWh=annual_load_kWh,
        debug_annual_load_typical_range="Typical home: 10,000-15,000 kWh/year"
    )
    
    # Check if load profile appears to be in kW (power) vs kWh (energy)
    # If in kW, annual sum should be ~10,000-15,000 for typical home
    # If hourly kWh values, sum would be much smaller
    if annual_load_kWh < 1000:
        log(debug_load_units_likely="kWh per hour (energy intervals)")
    elif 5000 < annual_load_kWh < 30000:
        log(debug_load_units_likely="kW values (instantaneous power)")
    else:
        log(debug_load_units_likely="unclear units, unusual range")

    # Documentation of column names here: https://github.com/NREL/pysam/blob/8a5f6889cf2bae867d70bcff6ca408d142bd4b61/Examples/NonAnnualSimulation.ipynb#L358
    # In a solar resource file, global horizontal irradiance (gh) includes both the direct (beam) component of sunlight and the diffuse (scattered) component.
    # Diffuse irradiance (df) only includes the scattered portion of sunlight that reaches the surface.
    
    # extract global horizontal irradiance across the year [W/m2]
    gh_w_per_m2 = solar_resource_data["gh"]

    # ========== DEBUGGING: Irradiance Analysis ==========
    log(
        debug_irradiance_sample=gh_w_per_m2[:10],  # First 10 values
        debug_irradiance_min=min(gh_w_per_m2),
        debug_irradiance_max=max(gh_w_per_m2),
        debug_irradiance_mean=statistics.mean(gh_w_per_m2),
        debug_irradiance_typical_range="Typical: 0-1200 W/m² (0 at night, ~1000 peak sun)"
    )

    # compute average annual GHI in [W/m2]
    mean_gh_w_per_m2 = statistics.mean(gh_w_per_m2)

    # ========== STEP 3: Solar Irradiance Analysis ==========
    # Convert average GHI to daily energy [kWh/m²/day]
    # Formula: (W/m²) × (24 hours/day) ÷ (1000 W/kW) = kWh/m²/day
    daily_irradiance_kWh_per_m2_per_day = mean_gh_w_per_m2 * 24 / 1000

    # ========== DEBUGGING: Daily Irradiance Calculation ==========
    log(
        debug_mean_irradiance_w_per_m2=mean_gh_w_per_m2,
        debug_daily_irradiance_kWh_per_m2=daily_irradiance_kWh_per_m2_per_day,
        debug_daily_irradiance_expected_range="Expected: 3-7 kWh/m²/day for CA",
        debug_calculation_formula=f"{mean_gh_w_per_m2} W/m² * 24 h / 1000 = {daily_irradiance_kWh_per_m2_per_day} kWh/m²/day"
    )

    # ========== STEP 4: System Configuration Parameters ==========
    # Oversizing factor for extra buffer (1.0 = no oversizing, 1.2 = 20% more)
    oversizing_factor = 1.0  # Currently no oversizing

    # Panel nameplate power density [kW/m²] - peak DC power under standard test conditions
    # Tesla solar panels specification:
    # - Wattage: 420W, Dimensions: 82.4" × 40.9", Area: 2.171 m²
    # - Power density = 420 W ÷ 2.171 m² = 193.5 W/m² = 0.193 kW/m²
    # Tesla module datasheet: 
    # https://es-media-prod.s3.amazonaws.com/media/components/panels/spec-sheets/Tesla_Module_Datasheet.pdf
    # Typical range: 0.15-0.22 kW/m² for modern panels
    panel_nameplate_power_density_kW_per_m2 = 0.193

    # System performance factors for real-world energy production
    # Accounts for inverter losses, wiring losses, soiling, shading, temperature effects
    # Typical range: 0.75-0.85 for well-designed systems
    system_performance_ratio = 0.80  # 80% of theoretical peak performance

    # Solar capacity factor - ratio of actual annual energy to theoretical maximum
    # Varies by location: CA ~20-25%, AZ ~27%, Northeast ~15%
    # Formula: actual kWh/year ÷ (nameplate kW × 8760 hours)
    solar_capacity_factor = 0.22  # 22% typical for California residential

    # ========== STEP 5: Calculate Annual Energy Production Using NREL Irradiance Method ==========
    # Method: Based on actual NREL solar irradiance data with proper PV physics
    
    # Step 5a: Calculate theoretical solar energy available from NREL weather data
    annual_irradiance_kWh_per_m2 = daily_irradiance_kWh_per_m2_per_day * 365
    
    # Step 5b: Apply photovoltaic cell efficiency (converts sunlight to electricity)
    # Modern silicon PV cells: ~20-22% efficiency under standard test conditions
    # Tesla panels: ~20.6% efficiency per datasheet
    # This is the fundamental physics conversion from solar irradiance to DC electricity
    pv_cell_efficiency = 0.206  # 20.6% - converts solar irradiance to DC electricity
    
    # Step 5c: Apply system performance ratio (accounts for real-world losses)
    # Inverter losses: ~4%, wiring losses: ~2%, soiling: ~5%, temperature derating: ~10%, etc.
    # Combined system losses: ~20% → performance ratio of 0.80
    # Note: This is separate from PV cell efficiency - it's the additional real-world losses
    system_performance_ratio = 0.80  # 80% - accounts for inverter, wiring, soiling, temperature losses
    
    # Step 5d: Calculate actual electrical energy production per m²
    # Formula: (solar energy [kWh/m²]) × (PV efficiency) × (system performance ratio)
    annual_energy_production_kWh_per_m2 = (annual_irradiance_kWh_per_m2 * 
                                          pv_cell_efficiency * 
                                          system_performance_ratio)

    log(
        debug_annual_irradiance_kWh_per_m2=annual_irradiance_kWh_per_m2,
        debug_pv_cell_efficiency=pv_cell_efficiency,
        debug_system_performance_ratio=system_performance_ratio,
        debug_annual_energy_production_kWh_per_m2=annual_energy_production_kWh_per_m2,
        debug_expected_range="Expected: ~300-400 kWh/m²/year for CA after all losses",
        debug_calculation_formula=f"{annual_irradiance_kWh_per_m2} × {pv_cell_efficiency} × {system_performance_ratio} = {annual_energy_production_kWh_per_m2} kWh/m²/year"
    )

    # ========== STEP 6: Calculate Required Panel Area ==========
    # Solar panel area [m²] needed to cover annual load with oversizing
    # Formula: (energy demand [kWh/year] × oversizing) ÷ (energy production [kWh/m²/year])
    required_panel_area_m2 = (annual_load_kWh * oversizing_factor) / annual_energy_production_kWh_per_m2

    # ========== STEP 7: Convert Area to DC Nameplate Capacity ==========
    # Convert required panel area to DC capacity [kW] using nameplate power density
    # Formula: (panel area [m²]) × (nameplate power density [kW/m²]) = total DC capacity [kW]
    required_dc_capacity_kW = required_panel_area_m2 * panel_nameplate_power_density_kW_per_m2

    # ========== DEBUGGING: Final Sizing Results ==========
    log(
        debug_required_panel_area_m2=required_panel_area_m2,
        debug_required_dc_capacity_kW=required_dc_capacity_kW,
        debug_typical_residential_system="Typical: 20-40 m², 4-8 kW for CA home",
        debug_calculation_check=f"Load: {annual_load_kWh} kWh/year ÷ {annual_energy_production_kWh_per_m2} kWh/m²/year = {required_panel_area_m2} m²",
        debug_capacity_check=f"Area: {required_panel_area_m2} m² × {panel_nameplate_power_density_kW_per_m2} kW/m² = {required_dc_capacity_kW} kW"
    )

    return solar_resource_data, load_profile, required_dc_capacity_kW

def create_solar_model(solar_resource_data, system_capacity, years_of_analysis):
    # Initialize PV system
    solar = pvwatts.new() # Or could use FlatPlatePVResidential

    dir = "./SAM_configuration/"
    file_names = ["untitled__1__pvwattsv8"]
    modules = [solar]

    for f, m in zip(file_names, modules):
        with open(dir + f + ".json", 'r') as file:
            data = json.load(file)
            for k, v in data.items():
                if k not in ["number_inputs", "batt_adjust_constant", "batt_adjust_en_timeindex", "batt_adjust_en_periods", "batt_adjust_timeindex", "batt_adjust_periods"]:
                    m.value(k, v)

    solar.SolarResource.solar_resource_data = solar_resource_data 
    # TODO, Ana: only allow solar panels of specific sizes that actually exist on the market
    # this would require looking at the load profile / system_capacity, and finding the solar
    # panel that is the closest to the size specified here
    # https://nrel-pysam.readthedocs.io/en/main/modules/Pvwattsv8.html#systemdesign-group
    solar.SystemDesign.system_capacity = system_capacity # System size (DC nameplate) measured in kW. Depends on dc_ac_ratio
    # this property defines the ratio of the DC power to the AC power.
    # The default value is 1.1, which means that the DC power is 10% higher than the AC power
    # This is a common value for residential systems
    # solar.SystemDesign.dc_ac_ratio = 1.1 # Automatically set to 1.1 if not assigned explicitly
    # solar.SystemDesign.tilt = 20 # 
    # solar.SystemDesign.azimuth = 180 # Angle in degrees. Can be E=90; S=180, W=270
    solar.Lifetime.dc_degradation = [0.5] * years_of_analysis
    log(solar_system_capacity=system_capacity) # measured in kW

    return solar

def create_battery_model(solar, load_profile, years_of_analysis):
    # Tesla powerwall specs
    # https://energylibrary.tesla.com/docs/Public/EnergyStorage/Powerwall/2/Datasheet/en-us/Powerwall-2-Datasheet.pdf
    # Battery configuration: https://github.com/NREL/ssc/blob/patch/ssc/cmod_battery.cpp

    # ---- Initialize Battery model
    battery = battery_model.from_existing(solar) # StandaloneBatteryResidential

    dir = "./SAM_configuration/"
    file_names = ["untitled__1__battwatts"]

    for f, m in zip(file_names, [battery]):
        with open(dir + f + ".json", 'r') as file:
            data = json.load(file)
            for k, v in data.items():
                if k not in ["number_inputs", "batt_adjust_constant", "batt_adjust_en_timeindex", "batt_adjust_en_periods", "batt_adjust_timeindex", "batt_adjust_periods"]:
                    m.value(k, v)

    # ---- BatteryCell
    # ['LeadAcid_q10_computed', 'LeadAcid_q20_computed', 'LeadAcid_qn_computed', 'LeadAcid_tn', 'batt_C_rate', 'batt_Cp', 'batt_Qexp', 'batt_Qfull', 'batt_Qfull_flow', 'batt_Qnom', 'batt_Vcut', 'batt_Vexp', 'batt_Vfull', 'batt_Vnom', 'batt_Vnom_default', 'batt_calendar_a', 'batt_calendar_b', 'batt_calendar_c', 'batt_calendar_choice', 'batt_calendar_lifetime_matrix', 'batt_calendar_q0', 'batt_chem', 'batt_h_to_ambient', 'batt_initial_SOC', 'batt_life_model', 'batt_lifetime_matrix', 'batt_maximum_SOC', 'batt_minimum_SOC', 'batt_minimum_modetime', 'batt_minimum_outage_SOC', 'batt_resistance', 'batt_room_temperature_celsius', 'batt_voltage_choice', 'batt_voltage_matrix', 'cap_vs_temp']
    # battery.BatteryCell.batt_Vnom_default = 50.0 # Nominal voltage of the battery [V]
    # Convert usable energy (13.5 kWh) to ampere-hours:
    # Capacity [Ah] = 13500 Wh / 50 V = 270 Ah.
    # battery.BatteryCell.batt_Qfull = 293.5      # Fully charged cell capacity [Ah] # 270 for powerwall, but set to be 293.5 so we get full 13.5 kWh of usable Tesla battery capacity
    # battery.BatteryCell.batt_Qnom = 293.5    # Nominal (usable) capacity [Ah] # 270 for powerwall, but set to 293.5 so we get full 13.5 kWh of usable battery capacity as Tesla advertises
    # battery.BatteryCell.batt_initial_SOC = 50.0 # default 50
    # battery.BatteryCell.batt_minimum_SOC = 0 # default 30
    # battery.BatteryCell.batt_maximum_SOC = 1 # default 30
    # Usable energy = 293.5 Ah * 50 V * 0.92 = 13.5 kWh

    # --- BatterySystem
    # dict_keys(['batt_ac_dc_efficiency', 'batt_ac_or_dc', 'batt_computed_bank_capacity', 'batt_computed_series', 'batt_computed_strings', 'batt_current_charge_max', 'batt_current_choice', 'batt_current_discharge_max', 'batt_dc_ac_efficiency', 'batt_dc_dc_efficiency', 'batt_inverter_efficiency_cutoff', 'batt_loss_choice', 'batt_losses', 'batt_losses_charging', 'batt_losses_discharging', 'batt_losses_idle', 'batt_mass', 'batt_meter_position', 'batt_power_charge_max_kwac', 'batt_power_charge_max_kwdc', 'batt_power_discharge_max_kwac', 'batt_power_discharge_max_kwdc', 'batt_replacement_capacity', 'batt_replacement_option', 'batt_replacement_schedule_percent', 'batt_surface_area', 'en_batt', 'en_standalone_batt'])
    # battery.BatterySystem.batt_meter_position = 0 # 0=behind the meter, 1=front of the meter
    # battery.BatterySystem.batt_ac_dc_efficiency = 1
    # battery.BatterySystem.batt_dc_ac_efficiency = 1

    # ---- Load
    # dict_keys(['crit_load', 'crit_load_escalation', 'grid_outage', 'load', 'load_escalation', 'run_resiliency_calcs'])
    # battery.Load.load = load_profile # NEED to overwrite this because some default modules provide a load eg GenericBatteryResidential does this

    battery.Battery.assign({'load': load_profile})

    # ---- BatteryDispatch
    # dict_keys(['batt_custom_dispatch', 'batt_cycle_cost', 'batt_cycle_cost_choice', 'batt_dispatch_auto_btm_can_discharge_to_grid', 'batt_dispatch_auto_can_gridcharge', 'batt_dispatch_choice', 'batt_dispatch_load_forecast_choice', 'batt_dispatch_wf_forecast_choice', 'batt_load_ac_forecast', 'batt_load_ac_forecast_escalation', 'batt_pv_ac_forecast', 'batt_pv_clipping_forecast', 'batt_target_choice', 'batt_target_power', 'batt_target_power_monthly', 'dispatch_manual_btm_discharge_to_grid', 'dispatch_manual_charge', 'dispatch_manual_discharge', 'dispatch_manual_gridcharge', 'dispatch_manual_percent_discharge', 'dispatch_manual_percent_gridcharge', 'dispatch_manual_sched', 'dispatch_manual_sched_weekend', 'dispatch_manual_system_charge_first'])
    # battery.BatteryDispatch.batt_target_choice = 0 # Behind the meter = 0
    # battery.BatteryDispatch.batt_dispatch_choice = 5 # 0=PeakShaving,1=InputGridTarget,2=InputBatteryPower,3=ManualDispatch,4=RetailRateDispatch,5=SelfConsumption
    # # battery.BatteryDispatch.batt_dispatch_auto_btm_can_discharge_to_grid = 0 # No discharge to grid
    # battery.BatteryDispatch.batt_dispatch_auto_can_charge = 1 # Is battery charging allowed from solar? Yes
    # battery.BatteryDispatch.batt_dispatch_auto_can_gridcharge = 1 # Is battery allowed to charge from grid? Yes
    # battery.BatteryDispatch.batt_dispatch_auto_can_clipcharge = 1
    # battery.BatteryDispatch.batt_dispatch_auto_can_curtailcharge = 1
    # battery.BatteryDispatch.batt_dispatch_auto_btm_can_discharge_to_grid = 1
    # battery.BatteryDispatch.batt_dispatch_charge_only_system_exceeds_load = 1
    # battery.BatteryDispatch.batt_dispatch_discharge_only_load_exceeds_system = 1

    # ---- Lifetime
    # dict_keys(['analysis_period', 'inflation_rate', 'system_use_lifetime_output'])
    # battery.Lifetime.analysis_period = years_of_analysis

    return battery

def run_models_and_extract_outputs(solar, battery, load_profile):
    solar.execute(0)
    # print(solar.Outputs.export().keys()) 
    # print(solar.Outputs.annual_energy)
    # print(solar.Outputs.ac_monthly)
    battery.execute(0)

    load = battery.Battery.load
    system_to_load = battery.Outputs.system_to_load
    batt_to_load = battery.Outputs.batt_to_load
    grid_to_load = battery.Outputs.grid_to_load
    grid_to_batt = battery.Outputs.grid_to_batt
    system_to_batt = battery.Outputs.system_to_batt
    system_to_batt_dc = battery.Outputs.system_to_batt_dc
    system_to_grid = battery.Outputs.system_to_grid
    battery_soc = battery.Outputs.batt_SOC

    solar_battery_to_load = [s + b for s, b in zip(system_to_load, batt_to_load)]
    total_supply = [s + b + g for s, b, g in zip(system_to_load, batt_to_load, grid_to_load)]
    difference = [l - t for l, t in zip(load_profile, total_supply)]

    return system_to_load, batt_to_load, grid_to_load, solar_battery_to_load, total_supply, difference, grid_to_batt, system_to_batt, system_to_batt_dc, system_to_grid, load, battery_soc, solar.SystemDesign.system_capacity, battery.Outputs.batt_bank_installed_capacity

# def configure_rate_plan(battery, rate_plan):
    # battery.UtilityRateStructure.elec_rate = rate_plan
    # battery.BatteryDispatch.batt_dispatch_choice = 4
    # pass

def validate_and_save_results(county, load_profile, system_to_load, batt_to_load, grid_to_load, solar_battery_to_load, total_supply, difference, output_file, grid_to_batt, system_to_batt, system_to_batt_dc, system_to_grid, load, battery_soc):
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

    # TODO: Ana, I think the load profiles need to be shifted by 3 hours 
    # They are provided in ET, we're working with PT
    log(
        at="step8_run_sam_model_for_solar_storage",
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

def process(base_input_dir, base_output_dir, scenario, housing_type, counties=None, years_of_analysis=1, force_recompute=False):
    # Define the scenario path to dynamically list counties
    scenario_path = get_scenario_path(base_input_dir, scenario, housing_type)
    counties_to_run = get_counties(scenario_path, counties)
    capacity_dict = {}

    for county in counties_to_run:
        try:
            log(county=county)
            # log(at="step8", scenario=scenario, scenario_path=scenario_path, county=county)

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
                # TODO: Ana, this should raise, all load profiles should exist
                # Subsequent steps will fail if this fails
                print(f"Load file not found: {load_file}. Skipping...")
                continue

            solar_resource_data, load_profile, system_capacity = prepare_data_and_compute_system_capacity(weather_file, load_file, years_of_analysis)
            solar = create_solar_model(solar_resource_data, system_capacity, years_of_analysis)
            battery = create_battery_model(solar, load_profile, years_of_analysis)
            # configure_rate_plan(battery, some_rate_plan)

            system_to_load, batt_to_load, grid_to_load, solar_battery_to_load, total_supply, difference, grid_to_batt, system_to_batt, system_to_batt_dc, system_to_grid, load, battery_soc, solar_capacity, battery_capacity = run_models_and_extract_outputs(solar, battery, load_profile)

            capacity_dict[county] = {
                "Solar Capacity (kW)": to_decimal_number(solar_capacity),
                "Battery Capacity (kWh)": to_decimal_number(battery_capacity)
            }

            validate_and_save_results(county, load_profile, system_to_load, batt_to_load, grid_to_load, solar_battery_to_load, total_supply, difference, output_file, grid_to_batt, system_to_batt, system_to_batt_dc, system_to_grid, load, battery_soc)
        except Exception as e:
            print(f"Error processing {county}: {e}")
    
    capital_costs_folder = f"{base_input_dir}/{scenario}/{housing_type}/{CAPITAL_COSTS_FOLDER_NAME}"
    os.makedirs(capital_costs_folder, exist_ok=True)

    capacity_df = pd.DataFrame.from_dict(capacity_dict, orient='index').rename_axis('County')
    output_csv_path = f"{capital_costs_folder}/{SOLAR_STORAGE_CAPACITY_PREFIX}.csv"
    capacity_df.to_csv(output_csv_path)

# # Example usage
scenario = "heat_pump" # "heat_pump_and_water_heater", 
             # "heat_pump_water_heater_and_induction_stove",
             # "heat_pump_heating_cooling_water_heater_and_induction_stove"]
housing_type = "single-family-detached" # "single-family-attached"]

# counties = ["Alameda County"]

# # rate_plan = ...

if __name__ == '__main__':
    process("data/loadprofiles", "data/loadprofiles", scenario, housing_type, norcal_counties + socal_counties + central_counties, force_recompute=True) # ["Alameda County"])
    # norcal_counties + central_counties + socal_counties