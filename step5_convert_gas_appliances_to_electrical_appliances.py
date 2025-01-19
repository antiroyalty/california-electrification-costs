
import os
import pandas as pd
import numpy as np

from helpers import slugify_county_name

# TODO: Make this a Monte Carlo simulation, trying all values in range
# TODO: Add climate-dependent (county-dependent?) COP values
# Conversion constants
EFFICIENCY_GAS_STOVE = 0.45  # Average efficiency (40-50%)
EFFICIENCY_INDUCTION_STOVE = 0.875  # Average efficiency (85-90%)
COP_HEAT_PUMP = 2.75  # Average effective COP (2.0-3.0 for ducted, 2.5-4.0 for non-ducted)
EFFICIENCY_GAS_HEATING = 0.875  # Average efficiency (80-95%)
COP_HPWH = 2.75  # Average effective COP (2.0-3.5)
EFFICIENCY_GAS_WATER_HEATER = 0.75  # Average efficiency (60-90%)

# Conversion functions
def convert_gas_heating_to_electric_heatpump(gas_heating_kwh):
    electric_heatpump_kwh = gas_heating_kwh / COP_HEAT_PUMP * EFFICIENCY_GAS_HEATING
    return electric_heatpump_kwh

def convert_gas_stove_to_induction_stove(gas_stove_kwh):
    induction_stove_kwh = gas_stove_kwh * (EFFICIENCY_GAS_STOVE / EFFICIENCY_INDUCTION_STOVE)
    return induction_stove_kwh

def convert_gas_water_heater_to_electric_waterheater(gas_water_heating_kwh):
    electric_water_heating_kwh = gas_water_heating_kwh / COP_HPWH * EFFICIENCY_GAS_WATER_HEATER
    return electric_water_heating_kwh

def convert_appliances_for_county(county, base_input_dir, base_output_dir, scenarios, housing_type):
    for scenario in scenarios:
        input_file = os.path.join(base_input_dir, scenario, housing_type, county, f"gas_loads_{county}.csv")
        output_file = os.path.join(base_output_dir, scenario, housing_type, county, f"electricity_loads_simulated_{county}.csv")

        if not os.path.exists(input_file):
            print(f"Gas load profile not found for {county} in scenario {scenario}. Looked in: {input_file}. Skipping...")
            continue
        
        try:
            gas_loads = pd.read_csv(input_file)
            simulated_electricity_loads = pd.DataFrame()
            simulated_electricity_loads['timestamp'] = gas_loads['timestamp'].copy()

            print(f"Processing {county} for scenario {scenario}...")

            simulated_electricity_loads["simulated.electricity.heat_pump.energy_consumption.electricity.total.kwh"] = gas_loads[
                "out.natural_gas.heating.energy_consumption.gas.total.kwh"
            ].apply(convert_gas_heating_to_electric_heatpump)
            
            simulated_electricity_loads["simulated.electricity.induction_stove.energy_consumption.electricity.total.kwh"] = gas_loads[
                "out.natural_gas.range_oven.energy_consumption.gas.total.kwh"
            ].apply(convert_gas_stove_to_induction_stove)
            
            simulated_electricity_loads["simulated.electricity.hot_water.energy_consumption.electricity.total.kwh"] = gas_loads[
                "out.natural_gas.hot_water.energy_consumption.gas.total.kwh"
            ].apply(convert_gas_water_heater_to_electric_waterheater)

            # Save the converted load profiles
            os.makedirs(os.path.dirname(output_file), exist_ok=True)
            simulated_electricity_loads.to_csv(output_file, index=False)
            print(f"Converted load profiles saved for {county} in scenario {scenario}. Saved to: {output_file}")
        
        except KeyError as e:
            print(f"Error: Missing expected column in {input_file}. {e}")
            continue
        except Exception as e:
            print(f"An unexpected error occurred while processing {county} in scenario {scenario}: {e}")
            continue

def process(base_input_dir, base_output_dir, counties=None, scenarios=None, housing_types=None):
    if counties is None:
        scenario_path = os.path.join(base_input_dir, scenarios[0], housing_types[0])

        if not os.path.exists(scenario_path):
            print(f"Scenario path does not exist: {scenario_path}")
            return

        # Dynamically determine counties from folder structure
        counties = [county for county in os.listdir(scenario_path) if os.path.isdir(os.path.join(scenario_path, county))]
        print(counties)

    for county in counties:
        county_slug = slugify_county_name(county)
                        
        for housing_type in housing_types:
            convert_appliances_for_county(county_slug, base_input_dir, base_output_dir, scenarios, housing_type)

# # Example usage
# base_input_dir = "data"
# base_output_dir = "data"
# counties = ["alameda", "riverside"]
# housing_types = ["single-family-detached"]
# scenarios = ["baseline"] # "heat_pump_and_water_heater", "heat_pump_water_heater_and_induction_stove"]
# convert_loads_for_counties(base_input_dir, base_output_dir, None, scenarios, housing_types)