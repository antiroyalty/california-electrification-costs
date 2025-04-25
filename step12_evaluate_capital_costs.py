# build a table of key-value pairs for solar capacity, storage capacity, and costs
# one entry per county? or by climate zone?
# first start for all of california and look at the capital cost differences due to the diff sizes of solar and storage

# https://www.tesla.com/learn/solar-panel-cost-breakdown
CAPITAL_COSTS = {
    "solar": {
        "dollars_per_watt": 2.83, # https://www.tesla.com/learn/solar-panel-cost-breakdown
        "installation_labor": 0.07, # Installation labor makes up around 7% of your total expenses
        "design_eng_overhead_percent": 0.28, # The design, engineering, project management, processing of approvals, and other overhead account for the remaining 28% of costs. 2 For example, if your final quote is $20,000, the labor cost will be around $1,400 while design, engineering, and processing cost would land around $5,600 (installation costs vary by provider).  
    },
    "storage": {
        "powerwall_13.5kwh": 10748, # Dollars for one powerwall, discount for 2 or more. After $6106 of incentives https://www.tesla.com/powerwall/design/overview
    },
    "ev_charging": {
        "tesla_wall_connector": 1150,
        "universal_wall_connector": 1350,
    }
}

import os
import pandas as pd
from datetime import datetime
from helpers import get_counties, get_scenario_path, to_decimal_number, norcal_counties, socal_counties, central_counties
from utility_helpers import get_utility_for_county

# ---------------------------------------------------------------------------
# Helper functions for file handling and cost data extraction
# ---------------------------------------------------------------------------
def extract_timestamp_from_filename(filename):
    parts = filename.rstrip(".csv").split("_")
    ts = parts[-2] + "_" + parts[-1]

    return datetime.strptime(ts, "%Y%m%d_%H")

def get_latest_csv_file(directory, prefix):
    """
    Returns the path to the latest CSV file in 'directory' whose filename starts with 'prefix'.
    """
    files = [f for f in os.listdir(directory) if f.startswith(prefix) and f.endswith(".csv")]

    if not files:
        raise FileNotFoundError(f"No file found in {directory} with prefix {prefix}")
    latest_file = max(files, key=lambda f: extract_timestamp_from_filename(f))
    return os.path.join(directory, latest_file)

def load_cost_data(file_path, subfolder, prefix):
    path = os.path.join(file_path, "results", subfolder)
    county = os.path.basename(file_path)
    full_prefix = f"{prefix}_{county}_"
    file_path = get_latest_csv_file(path, full_prefix)
    df = pd.read_csv(file_path, index_col="scenario")
    if subfolder == "solarstorage":
        # Assumes that the second row is for the solar+storage scenario
        return df.iloc[1]
    else:
        # Use the first row for the baseline
        return df.iloc[0]

# ---------------------------------------------------------------------------
# Cost and payback calculation functions
# ---------------------------------------------------------------------------
def calculate_system_payback(solar_capacity_kw, dollars_per_watt, annual_savings,
                             labour_pct, design_pct, storage_cost):
    """
    Calculate the total installation cost and the payback period for a solar+storage system.

    Parameters:
      solar_capacity_kw (float): Solar capacity in kilowatts.
      dollars_per_watt (float): Base cost for solar panels ($/W).
      annual_savings (float): Annual electricity cost savings (difference between baseline and solar+storage).
      labour_pct (float): Additional labor percentage.
      design_pct (float): Additional design/engineering overhead percentage.
      storage_cost (float): Cost for storage (e.g., one Powerwall).

    Returns:
      total_cost (float): Total system cost (solar + storage).
      payback_period (float): Payback period in years.
    """
    # Convert kW to W and calculate base solar panel cost
    panel_cost = solar_capacity_kw * 1000 * dollars_per_watt
    solar_total_cost = panel_cost * (1 + labour_pct + design_pct)
    total_cost = solar_total_cost + storage_cost
    payback_period = total_cost / annual_savings if annual_savings != 0 else float('inf')
    
    return total_cost, payback_period

def load_electrified_assets(scenario_path):
    assets_path = os.path.join(scenario_path, "CAPITAL_COSTS", "electrified_assets.csv")
    if not os.path.exists(assets_path):
        raise FileNotFoundError(f"Electrified assets file not found at {assets_path}")
    
    df = pd.read_csv(assets_path)
    if "County" not in df.columns or "Solar Capacity (kW)" not in df.columns:
        raise ValueError("electrified_assets.csv must contain 'County' and 'Solar Capacity (kW)' columns")
    
    assets_mapping = df.set_index("County")["Solar Capacity (kW)"].to_dict()
    return assets_mapping

# ---------------------------------------------------------------------------
# Main class and process function
# ---------------------------------------------------------------------------
# class CalculatePaybackPeriod:
#     @staticmethod
def process(base_input_dir, base_output_dir, scenario, housing_type, counties, desired_rate_plans):
    """
    Processes each county to calculate the solar+storage payback period for each utility.

    It reads cost data for baseline and solar+storage scenarios, computes annual savings,
    and calculates system cost and payback period using the solar capacity value from
    the electrified_assets file. The results are written to a CSV file.

    Parameters:
        base_input_dir (str): Directory with input data.
        base_output_dir (str): Directory where output CSV is saved.
        scenario (str): Scenario name.
        housing_type (str): Housing type.
        counties (list): List of county names.
        desired_rate_plans (dict): Dictionary of rate plans keyed by utility. For example:
            {
                "PG&E": {"electricity": "E-TOU-D", "gas": "G-1"},
                "SCE": {"electricity": "TOU-D-4-9PM", "gas": "GR"},
                "SDG&E": {"electricity": "TOU-DR1", "gas": "GR"}
            }
    """
    # Construct scenario path and determine the valid counties
    scenario_path = get_scenario_path(base_input_dir, scenario, housing_type)
    valid_counties = get_counties(scenario_path, counties)

    # Load electrified assets mapping: a dict mapping county -> solar capacity (kW)
    assets_mapping = load_electrified_assets(scenario_path)

    results = []

    # Iterate over each valid county
    for county in valid_counties:
        county_dir = os.path.join(scenario_path, county)
        try:
            # Load cost data from the "electricity" (baseline) and "solarstorage" subfolders
            baseline_data = load_cost_data(county_dir, subfolder="totals", prefix="RESULTS_total_annual_costs")
            solarstorage_data = load_cost_data(county_dir, subfolder="solarstorage", prefix="RESULTS_total_annual_costs")

            county_results = {"County": county}

            # Look up the solar capacity (kW) for the current county from assets_mapping
            if county not in assets_mapping:
                raise ValueError(f"Solar capacity data not found for county '{county}' in electrified_assets.csv")
            solar_capacity_kw = assets_mapping[county]

            # Iterate through the desired rate plans for each utility
            utility = get_utility_for_county(county)
            # Check that the utility is in desired_rate_plans.
            if utility not in desired_rate_plans:
                print(f"Utility for county {county} ({utility}) is not in desired_rate_plans; skipping.")
                continue

            rate_elec = desired_rate_plans[utility]["electricity"]
            rate_gas   = desired_rate_plans[utility]["gas"]
            # Construct column name using the convention:
            # total.<UTILITY>.<electricity_rate>+<UTILITY>.<gas_rate>
            col_name = f"total.{utility}.{rate_elec}+{utility}.{rate_gas}"
            
            if col_name not in baseline_data or col_name not in solarstorage_data:
                print(f"Column {col_name} not found for county {county}; skipping {utility}.")
                continue

            baseline_cost = baseline_data[col_name]
            solarstorage_cost = solarstorage_data[col_name]
            annual_savings = baseline_cost - solarstorage_cost

            # Retrieve the solar cost inputs from CAPITAL_COSTS
            dollars_per_watt = CAPITAL_COSTS["solar"]["dollars_per_watt"]
            labour_pct = CAPITAL_COSTS["solar"]["installation_labor"]
            design_pct = CAPITAL_COSTS["solar"]["design_eng_overhead_percent"]
            
            # Storage cost as a fixed cost for one Powerwall
            storage_cost = CAPITAL_COSTS["storage"]["powerwall_13.5kwh"]

            total_cost, payback_years = calculate_system_payback(
                solar_capacity_kw,
                dollars_per_watt,
                annual_savings,
                labour_pct,
                design_pct,
                storage_cost
            )

            county_results[f"{utility}.{rate_elec}+{rate_gas}.total_cost"] = to_decimal_number(total_cost)
            county_results[f"{utility}.{rate_elec}+{rate_gas}.payback_years"] = to_decimal_number(payback_years)
            county_results[f"{utility}.{rate_elec}+{rate_gas}.annual_savings"] = to_decimal_number(annual_savings)

            results.append(county_results)
        except Exception as ex:
            print(f"Error processing county {county}: {ex}")

    results_df = pd.DataFrame(results).set_index("County")
    output_csv = os.path.join(base_output_dir, scenario, housing_type, "CAPITAL_COSTS", "system_payback_by_county.csv")
    results_df.to_csv(output_csv)
    print(f"Results saved to: {output_csv}")

if __name__ == '__main__':
    base_input_dir = "data/loadprofiles"
    base_output_dir = "data/loadprofiles"
    scenario = "baseline"  # or another scenario name
    housing_type = "single-family-detached"  # example housing type
    counties = ["Alameda County", "Contra Costa", "Los Angeles County"]  # example list of counties
    rate_plans = {
        "PG&E": {
            "electricity": "E-TOU-D",
            "gas": "G-1"
        },
        "SCE": {
            "electricity": "TOU-D-4-9PM",
            "gas": "GR"
        },
        "SDG&E": {
            "electricity": "TOU-DR1",
            "gas": "GR"
        }
    }

    process(base_input_dir, base_output_dir, scenario, housing_type, norcal_counties + socal_counties + central_counties, rate_plans)