import os
import pytest
from unittest.mock import patch, MagicMock

import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../')))

from step7_get_weather_files import process

@pytest.fixture
def mock_geolocator():
    with patch("step7_get_weather_files.Nominatim") as mock_init:
        geolocator_instance = MagicMock()
        mock_init.return_value = geolocator_instance
        yield geolocator_instance

@pytest.fixture
def mock_requests_get():
    with patch("step7_get_weather_files.requests.get") as mock_req:
        yield mock_req

@pytest.fixture
def setup_dirs(tmp_path):
    base_input_dir = tmp_path / "data"
    base_input_dir.mkdir()
    scenario = "baseline"
    housing_type = "single-family-detached"
    scenario_dir = base_input_dir / scenario
    scenario_dir.mkdir()
    housing_dir = scenario_dir / housing_type
    housing_dir.mkdir()
    county_dir = housing_dir / "alameda"
    county_dir.mkdir()
    output_dir = tmp_path / "output"
    return str(base_input_dir), str(output_dir)

def test_get_tmy_weather_data_success(mock_geolocator, mock_requests_get, setup_dirs):
    base_input_dir, output_dir = setup_dirs
    mock_geolocator.geocode.return_value = MagicMock(latitude=37.8, longitude=-122.3)
    mock_requests_get.return_value.status_code = 200
    mock_requests_get.return_value.text = "weather data"

    process(
        base_input_dir=base_input_dir,
        output_dir=output_dir,
        scenarios=["baseline"],
        housing_types=["single-family-detached"],
        counties=["alameda"],
    )

    assert mock_requests_get.call_count == 1
    file_path = os.path.join(output_dir, "baseline", "single-family-detached", "alameda", "weather_TMY_alameda.csv")
    assert os.path.exists(file_path)

def test_get_tmy_weather_data_missing_directory(mock_geolocator, mock_requests_get, tmp_path):
    base_input_dir = str(tmp_path / "non_existent")
    output_dir = str(tmp_path / "output")

    process(
        scenarios=["baseline"],
        housing_types=["single-family-detached"],
        counties=["alameda"],
        base_input_dir=base_input_dir,
        output_dir=output_dir,
    )
    assert mock_requests_get.call_count == 0

def test_get_tmy_weather_data_missing_county_centroid(mock_geolocator, mock_requests_get, setup_dirs):
    base_input_dir, output_dir = setup_dirs
    mock_geolocator.geocode.return_value = None

    process(
        base_input_dir=base_input_dir,
        output_dir=output_dir,
        scenarios=["baseline"],
        housing_types=["single-family-detached"],
        counties=["missing_county"],
    )
    assert mock_requests_get.call_count == 0

def test_get_tmy_weather_data_failed_request(mock_geolocator, mock_requests_get, setup_dirs):
    base_input_dir, output_dir = setup_dirs
    mock_geolocator.geocode.return_value = MagicMock(latitude=37.8, longitude=-122.3)
    mock_requests_get.return_value.status_code = 404
    mock_requests_get.return_value.text = "Not found"

    process(
        base_input_dir=base_input_dir,
        output_dir=output_dir,
        scenarios=["baseline"],
        housing_types=["single-family-detached"],
        counties=["alameda"],
    )
    assert mock_requests_get.call_count == 1
    file_path = os.path.join(output_dir, "baseline", "single-family-detached", "alameda", "weather_TMY_alameda.csv")
    assert not os.path.exists(file_path)

def test_get_tmy_weather_data_no_counties(mock_geolocator, mock_requests_get, setup_dirs):
    base_input_dir, output_dir = setup_dirs
    mock_geolocator.geocode.return_value = MagicMock(latitude=37.8, longitude=-122.3)
    mock_requests_get.return_value.status_code = 200
    mock_requests_get.return_value.text = "weather data"

    process(
        base_input_dir=base_input_dir,
        output_dir=output_dir,
        scenarios=["baseline"],
        housing_types=["single-family-detached"],
        counties=None,
    )

    assert mock_requests_get.call_count == 1