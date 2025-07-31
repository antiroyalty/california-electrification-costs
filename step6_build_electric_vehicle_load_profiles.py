"""
Step 6: Build Electric Vehicle Load Profiles

This step processes EV load profiles for each specified county.
Currently a placeholder for future EV integration.

TODO: Implement EV load profile processing when EV scenarios are added.
"""

import os
import pandas as pd
from main_helpers import get_counties, get_scenario_path, log

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
            new_col = f"{col}_per_vehicle_kW"
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

# split_file_per_county #or group together the utility

def process(base_input_dir: str, base_output_dir: str, scenario: str, 
           housing_types: list, counties: list, force_recompute: bool = False):
    """
    Process EV load profiles for each specified county.
    
    Args:
        base_input_dir: Input directory path
        base_output_dir: Output directory path
        scenario: Scenario name
        housing_types: List of housing types to process
        counties: List of counties to process
        force_recompute: Whether to force recomputation
    """
    
    log(
        at="step6_build_electric_vehicle_load_profiles",
        info="starting_ev_processing",
        scenario=scenario,
        counties_requested=len(counties)
    )

    hourly_df = convert_excel_minute_to_hourly("data/AB2127_LoadCurveData_Eleanor.xlsx")

    hourly_df_per_vehicle = convert_all_columns_to_per_vehicle(hourly_df, fleet_size=7_100_000)

    hourly_df_8760 = expand_hourly_profile_to_8760_with_datetime(hourly_df)

    hourly_df_8760.to_csv(os.path.join(base_output_dir, "8760_EV_load_profile.csv"), index=False)

if __name__ == "__main__":
    # Test configuration
    process(
        base_input_dir="data/loadprofiles",
        base_output_dir="data/loadprofiles", 
        scenario="baseline",
        housing_types=["single-family-detached"],
        counties=["Alameda County"],
        force_recompute=False
    )