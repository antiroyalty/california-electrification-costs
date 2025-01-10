import os
import PySAM.Pvwattsv8 as pvwatts
import PySAM.Battery as battery_model
import PySAM.ResourceTools as tools
import pandas as pd
import matplotlib.pyplot as plt

LOADPROFILE_FILE_PREFIX = "electricity_loads"
TOTAL_LOAD_COLUMN_NAME = "total_load"
OUTPUT_LOADPROFILE_FILE_PREFIX = "sam_optimized_load_profiles"

def generate_solar_storage_profiles(base_input_dir, base_output_dir, scenarios, housing_types, counties=None, years_of_analysis=1):
    for scenario in scenarios:
        for housing_type in housing_types:
            # Define the scenario path to dynamically list counties
            scenario_path = os.path.join(base_input_dir, scenario, housing_type)
            if not os.path.exists(scenario_path):
                print(f"Scenario path not found: {scenario_path}")
                continue
            
            if counties == None:
                print("counties is none")
                # Dynamically fetch counties
                counties = [county for county in os.listdir(scenario_path) if os.path.isdir(os.path.join(scenario_path, county))]
            
            for county in counties:
                print(f"Processing {county} for {scenario}, {housing_type}...")
                try:
                    # Set up paths
                    weather_file = os.path.join(base_input_dir, scenario, housing_type, county, f"weather_TMY_{county}.csv")
                    load_file = os.path.join(scenario_path, county, f"{LOADPROFILE_FILE_PREFIX}_{county}.csv")
                    output_file = os.path.join(base_output_dir, scenario, housing_type, county, f"{OUTPUT_LOADPROFILE_FILE_PREFIX}_{county}.csv")

                    # Ensure files exist
                    if not os.path.exists(weather_file):
                        print(f"Weather file not found: {weather_file}. Skipping...")
                        continue
                    if not os.path.exists(load_file):
                        print(f"Load file not found: {load_file}. Skipping...")
                        continue

                    # Load SAM CSV solar resource data
                    solar_resource_data = tools.SAM_CSV_to_solar_data(weather_file)

                    # TODO: Ana, convert system capacity to be dynamically assigned based on the household load, rather than static = 5 kW system
                    annual_load_kwh = load_data.sum().iloc[0]  # Sum of 8760 values (assuming single column of kWh)
                    avg_daily_irradiance = solar_resource_data["dni"].mean() * 24 / 1000  # kWh/m²/day
                    system_efficiency = 0.15  # PV system efficiency (adjust as necessary)
                    desired_offset = 1.0
                    system_capacity = (annual_load_kwh * desired_offset) / (avg_daily_irradiance * 365 * system_efficiency)

                    # Initialize PV system
                    solar = pvwatts.default("PVWattsResidential")
                    solar.SolarResource.solar_resource_data = solar_resource_data
                    solar.SystemDesign.system_capacity = 5  # 5 kW system
                    solar.SystemDesign.dc_ac_ratio = 1.2
                    solar.SystemDesign.tilt = 20
                    solar.SystemDesign.azimuth = 180
                    solar.Lifetime.dc_degradation = [0.5] * years_of_analysis

                    # Initialize battery model
                    battery = battery_model.from_existing(solar, "GenericBatteryResidential")

                    # Load the household load profile
                    load_data = pd.read_csv(load_file)
                    load_column_name = TOTAL_LOAD_COLUMN_NAME  # Adjust if column name is different
                    load_profile = load_data[load_column_name].tolist()
                    battery.Load.load = load_profile

                    # Configure battery parameters
                    battery.BatteryCell.batt_chem = 1
                    battery.BatteryCell.batt_Vnom_default = 3.6
                    battery.BatteryCell.batt_Qfull = 13.5 * 1000 / 3.6
                    battery.BatterySystem.batt_ac_or_dc = 1
                    battery.BatterySystem.batt_meter_position = 0
                    battery.BatterySystem.batt_power_discharge_max_kwac = 5
                    battery.BatterySystem.batt_power_charge_max_kwac = 5
                    battery.BatterySystem.batt_ac_dc_efficiency = 96
                    battery.BatterySystem.batt_dc_ac_efficiency = 96

                    battery.BatteryDispatch.batt_dispatch_choice = 0 # 0 = peak-shaving, 4 = retail rate dispatch
                    
                    # Apply electricity rates
                    # battery.UtilityRateStructure.elec_rate = rate_plan  # Pass the rate plan here
                    
                    battery.BatteryDispatch.batt_dispatch_auto_can_charge = 1
                    battery.BatteryDispatch.batt_dispatch_auto_can_gridcharge = 0
                    battery.BatteryDispatch.batt_dispatch_auto_can_clipcharge = 1
                    battery.BatteryDispatch.batt_dispatch_discharge_only_load_exceeds_system = 0

                    battery.Lifetime.system_use_lifetime_output = 1
                    battery.Lifetime.analysis_period = years_of_analysis

                    # Execute models
                    solar.execute(0)
                    battery.execute(0)

                    # Extract outputs
                    system_to_load = battery.Outputs.system_to_load
                    batt_to_load = battery.Outputs.batt_to_load
                    grid_to_load = battery.Outputs.grid_to_load
                    solar_battery_to_load = [s + b for s, b in zip(system_to_load, batt_to_load)]
                    total_supply = [s + b + g for s, b, g in zip(system_to_load, batt_to_load, grid_to_load)]
                    difference = [l - t for l, t in zip(load_profile, total_supply)]

                    # Validate outputs
                    max_difference = max(abs(d) for d in difference)
                    if max_difference > 1e-6:
                        print(f"Warning: Discrepancy found in {county}. Max difference: {max_difference}")

                    # Save to CSV
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
                    df.to_csv(output_file)
                    print(f"Saved results for {county} to {output_file}")

                except Exception as e:
                    print(f"Error processing {county}: {e}")

# Example usage
base_input_dir = "./data"
base_output_dir = "./data"
scenarios = ["baseline"] # "heat_pump_and_water_heater", 
             # "heat_pump_water_heater_and_induction_stove",
             # "heat_pump_heating_cooling_water_heater_and_induction_stove"]
housing_types = ["single-family-detached"] # "single-family-attached"]

counties = ["alameda", "alpine", "riverside"]

# rate_plan = ...

generate_solar_storage_profiles(base_input_dir, base_output_dir, scenarios, housing_types, counties)