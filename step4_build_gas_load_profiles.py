import os
import pandas as pd

# Conversion factor
KWH_TO_THERMS = 0.0341296

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

def process_building_data(data, end_uses):
    if 'timestamp' not in data.columns or not all(col in data.columns for col in end_uses):
        raise ValueError("Missing required columns: 'timestamp' and/or end_uses.")

    data['timestamp'] = pd.to_datetime(data['timestamp'])
    hourly_data = data[['timestamp'] + end_uses].copy()
    hourly_data['load.gas.total.kwh'] = hourly_data[end_uses].sum(axis=1)

    grouped = hourly_data.groupby('timestamp', as_index=False).sum()

    return grouped # hourly_data.groupby('timestamp', as_index=False)['total_load_kwh'].sum()

def update_county_totals(county_gas_totals, building_gas_totals, building_count, end_uses):
    suffixed_end_uses = [f"{col}.gas.total.kwh" for col in end_uses]

    if county_gas_totals is None:
        # Initialize county totals with the first building
        county_gas_totals = building_gas_totals.rename(columns={col: f"{col}.gas.total.kwh" for col in end_uses}).copy()
        county_gas_totals['load.gas.total.therms'] = county_gas_totals['load.gas.total.kwh'] * KWH_TO_THERMS
    else:
        # Aggregate totals for each end use with the suffixed column names
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
                print(file_path)
            except Exception as e:
                print(f"Error reading {file_path}: {e}")
                continue

            if 'timestamp' in data.columns and all(col in data.columns for col in end_uses):
                building_gas_totals = process_building_data(data, end_uses)

                building_count += 1
                county_gas_totals = update_county_totals(county_gas_totals, building_gas_totals, building_count, end_uses)

    return county_gas_totals, building_count

def average_county_gas_profiles(county_gas_totals, building_count, end_uses):
    print(county_gas_totals.head())

    if building_count > 0:
        # Calculate average for total load
        county_gas_totals['load.gas.avg.kwh'] = county_gas_totals['load.gas.total.kwh'].div(building_count)
        county_gas_totals['load.gas.avg.therms'] = county_gas_totals['load.gas.avg.kwh'] * KWH_TO_THERMS

        # Calculate averages for each individual end use in kWh and therms
        for col in end_uses:
            total_col = f"{col}.gas.total.kwh"
            avg_kwh_col = f"{col}.gas.avg.kwh"
            avg_therms_col = f"{col}.gas.avg.therms"

            if total_col in county_gas_totals.columns:
                # Average in kWh
                county_gas_totals[avg_kwh_col] = county_gas_totals[total_col].div(building_count)

                # Average in therms
                county_gas_totals[avg_therms_col] = county_gas_totals[avg_kwh_col] * KWH_TO_THERMS

    # county_gas_totals.to_csv('county_gas_totals_with_averages.csv')
    return county_gas_totals

def save_county_gas_profiles(county_gas_totals, county, output_dir):
    os.makedirs(output_dir, exist_ok=True)
    output_file = os.path.join(output_dir, f"gas_loads_{county}.csv")
    county_gas_totals.to_csv(output_file)
    print(f"Saved results to {output_file}")

def build_county_gas_profile(scenario, housing_type, county, county_dir, output_dir, end_uses):
    county_gas_totals, building_count = sum_county_gas_profiles(county_dir, end_uses)

    if county_gas_totals is None or building_count == 0:
        print(f"No valid data found in {county_dir} for {scenario} - {housing_type}. Skipping.")
        return

    county_gas_totals = average_county_gas_profiles(county_gas_totals, building_count, end_uses)

    save_county_gas_profiles(county_gas_totals, county, output_dir)

def build_gas_load_profiles(scenarios, housing_types, base_input_dir, base_output_dir, counties=None):
    for scenario in scenarios:
        for housing_type in housing_types:
            scenario_path = os.path.join(base_input_dir, scenario, housing_type)
            if not os.path.exists(scenario_path):
                print(f"Scenario path not found: {scenario_path}")
                continue
            
            if counties is None:
                # Dynamically collect all county names
                counties = [county for county in os.listdir(scenario_path) 
                        if os.path.isdir(os.path.join(scenario_path, county))]
            
            for county in counties:
                print(f"Processing {county} for {scenario}, {housing_type}")
                
                # Define input and output paths
                county_dir = os.path.join(scenario_path, county, "buildings")
                output_dir = os.path.join(base_output_dir, scenario, housing_type, county)
                
                if not os.path.exists(county_dir):
                    print(f"County directory not found: {county_dir}")
                    continue
                
                # Collect all end use columns relevant to the scenario
                end_use_categories = scenarios[scenario]
                end_uses = [col for category in end_use_categories for col in END_USE_COLUMNS[category]]
                
                # Build the gas profile for the county
                build_county_gas_profile(scenario, housing_type, county, county_dir, output_dir, end_uses)

base_input_dir = "data"
base_output_dir = "data"
counties = ["alameda"] # "alpine", "riverside"]
housing_types = ["single-family-detached"]

build_gas_load_profiles(SCENARIOS, housing_types, base_input_dir, base_output_dir, counties)