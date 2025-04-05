# PG&E October 2024 Gas Rate Structure
import os
import pandas as pd
from typing import Any

from helpers import get_counties, get_scenario_path, slugify_county_name, log, to_number, get_timestamp, norcal_counties, socal_counties, central_counties
from gas_rate_helpers import BASELINE_ALLOWANCES, GAS_RATE_PLANS, PGE_RATE_TERRITORY_COUNTY_MAPPING, SCE_RATE_TERRITORY_COUNTY_MAPPING, SDGE_RATE_TERRITORY_COUNTY_MAPPING
from utility_helpers import  get_utility_for_county

INPUT_FILE_NAME = "loadprofiles_for_rates"
OUTPUT_FILE_NAME = "RESULTS_gas_annual_costs"
OUTPUT_COLUMNS = ["county", "scenario", "housing_type", "territory", "annual_cost"]

LOAD_FOR_RATE_GAS_COLUMN_SUFFIX = ".gas.therms"

def utility_to_rate_plans(utility: str) -> dict[str, Any]:
    match utility:
        case "PG&E":
            return GAS_RATE_PLANS["PG&E"]
        case "SCE":
            return GAS_RATE_PLANS["SCE"]
        case "SDG&E":
            return GAS_RATE_PLANS["SDG&E"]
        case _:
            raise ValueError(f"Unknown utility: {utility}")
        
def utility_to_county_territory_mapping(utility):
    match utility:
        case "PG&E":
            return PGE_RATE_TERRITORY_COUNTY_MAPPING
        case "SCE":
            return SCE_RATE_TERRITORY_COUNTY_MAPPING
        case "SDG&E":
            return SDGE_RATE_TERRITORY_COUNTY_MAPPING
        case _:
            raise ValueError(f"Unknown utility: {utility}")

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
def calculate_annual_costs_gas(load_profile_df, territory, load_type, utility, rate_plan: str) -> float:
    seasonal_therms, total_therms = sum_therms_by_season(load_profile_df, load_type)
    
    total_cost = 0.0
    
    for season, therms_used in seasonal_therms.items():
        # Retrieve the baseline allowance for the season

        baseline = BASELINE_ALLOWANCES[utility][rate_plan]["territories"][territory][season]
        
        if therms_used <= baseline:
            rate = GAS_RATE_PLANS[utility][rate_plan]["baseline"]["total_charge"]
        else:
            rate = GAS_RATE_PLANS[utility][rate_plan]["excess"]["total_charge"]
        
        seasonal_cost = therms_used * rate
        total_cost += seasonal_cost
    
    return total_cost

def get_territory_for_county(county, utility):
    # TODO: Ana, establish key-value pair of mapping for all counties to gas rate territories
    # Currently implemented for SOME PG&E territories
    # This assumes that each county can only belong to one territory, but this is not necessarily the case
    # The allocation is done visually, roughly by area
    # County that has the largest area in a territory gets attributed to that territory
    utility_county_mapping = utility_to_county_territory_mapping(utility)

    for territory, counties in utility_county_mapping.items():
        if county in counties:
            return territory
    else:
        raise ValueError(f"County to gas territory mapping not specified for: {county}, {utility}")

def process_county_scenario(scenario_path, county, load_type, utility, rate_plan: str):
    file = os.path.join(scenario_path, county, f"{INPUT_FILE_NAME}_{county}.csv")

    if not os.path.exists(file):
        log(
            at="step10_evaluate_gas_rates",
            file_not_found=file,
        )
        return None

    load_profile_df = pd.read_csv(file, parse_dates=["timestamp"])
    load_profile_df["month"] = load_profile_df["timestamp"].dt.month
    territory = get_territory_for_county(county, utility)
    
    return calculate_annual_costs_gas(load_profile_df, territory, load_type=load_type, utility=utility, rate_plan=rate_plan)

def get_output_file_path(base_output_dir, scenario, housing_type, county, timestamp):
    output_path = os.path.join(
        base_output_dir,
        scenario,
        housing_type,
        county,
        "results",
        "gas",
        f"{OUTPUT_FILE_NAME}_{county}_{timestamp}.csv"
    )

    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    return output_path

def update_csv_with_results(output_file_path, results_df):
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
    
def build_results_df(scenario, annual_costs, annual_costs_solarstorage, utility, rate_plan):
    data = {f"gas.{utility}.{rate_plan}": [annual_costs, annual_costs_solarstorage]}
    index = [scenario, f"{scenario}.solarstorage"]
    df = pd.DataFrame(data, index=index)

    return df

def process(base_input_dir, base_output_dir, scenario, housing_types, counties):
    timestamp = get_timestamp()

    for housing_type in housing_types:
        scenario_path = get_scenario_path(base_input_dir, scenario, housing_type)
        scenario_counties = get_counties(scenario_path, counties)

        for county in scenario_counties:
            results_df = pd.DataFrame()
            utility = get_utility_for_county(county)
            assert utility is not None, f"Utility not found for county: {county}"
            rate_plans = utility_to_rate_plans(utility)

            log_kwargs = {}
            for rate_plan in rate_plans:
                annual_costs = process_county_scenario(scenario_path, county, load_type="default", utility=utility, rate_plan=rate_plan)
                annual_costs_solarstorage = process_county_scenario(scenario_path, county, load_type="solarstorage", utility=utility, rate_plan=rate_plan)
                annual_costs_results = build_results_df(scenario, annual_costs, annual_costs_solarstorage, utility=utility, rate_plan=rate_plan)

                results_df = update_df_with_results(results_df, annual_costs_results)

                log_kwargs.update({
                    f"annual_electricity_costs_{rate_plan}": to_number(annual_costs or 0.0),
                    f"annual_electricity_costs_solarstorage_{rate_plan}": to_number(annual_costs_solarstorage or 0.0)
                })  

            output_file_path = get_output_file_path(base_output_dir, scenario, housing_type, county, timestamp)
            combined_df = update_csv_with_results(output_file_path, results_df)
            combined_df.to_csv(output_file_path, index_label="scenario")

            log(
                at="step10_evaluate_gas_rates",
                county=county,
                **log_kwargs,
                saved_to=output_file_path,
            )

if __name__ == '__main__':
    base_input_dir = "data/loadprofiles"
    base_output_dir = "data/loadprofiles"
    counties = ["Los Angeles County"] # , "alpine", "riverside"]
    scenarios = "baseline"
    housing_types = ["single-family-detached"]

    process(base_input_dir, base_output_dir, scenarios, housing_types, norcal_counties + socal_counties + central_counties)
