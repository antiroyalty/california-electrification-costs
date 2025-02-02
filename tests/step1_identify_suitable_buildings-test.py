import pandas as pd
import pytest
import os
import sys
import warnings

warnings.filterwarnings("ignore", category=pd.errors.DtypeWarning) # suppress warnings
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../')))

from helpers import LOADPROFILES

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
        "in.county_name": ["Alameda County", "Contra Costa County", "San Francisco County"],
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

    filtered = filter_metadata(sample_metadata, "single-family-detached", "001", "Alameda County", "baseline")
    assert len(filtered) == 1
    assert filtered.iloc[0]["bldg_id"] == 101

def test_filter_metadata_scenario_not_defined(sample_metadata):
    with pytest.raises(ValueError):
        filter_metadata(sample_metadata, "single-family-detached", "001", "Alameda County", "non_existent_scenario")

def test_save_building_ids(sample_metadata, tmp_path):
    output_dir = tmp_path / "output"
    os.makedirs(output_dir, exist_ok=True)

    output_csv = save_building_ids(sample_metadata, LOADPROFILES, "Test County", output_dir)
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
            LOADPROFILES,
            "single-family-detached",
            generate_output_filename("Alameda"),
            "step1_filtered_building_ids.csv",
        ),
        os.path.join(
            mock_output_dir,
            LOADPROFILES,
            "single-family-detached",
            generate_output_filename("Contra Costa"),
            "step1_filtered_building_ids.csv",
        ),
        os.path.join(
            mock_output_dir,
            LOADPROFILES,
            "single-family-detached",
            generate_output_filename("San Francisco"),
            "step1_filtered_building_ids.csv",
        ),
    ]

    assert sorted(result) == sorted(expected_paths), "The output file paths should match the expected directory structure."

def test_process_multiple_counties(mocker, sample_metadata, tmp_path):
    mocker.patch("step1_identify_suitable_buildings.get_metadata", return_value=sample_metadata)

    def mock_save_building_ids(filtered_metadata, scenario, county_name, output_dir):
        os.makedirs(output_dir, exist_ok=True)  # Ensure the directory exists
        return os.path.join(output_dir, "step1_filtered_building_ids.csv")

    mocker.patch("step1_identify_suitable_buildings.save_building_ids", side_effect=mock_save_building_ids)

    mock_output_dir = tmp_path / "test_data"

    target_counties = ["Alameda County", "Contra Costa County"] # County names must be suffixed by "County" because that's how the metadata is formatted

    # Run process function with multiple real counties
    result = process("baseline", "single-family-detached", output_base_dir=mock_output_dir, target_counties=target_counties)

    # Expected output paths
    expected_paths = [
        os.path.join(
            mock_output_dir,
            LOADPROFILES,
            "single-family-detached",
            generate_output_filename("Alameda"),
            "step1_filtered_building_ids.csv",
        ),
        os.path.join(
            mock_output_dir,
            LOADPROFILES,
            "single-family-detached",
            generate_output_filename("Contra Costa"),
            "step1_filtered_building_ids.csv",
        ),
    ]

    # Validate that only the specified counties are processed
    assert sorted(result) == sorted(expected_paths), "Process should return results for multiple specified California counties."

def test_process_creates_expected_file(mocker, sample_metadata, tmp_path):
    mocker.patch("step1_identify_suitable_buildings.get_metadata", return_value=sample_metadata)

    def mock_save_building_ids(filtered_metadata, scenario, county_name, output_dir):
        os.makedirs(output_dir, exist_ok=True)  # Ensure the directory exists
        output_file = os.path.join(output_dir, "step1_filtered_building_ids.csv")
        with open(output_file, "w") as f:
            f.write("bldg_id\n101\n")  # Simulate a valid file being written
        return output_file

    mocker.patch("step1_identify_suitable_buildings.save_building_ids", side_effect=mock_save_building_ids)

    mock_output_dir = tmp_path / "mock_data"

    result = process("baseline", "single-family-detached", output_base_dir=mock_output_dir, target_counties=["Alameda County"])

    expected_dir = os.path.join(mock_output_dir, LOADPROFILES, "single-family-detached", "alameda")
    expected_file = os.path.join(expected_dir, "step1_filtered_building_ids.csv")

    assert os.path.exists(expected_dir), f"Directory {expected_dir} should be created."
    assert os.path.exists(expected_file), f"File {expected_file} should exist."
    assert expected_file in result, "Expected file path should be in the result list."

    # Check file content
    with open(expected_file, "r") as f:
        content = f.read()
        assert "bldg_id\n101\n" in content, "File content should contain expected building IDs."

def test_get_metadata_loads_correct_file(mocker):
    mock_read_csv = mocker.patch("pandas.read_csv", return_value=pd.DataFrame({"test": [1, 2, 3]}))
    mock_path_join = mocker.patch("os.path.join", return_value="data/CA_metadata_and_annual_results.csv")

    metadata = get_metadata("baseline")

    mock_path_join.assert_called_once_with("data", "CA_metadata_and_annual_results.csv")
    mock_read_csv.assert_called_once_with("data/CA_metadata_and_annual_results.csv", low_memory=False)
    assert not metadata.empty, "Metadata should not be empty"

def test_process_output_file_row_count_real_data(tmp_path):
    metadata_path = os.path.join("data", "CA_metadata_and_annual_results.csv")

    assert os.path.exists(metadata_path), f"Metadata file {metadata_path} does not exist."

    mock_output_dir = tmp_path / "test_output"
    result = process("baseline", "single-family-detached", output_base_dir=mock_output_dir, target_counties=["Alameda County"])
    expected_file = os.path.join(mock_output_dir, LOADPROFILES, "single-family-detached", "alameda", "step1_filtered_building_ids.csv")

    assert expected_file in result, f"Expected {expected_file} in process() return list, but got {result}"
    assert os.path.exists(expected_file), f"File {expected_file} should exist."

    output_df = pd.read_csv(expected_file)

    # BTW I manually checked this on Jan 30 2025
    # Adding filters to CA_metadata_and_annual_results.csv in Numbers
    # that aligned with the filters described in SCENARIOS for "baseline"
    # And it resulted in 185 rows of results, with 1 header row
    assert output_df.shape[0] == 185, f"Expected 185 rows in {expected_file}, but found {output_df.shape[0]}." # Should be 185 + one header