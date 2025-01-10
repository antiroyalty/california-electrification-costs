# establish a mapping of IOUs to counties
# look up each county and find their IOU
# calculate their annual electricity bill based on tarrifs
# save one file for each county for average daily, monthly, and annual bills
# also save the average electricity consumption for daily, monthly, and annual (this will be useful for solar+storage capital costs via tesla later)

# Baseline Allowance per Territory and Season
# https://www.pge.com/en/account/rate-plans/how-rates-work/baseline-allowance.html#accordion-2fb51186db-item-2ea52b55e4
# Baseline Allowances for E-TOU-C Rate Plan

from datetime import datetime, timedelta
import os
import pandas as pd

BASELINE_ALLOWANCES = {
    "PGE": {
        "E-TOU-C": {
            "territories": {
                "T": {  # Territory T
                    "summer": 6.5,  # kWh/day
                    "winter": 7.5,  # kWh/day
                },
                # Add other territories as needed
                "P": {
                    "summer": 13.5,
                    "winter": 11.0,
                },
                "Q": {
                    "summer": 9.8,
                    "winter": 11.0,
                },
                "R": {
                    "summer": 17.7,
                    "winter": 10.4,
                },
                "S": {
                    "summer": 15.0,
                    "winter": 10.2,
                },
                "V": {
                    "summer": 7.1,
                    "winter": 8.1,
                },
                "W": {
                    "summer": 19.2,
                    "winter": 9.8,
                },
                "X": {
                    "summer": 9.8,
                    "winter": 9.7,
                },
                "Y": {
                    "summer": 10.5,
                    "winter": 11.1,
                },
                "Z": {
                    "summer": 5.9,
                    "winter": 7.8,
                },
            }
        }
    }
}

RATE_PLANS = {
    "PGE": {
        "E-TOU-C": {
            "summer": { 
                "peak": 0.49, 
                "offPeak": 0.39, 
                "peakHours": [16, 17, 18, 19, 20], 
                "offPeakHours": [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 21, 22, 23],
                "fixedCharge": 0.00,
                "baseline_allowance": BASELINE_ALLOWANCES["PGE"]["E-TOU-C"]["territories"]["T"]["summer"],  # 6.5 kWh/day
            },
            "winter": { 
                "peak": 0.38, 
                "offPeak": 0.35, 
                "peakHours": [16, 17, 18, 19, 20], 
                "offPeakHours": [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 21, 22, 23],
                "fixedCharge": 0.00,
                "baseline_allowance": BASELINE_ALLOWANCES["PGE"]["E-TOU-C"]["territories"]["T"]["winter"],  # 6.5 kWh/day
            }
        },
        "E-TOU-D": {
            "summer": { 
                "peak": 0.55, 
                "offPeak": 0.42, 
                "peakHours": [17, 18, 19], 
                "offPeakHours": [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 20, 21, 22, 23],
                "fixedCharge": 0.00,
            },
            "winter": { 
                "peak": 0.46, 
                "offPeak": 0.42, 
                "peakHours": [17, 18, 19], 
                "offPeakHours": [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 20, 21, 22, 23],
                "fixedCharge": 0.00,
            }
        },
        "EV2-A": {
            "summer": { 
                "peak": 0.62, 
                "offPeak": 0.31, 
                "partPeak": 0.51, 
                "peakHours": [16, 17, 18, 19, 20], 
                "partPeakHours": [15, 21, 22, 23], 
                "offPeakHours": [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14],
                "fixedCharge": 0.00,
            },
            "winter": { 
                "peak": 0.49, 
                "offPeak": 0.31, 
                "partPeak": 0.48, 
                "peakHours": [16, 17, 18, 19, 20], 
                "partPeakHours": [15, 21, 22, 23], 
                "offPeakHours": [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14],
                "fixedCharge": 0.00,
            }
        },
        "EV-B": {
            "summer": { 
                "peak": 0.69, 
                "offPeak": 0.33, 
                "partPeak": 0.44, 
                "peakHours": [14, 15, 16, 17, 18, 19, 20], 
                "partPeakHours": [7, 8, 9, 10, 11, 12, 13, 21, 22], 
                "offPeakHours": [0, 1, 2, 3, 4, 5, 6, 23],
                "fixedCharge": 0.00,
            },
            "winter": { 
                "peak": 0.50, 
                "offPeak": 0.30, 
                "partPeak": 0.37, 
                "peakHours": [14, 15, 16, 17, 18, 19, 20], 
                "partPeakHours": [7, 8, 9, 10, 11, 12, 13, 21, 22], 
                "offPeakHours": [0, 1, 2, 3, 4, 5, 6, 23],
                "fixedCharge": 0.00,
            }
        },
        "E-ELEC": {
            "summer": { 
                "peak": 0.60, 
                "offPeak": 0.38, 
                "partPeak": 0.44, 
                "peakHours": [16, 17, 18, 19, 20], 
                "partPeakHours": [15, 21, 22, 23], 
                "offPeakHours": [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14],
                "fixedCharge": 15.00, # Only E-ELEC has fixed charges: https://www.pge.com/assets/pge/docs/account/rate-plans/residential-electric-rate-plan-pricing.pdf
            },
            "winter": { 
                "peak": 0.37, 
                "offPeak": 0.33, 
                "partPeak": 0.35, 
                "peakHours": [16, 17, 18, 19, 20], 
                "partPeakHours": [15, 21, 22, 23], 
                "offPeakHours": [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14],
                "fixedCharge": 15.00,
            }
        }
    }
}

INPUT_FILE_NAME = "loadprofiles_for_rates"
OUTPUT_FILE_NAME = "RESULTS_electricity_annual_costs"

LOAD_FOR_RATE_ELECTRICITY_COLUMN = ".electricity.kwh"

def get_season(hour_index):
    start_date = datetime(year=2018, month=1, day=1)  # Consistent with NREL inputs
    current_datetime = start_date + timedelta(hours=hour_index)
    month = current_datetime.month
    return 'summer' if 6 <= month <= 9 else 'winter'

def calculate_annual_costs_electricity(load_profile):
    from collections import defaultdict

    annual_costs = defaultdict(float)
    for hour_index, hourly_load in enumerate(load_profile):
        season = get_season(hour_index)
        current_datetime = datetime(year=2023, month=1, day=1) + timedelta(hours=hour_index)
        hour = current_datetime.hour

        for plan_name, plan_details in RATE_PLANS["PGE"].items():
            season_rates = plan_details.get(season)
            if not season_rates:
                continue

            # Determine hourly rate
            if hour in season_rates["peakHours"]:
                rate = season_rates["peak"]
            elif hour in season_rates.get("partPeakHours", []):
                rate = season_rates["partPeak"]
            else:
                rate = season_rates["offPeak"]

            # Calculate hourly cost
            energy_cost = hourly_load * rate
            annual_costs[plan_name] += energy_cost

            # Add fixed charges
            fixed_charge = season_rates.get("fixedCharge", 0.0)
            annual_costs[plan_name] += fixed_charge / 12  # Spread across months

    return annual_costs

def process_county_scenario(file_path, county, load_type):
    file = os.path.join(file_path, f"{INPUT_FILE_NAME}_{county}.csv")
    if not os.path.exists(file):
        raise FileNotFoundError(f"File not found: {file}")

    column_name = f"{load_type}{LOAD_FOR_RATE_ELECTRICITY_COLUMN}"
    df = pd.read_csv(file, usecols=[column_name])

    load_profile = df[column_name].tolist()

    return calculate_annual_costs_electricity(load_profile)

def process_all_counties(base_input_dir, base_output_dir, counties, scenarios, housing_types, load_type):
    valid_load_types = ["default", "solarstorage"]
    if load_type not in valid_load_types:
        raise ValueError(f"Invalid load_type '{load_type}'. Must be one of {valid_load_types}.")

    timestamp = datetime.now().strftime("%Y%m%d_%H")

    for housing_type in housing_types:
        for county in counties:
            for scenario in scenarios:
                file_path = os.path.join(base_input_dir, scenario, housing_type, county)

                annual_costs = process_county_scenario(file_path, county, load_type)

                print(f"For {county}, {load_type}, annual electricity costs are:")
                print(annual_costs)

                # Prepare results as a DataFrame
                results_data = {
                    f"{load_type}.electricity.{plan}.usd": [cost]
                    for plan, cost in annual_costs.items()
                }
                results_df = pd.DataFrame(results_data, index=[scenario])

                # Output file
                output_file_path = os.path.join(base_output_dir, scenario, housing_type, county, "results", f"{OUTPUT_FILE_NAME}_{county}_{timestamp}.csv")

                os.makedirs(os.path.dirname(output_file_path), exist_ok=True)

                if os.path.exists(output_file_path):
                    existing_df = pd.read_csv(output_file_path, index_col="scenario")

                    # Overwrite overlapping columns with the new data
                    for col in results_df.columns:
                        existing_df[col] = results_df[col]

                    combined_df = existing_df
                else:
                    combined_df = results_df

                # Save results
                combined_df.to_csv(output_file_path, index_label="scenario")
                print(f"Results saved to {output_file_path}")

base_input_dir = "./data"
base_output_dir = "./data"
counties = ["alameda"]
scenarios = ["baseline"]
housing_types = ["single-family-detached"]
load_type = "default" # default, solarstorage

process_all_counties(base_input_dir, base_output_dir, counties, scenarios, housing_types, load_type)