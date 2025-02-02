import pandas as pd
import os
import re
from helpers import LOADPROFILES

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
    # "heat_pump_and_water_heater": {
    #     "in.vacancy_status": "Occupied",
    #     "in.cooking_range": ["Gas"],
    #     "in.heating_fuel": "Electricity",
    #     "in.water_heater_fuel": "Electricity",
    #     "in.has_pv": "No",
    #     "in.hvac_cooling_type": None,
    #     "in.hvac_heating_type": ["Ducted Heat Pump", "Non-Ducted Heat Pump"],
    # },
    # "heat_pump_water_heater_and_induction_stove": {
    #     "in.cooking_range": ["Electric Induction"],
    #     "in.heating_fuel": "Electricity",
    #     "in.hvac_heating_type": ["Ducted Heat Pump", "Non-Ducted Heat Pump"],
    #     "in.water_heater_fuel": "Electricity",
    #     "in.has_pv": "No",
    #     "in.vacancy_status": "Occupied",
    # },
    # "heat_pump_heating_cooling_water_heater_and_induction_stove": {
    #     "in.cooking_range": ["Electric Induction"],
    #     "in.heating_fuel": "Electricity",
    #     "in.hvac_heating_type": ["Ducted Heat Pump", "Non-Ducted Heat Pump"],
    #     "in.water_heater_fuel": "Electricity",
    #     "in.has_pv": "No",
    #     "in.hvac_cooling_type": ["Ducted Heat Pump", "Non-Ducted Heat Pump"],
    #     "in.vacancy_status": "Occupied",
    # },
    # "baseline_sell_back_to_grid": {
    #     "in.cooking_range": ["Gas"],
    #     "in.heating_fuel": "Natural Gas",
    #     "in.water_heater_fuel": "Natural Gas",
    #     "in.has_pv": "No",
    #     "in.hvac_cooling_type": None,
    #     "in.vacancy_status": "Occupied",
    # }
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
    
    housing_name_map = {
        "single-family-detached": "Single-Family Detached",
        "single-family-attached": "Single-Family Attached",
    }

    # Initial conditions based on county and housing type
    upgrade = "0" # baseline, no housing upgrades
    county_condition = metadata["in.county"] == county_code
    county_name_condition = metadata["in.county_name"] == county_name
    housing_condition = metadata["in.geometry_building_type_recs"] == housing_name_map[housing_type]

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

def generate_output_filename(county_name):
    filename = county_name.lower()
    filename = re.sub(r'[\s_]+', '-', filename)
    filename = filename.replace('county', '').strip('-')

    return filename

def process(scenario, housing_type, output_base_dir="data", target_counties=None):
    metadata = get_metadata(scenario)
    unique_counties = metadata[['in.county', 'in.county_name']].drop_duplicates()

    if target_counties:
        print("inside specified target counties")
        print(target_counties)
        print(unique_counties)
        counties = unique_counties[unique_counties['in.county_name'].isin(target_counties)]
        print(counties)
    else:
        counties = unique_counties

    output_csv_paths = []

    for _, row in counties.iterrows():
        county_code = row['in.county']
        county_name = row['in.county_name']

        print("Running in for loop")
        formatted_county_name = generate_output_filename(county_name)
        print(formatted_county_name)
        output_dir = os.path.join(output_base_dir, LOADPROFILES, housing_type, formatted_county_name)
        filtered_metadata = filter_metadata(metadata, housing_type, county_code, county_name, scenario)
        print("Metadata filtered")
        print(filtered_metadata)
        output_csv = save_building_ids(filtered_metadata, scenario, county_name, output_dir)
        
        output_csv_paths.append(output_csv)

    return output_csv_paths

