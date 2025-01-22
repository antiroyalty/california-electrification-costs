# PG&E October 2024 Gas Rate Structure
from datetime import datetime, timedelta
import os
import pandas as pd

# Need mapping from county to service region
# Need other utilities gas rates

# Baseline Allowance for Residential Gas Rates (in therms/day)
BASELINE_ALLOWANCES = {
    "PGE": {
        "G-1": {
            "territories": {
                "P": {
                    "summer": 0.39,  # therms/day
                    "winter_offpeak": 1.88,
                    "winter_onpeak": 2.19,
                },
                "Q": {
                    "summer": 0.56,
                    "winter_offpeak": 1.48,
                    "winter_onpeak": 2.00,
                },
                "R": {
                    "summer": 0.36,
                    "winter_offpeak": 1.24,
                    "winter_onpeak": 1.81,
                },
                "S": {
                    "summer": 0.39,
                    "winter_offpeak": 1.38,
                    "winter_onpeak": 1.94,
                },
                "T": {
                    "summer": 0.56,
                    "winter_offpeak": 1.31,
                    "winter_onpeak": 1.68,
                },
                "V": {
                    "summer": 0.59,
                    "winter_offpeak": 1.51,
                    "winter_onpeak": 1.71,
                },
                "W": {
                    "summer": 0.39,
                    "winter_offpeak": 1.14,
                    "winter_onpeak": 1.68,
                },
                "X": {
                    "summer": 0.49,
                    "winter_offpeak": 1.48,
                    "winter_onpeak": 2.00,
                },
                "Y": {
                    "summer": 0.72,
                    "winter_offpeak": 2.22,
                    "winter_onpeak": 2.58,
                }
            }
        }
    }
}

# Rate plans for gas (per therm)
RATE_PLANS = {
    "PGE": {
        "G-1": {
            "baseline": {
                "procurement_charge": 0.35402,  # per therm
                "transportation_charge": 1.94995,  # per therm
                "total_charge": 2.30397,  # per therm
            },
            "excess": {
                "procurement_charge": 0.35402,  # per therm
                "transportation_charge": 2.44371,  # per therm
                "total_charge": 2.79773,  # per therm
            }
        },
        "G-PPPS": {  # Public Purpose Program Surcharge
            "residential": 0.11051,  # per therm
        },
        "G-NT": {
            "procurement_charge": 0.27473,
            "transportation_charge": 1.30455,  # based on usage tiers
            "total_charge": 1.57928  # per therm (example tier)
        }
    }
}

# https://www.pge.com/assets/rates/tariffs/PGECZ_90Rev.pdf
PGE_RATE_TERRITORY_COUNTY_MAPPING = {
    "T": ["Marin", "San Francisco", "San Mateo"],
    "Q": ["Santa Cruz", "Monterey"],
    "X": [
        "San Luis Obispo", "San Benito", "Santa Clara", 
        "Alameda", "Contra Costa", "Napa", "Sonoma", 
        "Mendocino", "Santa Barbara"
    ],
    "P": ["Sacramento", "Placer", "El Dorado", "Amador"],
    "S": ["Glenn", "Colusa", "Yolo", "Sutter", "Butte"],
    "R": ["Merced", "Fresno", "Madera", "Mariposa", "Tehama"],
    "Y&Z": ["Nevada", "Plumas", "Humboldt", "Trinity", "Lake", "Shasta", "Sierra", "Alpine", "Mono"],
    "W": ["Kings"]
}

INPUT_FILE_NAME = "loadprofiles_for_rates"
OUTPUT_FILE_NAME = "RESULTS_gas_annual_costs"
OUTPUT_COLUMNS = ["county", "scenario", "housing_type", "territory", "annual_cost"]

LOAD_FOR_RATE_GAS_COLUMN_SUFFIX = ".gas.therms"

def categorize_season(month_number):
    # TODO, Ana: Make sure that these season categorizations are the same for each utility
    # ie, each peak / offpeak period corresponds to the right seasons here
    if month_number in [11, 2, 3]:  # November, February, March
        return 'winter_offpeak'
    elif month_number in [12, 1]:   # December, January
        return 'winter_onpeak'
    elif month_number in range(4, 11):  # April to October (inclusive)
        return 'summer'
    else:
        raise ValueError(f"Unexpected month provided: {month_number}")  # Fallback, shouldn't happen if months are correct

def sum_therms_by_season(gas_data, load_type):
    gas_data['season'] = gas_data['month'].apply(categorize_season)
    
    therms_by_season = gas_data.groupby('season')[f"{load_type}{LOAD_FOR_RATE_GAS_COLUMN_SUFFIX}"].sum()
    total_therms = gas_data[f"{load_type}{LOAD_FOR_RATE_GAS_COLUMN_SUFFIX}"].sum()
    
    return therms_by_season, total_therms

# TODO, Ana: this currently only works for PG&E rates. Add SCE and SDGE rates too.
def calculate_annual_costs_gas(load_profile_df, territory, load_type):
    seasonal_therms, total_therms = sum_therms_by_season(load_profile_df, load_type)
    
    # Initialize the total cost
    total_cost = 0.0
    
    # Loop through each season and calculate the cost
    for season, therms_used in seasonal_therms.items():
        # Retrieve the baseline allowance for the season
        baseline = BASELINE_ALLOWANCES["PGE"]["G-1"]["territories"][territory][season]
        
        # Determine if usage is within baseline or exceeds it
        if therms_used <= baseline:
            rate = RATE_PLANS["PGE"]["G-1"]["baseline"]["total_charge"]
        else:
            rate = RATE_PLANS["PGE"]["G-1"]["excess"]["total_charge"]
        
        seasonal_cost = therms_used * rate
        total_cost += seasonal_cost
    
    return total_cost

def get_territory_for_county(county):
    # TODO: Ana, establish key-value pair of mapping for all counties to gas rate territories
    # Currently implemented for SOME PG&E territories
    # This assumes that each county can only belong to one territory, but this is not necessarily the case
    # The allocation is done visually, roughly by area
    # County that has the largest area in a territory gets attributed to that territory
    # Yet to add support for SCE and SDGE
    for territory, counties in PGE_RATE_TERRITORY_COUNTY_MAPPING.items():
        if county in counties:
            return territory
    else:
        raise ValueError("Step10@get_territory_for_county: County to gas territory mapping not specified.")

def process_county_scenario(file_path, county, load_type):
    file = os.path.join(file_path, f"{INPUT_FILE_NAME}_{county}.csv")

    if not os.path.exists(file):
        print(f"Step10@process_county_scenario: File not found: {file}")
        return None

    load_profile_df = pd.read_csv(file, parse_dates=["timestamp"])
    load_profile_df["month"] = load_profile_df["timestamp"].dt.month

    print(load_profile_df["month"])

    territory = get_territory_for_county(county) # "T"  # Placeholder for territory mapping logic. Alameda == territory T
    
    return calculate_annual_costs_gas(load_profile_df, territory, load_type)

def process(base_input_dir, base_output_dir, scenarios, housing_types, counties, load_type):
    valid_load_types = ["default", "solarstorage"]
    if load_type not in valid_load_types:
        raise ValueError(f"Invalid load_type '{load_type}'. Must be one of {valid_load_types}.")
    
    timestamp = datetime.now().strftime("%Y%m%d_%H")

    for housing_type in housing_types:
        for county in counties:
            for scenario in scenarios:
                file_path = os.path.join(base_input_dir, scenario, housing_type, county)

                annual_costs = process_county_scenario(file_path, county, load_type)
            
                print(f"For {county}, {load_type}, total annual gas costs are: {annual_costs}")
                results_df = pd.DataFrame({
                    f"{load_type}.gas.usd": [annual_costs],
                }, index=[scenario])

                # Define the output file path
                output_file_path = os.path.join(base_output_dir, scenario, housing_type, county, "results", f"{OUTPUT_FILE_NAME}_{county}_{timestamp}.csv")

                if os.path.exists(output_file_path):
                    # Read the existing file
                    existing_df = pd.read_csv(output_file_path, index_col="scenario")
                    
                    # Overwrite the column if it exists
                    if f"{load_type}.gas.usd" in existing_df.columns:
                        print(f"Overwriting existing column '{load_type}.gas.usd'.")
                        existing_df = existing_df.drop(columns=[f"{load_type}.gas.usd"])
                    
                    # Merge the new column
                    combined_df = existing_df.join(results_df, how="outer")
                else:
                    # If the file doesn't exist, use the new DataFrame
                    combined_df = results_df

                # Save the updated DataFrame
                combined_df.to_csv(output_file_path, index_label="scenario")
                print(f"Results saved to {output_file_path}")

# base_input_dir = "data"
# base_output_dir = "data"
# counties = ["alameda"] # , "alpine", "riverside"]
# scenarios = ["baseline"]
# housing_types = ["single-family-detached"]
# load_type = "solarstorage" # default, solarstorage

# process(base_input_dir, base_output_dir, scenarios, housing_types, counties, load_type)
