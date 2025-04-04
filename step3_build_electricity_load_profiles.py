import os
import pandas as pd
from helpers import get_counties, get_scenario_path, is_valid_csv, log, to_number

END_USE_COLUMNS = {
    "cooling": [
        'out.electricity.cooling.energy_consumption',
        'out.electricity.cooling_fans_pumps.energy_consumption',
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

def read_building_profile(file_path, end_uses):
    """
    Reads a building's Parquet file, converts the timestamp to datetime, sets it as the index,
    and returns only the columns of interest (end_uses).
    """
    data, error = read_parquet_file(file_path, ["timestamp"] + end_uses)
    if error:
        return None, error
    data["timestamp"] = pd.to_datetime(data["timestamp"])
    data = data.set_index("timestamp")
    return data[end_uses], None

def get_building_profiles(input_dir, end_uses):
    """
    Iterates over all Parquet files in the input directory, reading and collecting each building's data.
    Returns a list of DataFrames.
    """
    all_files = list_parquet_files(input_dir)
    profiles = []
    for file_name in all_files:
        file_path = os.path.join(input_dir, file_name)
        profile, error = read_building_profile(file_path, end_uses)
        if error:
            print(error)
            continue
        profiles.append(profile)
    return profiles

def compute_typical_profile(profiles):
    """
    Combines individual building profiles side-by-side so that each building's data remains separate,
    then computes the average (typical) load for each end-use across buildings.
    Returns a DataFrame at the native resolution (e.g. 15-minute intervals).
    """
    # Create a MultiIndex on the columns: level 0 will be the building index.
    combined = pd.concat(profiles, axis=1, keys=range(len(profiles)))
    # Group by the end-use column names (level 1) and compute the mean across buildings.
    typical_15min = combined.groupby(level=1, axis=1).mean()
    return typical_15min

def resample_profile_to_hourly(typical_profile, agg_method="sum"):
    """
    Resamples the typical profile from its native resolution (e.g. 15 minutes) to hourly.
    The aggregation method can be 'sum' (to add up the 15-minute intervals) or 'mean' if needed.
    Fills any missing timestamps with 0.
    """
    if agg_method == "sum":
        hourly_profile = typical_profile.resample("H").sum()
    elif agg_method == "mean":
        hourly_profile = typical_profile.resample("H").mean()
    else:
        raise ValueError("Unsupported aggregation method: choose 'sum' or 'mean'")
    return hourly_profile.fillna(0)

def compute_annual_totals(profile, end_uses):
    """
    Computes annual totals for each end-use by summing the values in the profile.
    """
    return profile[end_uses].sum(axis=0).to_dict()

def save_profile(profile, output_path):
    """
    Saves the profile DataFrame to a CSV file.
    """
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    profile = profile.reset_index().rename(columns={"index": "timestamp"})
    profile.to_csv(output_path, index=False)

def format_end_use_name(key):
    prefix = "out.electricity."
    suffix = ".energy_consumption"
    if key.startswith(prefix):
        key = key[len(prefix):]
    if key.endswith(suffix):
        key = key[:-len(suffix)] + " kwh"
    return key

def log_annual_totals(county, annual_totals):
    dynamic_kwargs = { format_end_use_name(k): to_number(v) for k, v in annual_totals.items() }

    log(at="step3_build_electricity_load_profiles", county=county, **dynamic_kwargs)

def process_county_data(county, input_dir, output_path, end_uses):
    """
    Processes all building Parquet files in the county directory:
      1. Reads each building file and collects the building profiles.
      2. Computes the typical (average) building load at each timestamp across buildings.
      3. Resamples the resulting profile to hourly resolution.
      4. Computes annual totals for each end use.
      5. Saves the final typical load profile to CSV.
      
    Returns:
      status (str), num_files (int), annual_totals (dict)
    """
    profiles = get_building_profiles(input_dir, end_uses)
    if not profiles:
        return "empty_data", 0

    # Compute the average (typical) 15-minute profile across buildings.
    typical_15min = compute_typical_profile(profiles)

    # Resample the typical profile to hourly resolution.
    typical_hourly = resample_profile_to_hourly(typical_15min, agg_method="sum")

    # Optionally, compute a total load column (sum across all end uses).
    typical_hourly["total_load"] = typical_hourly[end_uses].sum(axis=1)

    # Compute annual totals for each end use.
    annual_totals = compute_annual_totals(typical_hourly, end_uses)
    log_annual_totals(county, annual_totals)

    save_profile(typical_hourly, output_path)

    return "processed", len(profiles)

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
        if scenario != "baseline":
            log(at="step3_build_electricity_load_profiles", message="no new electricity profiles needed to be downloaded")
            return
    
        for housing_type in housing_types:
            scenario_path = get_scenario_path(base_input_dir, scenario, housing_type)
            counties = get_counties(scenario_path, counties)

            for county in counties:
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
                    county_info["status"] = "skipped_existing"
                    summary["skipped"].append(county_info)
                    continue  # Skip processing

                # 2. Make sure input directory exists
                if not os.path.exists(input_dir):
                    county_info["status"] = "directory_not_found"
                    summary["skipped"].append(county_info)
                    continue

                # 3. Process data
                end_uses = get_end_use_columns(end_use_categories)
                status, num_files = process_county_data(county, input_dir, output_path, end_uses)

                county_info["status"] = status
                county_info["num_files"] = num_files

                if status == "processed":
                    summary["processed"].append(county_info)
                else:
                    summary["skipped"].append(county_info)

    log(
        step=3,
        title="build electricity load profiles",
        processed=summary["processed"],
        skipped=summary["skipped"],
        errors=summary["errors"]
    )

    return summary

# BASELINE_SCENARIO = {
#     "baseline": {"gas": {"heating", "hot_water", "cooking"}, "electric": {"appliances", "misc"}}
# }
# process(BASELINE_SCENARIO, ["single-family-detached"], ["Alpine County", "Marin County"], "data", "data/loadprofiles", force_recompute=True)