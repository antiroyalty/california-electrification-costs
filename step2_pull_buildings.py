import os
import pandas as pd
import boto3
from botocore.client import Config
from botocore import UNSIGNED

# Initialize S3 client
s3 = boto3.client('s3', config=Config(signature_version=UNSIGNED))

def download_parquet_file(bucket_name, s3_key, output_dir):
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
    
    output_file = os.path.join(output_dir, os.path.basename(s3_key))
    
    # Skip downloading if the file already exists
    if os.path.exists(output_file):
        print(f"File already exists: {output_file}. Skipping download.")
        return
    try:
        s3.download_file(Bucket=bucket_name, Key=s3_key, Filename=output_file)
        print(f"Downloaded {s3_key} to {output_file}")
    except Exception as e:
        print(f"Error downloading {s3_key}: {e}")

def process_county(scenario, housing_type, county_path, bucket_name, s3_prefix, output_base_dir):
    # Load county-specific metadata
    metadata_path = os.path.join(county_path, "step1_filtered_building_ids.csv")
    try:
        county_buildings = pd.read_csv(metadata_path)
        print(f"Loaded metadata from {metadata_path}")
    except FileNotFoundError:
        print(f"Metadata file not found at {metadata_path}")
        return False

    building_ids = county_buildings["bldg_id"].to_list()
    
    # Correct the output directory construction
    county_name = os.path.basename(county_path)
    output_dir = os.path.join(output_base_dir, scenario, housing_type, county_name, "buildings")

    # Ensure the directory exists before proceeding
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
        print(f"Created directory: {output_dir}")

    # Check if the directory is already populated
    downloaded_files = [f for f in os.listdir(output_dir) if os.path.isfile(os.path.join(output_dir, f))]
    if len(downloaded_files) == len(building_ids):
        print(f"All files already exist for {county_path}. Skipping.")
        return True

    # Download each specified Parquet file
    for bldg_id in building_ids:
        s3_key = f"{s3_prefix}{bldg_id}-0.parquet"
        download_parquet_file(bucket_name, s3_key, output_dir)

    # Verify all files were downloaded
    downloaded_file_count = len([f for f in os.listdir(output_dir) if os.path.isfile(os.path.join(output_dir, f))])
    if len(building_ids) == downloaded_file_count:
        print(f"All files successfully downloaded for {county_path}")
        return True
    else:
        print(f"Mismatch in file count for {county_path}: {len(building_ids)} IDs, {downloaded_file_count} files")
        return False

def process(output_base_dir="data", download_new_files=True):
    bucket_name = "oedi-data-lake"
    s3_prefix = "nrel-pds-building-stock/end-use-load-profiles-for-us-building-stock/2024/resstock_amy2018_release_2/timeseries_individual_buildings/by_state/upgrade=0/state=CA/"

    housing_types = ["single-family-detached", "single-family-attached"]
    scenarios = ["baseline", "heat_pump_and_water_heater", "heat_pump_water_heater_and_induction_stove",
                 "heat_pump_heating_cooling_water_heater_and_induction_stove"]

    success_summary = []
    failure_summary = []

    if not download_new_files:
        return {
            "success_summary": ["No new building files needed to be downloaded."],
            "failure_summary": failure_summary,
        }

    for scenario in scenarios:
        for housing_type in housing_types:
            scenario_path = os.path.join(output_base_dir, scenario, housing_type)
            if not os.path.exists(scenario_path):
                print(f"Scenario path not found: {scenario_path}")
                continue

            counties = [os.path.join(scenario_path, county) for county in os.listdir(scenario_path) 
                        if os.path.isdir(os.path.join(scenario_path, county))]
            
            for county_path in counties:
                print(f"Processing: {county_path}")
                metadata_path = os.path.join(county_path, "step1_filtered_building_ids.csv")
                
                # Call process_county to handle the downloading logic
                success = process_county(
                    scenario=scenario,
                    housing_type=housing_type,
                    county_path=county_path,
                    bucket_name=bucket_name,
                    s3_prefix=s3_prefix,
                    output_base_dir=output_base_dir
                )

                if not success:
                    try:
                        county_buildings = pd.read_csv(metadata_path)
                        total_buildings = len(county_buildings["bldg_id"].to_list())
                    except FileNotFoundError:
                        total_buildings = 0
                    failure_summary.append({
                        "county": os.path.basename(county_path),
                        "scenario": scenario,
                        "housing_type": housing_type,
                        "total_buildings": total_buildings,
                        "retrieved_buildings": 0,
                        "missing_buildings": total_buildings
                    })
                else:
                    # Verify the building count after successful processing
                    try:
                        county_buildings = pd.read_csv(metadata_path)
                        building_ids = county_buildings["bldg_id"].to_list()
                        total_buildings = len(building_ids)
                        county_name = os.path.basename(county_path)
                        output_dir = os.path.join(output_base_dir, scenario, housing_type, county_name, "buildings")
                        retrieved_files = [f for f in os.listdir(output_dir) if os.path.isfile(os.path.join(output_dir, f))]
                        retrieved_buildings = len(retrieved_files)
                        missing_buildings = total_buildings - retrieved_buildings

                        if missing_buildings == 0:
                            success_summary.append({
                                "county": os.path.basename(county_path),
                                "scenario": scenario,
                                "housing_type": housing_type,
                                "total_buildings": total_buildings,
                                "retrieved_buildings": retrieved_buildings
                            })
                        else:
                            failure_summary.append({
                                "county": os.path.basename(county_path),
                                "scenario": scenario,
                                "housing_type": housing_type,
                                "total_buildings": total_buildings,
                                "retrieved_buildings": retrieved_buildings,
                                "missing_buildings": missing_buildings
                            })
                    except FileNotFoundError:
                        print(f"Metadata file not found at {metadata_path}")
                        continue

    print("\nSummary Report:")
    print("Successes:")
    for success in success_summary:
        print(f"- {success['county']} ({success['scenario']}, {success['housing_type']}): "
              f"{success['total_buildings']} total, {success['retrieved_buildings']} retrieved, 0 missing")
    
    print("\nFailures:")
    for failure in failure_summary:
        print(f"- {failure['county']} ({failure['scenario']}, {failure['housing_type']}): "
              f"{failure['total_buildings']} total, {failure['retrieved_buildings']} retrieved, "
              f"{failure['missing_buildings']} missing")
        

    return {
        # "logs": logs,
        "success_summary": success_summary,
        "failure_summary": failure_summary,
    }
