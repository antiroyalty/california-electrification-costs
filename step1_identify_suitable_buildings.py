import pandas as pd
import os
import re
from helpers import LOADPROFILES, slugify_county_name, is_valid_csv

SCENARIOS = {
    "baseline": {
        # "in.vacancy_status": "Occupied",
        "in.cooking_range": ["Gas"],
        "in.heating_fuel": "Natural Gas",
        "in.water_heater_fuel": "Natural Gas",
        "in.has_pv": "No",
        "in.hvac_cooling_type": None,
        # "in.tenure": "Owner",
    },
}

HOUSING_NAME_MAP = {
    "single-family-detached": "Single-Family Detached",
    "single-family-attached": "Single-Family Attached",
}

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
    if scenario not in SCENARIOS:
        raise ValueError(f"Scenario '{scenario}' is not defined in SCENARIOS dictionary.")
    
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

def process(scenario, housing_type, output_base_dir="data", target_counties=None, force_recompute=True):
    metadata = get_metadata(scenario)
    unique_counties = metadata[['in.county', 'in.county_name']].drop_duplicates()

    if target_counties:
        counties = unique_counties[unique_counties['in.county_name'].isin(target_counties)]
    else:
        counties = unique_counties

    output_csv_paths = []

    for _, row in counties.iterrows():
        county_code = row['in.county']
        county_name = row['in.county_name']

        formatted_county_name = slugify_county_name(county_name)
        output_dir = os.path.join(output_base_dir, LOADPROFILES, housing_type, formatted_county_name)
        output_csv = os.path.join(output_dir, "step1_filtered_building_ids.csv")

         # Step 1: Check if processing is necessary
        if not force_recompute:
            print(f"Skipping {county_name} - existing valid file found at {output_csv}")
            output_csv_paths.append(output_csv)
            continue  # Skip processing

        print(f"Processing {county_name}...")

        # Step 2: Generate metadata
        filtered_metadata = filter_metadata(metadata, housing_type, county_code, county_name, scenario)

        # Step 3: Save building IDs
        output_csv = save_building_ids(filtered_metadata, scenario, county_name, output_dir)
        output_csv_paths.append(output_csv)

    return output_csv_paths

