"""
Step 6: Build Vehicle Load Profiles

This step processes vehicle load profiles for each specified county based on the scenario:
- For ICE car scenarios: Generate gasoline consumption profiles
- For EV car scenarios: Generate electric vehicle charging profiles using NREL EVI-Pro Lite API
- For no car scenarios: Skip vehicle profile generation

The profiles are saved as CSV files that will be combined with appliance loads in step 7.
"""

import os
import pandas as pd
import requests
import json
from datetime import datetime
import time
from helpers.main_helpers import get_counties, get_scenario_path, log, slugify_county_name

def convert_excel_minute_to_hourly(excel_path):
    """
    Extracts minute-level Residential Level 1 load data from the 'Figure 20' sheet
    in an Excel file, averages it to hourly values (based on first 1440 rows),
    and saves as a new CSV.
    
    Parameters:
    - excel_path: str, path to the Excel file
    - output_csv_path: str, path to save the hourly-averaged CSV
    """
    # Load the "Figure 20" sheet, skipping header rows
    df = pd.read_excel(excel_path, sheet_name="Figure 20", skiprows=2)

    df = df.rename(columns={
        df.columns[0]: "time",
        df.columns[1]: "residential_L1_MW"
    })

    df["residential_L1_MW"] = pd.to_numeric(df["residential_L1_MW"], errors="coerce")
    df = df.dropna(subset=["residential_L1_MW"])

    df = df.iloc[:1440]

    hourly_df = df.groupby(df.index // 60).mean(numeric_only=True)
    hourly_df.index.name = "hour"
    hourly_df.reset_index(inplace=True)

    return hourly_df

def convert_all_columns_to_per_vehicle(hourly_df, fleet_size=7_100_000):
    """
    Converts all MW load columns in the DataFrame to per-vehicle kW load,
    and saves the result to a new CSV.

    Parameters:
    - hourly_df: pd.DataFrame with hourly statewide EV load values in MW
    - output_csv_path: str, path to save the updated CSV with per-vehicle columns
    - fleet_size: int, number of EVs represented in the data (default: 7.1 million)

    Returns:
    - pd.DataFrame with added per-vehicle kW columns for each MW input column
    """
    for col in hourly_df.columns:
        if col != "hour" and hourly_df[col].dtype in [float, int]:
            new_col = f"{col}_per_vehicle_kWh"
            hourly_df[new_col] = (hourly_df[col] / fleet_size) * 1000

    return hourly_df

def expand_hourly_profile_to_8760_with_datetime(hourly_df):
    """
    Expands a 24-hour load profile to 8760 hours and adds a datetime column
    starting from Jan 1, 2030, 00:00. Saves the result to CSV.

    Parameters:
    - hourly_df: pd.DataFrame with 24 rows (hourly load data)
    - output_csv_path: str, file path to save the 8760-hour expanded CSV

    Returns:
    - pd.DataFrame with 8760 rows and a datetime column
    """
    if len(hourly_df) != 24:
        raise ValueError("Input DataFrame must have exactly 24 rows (1 day of hourly data)")

    repeated_df = pd.concat([hourly_df] * 365, ignore_index=True)

    timestamps = pd.date_range(start="2030-01-01 00:00", periods=8760, freq="h")

    repeated_df.insert(0, "datetime", timestamps)

    return repeated_df

def get_ice_fuel_profile():
    """
    Generate gasoline consumption profile for ICE vehicles.
    Returns daily fuel consumption distributed across typical driving hours.
    
    Returns:
        list: 24-hour fuel consumption profile in gallons per hour
    """
    # Average household drives ~35 miles per day, ~25 MPG = 1.4 gallons/day
    # Distribute fuel consumption during typical driving hours
    daily_gallons = 1.4
    
    # Driving pattern: morning commute, midday errands, evening commute
    hourly_fractions = [
        0.01, 0.01, 0.01, 0.01, 0.01, 0.02,  # 0-5 AM: Minimal driving
        0.05, 0.10, 0.12, 0.08, 0.06, 0.05,  # 6-11 AM: Morning commute peak
        0.06, 0.07, 0.08, 0.07, 0.06, 0.08,  # 12-5 PM: Midday activity
        0.10, 0.08, 0.06, 0.04, 0.03, 0.02   # 6-11 PM: Evening commute
    ]
    
    # Convert to gallons per hour
    fuel_profile = [daily_gallons * fraction for fraction in hourly_fractions]
    return fuel_profile

def save_vehicle_profiles_by_county(base_output_dir: str, scenario: str, scenario_config: dict, 
                                  housing_types: list, counties: list, hourly_df_8760: pd.DataFrame):
    """
    Save vehicle profiles for each county based on scenario configuration.
    
    Args:
        base_output_dir: Output directory path
        scenario: Scenario name
        scenario_config: Dictionary with 'gas' and 'electric' sets defining the scenario
        housing_types: List of housing types to process
        counties: List of counties to process
        hourly_df_8760: DataFrame with EV load profile data
    """
    # Determine what vehicle profiles to generate based on scenario
    generate_ice_profile = "vehicle_fuel" in scenario_config.get("gas", set())
    generate_ev_profile = "vehicle_charging" in scenario_config.get("electric", set())
    
    if not generate_ice_profile and not generate_ev_profile:
        print("No vehicle loads needed for this scenario, skipping vehicle profile generation")
        return
    
    # Generate ICE fuel profile if needed
    ice_fuel_data = None
    if generate_ice_profile:
        daily_ice_profile = get_ice_fuel_profile()
        # Expand to 8760 hours
        ice_fuel_data = daily_ice_profile * 365  # Repeat daily pattern for full year for now
    
    # Process each county
    for county in counties:
        county_slug = slugify_county_name(county)
        
        for housing_type in housing_types:
            housing_slug = housing_type.replace(" ", "-").lower()
            
            # Create county-specific directory
            county_dir = os.path.join(base_output_dir, scenario, housing_slug, county_slug)
            os.makedirs(county_dir, exist_ok=True)
            
            # Save EV charging profile if needed
            if generate_ev_profile:
                ev_output_path = os.path.join(county_dir, f"vehicle_charging_profile_{county_slug}_{housing_slug}.csv")
                
                # Use the existing EV profile from Excel data
                ev_df = hourly_df_8760.copy()

                # Add new column summing the two per-vehicle kW columns
                if 'residential_L1_MW_per_vehicle_kWh' in ev_df.columns and 'Residential Level 2_per_vehicle_kWh' in ev_df.columns:
                    ev_df['total_vehicle_charging'] = (
                        ev_df['residential_L1_MW_per_vehicle_kWh'] + ev_df['Residential Level 2_per_vehicle_kWh']
                    )
                
                ev_df = ev_df.rename(columns={'total_vehicle_charging': 'vehicle_charging'})
                
                ev_df.to_csv(ev_output_path, index=False)
                
                log(
                    at="step6_build_vehicle_load_profiles",
                    info="ev_profile_saved",
                    county=county,
                    output_path=ev_output_path,
                    avg_charging_kw=round(ev_df['vehicle_charging'].mean(), 3)
                )
            
            # Save ICE fuel profile if needed
            if generate_ice_profile:
                ice_output_path = os.path.join(county_dir, f"vehicle_fuel_profile_{county_slug}_{housing_slug}.csv")
                
                # Create datetime index for ICE profile if not available from EV data
                if hourly_df_8760 is not None and 'datetime' in hourly_df_8760.columns:
                    datetime_values = hourly_df_8760['datetime']
                else:
                    # Generate datetime index for full year (8760 hours)
                    import datetime as dt
                    start_date = dt.datetime(2024, 1, 1)
                    datetime_values = pd.date_range(start=start_date, periods=8760, freq='h')
                
                # Create ICE fuel DataFrame
                ice_df = pd.DataFrame({
                    'datetime': datetime_values,
                    'vehicle_fuel': ice_fuel_data
                })
                
                ice_df.to_csv(ice_output_path, index=False)
                
                log(
                    at="step6_build_vehicle_load_profiles",
                    info="ice_profile_saved",
                    county=county,
                    output_path=ice_output_path,
                    total_annual_gallons=round(sum(ice_fuel_data), 1)
                )

def process(base_input_dir: str, base_output_dir: str, scenario: str, scenario_config: dict,
           housing_types: list, counties: list, force_recompute: bool = False):
    """
    Process vehicle load profiles for each specified county based on scenario configuration.
    
    Args:
        base_input_dir: Input directory path
        base_output_dir: Output directory path
        scenario: Scenario name
        scenario_config: Dictionary with 'gas' and 'electric' sets defining the scenario
        housing_types: List of housing types to process
        counties: List of counties to process
        force_recompute: Whether to force recomputation
    """
    
    log(
        at="step6_build_vehicle_load_profiles",
        info="starting_vehicle_processing",
        scenario=scenario,
        counties_requested=len(counties),
        has_vehicle_fuel="vehicle_fuel" in scenario_config.get("gas", set()),
        has_vehicle_charging="vehicle_charging" in scenario_config.get("electric", set())
    )
    
    # Check if vehicle profiles are needed
    generate_ice_profile = "vehicle_fuel" in scenario_config.get("gas", set())
    generate_ev_profile = "vehicle_charging" in scenario_config.get("electric", set())
    
    if not generate_ice_profile and not generate_ev_profile:
        log(
            at="step6_build_vehicle_load_profiles",
            info="no_vehicle_loads_needed",
            scenario=scenario,

        )
        print("No vehicle loads needed for this scenario, skipping vehicle profile generation")
        return

    # Process EV data from Excel file if needed
    hourly_df_8760 = None
    if generate_ev_profile:
        print("Processing EV load profiles from AB2127_LoadCurveData_Eleanor.xlsx")
        
        # Convert Excel minute data to hourly
        hourly_df = convert_excel_minute_to_hourly(f"{base_input_dir}/AB2127_LoadCurveData_Eleanor.xlsx")
        
        # Convert to per-vehicle values
        hourly_df_per_vehicle = convert_all_columns_to_per_vehicle(hourly_df, fleet_size=7_100_000)
        
        # Expand to 8760 hours
        hourly_df_8760 = expand_hourly_profile_to_8760_with_datetime(hourly_df)
    
    # Save vehicle profiles for each county
    # NOTE that for now these will be identical load profiles for each county
    save_vehicle_profiles_by_county(
        base_output_dir, scenario, scenario_config, 
        housing_types, counties, hourly_df_8760
    )
    
    log(
        at="step6_build_vehicle_load_profiles",
        info="vehicle_processing_complete",
        scenario=scenario,
        counties_processed=len(counties)
    )

if __name__ == "__main__":
    # Test configuration - example EV scenario
    test_scenario_config = {
        "gas": {"heating", "hot_water", "cooking"},
        "electric": {"appliances", "misc", "vehicle_charging"}
    }
    
    process(
        base_input_dir="data",
        base_output_dir="data/loadprofiles", 
        scenario="baseline_ev_car", # baseline_ice_car, baseline_ev_car
        scenario_config=test_scenario_config,
        housing_types=["single-family-detached"],
        counties=["Alameda County"],
        force_recompute=True
    )