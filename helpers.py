# helpers.py
import os
import pandas as pd

LOADPROFILES = "loadprofiles" # folder name where all load profiles are stored

norcal_counties = [
    "Alameda County", "Contra Costa County", "Marin County", "Napa County", 
    "San Francisco County", "San Mateo County", "Santa Clara County", "Solano County", "Sonoma County",  # Bay Area
    "Del Norte County", "Humboldt County", "Lake County", "Mendocino County", "Trinity County",  # North Coast
    "Butte County", "Colusa County", "Glenn County", "Lassen County", "Modoc County", 
    "Nevada County", "Plumas County", "Shasta County", "Sierra County", "Siskiyou County", "Tehama County",  # North Valley & Sierra
]

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