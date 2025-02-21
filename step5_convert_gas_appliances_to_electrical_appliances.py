
import os
import pandas as pd
import numpy as np

from helpers import get_counties, get_scenario_path, log, to_number

# TODO: Make this a Monte Carlo simulation, trying all values in range
# TODO: Add climate-dependent (county-dependent?) COP values
# Conversion constants
# TODO: Consider a "low efficiency" and "high efficiency" household appliance adopter
EFFICIENCY_GAS_STOVE = 0.45  # Average efficiency (40-50%)
EFFICIENCY_INDUCTION_STOVE = 0.875  # Average efficiency (85-90%)
COP_HEAT_PUMP = 2.75  # Average effective COP (2.0-3.0 for ducted, 2.5-4.0 for non-ducted)
EFFICIENCY_GAS_HEATING = 0.875  # Average efficiency (80-95%)
COP_HPWH = 2.75  # Average effective COP (2.0-3.5)
EFFICIENCY_GAS_WATER_HEATER = 0.75  # Average efficiency (60-90%)

INPUT_FILE_PREFIX = "gas_loads" # from output of Step 4
OUTPUT_FILE_PREFIX = "electricity_loads_simulated"

# Note for typical homes in Alameda County
# Home Size	Heating & Cooling Consumption (kWh/year)
# 1,500 sq. ft.	~3,000 – 5,500 kWh
# 2,000 sq. ft.	~4,500 – 7,500 kWh
# 2,500 sq. ft.	~5,500 – 9,000 kWh

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

def save_converted_load_profiles(simulated_electricity_loads, output_file):
    os.makedirs(os.path.dirname(output_file), exist_ok=True)
    simulated_electricity_loads.to_csv(output_file, index=False)

    log(
        at='step5#convert_gas_appliances_to_electrical_appliances',
        heatpump_annual_kwh=to_number(simulated_electricity_loads['simulated.electricity.heat_pump.energy_consumption.electricity.kwh'].sum()),
        induction_stove_annual_kwh=to_number(simulated_electricity_loads['simulated.electricity.induction_stove.energy_consumption.electricity.kwh'].sum()),
        hot_water_annual_kwh=to_number(simulated_electricity_loads['simulated.electricity.hot_water.energy_consumption.electricity.kwh'].sum()),
        total_annual_kwh=to_number(simulated_electricity_loads.drop('timestamp', axis=1).sum().sum()),
        saved_to=output_file,
    )

def convert_appliances_for_county(county, base_input_dir, base_output_dir, scenarios, housing_type):
    for scenario in scenarios:
        input_file = os.path.join(base_input_dir, scenario, housing_type, county, f"{INPUT_FILE_PREFIX}_{county}.csv")
        output_file = os.path.join(base_output_dir, scenario, housing_type, county, f"{OUTPUT_FILE_PREFIX}_{county}.csv")

        if not os.path.exists(input_file):
            print(f"Gas load profile not found for {county} in scenario {scenario}. Looked in: {input_file}. Skipping...")
            continue
        
        try:
            gas_loads = pd.read_csv(input_file)
            simulated_electricity_loads = pd.DataFrame()
            simulated_electricity_loads['timestamp'] = gas_loads['timestamp'].copy()

            simulated_electricity_loads["simulated.electricity.heat_pump.energy_consumption.electricity.kwh"] = gas_loads[
                # This needs to sum by building_avg
                # Aka for a typical building in the given county, after looking at all the buildings within that county with the desired properties
                "out.natural_gas.heating.energy_consumption.gas.building_avg.kwh"
            ].apply(convert_gas_heating_to_electric_heatpump)

            log(
                gas_heating_kwh=to_number(gas_loads["out.natural_gas.heating.energy_consumption.gas.building_avg.kwh"].sum()),
                electric_heatpump_kwh=to_number(simulated_electricity_loads["simulated.electricity.heat_pump.energy_consumption.electricity.kwh"].sum()),
            )
            
            simulated_electricity_loads["simulated.electricity.induction_stove.energy_consumption.electricity.kwh"] = gas_loads[
                "out.natural_gas.range_oven.energy_consumption.gas.building_avg.kwh"
            ].apply(convert_gas_stove_to_induction_stove)

            log(
                gas_stove_kwh=to_number(gas_loads["out.natural_gas.range_oven.energy_consumption.gas.building_avg.kwh"].sum()),
                induction_stove_kwh=to_number(simulated_electricity_loads["simulated.electricity.induction_stove.energy_consumption.electricity.kwh"].sum()),
            )
            
            simulated_electricity_loads["simulated.electricity.hot_water.energy_consumption.electricity.kwh"] = gas_loads[
                "out.natural_gas.hot_water.energy_consumption.gas.building_avg.kwh"
            ].apply(convert_gas_water_heater_to_electric_waterheater)

            log(
                gas_water_heating_kwh=to_number(gas_loads["out.natural_gas.hot_water.energy_consumption.gas.building_avg.kwh"].sum()),
                electric_water_heating_kwh=to_number(simulated_electricity_loads["simulated.electricity.hot_water.energy_consumption.electricity.kwh"].sum())
            )

            save_converted_load_profiles(simulated_electricity_loads, output_file)
        
        except KeyError as e:
            print(f"Error: Missing expected column in {input_file}. {e}")
            continue
        except Exception as e:
            print(f"An unexpected error occurred while processing {county} in scenario {scenario}: {e}")
            continue

def process(base_input_dir, base_output_dir, counties, scenarios, housing_types):
    for housing_type in housing_types:
        for scenario in scenarios:
            scenario_path = get_scenario_path(base_input_dir, scenario, housing_type)
            counties = get_counties(scenario_path, counties)

            for county in counties:
                convert_appliances_for_county(county, base_input_dir, base_output_dir, scenarios, housing_type)

# base_input_dir = "data"
# base_output_dir = "data"
# counties = ["alameda", "riverside"]
# housing_types = ["single-family-detached"]
# scenarios = ["baseline"] # "heat_pump_and_water_heater", "heat_pump_water_heater_and_induction_stove"]
# convert_loads_for_counties(base_input_dir, base_output_dir, None, scenarios, housing_types)