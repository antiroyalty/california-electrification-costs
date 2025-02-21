import os
import pandas as pd

from helpers import slugify_county_name, get_counties, get_scenario_path, log

# Which columns should be used to calculate electricity and gas rates based on each scenario
SCENARIO_DATA_MAP = {
    "baseline": {
        # baseline
        "default": {
            "electricity": {
                "file_prefix": "electricity_loads_", # or "sam_optimized_load_profiles_"
                "column": "total_load" # or + "Total Load"
            },
            "gas": {
                "file_prefix": "gas_loads_",
                "column": "load.gas.building_avg.therms" # TODO: Ana, why am I using avg therms here? Is this a miscalculation? Revisit this logic. This is because this is a COUNTY average, not a time average
            },
        },
        # baseline w/ solar + storage
        "solar_storage": {
            "electricity": {
                "file_prefix": "sam_optimized_load_profiles_",
                "column": "Grid to Load"
            },
            "gas": {
                "file_prefix": "gas_loads_",
                "column": "load.gas.building_avg.therms"
            }
        },
    },
    "sc1": {
        # household adopted induction stove
        "default": {
            "electricity": {
                "file_prefix": "electricity_loads_",
                "column": "total_load_w_simulated_induction"
            },
            "gas": {
                "file_prefix": "gas_loads_",
                "column": "load.gas.no_stove.avg.therms" # TODO: need to calculate total + average columns for loads without gas stove, heating, water heating
            }
        },
        # household adopted induction stove w/ solar + storage
        "solar_storage": {
            "electricity": {
                "file_prefix": "sam_optimized_load_profiles_",
                "column": "Grid to Load"
            },
            "gas": {
                "file_prefix": "gas_loads_",
                "column": "load.gas.no_stove.avg.therms",
            }
        }
    },
    "sc2": {
        # household adopted induction stove, heat pump
        "default": {
            "electricity": {
                "file_prefix": "electricity_loads_",
                "column": "total_load_w_simulated_induction_heatpump"
            },
            "gas": {
                "file_prefix": "gas_loads_",
                "column": "load.gas.no_stove_heating.avg.therms" # TODO: need to calculate total + average columns for loads without gas stove, heating, water heating
            }
        },
        # household adopted induction stove, heat pump w/ solar + storage
        "solar_storage": {
            "electricity": {
                "file_prefix": "sam_optimized_load_profiles_",
                "column": "Grid to Load"
            },
            "gas": {
                "file_prefix": "gas_loads_",
                "column": "load.gas.no_stove_heating.avg.therms",
            }
        }
    },
    "sc3": {
        # household adopted induction stove, heat pump, water heater
        "default": {
            "electricity": {
                "file_prefix": "electricity_loads_",
                "column": "total_load_w_simulated_induction_heatpump_waterheater"
            },
            "gas": {
                "file_prefix": "gas_loads_",
                "column": "load.gas.no_stove_heating_waterheating.avg.therms" # TODO: need to calculate total + average columns for loads without gas stove, heating, water heating
            }
        },
        "solar_storage": {
            # household adopted induction stove, heat pump, water heater w/ solar + storage
            "electricity": {
                "file_prefix": "sam_optimized_load_profiles_",
                "column": "Grid to Load"
            },
            "gas": {
                "file_prefix": "gas_loads_",
                "column": "load.gas.no_stove_heating_waterheating.avg.therms",
            }
        }
    },
}

OUTPUT_FILE_NAME = "loadprofiles_for_rates"
OUTPUT_COLUMNS = ["timestamp", "default.electricity.kwh", "default.gas.therms", "solarstorage.electricity.kwh", "solarstorage.gas.therms"]

def aggregate_to_hourly(file_path, column_name):
    try:
        df = pd.read_csv(file_path, parse_dates=["timestamp"])
        if column_name not in df.columns:
            raise ValueError(f"Column '{column_name}' not found in file: {file_path}")
        
        df = df.set_index("timestamp")
        hourly_df = df.resample("H")[column_name].sum().reset_index() # Resample and reindex

        return hourly_df[column_name] # Return the single column of interest
    except Exception as e:
        raise RuntimeError(f"Error processing file {file_path}: {e}")

def get_file_path(path, county, file_prefix):
    return os.path.join(path, county, f"{file_prefix}{county}.csv")

def read_load_profile(file_path, column_name):
    try:
        df = pd.read_csv(file_path, usecols=[column_name])
        return df[column_name]
    except Exception as e:
        raise RuntimeError(f"Error reading file {file_path}: {e}")

def prepare_for_rates_analysis(base_input_dir, base_output_dir, housing_type, scenario, county):
    directory = SCENARIO_DATA_MAP.get(scenario, {})
    county = slugify_county_name(county)
    path = get_scenario_path(base_input_dir, scenario, housing_type)

    electricity_default_file = get_file_path(path, county, directory["default"]["electricity"]["file_prefix"])
    gas_default_file = get_file_path(path, county, directory["default"]["gas"]["file_prefix"])
    electricity_solar_storage_file = get_file_path(path, county, directory["solar_storage"]["electricity"]["file_prefix"])
    gas_solar_storage_file = get_file_path(path, county, directory["solar_storage"]["gas"]["file_prefix"])

    timestamp = read_load_profile(electricity_default_file, "timestamp")
    electricity_default = read_load_profile(electricity_default_file, directory["default"]["electricity"]["column"])
    electricity_solar_storage = read_load_profile(electricity_solar_storage_file, directory["solar_storage"]["electricity"]["column"])
    gas_default_hourly = aggregate_to_hourly(gas_default_file, directory["default"]["gas"]["column"])
    gas_solar_storage_hourly = aggregate_to_hourly(gas_solar_storage_file, directory["solar_storage"]["gas"]["column"])

    combined_df = pd.DataFrame({
        "timestamp": timestamp,
        "default.electricity.kwh": electricity_default,
        "default.gas.therms": gas_default_hourly,
        "solarstorage.electricity.kwh": electricity_solar_storage,
        "solarstorage.gas.therms": gas_solar_storage_hourly
    }).dropna()

    output_file_path = os.path.join(base_output_dir, scenario, housing_type, county, f"{OUTPUT_FILE_NAME}_{county}.csv")
    os.makedirs(os.path.dirname(output_file_path), exist_ok=True)
    combined_df.to_csv(output_file_path, index=False)
    
    log(
        at="step9_get_loads_for_rates",
        saved_to=output_file_path,
    )

def process(base_input_dir, base_output_dir, scenarios, housing_types, counties=None):
    for scenario in scenarios:
        for housing_type in housing_types:
            scenario_path = get_scenario_path(base_input_dir, scenario, housing_type)
            counties_list = get_counties(scenario_path, counties)
            for county in counties_list:
                prepare_for_rates_analysis(base_input_dir, base_output_dir, housing_type, scenario, county)

# base_input_dir = "data"
# base_output_dir = "data"

# counties = ['Alameda County']

# process(
#     base_input_dir=base_input_dir,
#     base_output_dir=base_output_dir,
#     scenarios=["baseline"],
#     housing_types=["single-family-detached"],
#     counties=counties
# )