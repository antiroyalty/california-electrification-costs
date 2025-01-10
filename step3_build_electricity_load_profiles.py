import os
import pandas as pd

# Define scenarios and corresponding end uses
SCENARIOS = {
    "baseline": ["appliances", "misc"],
    # "heat_pump_and_water_heater": ["heating", "hot_water", "appliances", "misc"],
    # "heat_pump_water_heater_and_induction_stove": ["heating", "cooling", "hot_water", "appliances", "cooking", "misc"],
    # "heat_pump_heating_cooling_water_heater_and_induction_stove": ["heating", "cooling", "hot_water", "appliances", "cooking", "misc"]
}

# Define end use columns
END_USE_COLUMNS = {
    "heating": [
        'out.electricity.heating.energy_consumption',
        'out.electricity.heating_fans_pumps.energy_consumption',
        'out.electricity.heating_hp_bkup.energy_consumption',
    ],
    "cooling": [
        'out.electricity.cooling.energy_consumption',
        'out.electricity.cooling_fans_pumps.energy_consumption',
    ],
    "cooking": [
        'out.electricity.range_oven.energy_consumption',
    ],
    "hot_water": [
        'out.electricity.hot_water.energy_consumption',
    ],
    "appliances": [
        'out.electricity.ceiling_fan.energy_consumption',
        # 'out.electricity.clothes_dryer.energy_consumption',
        'out.electricity.dishwasher.energy_consumption',
        'out.electricity.lighting_interior.energy_consumption',
        'out.electricity.lighting_garage.energy_consumption',
        'out.electricity.mech_vent.energy_consumption',
        'out.electricity.refrigerator.energy_consumption',
    ],
    "misc": [
        'out.electricity.plug_loads.energy_consumption',
        'out.electricity.pool_pump.energy_consumption',
        'out.electricity.pool_heater.energy_consumption',
        'out.electricity.permanent_spa_pump.energy_consumption',
        'out.electricity.permanent_spa_heat.energy_consumption',
        'out.electricity.freezer.energy_consumption',
    ]
}

# Base directories
BASE_INPUT_DIR = "data"
BASE_OUTPUT_DIR = "data"

INPUT_FOLDER_NAME = "buildings"
OUTPUT_FILE_PREFIX = "electricity_loads"

def build_load_profiles(scenarios, housing_types, counties):
    for scenario, end_use_categories in scenarios.items():
        for housing_type in housing_types:
            for county in counties:
                print(f"Processing {county} for {scenario}, {housing_type}")
                
                # Define input and output paths
                input_dir = os.path.join(BASE_INPUT_DIR, scenario, housing_type, county, INPUT_FOLDER_NAME)
                output_path = os.path.join(BASE_OUTPUT_DIR, scenario, housing_type, county, f"{OUTPUT_FILE_PREFIX}_{county}.csv")

                if not os.path.exists(input_dir):
                    print(f"Directory not found: {input_dir}")
                    continue

                # Collect all end use columns relevant to the scenario
                end_uses = []
                for category in end_use_categories:
                    end_uses.extend(END_USE_COLUMNS[category])

                all_data = pd.DataFrame()

                # Process all Parquet files in the directory
                for file_name in os.listdir(input_dir):
                    file_path = os.path.join(input_dir, file_name)
                    if file_path.endswith('.parquet'):
                        try:
                            data = pd.read_parquet(file_path)
                        except Exception as e:
                            print(f"Error reading {file_path}: {e}")
                            continue

                        # Ensure all required columns exist
                        if 'timestamp' in data.columns and all(col in data.columns for col in end_uses):
                            data['timestamp'] = pd.to_datetime(data['timestamp'])
                            data = data[['timestamp'] + end_uses]
                            all_data = pd.concat([all_data, data], axis=0, ignore_index=True)

                # Check if data was loaded
                if all_data.empty:
                    print(f"No data processed for {county} in {scenario} - {housing_type}")
                    continue

                # Group data by timestamp to calculate average across all buildings
                average_profile = all_data.groupby('timestamp')[end_uses].mean()

                # Create a full year's timestamp range
                full_year = pd.date_range(
                    start=all_data['timestamp'].min(), 
                    end=all_data['timestamp'].max(), 
                    freq='H'
                )

                # Reindex to include all hours in the range
                average_profile = average_profile.reindex(full_year)
                average_profile['total_load'] = average_profile[end_uses].sum(axis=1)

                # Reset index and save to CSV
                average_profile.reset_index(inplace=True)
                average_profile.rename(columns={'index': 'timestamp'}, inplace=True)
                os.makedirs(os.path.dirname(output_path), exist_ok=True)
                average_profile.to_csv(output_path, index=False)

                print(f"Saved load profile to {output_path}")

# Define housing types and counties
housing_types = ["single-family-detached"] # , "single-family-attached"]
counties = ["alameda", "alpine", "riverside"]  # Add more counties

# Build load profiles
build_load_profiles(SCENARIOS, housing_types, counties)