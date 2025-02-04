
import os
import pandas as pd
import numpy as np
from helpers import get_counties, get_scenario_path

OUTPUT_FILE_PREFIX = "combined_profiles"

SCENARIO_DATA_MAP = {
    "baseline": {
        # baseline
        "default": {
            "electricity": {
                "file_prefix": "electricity_loads_", # or "sam_optimized_load_profiles_"
                "columns": ["total_load"], # or + "Total Load"
            },
            "electricity_simulated": {
                "file_prefix": "electricity_loads_simulated_",
                "columns": [] # Nothing simulated
            },
            "gas": {
                "file_prefix": "gas_loads_",
                "columns": ["load.gas.avg.therms"] # TODO: Ana, why am I using avg therms here? Is this a miscalculation? Revisit this logic. This is because it's COUNTY average, not time average
            },
        },
    },
    "heat_pump_and_water_heater": { 
        # household adopted induction stove
        "default": {
            "electricity": {
                "file_prefix": "electricity_loads_",
                "columns": ["total_load"]
            },
            # As soon as I'm incorporating simulated loads, the electricity estimates become WAY off. Why?
            "electricity_simulated": {
                "file_prefix": "electricity_loads_simulated_",
                "columns": ["simulated.electricity.heat_pump.energy_consumption.electricity.total.kwh", "simulated.electricity.hot_water.energy_consumption.electricity.total.kwh"] # Add simulated heating, water heating
            },
            "gas": {
                "file_prefix": "gas_loads_",
                # SUBTRACT THES FROM GAS LOADS AVERAGE DONT ADD
                # Remove water heating and heating from gas
                "columns": ["load.gas.avg.therms"],
                "subtract_columns": ["out.natural_gas.hot_water.energy_consumption.gas.avg.therms", "out.natural_gas.heating.energy_consumption.gas.avg.therms"],
            }
        },
    },
}

# Gas data is every 15 minutes
# Meanwhile, electricity data is every hour
# So resample gas data on hourly timesteps so that it's compatible with other electricity data
# To later be summed and used in SAM solar modeling and rates
# Actually separate functionality of aggregation and resampling
    
def aggregate_columns(file_path, columns, operation="sum", resample_to_hourly=False):
    """
    Aggregate specified columns in a file, with optional resampling to hourly intervals.
    """
    try:
        df = pd.read_csv(file_path, usecols=["timestamp"] + columns, parse_dates=["timestamp"])
        df = df.set_index("timestamp")
        
        if operation == "sum":
            aggregated = df[columns].sum(axis=1)
        elif operation == "subtract":
            aggregated = -df[columns].sum(axis=1)
        else:
            raise ValueError(f"Step6@aggregate_columns: Unsupported operation: {operation}")
        
        print("aggregating columns")
        
        if resample_to_hourly:
            print("resampling to hourly")
            aggregated = aggregated.resample("H", label='left', closed='left').sum()

        expected_length = 8760
        if len(aggregated) > expected_length:
            print("Trimming the extra timestamp from resampled data")
            aggregated = aggregated.iloc[:expected_length]
        
        return aggregated
    except Exception as e:
        raise RuntimeError(f"Error processing file {file_path}: {e}")

def combine_profiles(input_dir, output_dir, scenario, housing_type, county, scenario_data_map):
    county_slug = county.lower().replace(" ", "_")
    # The retrieval of the profiles does not need to change based on scenario
    # All the loadprofiles are in 'baseline' (we are not pulling new files for each scenario)
    # though the output directory should be different
    base_path = os.path.join(input_dir, "baseline", housing_type, county_slug)

    # Real electricity profile
    electricity_real_file = os.path.join(base_path, f"{scenario_data_map['default']['electricity']['file_prefix']}{county_slug}.csv")
    electricity_real_columns = scenario_data_map['default']['electricity']['columns']
    print("electricity_real")
    electricity_real = aggregate_columns(electricity_real_file, electricity_real_columns)

    # Simulated electricity profile
    electricity_simulated_file = os.path.join(base_path, f"{scenario_data_map['default']['electricity_simulated']['file_prefix']}{county_slug}.csv")
    electricity_simulated_columns = scenario_data_map['default']['electricity_simulated']['columns']
    if electricity_simulated_columns:
        print("electricity_simulated")
        electricity_simulated = aggregate_columns(electricity_simulated_file, electricity_simulated_columns, operation="sum", resample_to_hourly=True)
    else:
        print("no electricity_simulated")
        electricity_simulated = pd.Series(0, index=electricity_real.index)  # No simulated data

    # Real gas profile
    gas_real_file = os.path.join(base_path, f"{scenario_data_map['default']['gas']['file_prefix']}{county_slug}.csv")
    gas_real_columns = scenario_data_map['default']['gas']['columns']
    print("real gas")
    gas_real = aggregate_columns(gas_real_file, gas_real_columns, operation="sum", resample_to_hourly=True)

    # Adjust gas profile by subtracting simulated loads
    if "columns" in scenario_data_map['default']['gas']:
        print("gas")
        gas_simulated_adjustment = aggregate_columns(gas_real_file, scenario_data_map['default']['gas']['columns'], operation="subtract", resample_to_hourly=True)
    else:
        gas_simulated_adjustment = pd.Series(0, index=electricity_real.index)  # No adjustments for gas / no subtraction for gas if no columns specified

    gas_combined = gas_real # + gas_simulated_adjustment
    electricity_combined = np.array(electricity_real) + np.array(electricity_simulated)
   
    print("A")
    print("*****")
    print(gas_combined.count())
    print("B")
    print(gas_combined)
    print("C")
    print(type(gas_combined))
    # Compute total annual consumption
    total_gas_consumed = gas_combined.sum()
    total_electricity_consumed = electricity_combined.sum()

    print(f"Total Gas Consumed (Therms): {total_gas_consumed}")
    print(f"Total Electricity Consumed (kWh): {total_electricity_consumed}")

    combined_df = pd.DataFrame({
        "timestamp": electricity_real.index,
        "electricity.real_and_simulated.for_typical_county_home.kwh": electricity_combined,
        "gas.hourly_total.for_typical_county_home.therms": gas_combined,
    }).reset_index(drop=True)

    print("C")

    output_path = os.path.join(output_dir, scenario, housing_type, county_slug)
    os.makedirs(output_path, exist_ok=True)
    output_file = os.path.join(output_path, f"{OUTPUT_FILE_PREFIX}_{scenario}_{county_slug}.csv")
    combined_df.to_csv(output_file, index=False)
    print(f"Combined profile saved to: {output_file}")

    return combined_df

def process(input_dir, output_dir, scenarios, housing_types, counties):
    results = []
    
    for scenario in scenarios:
        for housing_type in housing_types:
            scenario_path = get_scenario_path(input_dir, scenario, housing_type)
            counties = get_counties(scenario_path, counties)

            for county in counties:
                print(county)
                scenario_data_map = SCENARIO_DATA_MAP[scenario]
                result = combine_profiles(
                    input_dir, output_dir, scenario, housing_type, county, scenario_data_map
                )
                results.append(result)
    return results

# process("data", "data", ["baseline"], ["single-family-detached"], ["Alameda County"])