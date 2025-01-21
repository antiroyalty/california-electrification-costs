import pytest
import os
import pandas as pd
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../')))

from step3_build_electricity_load_profiles import (
    process,
    END_USE_COLUMNS
)

@pytest.fixture
def mock_os_path_exists(mocker):
    """Fixture to mock os.path.exists."""
    return mocker.patch("os.path.exists")

@pytest.fixture
def mock_os_listdir(mocker):
    """Fixture to mock os.listdir."""
    return mocker.patch("os.listdir")

@pytest.fixture
def mock_read_parquet(mocker):
    """Fixture to mock pandas.read_parquet."""
    return mocker.patch("pandas.read_parquet")

@pytest.fixture
def mock_to_csv(mocker):
    """Fixture to mock DataFrame.to_csv calls."""
    return mocker.patch("pandas.DataFrame.to_csv")

@pytest.fixture
def mock_makedirs(mocker):
    """Fixture to mock os.makedirs calls."""
    return mocker.patch("os.makedirs")

def test_build_load_profiles_no_input_directory(
    mock_os_path_exists,
    mock_os_listdir,
    mock_read_parquet,
    mock_to_csv,
    mock_makedirs
):
    """If input directory doesn't exist, I skip it and record in summary."""
    mock_os_path_exists.return_value = False  # directory doesn't exist
    mock_os_listdir.return_value = []  # won't be used

    scenarios = {"baseline": ["appliances", "misc"]}
    housing_types = ["single-family-detached"]
    counties = ["fake_county"]

    summary = process(scenarios, housing_types, counties)

    assert len(summary["processed"]) == 0, "No processed items if dir is missing"
    assert len(summary["skipped"]) == 1, "Should skip this county"
    assert summary["skipped"][0]["status"] == "directory_not_found"
    mock_read_parquet.assert_not_called()
    mock_to_csv.assert_not_called()

def test_build_load_profiles_empty_directory(
    mock_os_path_exists,
    mock_os_listdir,
    mock_read_parquet,
    mock_to_csv,
    mock_makedirs
):
    """If the directory exists but has no Parquet files, I skip processing."""
    mock_os_path_exists.return_value = True
    mock_os_listdir.return_value = []  # no files in directory

    scenarios = {"baseline": ["appliances", "misc"]}
    housing_types = ["single-family-detached"]
    counties = ["empty_county"]

    summary = process(scenarios, housing_types, counties)

    assert len(summary["processed"]) == 0
    assert len(summary["skipped"]) == 1
    assert summary["skipped"][0]["status"] == "no_files"
    mock_read_parquet.assert_not_called()
    mock_to_csv.assert_not_called()

def test_build_load_profiles_incomplete_columns(
    mock_os_path_exists,
    mock_os_listdir,
    mock_read_parquet,
    mock_to_csv,
    mock_makedirs
):
    """If a Parquet file is missing required columns, it should skip that file."""
    mock_os_path_exists.return_value = True
    mock_os_listdir.return_value = ["house1.parquet", "house2.parquet"]

    # Scenario requires 'timestamp' and columns in END_USE_COLUMNS["appliances"], "misc"
    # Let’s pretend I only have 'timestamp' and a partial set of columns
    df_missing_cols = pd.DataFrame({"timestamp": pd.date_range("2021-01-01", periods=2, freq="H")})
    mock_read_parquet.return_value = df_missing_cols

    scenarios = {"baseline": ["appliances", "misc"]}  # requires multiple columns
    housing_types = ["single-family-detached"]
    counties = ["test_county"]

    summary = process(scenarios, housing_types, counties)
    # No valid data => should skip the final step
    assert len(summary["processed"]) == 0
    assert len(summary["skipped"]) == 1
    assert summary["skipped"][0]["status"] == "empty_data"
    # Also I expect 2 errors about missing columns for house1 & house2
    assert len(summary["errors"]) == 2
    mock_to_csv.assert_not_called()

def test_build_load_profiles_some_files_valid(
    mock_os_path_exists,
    mock_os_listdir,
    mock_read_parquet,
    mock_to_csv,
    mock_makedirs
):
    """
    Some files have valid columns, others do not. I only process valid files.
    The final output is aggregated and saved to CSV.
    """
    mock_os_path_exists.return_value = True
    mock_os_listdir.return_value = ["house1.parquet", "house2.parquet", "house3.parquet"]

    # We'll define 2 valid DataFrames, 1 invalid
    valid_cols = [
        "timestamp",
        # Because baseline => ["appliances", "misc"] => I need all columns in END_USE_COLUMNS["appliances"] + END_USE_COLUMNS["misc"]
        "out.electricity.ceiling_fan.energy_consumption",
        "out.electricity.dishwasher.energy_consumption",
        "out.electricity.lighting_interior.energy_consumption",
        "out.electricity.lighting_garage.energy_consumption",
        "out.electricity.mech_vent.energy_consumption",
        "out.electricity.refrigerator.energy_consumption",
        "out.electricity.plug_loads.energy_consumption",
        "out.electricity.pool_pump.energy_consumption",
        "out.electricity.pool_heater.energy_consumption",
        "out.electricity.permanent_spa_pump.energy_consumption",
        "out.electricity.permanent_spa_heat.energy_consumption",
        "out.electricity.freezer.energy_consumption",
    ]

    df_valid = pd.DataFrame({
        "timestamp": pd.date_range("2021-01-01", periods=2, freq="H"),
        "out.electricity.ceiling_fan.energy_consumption": [0.1, 0.2],
        "out.electricity.dishwasher.energy_consumption": [0.3, 0.4],
        "out.electricity.lighting_interior.energy_consumption": [0.5, 0.6],
        "out.electricity.lighting_garage.energy_consumption": [0.7, 0.8],
        "out.electricity.mech_vent.energy_consumption": [0.9, 1.0],
        "out.electricity.refrigerator.energy_consumption": [1.1, 1.2],
        "out.electricity.plug_loads.energy_consumption": [1.3, 1.4],
        "out.electricity.pool_pump.energy_consumption": [1.5, 1.6],
        "out.electricity.pool_heater.energy_consumption": [1.7, 1.8],
        "out.electricity.permanent_spa_pump.energy_consumption": [1.9, 2.0],
        "out.electricity.permanent_spa_heat.energy_consumption": [2.1, 2.2],
        "out.electricity.freezer.energy_consumption": [2.3, 2.4],
    }, columns=valid_cols)  # ensure exact column order

    df_invalid = pd.DataFrame({"timestamp": pd.date_range("2021-01-01", periods=2, freq="H")})

    # Return a valid, invalid, then valid DataFrame in sequence
    mock_read_parquet.side_effect = [df_valid, df_invalid, df_valid]

    scenarios = {"baseline": ["appliances", "misc"]}  # requires those columns
    housing_types = ["single-family-detached"]
    counties = ["some_county"]

    summary = process(scenarios, housing_types, counties)

    # Expect 2 valid, 1 invalid => final data is from 2 valid files
    # => I finish with a "processed" status
    assert len(summary["processed"]) == 1
    processed_info = summary["processed"][0]
    assert processed_info["status"] == "processed"
    assert processed_info["num_files"] == 3, "I attempted 3 files, though 1 was partially invalid."

    # The code's data logic only appends valid columns => so I end up with data from the 2 valid frames
    # => 1 error about missing columns
    assert len(summary["errors"]) == 1
    assert "Missing columns" in summary["errors"][0]["error"]

    # Finally, ensure to_csv was called
    mock_to_csv.assert_called_once()

def test_build_load_profiles_empty_data_after_filter(
    mock_os_path_exists,
    mock_os_listdir,
    mock_read_parquet,
    mock_to_csv,
    mock_makedirs
):
    """All parquet files exist but none have the required columns => empty final data => skip."""
    mock_os_path_exists.return_value = True
    mock_os_listdir.return_value = ["house1.parquet", "house2.parquet"]

    df_invalid = pd.DataFrame({
        "timestamp": pd.date_range("2021-01-01", periods=2, freq="H"),
        "some_other_column": [1, 2]
    })
    mock_read_parquet.side_effect = [df_invalid, df_invalid]

    scenarios = {"baseline": ["appliances", "misc"]}
    housing_types = ["single-family-detached"]
    counties = ["empty_data_county"]

    summary = process(scenarios, housing_types, counties)

    assert len(summary["processed"]) == 0
    assert len(summary["skipped"]) == 1
    assert summary["skipped"][0]["status"] == "empty_data"
    mock_to_csv.assert_not_called()