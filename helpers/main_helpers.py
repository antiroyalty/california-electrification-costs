# helpers.py
import os
import pandas as pd
import subprocess
from datetime import datetime

LOADPROFILES = "loadprofiles" # folder name where all load profiles are stored

norcal_counties = [
    "Alameda County", "Contra Costa County", "Marin County", "Napa County", 
    "San Francisco County", "San Mateo County", "Santa Clara County", "Solano County", "Sonoma County",  # Bay Area
    "Sacramento County",
    "Del Norte County", "Humboldt County", "Lake County", "Mendocino County", "Trinity County",  # North Coast
    "Butte County", "Colusa County", # "Glenn County", "Lassen County", "Modoc County", 
    "Nevada County", "Plumas County", "Shasta County", "Sierra County", "Tehama County",  # "Siskiyou County", # North Valley & Sierra
]
# Counties with no buildings: Glenn, Modoc, Siskiyou

central_counties = [
    "Fresno County", "Kings County", "Madera County", "Merced County", 
    "San Joaquin County", "Stanislaus County", "Sutter County", 
    "Tulare County", "Yolo County",  # Central Valley
    "Monterey County", "San Benito County", "San Luis Obispo County", 
    "Santa Cruz County",
    "Alpine County", "Amador County", "Mono County",  # Eastern Sierra & Inland
]

socal_counties = [
    "Los Angeles County", "Orange County", "San Bernardino County", 
    "Santa Barbara County", "Kern County",
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

def log(*, log_level: str = "info", **metrics):
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
    if log_level.lower() != "debug":
        return

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

def git_short_sha() -> str:
    """Return the short git SHA for this repo, or 'nogit' if unavailable."""
    try:
        sha = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], 
            stderr=subprocess.DEVNULL
        ).decode().strip()
        return sha or "nogit"
    except Exception:
        return "nogit"


def format_load_profile(load_profile):
    return [round(x, 3) for x in load_profile[5:20]]


def merge_and_write_csv(df: pd.DataFrame, path: str, key_col="county_slug") -> None:
    """Write df to path, preserving existing rows whose key isn't in this run.

    Several pipeline outputs (capital_costs ledgers in step14, cross-scenario
    exports in step18) are single shared files covering every county (and, in
    step18's case, every scenario) for a given output, but a single call site
    often only computes a subset (e.g. a targeted re-run for 3 counties, or a
    cross-scenario comparison over one scenario family). A plain `to_csv`
    silently discards every row not in the current run — this happened for
    real once (an Alameda row was lost extending a 1-county analysis to 3
    more). Instead: drop any existing rows matching this run's keys (so
    re-runs correctly refresh them), then union with rows this run didn't
    touch.

    key_col: a single column name, or a list of column names for a composite
    key. Use a composite key (e.g. ["scenario", "county_slug"]) whenever a
    single call can supply a partial slice along more than one dimension —
    e.g. step18's by-county exports have one row per (scenario, county), so
    keying on county_slug alone would wrongly drop other scenarios' rows for
    a county that reappears in a later, differently-scoped run.

    Note: this is safe for sequential runs only. Concurrent writers to the
    same path can still race (read-modify-write, no locking).
    """
    key_cols = [key_col] if isinstance(key_col, str) else list(key_col)

    if os.path.exists(path):
        existing = pd.read_csv(path)
        if all(k in existing.columns for k in key_cols) and all(k in df.columns for k in key_cols):
            incoming_keys = set(map(tuple, df[key_cols].values.tolist()))
            existing_keys = existing[key_cols].apply(tuple, axis=1)
            existing = existing[~existing_keys.isin(incoming_keys)]
            df = pd.concat([existing, df], ignore_index=True)
    if all(k in df.columns for k in key_cols):
        df = df.sort_values(key_cols)
    df.to_csv(path, index=False)


def log_step(step: int | str, label: str | None = None) -> None:
    """Print a simple step banner for progress visibility.

    Examples
      log_step(8)
      log_step(9, label="PV/Storage")
    """
    name = label if label is not None else step
    print("-" * 15, f" Step {name} ", "-" * 15)
