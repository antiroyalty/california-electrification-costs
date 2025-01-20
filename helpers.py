# helpers.py
import os

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

    return [slugify_county_name(c) for c in counties]

def get_scenario_path(base_input_dir, scenario, housing_type):
    scenario_path = os.path.join(base_input_dir, scenario, housing_type)

    if not os.path.exists(scenario_path):
        print(f"Scenario path not found: {scenario_path}")

    return scenario_path