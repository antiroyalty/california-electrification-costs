import os
import pandas as pd
import boto3
from botocore.client import Config
from botocore import UNSIGNED
from helpers import get_scenario_path, get_counties, log, norcal_counties, socal_counties, central_counties

s3 = boto3.client('s3', config=Config(signature_version=UNSIGNED))
S3_PREFIX = "nrel-pds-building-stock/end-use-load-profiles-for-us-building-stock/2024/resstock_amy2018_release_2/timeseries_individual_buildings/by_state/upgrade=0/state=CA/"
S3_BUCKET_NAME = "oedi-data-lake"
METADATA_FILE_NAME = "step1_filtered_building_ids.csv"

def ensure_directory_exists(directory):
    if not os.path.exists(directory):
        os.makedirs(directory)
        log(
            at="ensure_directory_exists",
            directory=directory,
            status="created",
            details=f"Directory '{directory}' created."
        )

def download_parquet_file(bucket_name, s3_key, output_dir):
    output_file = os.path.join(output_dir, os.path.basename(s3_key))
    
    if os.path.exists(output_file):
        return
    
    try:
        s3.download_file(Bucket=bucket_name, Key=s3_key, Filename=output_file)
    except Exception as e:
        log(
            at="download_parquet_file",
            bucket_name=bucket_name,
            s3_key=s3_key,
            output_file=output_file,
            status="error",
            error=str(e),
            details="Error downloading file."
        )

def check_for_downloads(output_dir, building_ids):
    downloaded_files = [f for f in os.listdir(output_dir) if os.path.isfile(os.path.join(output_dir, f))]
    return len(building_ids) == len(downloaded_files)

def process_county(scenario, housing_type, county_path, bucket_name, s3_prefix, output_base_dir):
    county_metadata_path = os.path.join(county_path, METADATA_FILE_NAME)
    county_name = os.path.basename(county_path)
    scenario_path = get_scenario_path(output_base_dir, scenario, housing_type)

    try:
        county_buildings = pd.read_csv(county_metadata_path)
    except FileNotFoundError:
        log(
            at="process_county",
            county=county_name,
            status="error",
            details="Metadata file not found."
        )
        return {
            "county": county_name,
            "total_buildings": 0,
            "retrieved_buildings": 0,
            "missing_buildings": 0,
            "status": "failure"
        }

    building_ids = county_buildings["bldg_id"].to_list()
    total_buildings = len(building_ids)
    buildings_directory = os.path.join(scenario_path, county_name, "buildings")

    ensure_directory_exists(buildings_directory)

    if check_for_downloads(buildings_directory, building_ids):
        return {
            "county": county_name,
            "total_buildings": total_buildings,
            "retrieved_buildings": total_buildings,
            "missing_buildings": 0,
            "status": "success"
        }

    for bldg_id in building_ids:
        s3_key = f"{s3_prefix}{bldg_id}-0.parquet"
        download_parquet_file(bucket_name, s3_key, buildings_directory)

    downloaded_files = [f for f in os.listdir(buildings_directory) if os.path.isfile(os.path.join(buildings_directory, f))]
    retrieved_buildings = len(downloaded_files)
    missing_buildings = total_buildings - retrieved_buildings

    # Log only if the download is incomplete.
    if retrieved_buildings != total_buildings:
        log(
            at="process_county",
            county=county_name,
            status="error",
            details=f"Download incomplete: expected {total_buildings}, got {retrieved_buildings}."
        )

    return {
        "county": county_name,
        "total_buildings": total_buildings,
        "retrieved_buildings": retrieved_buildings,
        "missing_buildings": missing_buildings,
        "status": "success" if retrieved_buildings == total_buildings else "failure"
    }


def process(scenario, housing_type, counties, output_base_dir="data", download_new_files=True):
    results = []

    if not download_new_files or scenario != "baseline":
        log(at="process", details="No new building files needed to be downloaded.")
        return results

    scenario_path = get_scenario_path(output_base_dir, scenario, housing_type)
    counties_list = get_counties(scenario_path, counties)
    
    for county_name in counties_list:
        county_path = os.path.join(scenario_path, county_name)
        county_summary = process_county(
            scenario=scenario,
            housing_type=housing_type,
            county_path=county_path,
            bucket_name=S3_BUCKET_NAME,
            s3_prefix=S3_PREFIX,
            output_base_dir=output_base_dir
        )
        results.append(county_summary)

    total_counties = len(counties_list)
    total_buildings_expected = sum(entry.get("total_buildings", 0) for entry in results)
    total_buildings_downloaded = sum(entry.get("retrieved_buildings", 0) for entry in results)
    total_buildings_missing = sum(entry.get("missing_buildings", 0) for entry in results)

    log(
        at="process",
        total_counties=total_counties,
        total_buildings_expected=total_buildings_expected,
        total_buildings_downloaded=total_buildings_downloaded,
        total_buildings_missing=total_buildings_missing,
    )

    return results