import pytest
from unittest.mock import patch

import pandas as pd
from io import StringIO
import os
import glob
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../')))

from step11_evaluate_electricity_rates import (
    get_season,
    calculate_annual_costs_electricity,
    process_county_scenario,
    process_all_counties,
    RATE_PLANS,
)

# Test data and constants
TEST_LOAD_PROFILE = [1.0] * 8760  # Simplistic load profile: 1 kWh every hour
TEST_LOAD_TYPE = "default"

# Mock data for CSV files
MOCK_CSV_CONTENT = "default.electricity.kwh\n" + "\n".join(["1.0"] * 8760)

# Helper function to create a mock DataFrame
def create_mock_dataframe():
    return pd.DataFrame({"default.electricity.kwh": TEST_LOAD_PROFILE})


@pytest.fixture
def mock_csv_file():
    return StringIO(MOCK_CSV_CONTENT)


def test_get_season_summer():
    # June (month=6) is summer
    # Calculate hour_index for June 15, 2018
    # June 15 is month 6, day 15
    # Days before June: 31 (Jan) + 28 (Feb) + 31 (Mar) + 30 (Apr) + 31 (May) + 15 (June) - 1 = 165 days
    hour_index = 165 * 24
    assert get_season(hour_index) == "summer"


def test_get_season_winter():
    # January (month=1) is winter
    # hour_index for January 15, 2018
    hour_index = (14 * 24) + 6  # 14 days * 24 + 6 hours
    assert get_season(hour_index) == "winter"

def test_calculate_annual_costs_electricity():
    # Using a load profile of 1 kWh every hour
    annual_costs = calculate_annual_costs_electricity(TEST_LOAD_PROFILE)
    
    # Manually calculate expected costs for each rate plan
    # Since load is 1 kWh every hour, total kWh = 8760
    # For simplicity, fixed charges are spread over the year
    
    # Initialize expected costs
    expected_costs = {plan: 0.0 for plan in RATE_PLANS["PGE"].keys()}
    
    for hour_index in range(8760):
        season = get_season(hour_index)
        current_datetime = pd.Timestamp("2023-01-01") + pd.Timedelta(hours=hour_index)
        hour = current_datetime.hour

        for plan_name, plan_details in RATE_PLANS["PGE"].items():
            season_rates = plan_details.get(season)
            if not season_rates:
                continue

            # Determine hourly rate
            if hour in season_rates.get("peakHours", []):
                rate = season_rates["peak"]
            elif hour in season_rates.get("partPeakHours", []):
                rate = season_rates.get("partPeak", season_rates.get("offPeak", 0))
            else:
                rate = season_rates["offPeak"]

            # Calculate hourly cost
            energy_cost = 1.0 * rate  # 1 kWh
            expected_costs[plan_name] += energy_cost

            # Add fixed charges
            fixed_charge = season_rates.get("fixedCharge", 0.0)
            expected_costs[plan_name] += fixed_charge / 12  # Spread across months

    # Compare expected costs with calculated costs
    for plan, expected_cost in expected_costs.items():
        assert pytest.approx(annual_costs[plan], rel=1e-2) == expected_cost

def test_process_county_scenario(tmp_path):
    # Setup mock input file
    county = "testcounty"
    file_path = tmp_path / "data"
    file_path.mkdir(parents=True)
    mock_file = file_path / f"loadprofiles_for_rates_{county}.csv"
    load_data = pd.DataFrame({"default.electricity.kwh": [1.0] * 24})  # 1 kWh for every hour
    load_data.to_csv(mock_file, index=False)

    # Call the function
    annual_costs = process_county_scenario(file_path, county, "default")

    # Assertions
    assert annual_costs is not None
    for plan in RATE_PLANS["PGE"].keys():
        assert plan in annual_costs
    assert all(value > 0 for value in annual_costs.values())  # Costs should be positive

def test_process_all_counties(tmp_path):
    # Setup input directory
    base_input_dir = tmp_path / "input"
    base_output_dir = tmp_path / "output"
    county = "testcounty"
    input_file_dir = base_input_dir / "baseline" / "single-family-detached" / county
    input_file_dir.mkdir(parents=True)
    mock_file = input_file_dir / "loadprofiles_for_rates_testcounty.csv"
    load_data = pd.DataFrame({"default.electricity.kwh": [1.0] * 24})
    load_data.to_csv(mock_file, index=False)

    # Call the function
    process_all_counties(
        base_input_dir=base_input_dir,
        base_output_dir=base_output_dir,
        counties=[county],
        scenarios=["baseline"],
        housing_types=["single-family-detached"],
        load_type="default",
    )

    # Verify output
    output_dir = base_output_dir / "baseline" / "single-family-detached" / county / "results"
    output_files = list(output_dir.glob("RESULTS_electricity_annual_costs_testcounty_*.csv"))

    # Assert that exactly one file exists
    assert len(output_files) == 1, f"Expected 1 output file, found {len(output_files)}"

    # Verify contents of the file
    results_df = pd.read_csv(output_files[0])
    assert "default.electricity.E-TOU-C.usd" in results_df.columns
    assert results_df.iloc[0]["default.electricity.E-TOU-C.usd"] > 0  # Validate data

def test_process_county_scenario_file_not_found(tmp_path):
    # Call the function without creating the file
    file_path = tmp_path / "data"
    file_path.mkdir(parents=True)
    county = "missingcounty"

    # Capture printed output
    with pytest.raises(FileNotFoundError) as exc_info:
        process_county_scenario(file_path, county, "default")

    expected_message = f"File not found: {os.path.join(file_path, f'loadprofiles_for_rates_{county}.csv')}"
    assert str(exc_info.value) == expected_message

def test_invalid_load_type():
    base_input_dir = "./data"
    base_output_dir = "./data"
    counties = ["alameda"]
    scenarios = ["baseline"]
    housing_types = ["single-family-detached"]
    load_type = "invalid_load_type"

    with pytest.raises(ValueError) as exc_info:
        process_all_counties(base_input_dir, base_output_dir, counties, scenarios, housing_types, load_type)

    assert "Invalid load_type 'invalid_load_type'. Must be one of ['default', 'solarstorage']." in str(exc_info.value)