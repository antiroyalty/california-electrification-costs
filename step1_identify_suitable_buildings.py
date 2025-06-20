import pandas as pd
import os
import re
from helpers import LOADPROFILES, slugify_county_name, log, norcal_counties, socal_counties, central_counties

# Metadata downloaded from:
# 2024 edition of Resstock_AMY2018_release_2
# https://data.openei.org/s3_viewer?bucket=oedi-data-lake&prefix=nrel-pds-building-stock%2Fend-use-load-profiles-for-us-building-stock%2F2024%2Fresstock_amy2018_release_2%2Fmetadata_and_annual_results%2Fby_state%2Fstate%3DCA%2Fcsv%2F
# Instead, I could try 2024 TMY data available here:
# https://data.openei.org/s3_viewer?bucket=oedi-data-lake&prefix=nrel-pds-building-stock%2Fend-use-load-profiles-for-us-building-stock%2F2024%2Fresstock_dataset_2024.1%2Fresstock_tmy3%2Fmetadata_and_annual_results%2Fby_state%2Fstate%3DCA%2Fcsv%2FBaseline%2F
# But currently I use AMY2018
SCENARIOS = {
    "baseline": {
        "in.vacancy_status": "Occupied",
        "in.cooking_range": ["Gas"],
        "in.heating_fuel": "Natural Gas",
        "in.water_heater_fuel": "Natural Gas",
        # "in.has_pv": "No",
        # "in.hvac_cooling_type": None, # May not apply for central valley / socal
        "in.tenure": "Owner",
        # TODO: Ana, investigate whether we can get results for Owned vs. Rented
    },
}

SPECIAL_COUNTIES_CONDITIONS_NEEDED_TO_RETURN_AT_LEAST_ONE_BUILDING = {
    "Inyo County": "special_cooking_heating_water",

        "special_cooking_heating_water": {
        "in.vacancy_status": "Occupied",
        "in.cooking_range": ["Electric Resistance", "Electric Induction"],
        # "in.heating_fuel": ["Electricity"],
        # "in.water_heater_fuel": "Electricity",
    }
}

HOUSING_NAME_MAP = {
    "single-family-detached": "Single-Family Detached",
    "single-family-attached": "Single-Family Attached",
}

SPECIAL_CASE_COUNTIES = ["Inyo County"]

def get_metadata(scenario):
    metadata_path = os.path.join(
        "data",
        f"CA_metadata_and_annual_results.csv"
    )
    
    try:
        metadata = pd.read_csv(metadata_path, low_memory=False)
    except FileNotFoundError:
        raise FileNotFoundError(f"Metadata file not found at {metadata_path}")
    
    return metadata

def filter_metadata(metadata, housing_type, county_code, county_name, scenario):
    # Only need new metadata filters for baseline
    # Because we are doing an apples-to-apples comparison
    # So we have to be converting existing buildings via thermo / phyiscs properties
    
# Initial conditions based on upgrade, county and housing type
    upgrade = (metadata["upgrade"] == 0) # baseline, no housing upgrades
    county_condition = metadata["in.county"] == county_code
    county_name_condition = metadata["in.county_name"] == county_name
    housing_condition = metadata["in.geometry_building_type_recs"] == HOUSING_NAME_MAP[housing_type]

    # Combine initial conditions using bitwise AND
    conditions = upgrade & county_condition & county_name_condition & housing_condition

    scenario_filters = SCENARIOS[scenario]

    for column, condition in scenario_filters.items():
        if condition is None:
            conditions &= metadata[column].isna()
        elif isinstance(condition, list):
            conditions &= metadata[column].isin(condition)
        else:
            conditions &= (metadata[column] == condition)

        filtered_count = metadata[conditions].shape[0]

    filtered_metadata = metadata[conditions]

    return filtered_metadata

def save_building_ids(filtered_metadata, scenario, county, output_dir):
    os.makedirs(output_dir, exist_ok=True)
    
    building_id_column = "bldg_id"

    if building_id_column not in filtered_metadata.columns:
        raise ValueError(f"Column '{building_id_column}' not found in metadata")
    
    building_ids = filtered_metadata[building_id_column].unique()
    df_building_ids = pd.DataFrame(building_ids, columns=[building_id_column])
    
    output_csv_path = os.path.join(
        output_dir,
        f"step1_filtered_building_ids.csv"
    )
    
    df_building_ids.to_csv(output_csv_path, index=False)
    
    return output_csv_path

def get_metadata_for_counties_including_special_case_counties(metadata, housing_type, county_code, county_name, scenario):
    # if county_name in SPECIAL_CASE_COUNTIES:
    #     print("inside the special case")
    #     special_conditions = SPECIAL_COUNTIES_CONDITIONS_NEEDED_TO_RETURN_AT_LEAST_ONE_BUILDING[county_name]
    #     print(special_conditions)

    #     return filter_metadata(metadata, housing_type, county_code, county_name, special_conditions)
    # else:
        return filter_metadata(metadata, housing_type, county_code, county_name, scenario)

def process(scenario, housing_type, output_base_dir="data", target_counties=None, force_recompute=True):
    if scenario != "baseline":
        log(at="step1_identify_suitable_buildings", message="not baseline scenario, no need to download new files", scenario=scenario)
        return [] # Early return; we only need to filter metadata for baseline -- for all other runs, use baseline metadata and buildings, and convert them using thermo properties

    metadata = get_metadata(scenario)
    unique_counties = metadata[['in.county', 'in.county_name']].drop_duplicates()

    if target_counties:
        counties = unique_counties[unique_counties['in.county_name'].isin(target_counties)]
    else:
        counties = unique_counties

    output_csv_paths = []
    processed_count = 0
    skipped_count = 0
    total_buildings = 0

    for _, row in counties.iterrows():
        county_code = row['in.county']
        county_name = row['in.county_name']

        formatted_county_name = slugify_county_name(county_name)
        output_dir = os.path.join(output_base_dir, scenario, housing_type, formatted_county_name)
        output_csv = os.path.join(output_dir, "step1_filtered_building_ids.csv")

         # Step 1: Check if processing is necessary
        if not force_recompute:
            output_csv_paths.append(output_csv)
            skipped_count += 1
            continue  # Skip processing

        # Step 2: Generate metadata
        filtered_metadata = get_metadata_for_counties_including_special_case_counties(metadata, housing_type, county_code, county_name, scenario)
        # filtered_metadata = filter_metadata(metadata, housing_type, county_code, county_name, scenario)
        num_buildings = filtered_metadata.shape[0]
        total_buildings += num_buildings

        # Step 3: Save building IDs
        output_csv = save_building_ids(filtered_metadata, scenario, county_name, output_dir)
        output_csv_paths.append(output_csv)
        processed_count += 1

    log(
        step=1,
        title="identify suitable buildings",
        num_counties_processed=len(output_csv_paths),
        total_csv_files_generated=len(output_csv_paths),
        counties_processed=processed_count,
        counties_skipped=skipped_count
    )
    return output_csv_paths

# Done: single-family-detached: norcal, socal, central
# Done: Single-family-attached: norcal, socal, central
# process("baseline", "single-family-attached", output_base_dir="data", target_counties=central_counties, force_recompute=True)

if __name__ == '__main__':
    process("baseline", "single-family-detached", output_base_dir="data", target_counties=["Inyo County"], force_recompute=True)
