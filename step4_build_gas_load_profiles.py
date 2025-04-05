import os
import pandas as pd

from helpers import get_scenario_path, get_counties, log, to_number

# Conversion factor
KWH_TO_THERMS = 0.0341296

# TODO: Ana, deduplicate
# Define scenarios and natural gas end uses
SCENARIOS = {
    "baseline": ["heating", "hot_water", "cooking", "appliances", "misc"],
}

# Define natural gas end use columns
END_USE_COLUMNS = {
    "heating": ['out.natural_gas.heating.energy_consumption'],
    "hot_water": ['out.natural_gas.hot_water.energy_consumption'],
    "cooking": ['out.natural_gas.range_oven.energy_consumption'],
    "appliances": ['out.natural_gas.clothes_dryer.energy_consumption'],
    "misc": ['out.natural_gas.fireplace.energy_consumption']
}

OUTPUT_FILE_PREFIX = "gas_loads"

def process_building_data(data, end_uses):
    if 'timestamp' not in data.columns or not all(col in data.columns for col in end_uses):
        raise ValueError("Missing required columns: 'timestamp' and/or end_uses.")

    data['timestamp'] = pd.to_datetime(data['timestamp'])
    hourly_data = data[['timestamp'] + end_uses].copy()
    # Sum it to a total
    hourly_data['load.gas.total.kwh'] = hourly_data[end_uses].sum(axis=1)
    # We also want a sum across all buildings by end-use

    grouped = hourly_data.groupby('timestamp', as_index=False).sum()

    return grouped # hourly_data.groupby('timestamp', as_index=False)['total_load_kwh'].sum()

def update_county_totals(county_gas_totals, building_gas_totals, building_count, end_uses):
    suffixed_end_uses = [f"{col}.gas.total.kwh" for col in end_uses]

    if county_gas_totals is None:
        # Initialize county totals with the first building
        county_gas_totals = building_gas_totals.rename(columns={col: f"{col}.gas.total.kwh" for col in end_uses}).copy()
        county_gas_totals['load.gas.total.therms'] = county_gas_totals['load.gas.total.kwh'] * KWH_TO_THERMS
    else:
        # Aggregate totals FOR EACH END USE with the suffixed column names
        for col, suffixed_col in zip(end_uses, suffixed_end_uses):
            county_gas_totals[suffixed_col] += building_gas_totals[col]

        county_gas_totals['load.gas.total.kwh'] += building_gas_totals['load.gas.total.kwh']
        county_gas_totals['load.gas.total.therms'] = county_gas_totals['load.gas.total.kwh'] * KWH_TO_THERMS

    county_gas_totals['building_count'] = building_count

    return county_gas_totals

def sum_county_gas_profiles(input_dir, end_uses):
    county_gas_totals = None
    building_count = 0

    for file_name in os.listdir(input_dir): # for every parquet file
        file_path = os.path.join(input_dir, file_name)
        if file_path.endswith('.parquet'):
            try:
                data = pd.read_parquet(file_path) # read it
            except Exception as e:
                log(error=f"Error reading {file_path}: {e}")
                continue

            if 'timestamp' in data.columns and all(col in data.columns for col in end_uses):
                building_gas_totals = process_building_data(data, end_uses)

                building_count += 1
                county_gas_totals = update_county_totals(county_gas_totals, building_gas_totals, building_count, end_uses)

    return county_gas_totals, building_count

def average_county_gas_profiles(county_gas_totals, building_count, end_uses):
    if building_count > 0:
        # Calculate average for total load
        county_gas_totals['load.gas.building_avg.kwh'] = county_gas_totals['load.gas.total.kwh'].div(building_count)
        county_gas_totals['load.gas.building_avg.therms'] = county_gas_totals['load.gas.building_avg.kwh'] * KWH_TO_THERMS

        # Calculate averages for each individual end use in kWh and therms
        for col in end_uses:
            total_col = f"{col}.gas.total.kwh"
            avg_kwh_col = f"{col}.gas.building_avg.kwh"
            avg_therms_col = f"{col}.gas.building_avg.therms"

            if total_col in county_gas_totals.columns:
                # Average in kWh
                county_gas_totals[avg_kwh_col] = county_gas_totals[total_col].div(building_count)

                # Average in therms
                county_gas_totals[avg_therms_col] = county_gas_totals[avg_kwh_col] * KWH_TO_THERMS

    return county_gas_totals

def save_county_gas_profiles(county_gas_totals, county, output_file):

    log(
        at="step4_build_gas_profiles#save_county_gas_profiles",
        gas_heating_kwh=to_number(county_gas_totals['out.natural_gas.heating.energy_consumption.gas.building_avg.kwh'].sum()),
        gas_range_oven_kwh=to_number(county_gas_totals['out.natural_gas.range_oven.energy_consumption.gas.building_avg.kwh'].sum()),
        gas_hot_water_kwh=to_number(county_gas_totals['out.natural_gas.hot_water.energy_consumption.gas.building_avg.kwh'].sum()),
        annual_gas_load_kwh=to_number(county_gas_totals['load.gas.building_avg.kwh'].sum()),
        annual_gas_load_therms=to_number(county_gas_totals['load.gas.building_avg.therms'].sum()),
        saved_at=output_file
    )

    county_gas_totals.to_csv(output_file)

def build_county_gas_profile(scenario, housing_type, county, county_dir, output_file, end_uses):
    county_gas_totals, building_count = sum_county_gas_profiles(county_dir, end_uses)

    if county_gas_totals is None or building_count == 0:
        log(details=f"No valid data found in {county_dir} for {scenario} - {housing_type}. Skipping.")
        return

    county_gas_totals = average_county_gas_profiles(county_gas_totals, building_count, end_uses)

    save_county_gas_profiles(county_gas_totals, county, output_file)

def should_skip_processing(output_path, force_recompute):
    if force_recompute:
        return False  # Always regenerate if forced

    return os.path.exists(output_path)

def process(scenarios, housing_types, base_input_dir, base_output_dir, counties=None, force_recompute=True):
    for scenario in scenarios:
        if scenario != "baseline":
            log(at="step4_build_gas_load_profiles", message="no new electricity profiles needed to be downloaded")
            return

        for housing_type in housing_types:
            scenario_path = get_scenario_path(base_input_dir, scenario, housing_type)
            counties = get_counties(scenario_path, counties)
            
            for county in counties:
                log(
                    at="step4_build_gas_load_profiles#process",
                    details=f"Processing gas load profile in {county} for {scenario}, {housing_type}",
                )
            
                county_dir = os.path.join(scenario_path, county, "buildings")
                output_dir = os.path.join(base_output_dir, scenario, housing_type, county)
                os.makedirs(output_dir, exist_ok=True)
                output_file = os.path.join(output_dir, f"{OUTPUT_FILE_PREFIX}_{county}.csv")

                if should_skip_processing(output_file, force_recompute):
                    continue
                
                if not os.path.exists(county_dir):
                    log(details=f"County directory not found: {county_dir}")
                    continue
                
                # Collect all GAS end use columns relevant to the scenario
                # Scenarios should be defined by constant in CostService and passed as an argument here
                end_use_categories = scenarios[scenario]['gas']
                end_uses = [col for category in end_use_categories for col in END_USE_COLUMNS[category]]
                
                build_county_gas_profile(scenario, housing_type, county, county_dir, output_file, end_uses)