import pytest
import os
import pandas as pd
from unittest.mock import MagicMock, patch
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../')))

from step2_pull_buildings import (
    download_parquet_file,
    process_county,
    process
)

@pytest.fixture
def mock_s3_client(mocker):
    """Mock the S3 client at step2_pull_buildings.s3."""
    s3_client_mock = mocker.patch("step2_pull_buildings.s3")
    return s3_client_mock

@pytest.fixture
def sample_metadata():
    """Sample metadata as a pandas DataFrame."""
    return pd.DataFrame({"bldg_id": ["bldg1", "bldg2", "bldg3"]})

def test_download_parquet_file_creates_output_dir_if_not_exists(mocker, tmp_path, mock_s3_client):
    """Test that the download_parquet_file function works correctly."""
    bucket_name = "test-bucket"
    s3_key = "test-key"
    output_dir = tmp_path / "output"
    output_file = output_dir / "test-key"
    
    # Create the output directory (download_parquet_file doesn't create directories)
    output_dir.mkdir(parents=True)

    download_parquet_file(bucket_name, s3_key, str(output_dir))

    mock_s3_client.download_file.assert_called_once_with(
        Bucket=bucket_name, Key=s3_key, Filename=str(output_file)
    )

def test_download_parquet_file_skips_if_file_exists(mocker, tmp_path, mock_s3_client):
    """Test that the function skips downloading if the file already exists."""
    bucket_name = "test-bucket"
    s3_key = "test-key"
    output_dir = tmp_path / "output"
    output_file = output_dir / "test-key"
    output_dir.mkdir()
    output_file.touch()

    download_parquet_file(bucket_name, s3_key, output_dir)
    mock_s3_client.download_file.assert_not_called()

def test_process_county_handles_missing_metadata_file(mocker, tmp_path):
    """Test process_county handles missing metadata file gracefully."""
    scenario = "test-scenario"
    housing_type = "test-housing"
    county_path = tmp_path / "county"
    bucket_name = "test-bucket"
    s3_prefix = "test-prefix/"
    output_base_dir = tmp_path / "output"
    county_path.mkdir(parents=True)
    
    # Mock get_scenario_path
    mocker.patch("step2_pull_buildings.get_scenario_path", return_value=str(tmp_path / "scenario"))

    # Don't create the CSV file, so it's missing
    result = process_county(
        scenario,
        housing_type,
        str(county_path),
        bucket_name,
        s3_prefix,
        str(output_base_dir)
    )
    # Should return a dictionary with failure status, not False
    assert isinstance(result, dict), "Should return dictionary"
    assert result["status"] == "failure", "Should have failure status when metadata file is missing"
    assert result["total_buildings"] == 0, "Should have 0 total buildings"

def test_process_county_downloads_files(mocker, tmp_path, sample_metadata, mock_s3_client):
    """Test process_county downloads all specified files."""
    scenario = "test-scenario"
    housing_type = "test-housing"
    county_path = tmp_path / "county"
    bucket_name = "test-bucket"
    s3_prefix = "test-prefix/"
    output_base_dir = tmp_path / "output"

    # Create the county directory and a fake metadata CSV
    county_path.mkdir(parents=True)
    metadata_file = county_path / "step1_filtered_building_ids.csv"
    sample_metadata.to_csv(metadata_file, index=False)
    
    # Mock get_scenario_path to return predictable path
    mocker.patch("step2_pull_buildings.get_scenario_path", return_value=str(tmp_path / "scenario"))

    # Mock pandas.read_csv to always return our in-memory DataFrame
    mocker.patch("pandas.read_csv", return_value=sample_metadata)
    
    # Mock ensure_directory_exists
    mocker.patch("step2_pull_buildings.ensure_directory_exists")

    # (1) First call -> no files, second call -> 3 “downloaded” files
    mock_listdir = mocker.patch("os.listdir", side_effect=[
        [],  # First check => empty => triggers download
        ["bldg1-0.parquet", "bldg2-0.parquet", "bldg3-0.parquet"],  # After download => 3 files
    ])

    # (2) So that each listed item is considered a file
    mocker.patch("os.path.isfile", return_value=True)

    # Now call the function under test
    result = process_county(
        scenario,
        housing_type,
        str(county_path),
        bucket_name,
        s3_prefix,
        str(output_base_dir)
    )

    # Should return a dictionary with success status
    assert isinstance(result, dict), "Should return dictionary"
    assert result["status"] == "success", "Should have success status after downloading all files"
    assert result["total_buildings"] == len(sample_metadata), "Should match total buildings"
    assert result["retrieved_buildings"] == len(sample_metadata), "Should have retrieved all buildings"
    # Each building triggers a download, so 3 total calls
    assert mock_s3_client.download_file.call_count == len(sample_metadata), \
        "Should call S3 download once per building ID"

def test_process_all_scenarios_no_download(mocker, tmp_path):
    """Test process does nothing if download_new_files=False."""
    # Patch process_county to ensure it is NOT called
    mock_process_county = mocker.patch("step2_pull_buildings.process_county")

    # Even if directories exist, if download_new_files=False it should do nothing
    tmp_path.mkdir(exist_ok=True)
    result = process('baseline', 'single-family-detached', ['Alameda County', 'Contra Costa County'], output_base_dir=str(tmp_path), download_new_files=False)

    # Verify that it didn't enter the logic that downloads files
    mock_process_county.assert_not_called()

    # Process returns empty list when download_new_files=False
    assert result == [], "Should return empty list when download_new_files=False"

def test_process_non_baseline_scenario(mocker, tmp_path):
    """Test process returns empty list for non-baseline scenarios."""
    # Patch process_county to ensure it is NOT called
    mock_process_county = mocker.patch("step2_pull_buildings.process_county")

    result = process('heat_pump', 'single-family-detached', ['Alameda County'], output_base_dir=str(tmp_path), download_new_files=True)

    # Verify that it didn't enter the logic that downloads files
    mock_process_county.assert_not_called()

    # Process returns empty list for non-baseline scenarios
    assert result == [], "Should return empty list for non-baseline scenarios"