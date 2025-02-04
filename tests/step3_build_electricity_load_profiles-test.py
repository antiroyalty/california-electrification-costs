import pytest
import os
import pandas as pd
from unittest.mock import patch, MagicMock
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../')))

from step3_build_electricity_load_profiles import (
    process,
    process_county_data,
    read_parquet_file,
    list_parquet_files,
    get_end_use_columns,
    END_USE_COLUMNS
)

# -----------------------------------
# FIXTURES
# -----------------------------------
@pytest.fixture
def mock_os_path_exists(mocker):
    return mocker.patch("os.path.exists")

@pytest.fixture
def mock_os_listdir(mocker):
    return mocker.patch("os.listdir")

@pytest.fixture
def mock_read_parquet(mocker):
    return mocker.patch("pandas.read_parquet")

@pytest.fixture
def mock_to_csv(mocker):
    return mocker.patch("pandas.DataFrame.to_csv")

@pytest.fixture
def mock_makedirs(mocker):
    return mocker.patch("os.makedirs")


# -----------------------------------
# UNIT TESTS
# -----------------------------------

def test_get_end_use_columns():
    """Test if function correctly extracts end-use columns."""
    categories = {"electric": ["appliances", "misc"]}
    expected_columns = [
        'out.electricity.ceiling_fan.energy_consumption',
        'out.electricity.clothes_dryer.energy_consumption',
        'out.electricity.dishwasher.energy_consumption',
        'out.electricity.lighting_interior.energy_consumption',
        'out.electricity.lighting_garage.energy_consumption',
        'out.electricity.mech_vent.energy_consumption',
        'out.electricity.refrigerator.energy_consumption',
        'out.electricity.plug_loads.energy_consumption',
        'out.electricity.pool_pump.energy_consumption',
        'out.electricity.pool_heater.energy_consumption',
        'out.electricity.permanent_spa_pump.energy_consumption',
        'out.electricity.permanent_spa_heat.energy_consumption',
        'out.electricity.freezer.energy_consumption',
    ]
    assert sorted(get_end_use_columns(categories)) == sorted(expected_columns)


def test_list_parquet_files(mock_os_path_exists, mock_os_listdir):
    """Test if Parquet files are listed correctly."""
    mock_os_path_exists.return_value = True
    mock_os_listdir.return_value = ["file1.parquet", "file2.parquet", "not_a_parquet.txt"]

    assert list_parquet_files("fake_directory") == ["file1.parquet", "file2.parquet"]


def test_list_parquet_files_no_directory(mock_os_path_exists):
    """Test if function handles a missing directory."""
    mock_os_path_exists.return_value = False
    assert list_parquet_files("missing_directory") == []


def test_read_parquet_file_valid(mock_read_parquet):
    """Test if a valid Parquet file is read correctly."""
    df = pd.DataFrame({"timestamp": ["2021-01-01 00:00"], "energy": [10]})
    mock_read_parquet.return_value = df

    data, error = read_parquet_file("valid.parquet", ["timestamp", "energy"])
    assert error is None
    assert not data.empty


def test_read_parquet_file_missing_columns(mock_read_parquet):
    """Test if function correctly identifies missing columns."""
    df = pd.DataFrame({"timestamp": ["2021-01-01 00:00"]})  # Missing "energy"
    mock_read_parquet.return_value = df

    data, error = read_parquet_file("invalid.parquet", ["timestamp", "energy"])
    assert data is None
    assert "Missing columns" in error


def test_read_parquet_file_invalid_format(mock_read_parquet):
    """Test if function correctly handles read errors."""
    mock_read_parquet.side_effect = Exception("File corrupt")

    data, error = read_parquet_file("corrupt.parquet", ["timestamp", "energy"])
    assert data is None
    assert "Error reading" in error


# -----------------------------------
# INTEGRATION TESTS
# -----------------------------------

def test_process_county_data_no_files(mock_os_path_exists, mock_os_listdir):
    """Test if process_county_data correctly skips when no files exist."""
    mock_os_path_exists.return_value = True
    mock_os_listdir.return_value = []  # No files

    status, num_files = process_county_data("some_input_dir", "output.csv", ["energy"])
    assert status == "no_files"
    assert num_files == 0


def test_process_county_data_valid_files(
    mock_os_path_exists, mock_os_listdir, mock_read_parquet, mock_to_csv, mock_makedirs
):
    """Test if process_county_data processes valid Parquet files correctly."""
    mock_os_path_exists.return_value = True
    mock_os_listdir.return_value = ["valid1.parquet", "valid2.parquet"]

    df = pd.DataFrame({
        "timestamp": pd.date_range("2021-01-01", periods=2, freq="H"),
        "energy": [1.0, 2.0]
    })
    mock_read_parquet.return_value = df

    status, num_files = process_county_data("some_input_dir", "output.csv", ["energy"])
    assert status == "processed"
    assert num_files == 2
    mock_to_csv.assert_called_once()


def test_process_county_data_some_invalid_files(
    mock_os_path_exists, mock_os_listdir, mock_read_parquet, mock_to_csv, mock_makedirs
):
    """Test if process_county_data skips invalid files but still processes valid ones."""
    mock_os_path_exists.return_value = True
    mock_os_listdir.return_value = ["valid.parquet", "invalid.parquet"]

    df_valid = pd.DataFrame({
        "timestamp": pd.date_range("2021-01-01", periods=2, freq="H"),
        "energy": [1.0, 2.0]
    })
    df_invalid = pd.DataFrame({"timestamp": pd.date_range("2021-01-01", periods=2, freq="H")})  # Missing "energy"

    mock_read_parquet.side_effect = [df_valid, df_invalid]

    status, num_files = process_county_data("some_input_dir", "output.csv", ["energy"])
    assert status == "processed"
    assert num_files == 2
    mock_to_csv.assert_called_once()


def test_process_full_pipeline(
    mock_os_path_exists, mock_os_listdir, mock_read_parquet, mock_to_csv, mock_makedirs
):
    """Test the full process function with multiple scenarios and housing types."""
    mock_os_path_exists.return_value = True
    mock_os_listdir.return_value = ["valid.parquet"]

    end_use_categories = {"electric": ["appliances", "misc"]}
    required_columns = ["timestamp"] + sum(
        [END_USE_COLUMNS[category] for category in end_use_categories["electric"]], []
    )

    # Create a mock DataFrame with all required columns
    df = pd.DataFrame({col: [0.1, 0.2] for col in required_columns})
    df["timestamp"] = pd.date_range("2021-01-01", periods=2, freq="H")  # Ensure timestamp format

    mock_read_parquet.return_value = df
    
    scenarios = {"baseline": end_use_categories}
    housing_types = ["single-family"]
    counties = ["test_county"]

    summary = process(scenarios, housing_types, counties, "input_dir", "output_dir")

    assert len(summary["processed"]) == 1  # Expect 1 processed county
    assert summary["processed"][0]["status"] == "processed"
    mock_to_csv.assert_called_once()  # Ensure CSV was saved

def test_process_county_data_all_invalid_files(
    mock_os_path_exists, mock_os_listdir, mock_read_parquet, mock_to_csv, mock_makedirs
):
    """Test if process_county_data correctly skips when all files have missing required columns."""
    mock_os_path_exists.return_value = True
    mock_os_listdir.return_value = ["invalid1.parquet", "invalid2.parquet"]

    # Both files have no required columns
    df_invalid = pd.DataFrame({"some_other_column": [1, 2]})
    mock_read_parquet.return_value = df_invalid

    status, num_files = process_county_data("some_input_dir", "output.csv", ["energy"])

    assert status == "empty_data"
    assert num_files == 0
    mock_to_csv.assert_not_called()