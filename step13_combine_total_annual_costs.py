import os
import pandas as pd
from datetime import datetime

from helpers import get_counties, get_scenario_path, log, norcal_counties, socal_counties, central_counties

ELECTRICITY_PREFIX = "RESULTS_electricity_annual_costs"
GAS_PREFIX = "RESULTS_gas_annual_costs"
TOTALS_PREFIX = "RESULTS_total_annual_costs"

def get_latest_csv_file(directory, prefix):
    files = [f for f in os.listdir(directory) if f.startswith(prefix) and f.endswith(".csv")]

    if not files:
        raise FileNotFoundError(f"No file found in {directory} with prefix {prefix}")
    def extract_timestamp(filename):
        parts = filename.rstrip(".csv").split("_")
        ts = parts[-2] + "_" + parts[-1]
        return datetime.strptime(ts, "%Y%m%d_%H")
    latest = max(files, key=lambda f: extract_timestamp(f))

    return os.path.join(directory, latest)

def get_costs_from_electricity(county_dir):
    elec_dir = os.path.join(county_dir, "results", "electricity")
    county = os.path.basename(county_dir)
    prefix = f"{ELECTRICITY_PREFIX}_{county}_"
    latest_file = get_latest_csv_file(elec_dir, prefix)

    return pd.read_csv(latest_file, index_col="scenario")

def get_costs_from_gas(county_dir):
    gas_dir = os.path.join(county_dir, "results", "gas")
    county = os.path.basename(county_dir)
    prefix = f"{GAS_PREFIX}_{county}_"
    latest_file = get_latest_csv_file(gas_dir, prefix)

    return pd.read_csv(latest_file, index_col="scenario")

def calculate_total_annual_costs(elec_df, gas_df):
    """
    For each row in elec_df (with index like 'baseline' or 'baseline.solarstorage'),
    add the gas cost (from gas_df) to every electricity cost
    Create a DataFrame with the same index and new total cost columns
    """
    totals = pd.DataFrame(index=elec_df.index)
    for col in elec_df.columns:
        if col.startswith("electricity."):
            # Extract a plan identifier from column name (e.g., "E-TOU-C")
            service_type, utility, plan = col.split('.')
            for gascol in gas_df.columns:
                if gascol.startswith("gas."):
                    gas_service_type, gas_utility, gas_plan = gascol.split('.')
                    new_col = f"total.{utility}.{plan}+{gas_utility}.{gas_plan}"
                    totals[new_col] = elec_df[col] + gas_df[gascol]

    return totals

def save_totals(totals_df, output_county_dir, subfolder):
    totals_dir = os.path.join(output_county_dir, "results", subfolder)
    os.makedirs(totals_dir, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H")
    county = os.path.basename(output_county_dir)
    file_name = f"{TOTALS_PREFIX}_{county}_{timestamp}.csv"
    output_file = os.path.join(totals_dir, file_name)

    totals_df.to_csv(output_file, index_label="scenario")

def process_each_county(county, scenario_path, base_output_dir, scenario, housing_type):
    input_county_dir = os.path.join(scenario_path, county)

    try:
        elec_df = get_costs_from_electricity(input_county_dir)
        gas_df = get_costs_from_gas(input_county_dir)

    except FileNotFoundError as e:
        log(county=county, message=f"skip county, missing data: {e}")
        return

    totals_df = calculate_total_annual_costs(elec_df, gas_df)
    output_county_dir = os.path.join(base_output_dir, scenario, housing_type, county)

    log(county=county, message="success")

    save_totals(totals_df, output_county_dir, "totals")
    save_totals(totals_df, output_county_dir, "solarstorage")

def process(base_input_dir, base_output_dir, scenario, housing_types, counties):
    for housing_type in housing_types:
        scenario_path = get_scenario_path(base_input_dir, scenario, housing_type)
        valid_counties = get_counties(scenario_path, counties)
        for county in valid_counties:
            process_each_county(county, scenario_path, base_output_dir, scenario, housing_type)

if __name__ == '__main__':
    base_input_dir = "data/loadprofiles"
    base_output_dir = "data/loadprofiles"
    counties = ['Los Angeles County']
    scenarios = "baseline"
    housing_types = ["single-family-detached"]

    process(base_input_dir, base_output_dir, scenarios, housing_types, norcal_counties+socal_counties+central_counties)