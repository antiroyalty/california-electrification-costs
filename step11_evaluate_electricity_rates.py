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
from helpers import get_counties, get_scenario_path, log, to_number

BASELINE_ALLOWANCES = {
    "PGE": {
        "E-TOU-C": {
            "territories": {
                "P": {"summer": 13.5, "winter": 11.0},
                "Q": {"summer": 9.8,  "winter": 11.0},
                "R": {"summer": 17.7, "winter": 10.4},
                "S": {"summer": 15.0, "winter": 10.2},
                "T": {"summer": 6.5,  "winter": 7.5},
                "V": {"summer": 7.1,  "winter": 8.1},
                "W": {"summer": 19.2, "winter": 9.8},
                "X": {"summer": 9.8,  "winter": 9.7},
                "Y": {"summer": 10.5, "winter": 11.1},
                "Z": {"summer": 5.9,  "winter": 7.8},
            }
        }
    }
}

# Revised rate plans for E-TOU-C.
# From the PDF, the Total Usage rates for E-TOU-C are:
#   Summer: Peak = $0.60729, Off-Peak = $0.50429, with a baseline credit of $0.10135.
#   Winter: Peak = $0.49312, Off-Peak = $0.46312, with the same baseline credit.
# Note: The baseline credit applies only to baseline usage.
RATE_PLANS = {
    "PGE": {
        "E-TOU-C": { # https://www.pge.com/tariffs/assets/pdf/tariffbook/ELEC_SCHEDS_E-TOU-C.pdf
            "summer": {
                "peak": 0.60729,
                "offPeak": 0.50429,
                "peakHours": list(range(16, 21)),  # 4:00 p.m. to 9:00 p.m.
                "offPeakHours": [h for h in range(24) if h not in range(16, 21)],
                "fixedCharge": 0.00,
                "baseline_credit": 0.10135,
                # Defaulting to territory T baseline allowance;
                # In practice this should be chosen per the customer's territory.
                "baseline_allowance": BASELINE_ALLOWANCES["PGE"]["E-TOU-C"]["territories"]["T"]["summer"],
            },
            "winter": {
                "peak": 0.49312,
                "offPeak": 0.46312,
                "peakHours": list(range(16, 21)),
                "offPeakHours": [h for h in range(24) if h not in range(16, 21)],
                "fixedCharge": 0.00,
                "baseline_credit": 0.10135,
                "baseline_allowance": BASELINE_ALLOWANCES["PGE"]["E-TOU-C"]["territories"]["T"]["winter"],
            }
        },
        "E-TOU-D": { # https://www.pge.com/tariffs/assets/pdf/tariffbook/ELEC_SCHEDS_E-TOU-D.pdf
            "summer": {
                # Updated from 0.55/0.42 to the PDF's Total Usage rates:
                "peak": 0.56462, 
                "offPeak": 0.42966, 
                # Peak period: 5:00 p.m. to 8:00 p.m. (i.e., hours 17, 18, 19)
                "peakHours": [17, 18, 19], 
                # Off-peak: All other hours (note: this does not account for holidays)
                "offPeakHours": [h for h in range(24) if h not in [17, 18, 19]],
                "fixedCharge": 0.00,
            },
            "winter": {
                # Updated from 0.46/0.42 to the PDF's Total Usage rates:
                "peak": 0.47502, 
                "offPeak": 0.43641, 
                "peakHours": [17, 18, 19], 
                "offPeakHours": [h for h in range(24) if h not in [17, 18, 19]],
                "fixedCharge": 0.00,
            }
        },
        "EV2-A": {  # https://www.pge.com/tariffs/assets/pdf/tariffbook/ELEC_SCHEDS_EV2%20(Sch).pdf EV2 bills are issued as EV2-A
            "summer": {
                "peak": 0.61590,      # Peak rate ($ per kWh)
                "partPeak": 0.50541,  # Partial-Peak rate ($ per kWh)
                "offPeak": 0.30339,   # Off-Peak rate ($ per kWh)
                # Peak: 4:00 p.m. to 9:00 p.m. every day (hours 16–20)
                "peakHours": [16, 17, 18, 19, 20],
                # Partial-Peak: 3:00 p.m. (15:00) and 9:00 p.m. to midnight (21–23)
                "partPeakHours": [15, 21, 22, 23],
                # Off-Peak: All other hours
                "offPeakHours": [h for h in range(24) if h not in [15, 16, 17, 18, 19, 20, 21, 22, 23]],
                # Delivery Minimum Bill Amount per meter per day:
                "fixedCharge": 0.39167,
            },
            "winter": {
                "peak": 0.48879,      # Peak rate ($ per kWh)
                "partPeak": 0.47209,  # Partial-Peak rate ($ per kWh)
                "offPeak": 0.30339,   # Off-Peak rate ($ per kWh)
                "peakHours": [16, 17, 18, 19, 20],
                "partPeakHours": [15, 21, 22, 23],
                "offPeakHours": [h for h in range(24) if h not in [15, 16, 17, 18, 19, 20, 21, 22, 23]],
                "fixedCharge": 0.39167,
            }
        },
        "E-ELEC": { # https://www.pge.com/tariffs/assets/pdf/tariffbook/ELEC_SCHEDS_E-ELEC.pdf
            "summer": {
                "peak": 0.60728,      # Peak rate (4:00–9:00 p.m.)
                "partPeak": 0.44540,  # Partial-Peak rate (3:00–4:00 p.m. and 9:00–12:00 a.m.)
                "offPeak": 0.38872,   # Off-Peak rate (all other hours)
                # Time periods based on the PDF’s special conditions:
                # Peak: 4:00 p.m. to 9:00 p.m. every day
                "peakHours": [16, 17, 18, 19, 20],
                # Partial-Peak: 3:00 p.m. (15) and 9:00 p.m. to midnight (21, 22, 23)
                "partPeakHours": [15, 21, 22, 23],
                # Off-Peak: All other hours
                "offPeakHours": [h for h in range(24) if h not in [15, 16, 17, 18, 19, 20, 21, 22, 23]],
                # Base Services Charge per meter per day
                "fixedCharge": 0.49281,
            },
            "winter": {
                # Winter Total Energy Rates per the PDF:
                "peak": 0.37577,      # Peak rate (4:00–9:00 p.m.)
                "partPeak": 0.35368,  # Partial-Peak rate (3:00–4:00 p.m. and 9:00–12:00 a.m.)
                "offPeak": 0.33982,   # Off-Peak rate (all other hours)
                "peakHours": [16, 17, 18, 19, 20],
                "partPeakHours": [15, 21, 22, 23],
                "offPeakHours": [h for h in range(24) if h not in [15, 16, 17, 18, 19, 20, 21, 22, 23]],
                "fixedCharge": 0.49281,
            }
        },
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

    file = os.path.join(file_path, f"{INPUT_FILE_NAME}_{county}.csv")

    if not os.path.exists(file):
        raise FileNotFoundError(f"File not found: {file}")
    if not os.path.exists(file):
        raise FileNotFoundError(f"File not found: {file}")

    column_name = f"{load_type}{LOAD_FOR_RATE_ELECTRICITY_COLUMN}"
    df = pd.read_csv(file, usecols=[column_name])

    load_profile = df[column_name].tolist()

    return calculate_annual_costs_electricity(load_profile)

def process(base_input_dir, base_output_dir, scenarios, housing_types, counties, load_type):
    valid_load_types = ["default", "solarstorage"]
    if load_type not in valid_load_types:
        raise ValueError(f"Invalid load_type '{load_type}'. Must be one of {valid_load_types}.")

    timestamp = datetime.now().strftime("%Y%m%d_%H")

    for housing_type in housing_types:
        for scenario in scenarios:
            scenario_path = get_scenario_path(base_input_dir, scenario, housing_type)
            counties = get_counties(scenario_path, counties)

            for county in counties:
                file_path = os.path.join(scenario_path, county)
                annual_costs = process_county_scenario(file_path, county, load_type)

                results_data = {
                    f"{load_type}.electricity.{plan}.usd": [cost]
                    for plan, cost in annual_costs.items()
                }
                results_df = pd.DataFrame(results_data, index=[scenario])

                output_file_path = os.path.join(base_output_dir, scenario, housing_type, county, "results", "electricity", f"{OUTPUT_FILE_NAME}_{county}_{timestamp}.csv")
                os.makedirs(os.path.dirname(output_file_path), exist_ok=True)

                if os.path.exists(output_file_path):
                    existing_df = pd.read_csv(output_file_path, index_col="scenario")

                    # Overwrite overlapping columns with the new data
                    for col in results_df.columns:
                        existing_df[col] = results_df[col]

                    combined_df = existing_df
                else:
                    combined_df = results_df

                log(
                    at="step11_evaluate_electricity_rates",
                    county=county,
                    load_type=load_type,
                    annual_electricity_cost_ETOUC=to_number(annual_costs['E-TOU-C']),
                    annual_electricity_costs_ETOUD=to_number(annual_costs['E-TOU-D']),
                    annual_electricity_costs_EV2A=to_number(annual_costs['EV2-A']),
                    annual_electricity_costs_EELEC=to_number(annual_costs['E-ELEC']),
                    saved_to=output_file_path
                )
                combined_df.to_csv(output_file_path, index_label="scenario")

# base_input_dir = "data"
# base_output_dir = "data"
# counties = ["alameda"]
# scenarios = ["baseline"]
# housing_types = ["single-family-detached"]
# load_type = "default" # default, solarstorage

# process(base_input_dir, base_output_dir, scenarios, housing_types, counties, load_type)