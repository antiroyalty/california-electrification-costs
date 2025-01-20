import pytest
import pandas as pd
import os
from unittest.mock import patch, MagicMock, call

import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../')))

from step9_get_loads_for_rates import (
    get_scenario_path,
    aggregate_to_hourly,
    get_file_path,
    read_load_profile,
    prepare_for_rates_analysis,
    process,
    SCENARIO_DATA_MAP,
    OUTPUT_FILE_NAME
)

@patch("os.makedirs")
@patch("pandas.DataFrame.to_csv")
@patch("pandas.read_csv")
@patch("step9_get_loads_for_rates.get_counties", return_value=["alameda"])
@patch("step9_get_loads_for_rates.slugify_county_name", return_value="alameda")
def test_process(
    mock_slugify,
    mock_counties,
    mock_read_csv,
    mock_to_csv,
    mock_makedirs,
    tmp_path
):
    """Test the full process_for_rates with scenario baseline:
       1) elec default file: col='timestamp'
       2) elec default file: col='total_load'
       3) elec solar file: col='Grid to Load'
       4) gas default => 'load.gas.avg.therms'
       5) gas solar => 'load.gas.avg.therms'
    """
    # Define a side_effect function for read_csv
    def mock_read_csv_side_effect(file_path, usecols=None, parse_dates=None, **kwargs):
        if "electricity_loads_alameda.csv" in file_path:
            if usecols == ["timestamp"]:
                return pd.DataFrame({
                    "timestamp": pd.date_range("2021-01-01 00:00:00", periods=1, freq="H")
                })
            elif usecols == ["total_load"]:
                return pd.DataFrame({
                    "total_load": [10]
                })
        elif "sam_optimized_load_profiles_alameda.csv" in file_path:
            if usecols == ["Grid to Load"]:
                return pd.DataFrame({
                    "Grid to Load": [5]
                })
        elif "gas_loads_alameda.csv" in file_path:
            if parse_dates == ["timestamp"]:
                return pd.DataFrame({
                    "timestamp": pd.date_range("2021-01-01 00:00:00", periods=1, freq="H"),
                    "load.gas.avg.therms": [0.1]
                })
        raise ValueError(f"Unmocked read_csv call: {file_path}, usecols={usecols}, parse_dates={parse_dates}")

    # Assign the side_effect function to mock_read_csv
    mock_read_csv.side_effect = mock_read_csv_side_effect

    # Set up temporary paths
    (tmp_path / "data/baseline/single-family-detached/alameda").mkdir(parents=True)
    base_input_dir = str(tmp_path / "data")
    base_output_dir = str(tmp_path / "data")

    # Capture the DataFrame passed to to_csv
    captured_dfs = []

    def capture_to_csv(file_path, index=False):
        # Retrieve the DataFrame from the mock_read_csv calls
        # Since to_csv is a method of DataFrame, we need to access the 'self' parameter
        # However, unittest.mock doesn't provide a straightforward way to capture 'self'
        # Instead, we can inspect the calls to read_csv and reconstruct the DataFrame
        # Alternatively, use a wrapper or a different mocking strategy
        pass  # We'll handle verification differently

    # Assign the side_effect to capture_to_csv
    mock_to_csv.side_effect = lambda file_path, index=False: captured_dfs.append(file_path)

    # Call the actual function
    process(
        base_input_dir=base_input_dir,
        base_output_dir=base_output_dir,
        scenarios=["baseline"],
        housing_types=["single-family-detached"],
        counties="alameda"
    )

    # Validate that os.makedirs was called correctly
    expected_output_dir = os.path.join(
        base_output_dir,
        "baseline",
        "single-family-detached",
        "alameda"
    )
    mock_makedirs.assert_called_once_with(expected_output_dir, exist_ok=True)

    # Validate that to_csv was called correctly
    expected_output_file = os.path.join(
        expected_output_dir,
        f"{OUTPUT_FILE_NAME}_alameda.csv"
    )
    mock_to_csv.assert_called_once_with(expected_output_file, index=False)

    # Additionally, verify that the correct DataFrames were processed
    # Since capturing the actual DataFrame is complex with method mocks, we'll verify the flow via mock calls

    # Verify the sequence of read_csv calls
    expected_read_csv_calls = [
        # Reading timestamp from electricity default
        call(os.path.join(base_input_dir, "baseline", "single-family-detached", "alameda", "electricity_loads_alameda.csv"),
             usecols=["timestamp"]),
        # Reading total_load from electricity default
        call(os.path.join(base_input_dir, "baseline", "single-family-detached", "alameda", "electricity_loads_alameda.csv"),
             usecols=["total_load"]),
        # Reading Grid to Load from solar storage
        call(os.path.join(base_input_dir, "baseline", "single-family-detached", "alameda", "sam_optimized_load_profiles_alameda.csv"),
             usecols=["Grid to Load"]),
        # Reading gas default with timestamp
        call(os.path.join(base_input_dir, "baseline", "single-family-detached", "alameda", "gas_loads_alameda.csv"),
             parse_dates=["timestamp"]),
        # Reading gas solar storage with timestamp
        call(os.path.join(base_input_dir, "baseline", "single-family-detached", "alameda", "gas_loads_alameda.csv"),
             parse_dates=["timestamp"]),
    ]

    # Extract actual calls excluding any irrelevant calls
    actual_read_csv_calls = mock_read_csv.call_args_list

    # Compare expected and actual read_csv calls
    for expected_call in expected_read_csv_calls:
        assert expected_call in actual_read_csv_calls, f"Expected read_csv call {expected_call} not found in actual calls."