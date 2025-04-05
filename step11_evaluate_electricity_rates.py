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
from collections import defaultdict
from datetime import datetime, timedelta
from helpers import get_counties, get_scenario_path, log, to_number, get_timestamp, norcal_counties, socal_counties, central_counties, slugify_county_name
from electricity_rate_helpers import PGE_RATE_PLANS, SCE_RATE_PLANS, SDGE_RATE_PLANS
from utility_helpers import get_utility_for_county


RATE_PLANS = {
    "PG&E": PGE_RATE_PLANS,
    "SCE": SCE_RATE_PLANS,
    "SDG&E": SDGE_RATE_PLANS,
}

INPUT_FILE_NAME = "loadprofiles_for_rates"
OUTPUT_FILE_NAME = "RESULTS_electricity_annual_costs"

LOAD_FOR_RATE_ELECTRICITY_COLUMN = ".electricity.kwh"

def get_season(hour_index):
    start_date = datetime(year=2018, month=1, day=1)  # Consistent with NREL inputs
    current_datetime = start_date + timedelta(hours=hour_index)
    month = current_datetime.month
    return 'summer' if 6 <= month <= 9 else 'winter'


def is_weekend(dt):
    return dt.weekday() >= 5

def select_rate_section(plan_details, season, dt):
    """
    Given a rate plan's details and a season (e.g., "summer" or "winter"),
    select and return the rate section that applies for the given datetime dt.
    
    If the season's rates are divided into day types (e.g., "weekdays" and "weekend"),
    this function returns the corresponding sub-dictionary; otherwise, it returns
    the season's flat rate configuration.
    """
    season_rates = plan_details.get(season)
    if not season_rates:
        return None

    if "weekdays" in season_rates or "weekend" in season_rates:
        return season_rates.get("weekend") if is_weekend(dt) else season_rates.get("weekdays")
    return season_rates

def get_hourly_rate(rate_section, hour):
    if "peakHours" in rate_section and hour in rate_section["peakHours"]:
        return rate_section["peak"]
    elif "partPeakHours" in rate_section and hour in rate_section["partPeakHours"]:
        return rate_section["partPeak"]
    elif "superOffPeakHours" in rate_section and hour in rate_section["superOffPeakHours"]:
        return rate_section["superOffPeak"]
    else:
        return rate_section["offPeak"]

# TODO: Implement minimum daily charge, baseline credits
def calculate_annual_costs_electricity(load_profile, utility, rate_plan_name):
    annual_costs = defaultdict(float)
    # Now plan_details has a nested structure: season -> {weekdays, weekends}
    plan_details = RATE_PLANS[utility][rate_plan_name]

    for hour_index, hourly_load in enumerate(load_profile):
        season = get_season(hour_index)
        current_datetime = datetime(year=2023, month=1, day=1) + timedelta(hours=hour_index)
        hour = current_datetime.hour

        # Determine whether the current day is a weekday (Monday-Friday) or weekend (Saturday-Sunday)
        dayotw_type = "weekdays" # if current_datetime.weekday() < 5 else "weekends"

        # Retrieve the seasonal rates and then the appropriate day type rates
        season_rates = plan_details.get(season)
        if not season_rates:
            continue

        dayotw_rates = season_rates.get(dayotw_type)
        if not dayotw_rates:
            continue

        if hour in dayotw_rates.get("peakHours", []):
            rate = dayotw_rates.get("peak", 0.0)
        elif "partPeakHours" in dayotw_rates and hour in dayotw_rates.get("partPeakHours", []):
            rate = dayotw_rates["partPeak"]
        elif "superOffPeakHours" in dayotw_rates and hour in dayotw_rates.get("superOffPeakHours", []):
            rate = dayotw_rates["superOffPeak"]
        else:
            rate = dayotw_rates.get("offPeak", 0.0)

        # Calculate the cost for the hour
        energy_cost = hourly_load * rate
        annual_costs[rate_plan_name] += energy_cost

        # Include fixed charges if available (spread monthly)
        fixed_charge = dayotw_rates.get("fixedCharge", 0.0)
        annual_costs[rate_plan_name] += fixed_charge / 12

    return annual_costs
    
def process_county_scenario(file_path, county, utility, selected_rate_plan, load_type):
    file = os.path.join(file_path, county, f"{INPUT_FILE_NAME}_{county}.csv")

    if not os.path.exists(file):
        raise FileNotFoundError(f"File not found: {file}")

    column_name = f"{load_type}{LOAD_FOR_RATE_ELECTRICITY_COLUMN}"
    df = pd.read_csv(file, usecols=[column_name])

    load_profile = df[column_name].tolist()

    return calculate_annual_costs_electricity(load_profile, utility, selected_rate_plan)

def build_results_df(scenario, utility, annual_costs, annual_costs_solarstorage):
    """
    Creates a DataFrame with two rows: 
    one for the default tariffs (row name = {scenario})
    one for the solarstorage tariffs (row name = '{scenario}.solarstorage')
    """
    columns = [f"electricity.{utility}.{tariff}" for tariff in annual_costs.keys()]
    df = pd.DataFrame(columns=columns, index=[scenario, f"{scenario}.solarstorage"])

    # Default tarrifs
    for tariff, cost in annual_costs.items():
        col_name = f"electricity.{utility}.{tariff}"
        df.loc[scenario, col_name] = cost

    # Solarstorage tarrifs
    for tariff, cost in annual_costs_solarstorage.items():
        col_name = f"electricity.{utility}.{tariff}"
        df.loc[f"{scenario}.solarstorage", col_name] = cost

    return df

def get_output_file_path(base_output_dir, scenario, housing_type, county, timestamp):
    output_path = os.path.join(
        base_output_dir,
        scenario,
        housing_type,
        county,
        "results",
        "electricity",
        f"{OUTPUT_FILE_NAME}_{county}_{timestamp}.csv"
    )

    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    return output_path

def update_csv_with_results(output_file_path, results_df):
    """
    If an output CSV exists, update overlapping rows/columns with new results
    else, use the new dataframe
    """

    if os.path.exists(output_file_path):
        existing_df = pd.read_csv(output_file_path, index_col="scenario")

        for idx in results_df.index:
            for col in results_df.columns:
                existing_df.loc[idx, col] = results_df.loc[idx, col]
        return existing_df
    else:
        return results_df
    
def update_df_with_results(orig_df, new_df):
    """
    Update the original DataFrame with new results.
    """
    for idx in new_df.index:
        for col in new_df.columns:
            orig_df.loc[idx, col] = new_df.loc[idx, col]
    return orig_df

def utility_to_rate_plans(utility: str):
    match utility:
        case "PG&E":
            return PGE_RATE_PLANS
        case "SCE":
            return SCE_RATE_PLANS
        case "SDG&E":
            return SDGE_RATE_PLANS
        case _:
            raise ValueError(f"Unknown utility: {utility}")
    
def process(base_input_dir, base_output_dir, scenario, housing_type, counties):
    timestamp = get_timestamp()

    scenario_path = get_scenario_path(base_input_dir, scenario, housing_type)
    scenario_counties = get_counties(scenario_path, counties)

    for county in scenario_counties:
        results_df = pd.DataFrame()
        utility = get_utility_for_county(county)
        assert utility is not None, f"Utility not found for county: {county}"
        rate_plans = utility_to_rate_plans(utility)
        
        log_kwargs = {}
        for rate_plan in rate_plans:
            # Process the county's scenario using the selected rate plan.
            annual_costs = process_county_scenario(scenario_path, county, utility, rate_plan, "default")
            annual_costs_solarstorage = process_county_scenario(scenario_path, county, utility, rate_plan, "solarstorage")
            annual_costs_results = build_results_df(scenario, utility, annual_costs, annual_costs_solarstorage) #  utility)

            results_df = update_df_with_results(results_df, annual_costs_results)

            log_kwargs.update({
                f"annual_electricity_costs_{rate_plan}": to_number(annual_costs[rate_plan]),
                f"annual_electricity_costs_solarstorage_{rate_plan}": to_number(annual_costs_solarstorage[rate_plan])
            })

        output_file_path = get_output_file_path(base_output_dir, scenario, housing_type, county, timestamp)
        combined_df = update_csv_with_results(output_file_path, results_df)
        combined_df.to_csv(output_file_path, index_label="scenario")

        log(
            at="step11_evaluate_electricity_rates",
            county=county,
            utility=utility,
            **log_kwargs,
            saved_to=output_file_path,
        )

if __name__ == '__main__':
    base_input_dir = "data/loadprofiles"
    base_output_dir = "data/loadprofiles"
    counties = ['Los Angeles']
    scenario = "baseline"
    housing_type = "single-family-detached"

    process(base_input_dir, base_output_dir, scenario, housing_type, norcal_counties+socal_counties+central_counties)