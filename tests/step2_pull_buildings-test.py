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
    """Test that the output directory is created if it does not exist."""
    bucket_name = "test-bucket"
    s3_key = "test-key"
    output_dir = tmp_path / "output"
    output_file = output_dir / "test-key"

    download_parquet_file(bucket_name, s3_key, output_dir)

    assert output_dir.exists(), "Output directory should be created"
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

    # Don't create the CSV file, so it's missing
    result = process_county(
        scenario,
        housing_type,
        county_path,
        bucket_name,
        s3_prefix,
        output_base_dir
    )
    assert result is False, "Should return False when metadata file is missing"

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

    # Mock pandas.read_csv to always return our in-memory DataFrame
    mocker.patch("pandas.read_csv", return_value=sample_metadata)

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
        county_path,
        bucket_name,
        s3_prefix,
        output_base_dir
    )

    # Should succeed because it "downloaded" 3 files
    assert result is True, "Should return True after 'downloading' all files"
    # Each building triggers a download, so 3 total calls
    assert mock_s3_client.download_file.call_count == len(sample_metadata), \
        "Should call S3 download once per building ID"

def test_process_all_scenarios_no_download(mocker, tmp_path):
    """Test process_all_scenarios does nothing if download_new_files=False."""
    # Patch process_county to ensure it is NOT called
    mock_process_county = mocker.patch("step2_pull_buildings.process_county")

    # Even if directories exist, if download_new_files=False it should do nothing
    tmp_path.mkdir(exist_ok=True)
    result = process('baseline', 'single-family-detached', ['Alameda County', 'Contra Costa County'], output_base_dir=str(tmp_path), download_new_files=False)

    # Verify that it didn't enter the logic that downloads files
    mock_process_county.assert_not_called()

    # Process returns a key-value pair with success and failure summaries as soon as it sees download_new_files=False
    assert result == {'failure_summary': [], 'success_summary': ['No new building files needed to be downloaded.']}