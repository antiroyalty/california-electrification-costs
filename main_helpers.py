# helpers.py
import os
import pandas as pd
from datetime import datetime

LOADPROFILES = "loadprofiles" # folder name where all load profiles are stored

norcal_counties = [
    "Alameda County", "Contra Costa County", "Marin County", "Napa County", 
    "San Francisco County", "San Mateo County", "Santa Clara County", "Solano County", "Sonoma County",  # Bay Area
    "Del Norte County", "Humboldt County", "Lake County", "Mendocino County", "Trinity County",  # North Coast
    "Butte County", "Colusa County", # "Glenn County", "Lassen County", "Modoc County", 
    "Nevada County", "Plumas County", "Shasta County", "Sierra County", "Tehama County",  # "Siskiyou County", # North Valley & Sierra
]
# Counties with no buildings: Glenn, Modoc, Siskiyou

central_counties = [
    "Fresno County", "Kern County", "Kings County", "Madera County", "Merced County", 
    "Sacramento County", "San Joaquin County", "Stanislaus County", "Sutter County", 
    "Tulare County", "Yolo County",  # Central Valley
    "Monterey County", "San Benito County", "San Luis Obispo County", "Santa Barbara County", 
    "Santa Cruz County", "Ventura County",  # Central Coast
    "Alpine County", "Amador County", "Mono County",  # Eastern Sierra & Inland
]

socal_counties = [
    "Los Angeles County", "Orange County", "San Bernardino County", 
    "Riverside County", "Ventura County",  # Greater Los Angeles
    "San Diego County", "Imperial County"  # San Diego & Imperial
]

def is_valid_csv(file_path):
    """Checks if a CSV file is valid: non-empty, contains expected data."""
    try:
        if os.path.getsize(file_path) == 0:  # Empty file
            return False

        df = pd.read_csv(file_path, nrows=10)  # Read only a few rows for efficiency

        required_columns = ["timestamp", "total_load"]  # Ensure necessary columns exist
        if not all(col in df.columns for col in required_columns):
            return False

        if df.empty or df["timestamp"].isnull().all():
            return False

        return True
    except Exception as e:
        print(f"Error validating {file_path}: {e}")
        return False

def slugify_county_name(county_name: str) -> str:
    """
    Takes a county name like "Santa Clara County" or "Riverside County"
    and converts it to a slug: "santa-clara", "riverside", etc.
    
    Example transformations:
      "Riverside County"   -> "riverside"
      "Santa Clara County" -> "santa-clara"
      " Lake County  "     -> "lake"
    """
    if not isinstance(county_name, str):
        raise TypeError(f"Expected a string for county_name, got {type(county_name).__name__}")
    
    return (
        county_name.lower()
                   .replace("county", "")
                   .strip()
                   .replace(" ", "-")
    )

def get_timestamp():
    return datetime.now().strftime("%Y%m%d_%H")

def get_counties(scenario_path, counties):
    if counties is None: # Dynamically retrieve counties
        return [c for c in os.listdir(scenario_path) if os.path.isdir(os.path.join(scenario_path, c))]

    # format as ['alameda'] not ['Alameda County']
    return [slugify_county_name(c) for c in counties]

def get_scenario_path(base_input_dir, scenario, housing_type):
    scenario_path = os.path.join(base_input_dir, scenario, housing_type)

    if not os.path.exists(scenario_path):
        print(f"Scenario path not found: {scenario_path}")

    return scenario_path

def log(**metrics):
    """
    Logs a standardized message summarizing key outputs from a processing step.
    
    Example usage:
    
        log(
            at=6,
            description="Combined load profiles computed for alameda",
            electricity_real="1351.94 kWh",
            electricity_simulated="0 kWh",
            combined_electricity="1351.94 kWh",
            gas_real="423.217 therms",
            gas_adjustment="-423.217 therms",
            combined_gas="0.0 therms"
        )
    
    Parameters:
        step (int or str, optional): Identifier for the processing step.
        description (str, optional): A brief description of what the step does.
        **metrics: Arbitrary key-value pairs for important numbers (e.g., counts, annual totals, costs).
    """
    if metrics:
        # Determine the longest key for nice alignment.
        key_length =[len(str(key)) for key in metrics.keys()]
        max_key_length = max(key_length + [30])
        for key, value in metrics.items():
            # Format the key to be title-cased and replace underscores with spaces.
            key_formatted = key.replace('_', ' ').ljust(max_key_length)
            print(f"{key_formatted}: {value}")

def to_number(number):
    if number is None or pd.isnull(number):
        return "N/A"
    try:
        return f"{number:_.0f}"
    except (TypeError, ValueError):
        return "N/A"

def to_decimal_number(number):
    if number is None or pd.isnull(number):
        return "N/A"
    try:
        return f"{number:,.2f}"
    except (TypeError, ValueError):
        return "N/A"


def format_load_profile(load_profile):
    return [round(x, 3) for x in load_profile[5:20]]