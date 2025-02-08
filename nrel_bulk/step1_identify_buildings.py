import pandas as pd
import os
import re
import sys

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from helpers import LOADPROFILES, slugify_county_name, is_valid_csv, norcal_counties, socal_counties, central_counties

SCENARIOS = {
    "all": {
    },
}
NREL_RESSTOCK_UPGRADE_NUMBER = 11

def get_metadata(scenario):
    metadata_path = os.path.join(
        "data",
        # f"CA_metadata_and_annual_results.csv"
        "CA_upgrade11_metadata_and_annual_results.csv"
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
    upgrade = (metadata["upgrade"] == NREL_RESSTOCK_UPGRADE_NUMBER) 
    county_condition = metadata["in.county"] == county_code
    county_name_condition = metadata["in.county_name"] == county_name

    # Combine initial conditions using bitwise AND
    conditions = upgrade & county_condition & county_name_condition

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
        output_dir = os.path.join(output_base_dir, formatted_county_name)
        print(f"Outputting files to: {output_dir}")
        output_csv = os.path.join(output_dir, "step1_nrel_bulkfiltered_building_ids.csv")

         # Step 1: Check if processing is necessary
        if not force_recompute:
            print(f"Skipping {county_name} since recompute was not request. Would have generated file in: {output_csv}")
            output_csv_paths.append(output_csv)
            continue  # Skip processing

        print(f"Processing {county_name}...")

        # Step 2: Generate metadata
        filtered_metadata = filter_metadata(metadata, housing_type, county_code, county_name, scenario)

        # Step 3: Save building IDs
        output_csv = save_building_ids(filtered_metadata, scenario, county_name, output_dir)
        output_csv_paths.append(output_csv)

    return output_csv_paths

# Done: upgrade0 norcal_counties, socal_counties, central_counties
# Done: upgrade6 norcal_counties, 
counties = norcal_counties + central_counties + socal_counties

process("all", "all", output_base_dir="../data/nrel/upgrade11", target_counties=counties, force_recompute=True)