import os
import pytest
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from tempfile import TemporaryDirectory

import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../')))

from step6_combine_real_and_simulated_electricity_loads import (
    aggregate_columns,
    combine_profiles,
    process,
    SCENARIO_DATA_MAP
)

# ============================================================================
# Tests for aggregate_columns
# ============================================================================

def test_aggregate_columns_sum_no_resample(tmp_path):
    data = pd.DataFrame({
        "timestamp": ["2021-01-01 00:00:00", "2021-01-01 01:00:00"],
        "total_load": [10, 20]
    })
    csv_file = tmp_path / "electricity.csv"
    data.to_csv(csv_file, index=False)
    
    result = aggregate_columns(str(csv_file), ["total_load"], operation="sum", resample_to_hourly=False)
    
    expected_index = pd.to_datetime(["2021-01-01 00:00:00", "2021-01-01 01:00:00"])
    expected_index.name = "timestamp"
    expected = pd.Series([10, 20], index=expected_index)
    
    pd.testing.assert_series_equal(result, expected, check_freq=False)


def test_aggregate_columns_sum_with_resample(tmp_path):
    # Create a CSV file with quarter-hourly data for two hours.
    timestamps = [
        "2021-01-01 00:00:00", "2021-01-01 00:15:00", "2021-01-01 00:30:00", "2021-01-01 00:45:00",
        "2021-01-01 01:00:00", "2021-01-01 01:15:00", "2021-01-01 01:30:00", "2021-01-01 01:45:00",
    ]
    # For the first hour, use 5 each so that sum=20; for the second hour use 10 each so that sum=40.
    values = [5, 5, 5, 5, 10, 10, 10, 10]
    data = pd.DataFrame({
        "timestamp": timestamps,
        "total_load": values
    })
    csv_file = tmp_path / "electricity_qh.csv"
    data.to_csv(csv_file, index=False)
    
    result = aggregate_columns(str(csv_file), ["total_load"], operation="sum", resample_to_hourly=True)
    
    # Expected: two hourly rows with sums 20 and 40.
    # Build expected index using pd.date_range so it has a freq of 'H'.
    expected_index = pd.date_range("2021-01-01 00:00:00", periods=2, freq="H")
    expected_index.name = "timestamp"
    expected = pd.Series([20, 40], index=expected_index)
    
    pd.testing.assert_series_equal(result, expected, check_freq=False)

def test_aggregate_columns_subtract(tmp_path):
    data = pd.DataFrame({
        "timestamp": ["2021-01-01 00:00:00", "2021-01-01 01:00:00"],
        "total_load": [10, 20]
    })
    csv_file = tmp_path / "subtract.csv"
    data.to_csv(csv_file, index=False)
    
    result = aggregate_columns(str(csv_file), ["total_load"], operation="subtract", resample_to_hourly=False)
    
    expected_index = pd.to_datetime(["2021-01-01 00:00:00", "2021-01-01 01:00:00"])
    expected_index.name = "timestamp"
    expected = pd.Series([-10, -20], index=expected_index)
    pd.testing.assert_series_equal(result, expected, check_freq=False)


def test_aggregate_columns_trimming(tmp_path):
    # Create a CSV with 8761 hourly rows
    start = pd.Timestamp("2021-01-01 00:00:00")
    timestamps = pd.date_range(start, periods=8761, freq="H")
    data = pd.DataFrame({
        "timestamp": timestamps,
        "total_load": 1
    })
    csv_file = tmp_path / "long.csv"
    data.to_csv(csv_file, index=False)
    
    # Call without resampling
    result = aggregate_columns(str(csv_file), ["total_load"], operation="sum", resample_to_hourly=False)
    
    # Should be trimmed to 8760 rows.
    assert len(result) == 8760
    # Use the first 8760 timestamps; even if the freq is set, ignore it in the comparison
    expected_index = timestamps[:8760]
    expected_index.name = "timestamp"
    expected = pd.Series([1]*8760, index=expected_index)
    pd.testing.assert_series_equal(result, expected, check_freq=False)

# ============================================================================
# combine_profiles
# ============================================================================

@pytest.fixture
def sample_input_output(tmp_path):
    """
    Create temporary input and output directories with a simulated folder structure.
    The structure for combine_profiles is:
        input_dir/
            baseline/
                <housing_type>/
                    <county_slug>/
                        electricity_loads_<county_slug>.csv
                        gas_loads_<county_slug>.csv
                        (electricity_loads_simulated_<county_slug>.csv may be absent)
    Returns a tuple (input_dir, output_dir).
    """
    input_dir = tmp_path / "input_data"
    output_dir = tmp_path / "output_data"
    input_dir.mkdir()
    output_dir.mkdir()
    return input_dir, output_dir

def create_profile_csvs(input_dir, housing_type, county):
    county_slug = county.lower().replace(" ", "_")
    base_path = os.path.join(input_dir, "baseline", housing_type, county_slug)
    os.makedirs(base_path, exist_ok=True)
    
    elec_data = pd.DataFrame({
        "timestamp": ["2021-01-01 00:00:00", "2021-01-01 01:00:00"],
        "total_load": [10, 20]
    })
    elec_file = os.path.join(base_path, f"electricity_loads_{county_slug}.csv")
    elec_data.to_csv(elec_file, index=False)
    
    # Gas CSV: quarter-hourly data for two hours.
    gas_timestamps = [
        "2021-01-01 00:00:00", "2021-01-01 00:15:00", "2021-01-01 00:30:00", "2021-01-01 00:45:00",
        "2021-01-01 01:00:00", "2021-01-01 01:15:00", "2021-01-01 01:30:00", "2021-01-01 01:45:00",
    ]
    # For first hour, values 1,2,3,4 (sum=10); for second hour, 5,6,7,8 (sum=26).
    gas_values = [1, 2, 3, 4, 5, 6, 7, 8]
    gas_data = pd.DataFrame({
        "timestamp": gas_timestamps,
        "load.gas.avg.therms": gas_values
    })
    gas_file = os.path.join(base_path, f"gas_loads_{county_slug}.csv")
    gas_data.to_csv(gas_file, index=False)
    
    return base_path

def test_combine_profiles(sample_input_output):
    input_dir, output_dir = sample_input_output
    housing_type = "single_family"
    county = "Test County"
    county_slug = county.lower().replace(" ", "_")
    
    create_profile_csvs(input_dir, housing_type, county)
    
    scenario = "baseline"
    scenario_data_map = SCENARIO_DATA_MAP[scenario]
    
    combined_df = combine_profiles(str(input_dir), str(output_dir), scenario, housing_type, county, scenario_data_map)
    
    expected_columns = [
        "timestamp",
        "electricity.real_and_simulated.for_typical_county_home.kwh",
        "gas.hourly_total.for_typical_county_home.therms",
    ]
    assert list(combined_df.columns) == expected_columns
    
    expected_timestamps = pd.to_datetime(["2021-01-01 00:00:00", "2021-01-01 01:00:00"])
    expected_electricity = np.array([10, 20])
    
    # For hour 00:00, sum = 1+2+3+4 = 10; for hour 01:00, sum = 5+6+7+8 = 26.
    expected_index = pd.date_range("2021-01-01 00:00:00", periods=2, freq="H")
    expected_index.name = "timestamp"
    expected_gas = pd.Series([10, 26], index=expected_index)
    
    # Compare timestamps.
    ts_series = pd.Series(combined_df["timestamp"], name="timestamp")
    pd.testing.assert_series_equal(ts_series, pd.Series(expected_timestamps, name="timestamp"), check_freq=False)
    
    np.testing.assert_allclose(combined_df["electricity.real_and_simulated.for_typical_county_home.kwh"], expected_electricity)
    np.testing.assert_allclose(combined_df["gas.hourly_total.for_typical_county_home.therms"], expected_gas.values)
    
    # Also check that the output file was created
    expected_output_dir = os.path.join(str(output_dir), scenario, housing_type, county_slug)
    expected_output_file = os.path.join(expected_output_dir, f"combined_profiles_{scenario}_{county_slug}.csv")
    assert os.path.exists(expected_output_file)
    
    df_from_file = pd.read_csv(expected_output_file, parse_dates=["timestamp"])
    pd.testing.assert_frame_equal(combined_df, df_from_file, check_like=True)

# ============================================================================
# process
# ============================================================================

def dummy_get_scenario_path(input_dir, scenario, housing_type):
    # For tests, simply return a path that will point to a folder under input_dir
    return os.path.join(input_dir, "baseline", housing_type)

def dummy_get_counties(scenario_path, counties):
    # For tests, just return the provided counties list
    return counties

@pytest.fixture
def patch_helpers(monkeypatch):
    # Patch the helper functions in the module where they are used.
    monkeypatch.setattr("step6_combine_real_and_simulated_electricity_loads.get_scenario_path", dummy_get_scenario_path)
    monkeypatch.setattr("step6_combine_real_and_simulated_electricity_loads.get_counties", dummy_get_counties)

def test_process(sample_input_output, patch_helpers):
    input_dir, output_dir = sample_input_output
    housing_type = "single_family"
    county = "Test County"  # We supply this as the only county.
    
    create_profile_csvs(input_dir, housing_type, county)
    
    # Call process with one scenario, one housing type, and one county.
    scenarios = ["baseline"]
    housing_types = [housing_type]
    counties = [county]
    
    results = process(str(input_dir), str(output_dir), scenarios, housing_types, counties)
    
    assert len(results) == 1
    
    combined_df = results[0]
    expected_timestamps = pd.to_datetime(["2021-01-01 00:00:00", "2021-01-01 01:00:00"])
    expected_electricity = np.array([10, 20])
    expected_gas = np.array([10, 26])
    
    ts_series = pd.Series(combined_df["timestamp"], name="timestamp")
    pd.testing.assert_series_equal(ts_series, pd.Series(expected_timestamps, name="timestamp"), check_freq=False)
    np.testing.assert_allclose(combined_df["electricity.real_and_simulated.for_typical_county_home.kwh"], expected_electricity)
    np.testing.assert_allclose(combined_df["gas.hourly_total.for_typical_county_home.therms"], expected_gas)
    
    county_slug = county.lower().replace(" ", "_")
    expected_output_file = os.path.join(str(output_dir), "baseline", housing_type,
                                        county_slug, f"combined_profiles_baseline_{county_slug}.csv")
    assert os.path.exists(expected_output_file)