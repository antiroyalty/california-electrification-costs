
import os
import pandas as pd
import numpy as np

from helpers import get_counties, get_scenario_path, log, to_number

OUTPUT_FILE_PREFIX = "combined_profiles"

SCENARIO_DATA_MAP = {
    "baseline": {
        # baseline
        "default": {
            "electricity": {
                "file_prefix": "electricity_loads_",
                "columns": ["total_load"], # or + "Total Load"
            },
            "electricity_simulated": {
                "file_prefix": "electricity_loads_simulated_",
                "columns": [] # Nothing simulated
            },
            "gas": {
                "file_prefix": "gas_loads_",
                "columns": ["out.natural_gas.range_oven.energy_consumption.gas.building_avg.therms", "out.natural_gas.hot_water.energy_consumption.gas.building_avg.therms", "out.natural_gas.heating.energy_consumption.gas.building_avg.therms"],
                # This is the TOTAL gas load column
                # "columns": ["load.gas.building_avg.therms"] # TODO: Ana, why am I using avg therms here? Is this a miscalculation? Revisit this logic. Ans: This is because it's COUNTY average, not time average
            },
        },
    },
    "heat_pump": { 
        "default": {
            "electricity": {
                "file_prefix": "electricity_loads_",
                "columns": ["total_load"]
            },
            "electricity_simulated": {
                "file_prefix": "electricity_loads_simulated_",
                "columns": ["simulated.electricity.heat_pump.energy_consumption.electricity.kwh"]
            },
            "gas": {
                "file_prefix": "gas_loads_",
                "columns":  ["out.natural_gas.range_oven.energy_consumption.gas.building_avg.therms", "out.natural_gas.hot_water.energy_consumption.gas.building_avg.therms"],
            }
        },
    },
    "induction_stove": { 
        "default": {
            "electricity": {
                "file_prefix": "electricity_loads_",
                "columns": ["total_load"]
            },
            "electricity_simulated": {
                "file_prefix": "electricity_loads_simulated_",
                "columns": ["simulated.electricity.induction_stove.energy_consumption.electricity.kwh"]
            },
            "gas": {
                "file_prefix": "gas_loads_",
                "columns":  ["out.natural_gas.heating.energy_consumption.gas.building_avg.therms", "out.natural_gas.hot_water.energy_consumption.gas.building_avg.therms"],
            }
        },
    },
}

# Gas data is every 15 minutes
# Meanwhile, electricity data is every hour
# So resample gas data on hourly timesteps so that it's compatible with other electricity data
# To later be summed and used in SAM solar modeling and rates
# Actually separate functionality of aggregation and resampling

def aggregate_columns(file_path, columns, resample_to_hourly=False):
    """
    Aggregate specified columns in a file, with optional resampling to hourly intervals.
    """
    if not os.path.exists(file_path):
        log(warning=f"File {file_path} not found. Skipping.")
        return None
    
    try:
        df = pd.read_csv(file_path, usecols=["timestamp"] + columns, parse_dates=["timestamp"])
        df = df.set_index("timestamp")
        
        # Sum the columns
        aggregated = df[columns].sum(axis=1)
        
        if resample_to_hourly:
            aggregated = aggregated.resample("H", label='left', closed='left').sum()

        expected_length = 8760
        if len(aggregated) > expected_length:
            aggregated = aggregated.iloc[:expected_length]
        
        return aggregated
    except Exception as e:
        print(f"Error processing file {file_path}: {e}")
        return None

def combine_profiles(input_dir, output_dir, scenario, housing_type, county, scenario_data_map):
    county_slug = county.lower().replace(" ", "_")
    # TODO, Ana:
    # The retrieval of the profiles does not need to change based on scenario
    # All the loadprofiles are in 'baseline' (we are not pulling new files for each scenario)
    # though the output directory should be different
    base_path = os.path.join(input_dir, "baseline", housing_type, county_slug) # ultimately I should rename the folder called "baseline" to be "nrel load profiles" or "nrel downloaded data or something". This is a TODO

    # Real electricity profile
    electricity_real_file = os.path.join(base_path, f"{scenario_data_map['default']['electricity']['file_prefix']}{county_slug}.csv")
    electricity_real_columns = scenario_data_map['default']['electricity']['columns']
    electricity_real = aggregate_columns(electricity_real_file, electricity_real_columns)

    # Simulated electricity profile
    electricity_simulated_file = os.path.join(base_path, f"{scenario_data_map['default']['electricity_simulated']['file_prefix']}{county_slug}.csv")
    electricity_simulated_columns = scenario_data_map['default']['electricity_simulated']['columns']

    if electricity_simulated_columns:
        electricity_simulated = aggregate_columns(electricity_simulated_file, electricity_simulated_columns, resample_to_hourly=True)
    else:
        electricity_simulated = pd.Series(0, index=electricity_real.index)  # No simulated data

    # Real gas profile
    gas_real_file = os.path.join(base_path, f"{scenario_data_map['default']['gas']['file_prefix']}{county_slug}.csv")
    gas_real_columns = scenario_data_map['default']['gas']['columns']
    gas_real = aggregate_columns(gas_real_file, gas_real_columns, resample_to_hourly=True)

    gas_simulated_adjustment = 0

    gas_combined = gas_real + gas_simulated_adjustment
    electricity_combined = np.array(electricity_real) + np.array(electricity_simulated)
   
    # Compute total annual consumption for logs
    total_gas_real = gas_real.sum()
    total_gas_adjusted = gas_simulated_adjustment
    total_gas_consumed = gas_combined.sum()

    total_electricity_real = electricity_real.sum()
    total_electricity_simulated = electricity_simulated.sum()
    total_electricity_consumed = electricity_combined.sum()

    combined_df = pd.DataFrame({
        "timestamp": electricity_real.index,
        "electricity.real_and_simulated.for_typical_county_home.kwh": electricity_combined,
        "gas.hourly_total.for_typical_county_home.therms": gas_combined,
    }).reset_index(drop=True)

    output_path = os.path.join(output_dir, scenario, housing_type, county_slug)
    os.makedirs(output_path, exist_ok=True)
    output_file = os.path.join(output_path, f"{OUTPUT_FILE_PREFIX}_{scenario}_{county_slug}.csv")
    combined_df.to_csv(output_file, index=False)

    log(
        at="step6_combine_real_and_simulated_electricity_profiles",
        total_electricity_real_kwh=f"{total_electricity_real:_.0f}",
        total_electricity_simulated_kwh=f"{total_electricity_simulated:_.0f}",
        total_electricity_consumed_kwh=f"{total_electricity_consumed:_.0f}",
        total_gas_real_therms=to_number(total_gas_real),
        total_gas_adjusted_therms=to_number(total_gas_adjusted),
        total_gas_consumed_therms=to_number(total_gas_consumed),
        saved_to=output_file,
    )

    return combined_df

def process(input_dir, output_dir, scenarios, housing_types, counties):
    results = []
    
    for scenario in scenarios:
        for housing_type in housing_types:
            scenario_path = get_scenario_path(input_dir, scenario, housing_type)
            counties = get_counties(scenario_path, counties)

            for county in counties:
                scenario_data_map = SCENARIO_DATA_MAP[scenario]
                result = combine_profiles(
                    input_dir, output_dir, scenario, housing_type, county, scenario_data_map
                )
                results.append(result)
    return results

# process("data", "data", ["baseline"], ["single-family-detached"], ["Alameda County"])