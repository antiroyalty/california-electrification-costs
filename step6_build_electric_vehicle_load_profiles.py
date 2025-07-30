"""
Step 6: Build Electric Vehicle Load Profiles

This step processes EV load profiles for each specified county.
Currently a placeholder for future EV integration.

TODO: Implement EV load profile processing when EV scenarios are added.
"""

import os
import pandas as pd
from main_helpers import get_counties, get_scenario_path, log

# def download_raw_data(): 
# we are using the CEC data from AB 2127 sent by Eleanor to start
#   get the data

# def cleanup_whatever_we_dont_want():
#    get_names_of_columns_we_need
#    make_sure_its_in_the_right_timezone

def convert_excel_minute_to_hourly(excel_path, output_csv_path):
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

    # Rename relevant columns
    df = df.rename(columns={
        df.columns[0]: "time",
        df.columns[1]: "residential_L1_MW"
    })

    # Convert values to numeric and drop invalid rows
    df["residential_L1_MW"] = pd.to_numeric(df["residential_L1_MW"], errors="coerce")
    df = df.dropna(subset=["residential_L1_MW"])

    # Keep only the first 1440 rows (exactly 24 hours)
    df = df.iloc[:1440]

    # Compute hourly averages (group every 60 minutes)
    hourly_df = df.groupby(df.index // 60).mean(numeric_only=True)
    hourly_df.index.name = "hour"
    hourly_df.reset_index(inplace=True)

    # Save the result
    hourly_df.to_csv(output_csv_path, index=False)
    return hourly_df

# Example usage
convert_excel_minute_to_hourly(
    excel_path="AB2127_LoadCurveData_Eleanor.xlsx",
    output_csv_path="Figure_20_hourly_residential_L1.csv"
)

# Divide_by_number_of_evs AND unit in kW

# get_8760

# split_file_per_county #or group together the utility

#def send_it
    # append_to_file_called electricity_loads_
    # write to column name: "evs"

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
    
    # Placeholder implementation
    # TODO: Add EV load profile processing logic
    print("Step 6: EV load profiles processing not yet implemented")
    print("This step will be activated when EV scenarios are added to the analysis")
    
    log(
        at="step6_build_electric_vehicle_load_profiles", 
        info="ev_processing_skipped",
        reason="not_yet_implemented"
    )


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