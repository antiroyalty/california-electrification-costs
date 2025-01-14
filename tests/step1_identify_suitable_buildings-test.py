import pandas as pd
import pytest
import os
import sys
import warnings

warnings.filterwarnings("ignore", category=pd.errors.DtypeWarning) # suppress warnings
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../')))

from step1_identify_suitable_buildings import (
    get_metadata,
    filter_metadata,
    save_building_ids,
    generate_output_filename,
    process,
)

@pytest.fixture
def sample_metadata():
    data = {
        "in.county": ["001", "002", "003"],
        "in.county_name": ["County A", "County B", "County C"],
        "in.geometry_building_type_recs": ["Single-Family Detached", "Single-Family Attached", "Single-Family Detached"],
        "in.cooking_range": ["Gas", "Gas", "Electric"],
        "in.heating_fuel": ["Natural Gas", "Electricity", "Natural Gas"],
        "in.water_heater_fuel": ["Natural Gas", "Electricity", "Natural Gas"],
        "in.has_pv": ["No", "No", "Yes"],
        "in.hvac_cooling_type": [None, None, None],
        "bldg_id": [101, 102, 103],
    }
    return pd.DataFrame(data)

def test_get_metadata(mocker):
    mock_csv_path = "mock_data.csv"
    mocker.patch("os.path.join", return_value=mock_csv_path)
    mock_read_csv = mocker.patch("pandas.read_csv", return_value=pd.DataFrame({"test": [1, 2, 3]}))

    metadata = get_metadata("mock_scenario")
    mock_read_csv.assert_called_once_with(mock_csv_path, low_memory=False)
    assert not metadata.empty

def test_get_metadata_file_not_found(mocker):
    mocker.patch("os.path.join", return_value="missing_file.csv")
    mocker.patch("pandas.read_csv", side_effect=FileNotFoundError)

    with pytest.raises(FileNotFoundError):
        get_metadata("mock_scenario")

def test_filter_metadata_valid_case(sample_metadata):
    SCENARIOS = {
        "baseline": {
            "in.cooking_range": ["Gas"],
            "in.heating_fuel": "Natural Gas",
            "in.water_heater_fuel": "Natural Gas",
            "in.has_pv": "No",
            "in.hvac_cooling_type": None,
        }
    }

    filtered = filter_metadata(sample_metadata, "single-family-detached", "001", "baseline")
    assert len(filtered) == 1
    assert filtered.iloc[0]["bldg_id"] == 101

def test_filter_metadata_scenario_not_defined(sample_metadata):
    with pytest.raises(ValueError):
        filter_metadata(sample_metadata, "single-family-detached", "001", "non_existent_scenario")

def test_save_building_ids(sample_metadata, tmp_path):
    output_dir = tmp_path / "output"
    os.makedirs(output_dir, exist_ok=True)

    output_csv = save_building_ids(sample_metadata, "baseline", "Test County", output_dir)
    assert os.path.exists(output_csv)

    saved_data = pd.read_csv(output_csv)
    assert "bldg_id" in saved_data.columns
    assert len(saved_data) == 3

def test_generate_output_filename():
    assert generate_output_filename("Riverside County") == "riverside"
    assert generate_output_filename("Los Angeles County") == "los-angeles"
    assert generate_output_filename("San_Francisco") == "san-francisco"

def test_process_function(mocker, sample_metadata, tmp_path):
    mocker.patch("step1_identify_suitable_buildings.get_metadata", return_value=sample_metadata)
    mocker.patch("step1_identify_suitable_buildings.save_building_ids", return_value="mock_output.csv")

    mock_output_dir = tmp_path / "mock_data"

    # Test Case 1: Iterates over all counties
    result = process("baseline", "single-family-detached", output_base_dir=tmp_path)
    assert len(result) == len(sample_metadata["in.county"]), "Process should iterate over all counties."

    # Test Case 2: Returns a list of file paths
    assert all(isinstance(path, str) for path in result), "Process should return a list of file paths."

    # Test Case 3: Handles empty metadata gracefully
    empty_metadata = pd.DataFrame(columns=sample_metadata.columns)
    mocker.patch("step1_identify_suitable_buildings.get_metadata", return_value=empty_metadata)
    result = process("baseline", "single-family-detached", output_base_dir=tmp_path)
    assert len(result) == 0, "Process should handle empty metadata without errors."

def test_process_output_file_paths(mocker, sample_metadata, tmp_path):
    mocker.patch("step1_identify_suitable_buildings.get_metadata", return_value=sample_metadata)

    def mock_save_building_ids(filtered_metadata, scenario, county_name, output_dir):
        os.makedirs(output_dir, exist_ok=True)  # Ensure the directory exists
        return os.path.join(output_dir, "step1_filtered_building_ids.csv")

    mocker.patch("step1_identify_suitable_buildings.save_building_ids", side_effect=mock_save_building_ids)

    mock_output_dir = tmp_path / "mock_data"

    result = process("baseline", "single-family-detached", output_base_dir=mock_output_dir)

    expected_paths = [
        os.path.join(
            mock_output_dir,
            "baseline",
            "single-family-detached",
            generate_output_filename("County A"),
            "step1_filtered_building_ids.csv",
        ),
        os.path.join(
            mock_output_dir,
            "baseline",
            "single-family-detached",
            generate_output_filename("County B"),
            "step1_filtered_building_ids.csv",
        ),
        os.path.join(
            mock_output_dir,
            "baseline",
            "single-family-detached",
            generate_output_filename("County C"),
            "step1_filtered_building_ids.csv",
        ),
    ]

    assert sorted(result) == sorted(expected_paths), "The output file paths should match the expected directory structure."