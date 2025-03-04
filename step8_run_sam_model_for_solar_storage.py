import os
import PySAM.Pvwattsv8 as pvwatts
import PySAM.Battery as battery_model
import PySAM.ResourceTools as tools
import pandas as pd
import matplotlib.pyplot as plt
import statistics

from helpers import get_counties, get_scenario_path, log, format_load_profile

# LOADPROFILE_FILE_PREFIX = "electricity_loads"
LOADPROFILE_FILE_PREFIX = "combined_profiles"
TOTAL_LOAD_COLUMN_NAME = "electricity.real_and_simulated.for_typical_county_home.kwh"
OUTPUT_LOADPROFILE_FILE_PREFIX = "sam_optimized_load_profiles"

def prepare_data_and_compute_system_capacity(weather_file, load_file, years_of_analysis):
    solar_resource_data = tools.SAM_CSV_to_solar_data(weather_file)
    load_data = pd.read_csv(load_file)
    load_profile = load_data[TOTAL_LOAD_COLUMN_NAME].tolist()
    annual_load_kwh = sum(load_profile)

    # Documentation of column names here: https://github.com/NREL/pysam/blob/8a5f6889cf2bae867d70bcff6ca408d142bd4b61/Examples/NonAnnualSimulation.ipynb#L358
    # In a solar resource file, global horizontal irradiance (gh) includes both the direct (beam) component of sunlight and the diffuse (scattered) component.
    # # Diffuse irradiance (df) only includes the scattered portion of sunlight that reaches the surface.
    avg_daily_irradiance = statistics.mean(solar_resource_data["gh"]) * 24 / 1000
    system_efficiency = 0.15
    desired_offset = 1.2
    # DONE: Ana, convert system capacity to be dynamically assigned based on the household load, rather than static = 5 kW system
    # TODO: Ana, only allow solar system capacities in increments that are actually sold on the market
    # TODO: explore whether I'm missing a "better" configuration of solar + storage where a smaller solar and storage system
    # could actually result in lower NPV and thus be "better"
    # what if we just looked at the "incremental" load profile
    # build enough solar + storage for ALL of your load, or just build enough solar + storage for your ELECTRIFIED load
    # exhaustively search each permutation
    system_capacity = (annual_load_kwh * desired_offset) / (avg_daily_irradiance * 365 * system_efficiency) # 5 # kW

    return solar_resource_data, load_profile, system_capacity

def create_solar_model(solar_resource_data, system_capacity, years_of_analysis):
    # Initialize PV system
    solar = pvwatts.default("PVWattsResidential")
    solar.SolarResource.solar_resource_data = solar_resource_data 
    # TODO, Ana: only allow solar panels of specific sizes that actually exist on the market
    # this would require looking at the load profile / system_capacity, and finding the solar
    # panel that is the closest to the size specified here
    solar.SystemDesign.system_capacity = system_capacity
    solar.SystemDesign.dc_ac_ratio = 1.2
    solar.SystemDesign.tilt = 20
    solar.SystemDesign.azimuth = 180
    solar.Lifetime.dc_degradation = [0.5] * years_of_analysis

    return solar

def create_battery_model(solar, load_profile, years_of_analysis):
    # Initialize battery model
    battery = battery_model.from_existing(solar, "GenericBatteryResidential")

    battery.Load.load = load_profile
    battery.BatteryCell.batt_chem = 1
    battery.BatteryCell.batt_Vnom_default = 3.6
    # TODO: Ana, adjust the size of the battery depending on what the household load profile is + solar performance
    # These battery profiles would likely need to be categorized into buckets that *actually* exist on the market
    battery.BatteryCell.batt_Qfull = 13.5 * 1000 / 3.6 # Adjust the size of the battery. Here it's statically specified to be 13.5 kWh
    battery.BatterySystem.batt_ac_or_dc = 1
    battery.BatterySystem.batt_meter_position = 0
    battery.BatterySystem.batt_power_discharge_max_kwac = 5
    battery.BatterySystem.batt_power_charge_max_kwac = 5
    battery.BatterySystem.batt_ac_dc_efficiency = 96
    battery.BatterySystem.batt_dc_ac_efficiency = 96
    battery.BatteryDispatch.batt_dispatch_choice = 0
    battery.BatteryDispatch.batt_dispatch_auto_can_charge = 1
    battery.BatteryDispatch.batt_dispatch_auto_can_gridcharge = 0
    battery.BatteryDispatch.batt_dispatch_auto_can_clipcharge = 1
    battery.BatteryDispatch.batt_dispatch_discharge_only_load_exceeds_system = 0
    battery.Lifetime.system_use_lifetime_output = 1
    battery.Lifetime.analysis_period = years_of_analysis

    return battery

def run_models_and_extract_outputs(solar, battery, load_profile):
    solar.execute(0)
    battery.execute(0)

    system_to_load = battery.Outputs.system_to_load
    batt_to_load = battery.Outputs.batt_to_load
    grid_to_load = battery.Outputs.grid_to_load
    solar_battery_to_load = [s + b for s, b in zip(system_to_load, batt_to_load)]
    total_supply = [s + b + g for s, b, g in zip(system_to_load, batt_to_load, grid_to_load)]
    difference = [l - t for l, t in zip(load_profile, total_supply)]

    return system_to_load, batt_to_load, grid_to_load, solar_battery_to_load, total_supply, difference

# def configure_rate_plan(battery, rate_plan):
    # battery.UtilityRateStructure.elec_rate = rate_plan
    # battery.BatteryDispatch.batt_dispatch_choice = 4
    # pass

def validate_and_save_results(county, load_profile, system_to_load, batt_to_load, grid_to_load, solar_battery_to_load, total_supply, difference, output_file):
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
        'Difference': difference
    }, index=date_range)

    # TODO: Ana, I think the load profiles need to be shifted by 3 hours 
    # They are provided in ET, we're working with PT
    log(
        at="step8_run_sam_model_for_solar_storage",
        load_profile=format_load_profile(load_profile),
        system_to_load=format_load_profile(system_to_load),
        battery_to_load=format_load_profile(batt_to_load),
        grid_to_load=format_load_profile(grid_to_load),
        solar_battery_to_load=format_load_profile(solar_battery_to_load),
        total_supply=format_load_profile(total_supply),
        difference=format_load_profile(difference),
        saved_to=output_file,
    )

    df.to_csv(output_file)

def process(base_input_dir, base_output_dir, scenarios, housing_types, counties=None, years_of_analysis=1):
    for scenario in scenarios:
        for housing_type in housing_types:
            # Define the scenario path to dynamically list counties
            scenario_path = get_scenario_path(base_input_dir, scenario, housing_type)
    
            counties_to_run = get_counties(scenario_path, counties)
    
            for county in counties_to_run:
                try:
                    log(at="step8", scenario=scenario, scenario_path=scenario_path, county=county)

                    weather_file = os.path.join(base_input_dir, scenario, housing_type, county, f"weather_TMY_{county}.csv")
                    load_file = os.path.join(scenario_path, county, f"{LOADPROFILE_FILE_PREFIX}_{scenario}_{county}.csv")
                    output_file = os.path.join(base_output_dir, scenario, housing_type, county, f"{OUTPUT_LOADPROFILE_FILE_PREFIX}_{county}.csv")

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

                    system_to_load, batt_to_load, grid_to_load, solar_battery_to_load, total_supply, difference = run_models_and_extract_outputs(solar, battery, load_profile)
                    validate_and_save_results(county, load_profile, system_to_load, batt_to_load, grid_to_load, solar_battery_to_load, total_supply, difference, output_file)
                except Exception as e:
                    print(f"Error processing {county}: {e}")

# Example usage
# base_input_dir = "data"
# base_output_dir = "data"
# scenarios = ["baseline"] # "heat_pump_and_water_heater", 
#              # "heat_pump_water_heater_and_induction_stove",
#              # "heat_pump_heating_cooling_water_heater_and_induction_stove"]
# housing_types = ["single-family-detached"] # "single-family-attached"]

# counties = ["alameda", "riverside"]

# # rate_plan = ...

# process(base_input_dir, base_output_dir, scenarios, housing_types, counties)