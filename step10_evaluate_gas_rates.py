# PG&E October 2024 Gas Rate Structure
import os
import pandas as pd

from helpers import get_counties, get_scenario_path, slugify_county_name, log, to_number, get_timestamp

# Need mapping from county to service region
# Need other utilities gas rates

# Baseline Allowance for Residential Gas Rates (in therms/day)
# TODO: Ana, go more granular in the data so that we can more easily map to the PG&E and SCE climate zones / tarrif regions
# Gas rates also have baseline summer / winter allowances
# https://www.pge.com/tariffs/assets/pdf/tariffbook/GAS_SCHEDS_G-1.pdf
# https://www.pge.com/tariffs/assets/pdf/tariffbook/GAS_MAPS_Service_Area_Map.pdf
# https://www.cpuc.ca.gov/news-and-updates/all-news/breaking-down-pges-natural-gas-costs-and-rates
BASELINE_ALLOWANCES = {
    "PGE": {
        "G-1": {
            "territories": {
                "P": {
                    "summer": 0.39,  # therms/day/dwelling unit
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
                "Y&Z": {
                    "summer": 0.72,
                    "winter_offpeak": 2.22,
                    "winter_onpeak": 2.58,
                }
            }
        }
    }
}

# Residential gas rates have baseline allowances:
# https://www.pge.com/tariffs/assets/pdf/tariffbook/GAS_SCHEDS_G-1.pdf
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
    } # TODO: There is also a gas public purpose program (G-PPPS) that comes with surcharges
}

# Baseline allowance map
PGE_RATE_TERRITORY_COUNTY_MAPPING = {
    "T": [slugify_county_name(county) for county in ["Marin", "San Francisco", "San Mateo"]],
    "Q": [slugify_county_name(county) for county in ["Santa Cruz", "Monterey"]],
    "X": [slugify_county_name(county) for county in [
        "San Luis Obispo", "San Benito", "Santa Clara", 
        "Alameda", "Contra Costa", "Napa", "Sonoma", 
        "Mendocino", "Santa Barbara", "Solano", "Del Norte"
    ]], # TODO: Ana, Double check whether Solano and Del Norte are correctly placed here
    "P": [slugify_county_name(county) for county in [
        "Placer", "El Dorado", "Amador", "Calaveras", "Lake"
    ]],
    "S": [slugify_county_name(county) for county in [
        "Glenn", "Colusa", "Yolo", "Sutter", "Butte", "Yuba",
        "Sacramento", "Stanislaus", "San Joaquin", "Solano", "Sutter"
    ]],
    "R": [slugify_county_name(county) for county in [
        "Merced", "Fresno", "Madera", "Mariposa", "Tehama"
    ]],
    "Y&Z": [slugify_county_name(county) for county in [
        "Nevada", "Plumas", "Humboldt", "Trinity", "Tulare", "Lassen"
        "Lake", "Shasta", "Sierra", "Alpine", "Mono", "Toulumne"
    ]],
    "W": [slugify_county_name(county) for county in [
        "Kings", 
        # Revisit these
        "Kern", "Inyo", "Mono", "Los Angeles", "Ventura", "San Bernadino", "Sierra", "Plumas", "Modoc", "Sisikiyou"
    ]]
}

# Revisit these (SCE or SDGE): Kern, Inyo, Mono, Los Angeles, Ventura, San Bernadino, Sierra, Plumas, Modoc, Sisikiyou

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
    
    total_cost = 0.0
    
    for season, therms_used in seasonal_therms.items():
        # Retrieve the baseline allowance for the season
        baseline = BASELINE_ALLOWANCES["PGE"]["G-1"]["territories"][territory][season]
        
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
        log(message="Step10@get_territory_for_county: County to gas territory mapping not specified", county=county)
        return "T" # use T as default for now

def process_county_scenario(scenario_path, county, load_type):
    file = os.path.join(scenario_path, county, f"{INPUT_FILE_NAME}_{county}.csv")

    if not os.path.exists(file):
        log(
            at="step10_evaluate_gas_rates",
            file_not_found=file,
        )
        return None

    load_profile_df = pd.read_csv(file, parse_dates=["timestamp"])
    load_profile_df["month"] = load_profile_df["timestamp"].dt.month
    territory = get_territory_for_county(county)
    
    return calculate_annual_costs_gas(load_profile_df, territory, load_type)

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
    
def build_results_df(scenario, annual_costs, annual_costs_solarstorage):
    data = {"gas.usd": [annual_costs, annual_costs_solarstorage]}
    index = [scenario, f"{scenario}.solarstorage"]
    df = pd.DataFrame(data, index=index)

    return df

def process(base_input_dir, base_output_dir, scenario, housing_types, counties):
    timestamp = get_timestamp()

    for housing_type in housing_types:
        scenario_path = get_scenario_path(base_input_dir, scenario, housing_type)
        scenario_counties = get_counties(scenario_path, counties)

        for county in scenario_counties:

            annual_costs = process_county_scenario(scenario_path, county, "default")
            annual_costs_solarstorage = process_county_scenario(scenario_path, county, "solarstorage")
            annual_costs_results = build_results_df(scenario, annual_costs, annual_costs_solarstorage)

            output_file_path = get_output_file_path(base_output_dir, scenario, housing_type, county, timestamp)
            combined_df = update_csv_with_results(output_file_path, annual_costs_results)

            log(
                at="step10_evaluate_gas_rates",
                county=county,
                annual_gas_costs=to_number(annual_costs),
                annual_gas_costs_solarstorage=to_number(annual_costs_solarstorage),
                saved_to=output_file_path,
            )

            combined_df.to_csv(output_file_path, index_label="scenario")

# base_input_dir = "data"
# base_output_dir = "data"
# counties = ["alameda"] # , "alpine", "riverside"]
# scenarios = ["baseline"]
# housing_types = ["single-family-detached"]
# load_type = "solarstorage" # default, solarstorage

# process(base_input_dir, base_output_dir, scenarios, housing_types, counties, load_type)
