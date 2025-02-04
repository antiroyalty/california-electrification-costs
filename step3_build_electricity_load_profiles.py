import os
import pandas as pd
from helpers import get_counties, get_scenario_path, is_valid_csv

END_USE_COLUMNS = {
    "heating": [
        'out.electricity.heating.energy_consumption',
        'out.electricity.heating_fans_pumps.energy_consumption',
        'out.electricity.heating_hp_bkup.energy_consumption',
    ],
    "cooling": [
        'out.electricity.cooling.energy_consumption',
        'out.electricity.cooling_fans_pumps.energy_consumption',
    ],
    "cooking": [
        'out.electricity.range_oven.energy_consumption',
    ],
    "hot_water": [
        'out.electricity.hot_water.energy_consumption',
    ],
    "appliances": [
        'out.electricity.ceiling_fan.energy_consumption',
        'out.electricity.clothes_dryer.energy_consumption',
        'out.electricity.dishwasher.energy_consumption',
        'out.electricity.lighting_interior.energy_consumption',
        'out.electricity.lighting_garage.energy_consumption',
        'out.electricity.mech_vent.energy_consumption',
        'out.electricity.refrigerator.energy_consumption',
    ],
    "misc": [
        'out.electricity.plug_loads.energy_consumption',
        'out.electricity.pool_pump.energy_consumption',
        'out.electricity.pool_heater.energy_consumption',
        'out.electricity.permanent_spa_pump.energy_consumption',
        'out.electricity.permanent_spa_heat.energy_consumption',
        'out.electricity.freezer.energy_consumption',
    ]
}

INPUT_FOLDER_NAME = "buildings"
OUTPUT_FILE_PREFIX = "electricity_loads"

def get_end_use_columns(end_use_categories):
    end_uses = []

    for category in end_use_categories["electric"]: # We're only building electric load profiles in this file
        end_uses.extend(END_USE_COLUMNS.get(category, []))

    return end_uses

def list_parquet_files(input_dir):
    if not os.path.exists(input_dir):
        return []
    return [f for f in os.listdir(input_dir) if f.endswith(".parquet")]

def read_parquet_file(file_path, required_cols):
    try:
        data = pd.read_parquet(file_path)
    except Exception as e:
        return None, f"Error reading {file_path}: {e}" # Returns (data, error) tuple

    missing_cols = [col for col in required_cols if col not in data.columns]
    if missing_cols:
        return None, f"Missing columns in {file_path}: {missing_cols}"

    data["timestamp"] = pd.to_datetime(data["timestamp"])
    return data[required_cols], None # Returns (data, error) tuple

def process_county_data(input_dir, output_path, end_uses):
    # Process all Parquet files in a county directory and save aggregated results.
    all_files = list_parquet_files(input_dir)

    if not all_files:
        return "no_files", 0 # nothin in there

    all_data = pd.DataFrame()

    for file_name in all_files:
        file_path = os.path.join(input_dir, file_name)

        data, error = read_parquet_file(file_path, ["timestamp"] + end_uses)
        if error:
            print(error)
            continue
        all_data = pd.concat([all_data, data], axis=0, ignore_index=True)

    if all_data.empty:
        return "empty_data", 0

    # Group by timestamp. What is the TYPICAL load at this timestamp (for that end use)? Calculate this here.
    average_profile = all_data.groupby("timestamp")[end_uses].mean()
    
    # Full year coverage
    full_year = pd.date_range(start=all_data["timestamp"].min(), end=all_data["timestamp"].max(), freq="H")
    average_profile = average_profile.reindex(full_year)
    average_profile["total_load"] = average_profile[end_uses].sum(axis=1) # Sum all end uses into the total_load column, at each given timestamp

    # Save to CSV
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    average_profile.reset_index(inplace=True)
    average_profile.rename(columns={"index": "timestamp"}, inplace=True)
    average_profile.to_csv(output_path, index=False)

    return "processed", len(all_files)

def should_skip_processing(output_path, force_recompute):
    if force_recompute:
        return False  # Always regenerate if forced

    return os.path.exists(output_path) and is_valid_csv(output_path)

def process(scenarios, housing_types, counties, base_input_dir, base_output_dir, force_recompute=True):
    """
    Returns a summary dict with structure:
      {
        "processed": [ { "county": ..., "status": ..., "num_files": ... }, ... ],
        "skipped":   [ { "county": ..., "status": ... }, ... ],
        "errors":    [ { "file_path": ..., "error": ... }, ... ],
      }
    """
    summary = {
        "processed": [],
        "skipped": [],
        "errors": []
    }

    for scenario, end_use_categories in scenarios.items():
        for housing_type in housing_types:
            scenario_path = get_scenario_path(base_input_dir, scenario, housing_type)
            counties = get_counties(scenario_path, counties)

            for county in counties:
                print(f"Processing electricity load profile in {county} for {scenario}, {housing_type}")

                # Record info about this county's run
                county_info = {
                    "county": county,
                    "scenario": scenario,
                    "housing_type": housing_type,
                    "status": None,
                    "num_files": 0
                }

                input_dir = os.path.join(base_input_dir, scenario, housing_type, county, INPUT_FOLDER_NAME)
                output_path = os.path.join(base_output_dir, scenario, housing_type, county, f"{OUTPUT_FILE_PREFIX}_{county}.csv")
                
                # 1. Make sure processing is necessary
                if should_skip_processing(output_path, force_recompute):
                    print(f"Skipping {county} - existing valid profile found at {output_path}")
                    county_info["status"] = "skipped_existing"
                    summary["skipped"].append(county_info)
                    continue  # Skip processing

                # 2. Make sure input directory exists
                if not os.path.exists(input_dir):
                    print(f"Directory not found: {input_dir}")
                    county_info["status"] = "directory_not_found"
                    summary["skipped"].append(county_info)
                    continue

                # 3. Process data
                end_uses = get_end_use_columns(end_use_categories)
                status, num_files = process_county_data(input_dir, output_path, end_uses)

                county_info["status"] = status
                county_info["num_files"] = num_files

                if status == "processed":
                    print(f"Saved electricity load profile to {output_path}")
                    summary["processed"].append(county_info)
                else:
                    summary["skipped"].append(county_info)

    print(summary)
    return summary