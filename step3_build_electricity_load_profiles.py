import os
import pandas as pd

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
        # 'out.electricity.clothes_dryer.energy_consumption',
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

BASE_INPUT_DIR = "data"
BASE_OUTPUT_DIR = "data"

INPUT_FOLDER_NAME = "buildings"
OUTPUT_FILE_PREFIX = "electricity_loads"

def process(scenarios, housing_types, counties):
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
            for county in counties:
                print(f"Processing {county} for {scenario}, {housing_type}")

                # Record info about this county's run
                county_info = {
                    "county": county,
                    "scenario": scenario,
                    "housing_type": housing_type,
                    "status": None,
                    "num_files": 0
                }

                # Define input and output paths
                input_dir = os.path.join(
                    BASE_INPUT_DIR, scenario, housing_type, county, INPUT_FOLDER_NAME
                )
                output_path = os.path.join(
                    BASE_OUTPUT_DIR, scenario, housing_type, county,
                    f"{OUTPUT_FILE_PREFIX}_{county}.csv"
                )

                # Check if input_dir exists
                if not os.path.exists(input_dir):
                    print(f"Directory not found: {input_dir}")
                    county_info["status"] = "directory_not_found"
                    summary["skipped"].append(county_info)
                    continue

                # List files
                all_files = os.listdir(input_dir)
                if not all_files:
                    # Directory is empty => skip
                    print(f"No data processed for {county} in {scenario} - {housing_type}")
                    county_info["status"] = "no_files"
                    summary["skipped"].append(county_info)
                    continue

                # Collect all end use columns relevant to the scenario
                end_uses = []
                for category in end_use_categories:
                    end_uses.extend(END_USE_COLUMNS[category])

                all_data = pd.DataFrame()

                # Process each Parquet
                for file_name in all_files:
                    file_path = os.path.join(input_dir, file_name)
                    if file_path.endswith(".parquet"):
                        county_info["num_files"] += 1
                        try:
                            data = pd.read_parquet(file_path)
                        except Exception as e:
                            print(f"Error reading {file_path}: {e}")
                            summary["errors"].append({
                                "file_path": file_path,
                                "error": str(e)
                            })
                            continue

                        # Ensure required columns
                        required_cols = ["timestamp"] + end_uses
                        missing = [col for col in required_cols if col not in data.columns]
                        if missing:
                            # Mark as missing columns
                            msg = f"Missing columns in {file_path}: {missing}"
                            print(msg)
                            summary["errors"].append({
                                "file_path": file_path,
                                "error": f"Missing columns: {missing}"
                            })
                            continue

                        # Filter data
                        data["timestamp"] = pd.to_datetime(data["timestamp"])
                        data = data[required_cols]
                        all_data = pd.concat([all_data, data], axis=0, ignore_index=True)

                # If after scanning all Parquet files, we have no valid data => skip
                if all_data.empty:
                    print(f"No data processed for {county} in {scenario} - {housing_type}")
                    county_info["status"] = "empty_data"
                    summary["skipped"].append(county_info)
                    continue

                # Group data by timestamp
                average_profile = all_data.groupby("timestamp")[end_uses].mean()

                # Full year range
                full_year = pd.date_range(
                    start=all_data["timestamp"].min(),
                    end=all_data["timestamp"].max(),
                    freq="H"
                )

                average_profile = average_profile.reindex(full_year)
                average_profile["total_load"] = average_profile[end_uses].sum(axis=1)

                # Save to CSV
                average_profile.reset_index(inplace=True)
                average_profile.rename(columns={"index": "timestamp"}, inplace=True)
                os.makedirs(os.path.dirname(output_path), exist_ok=True)
                average_profile.to_csv(output_path, index=False)

                print(f"Saved load profile to {output_path}")
                county_info["status"] = "processed"
                summary["processed"].append(county_info)

    return summary