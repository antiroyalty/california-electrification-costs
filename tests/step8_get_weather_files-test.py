import os
import pytest
from unittest.mock import patch, MagicMock

import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../')))

from step7_get_weather_files import (
    process,
    get_county_coordinates,
    fetch_weather_data,
    process_county_weather,
    should_skip_processing,
    data_only_for_year
)

@pytest.fixture
def mock_geolocator():
    with patch("step7_get_weather_files.get_county_coordinates") as mock_coords:
        yield mock_coords

@pytest.fixture
def mock_fetch_weather():
    with patch("step7_get_weather_files.fetch_weather_data") as mock_fetch:
        yield mock_fetch

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

def test_get_tmy_weather_data_success(mock_geolocator, mock_fetch_weather, setup_dirs):
    base_input_dir, output_dir = setup_dirs
    mock_geolocator.return_value = (37.8, -122.3)
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.text = "Year,Month,Day,Hour,DNI\n2018,1,1,0,100\n2018,1,1,1,150"
    mock_fetch_weather.return_value = mock_response

    with patch("step7_get_weather_files.data_only_for_year") as mock_data_filter:
        process(
            base_input_dir=base_input_dir,
            output_dir=output_dir,
            scenario="baseline",
            housing_types=["single-family-detached"],
            year=2018,
            counties=["alameda"],
            force_recompute=True
        )

    assert mock_fetch_weather.call_count == 1

def test_should_skip_processing_force_recompute_true():
    """Test that should_skip_processing returns False when force_recompute is True."""
    assert should_skip_processing("existing_file.csv", "existing_year_file.csv", force_recompute=True) == False

def test_should_skip_processing_force_recompute_false_both_exist(tmp_path):
    """Test that should_skip_processing returns True when both files exist and force_recompute is False."""
    raw_file = tmp_path / "weather_raw.csv"
    year_file = tmp_path / "weather_2018.csv"
    
    # Create both files
    raw_file.write_text("raw weather data")
    year_file.write_text("2018 weather data")
    
    assert should_skip_processing(str(raw_file), str(year_file), force_recompute=False) == True

def test_should_skip_processing_force_recompute_false_missing_files(tmp_path):
    """Test that should_skip_processing returns False when files are missing."""
    raw_file = tmp_path / "weather_raw.csv"
    year_file = tmp_path / "weather_2018.csv"
    
    # Test with no files
    assert should_skip_processing(str(raw_file), str(year_file), force_recompute=False) == False
    
    # Test with only raw file
    raw_file.write_text("raw weather data")
    assert should_skip_processing(str(raw_file), str(year_file), force_recompute=False) == False
    
    # Test with only year file
    raw_file.unlink()
    year_file.write_text("2018 weather data")
    assert should_skip_processing(str(raw_file), str(year_file), force_recompute=False) == False

def test_get_county_coordinates_success():
    """Test successful geocoding of county coordinates."""
    with patch("step7_get_weather_files.Nominatim") as mock_nominatim:
        mock_geolocator = MagicMock()
        mock_nominatim.return_value = mock_geolocator
        mock_location = MagicMock()
        mock_location.latitude = 37.8
        mock_location.longitude = -122.3
        mock_geolocator.geocode.return_value = mock_location
        
        coordinates = get_county_coordinates("alameda")
        assert coordinates == (37.8, -122.3)
        mock_geolocator.geocode.assert_called_once_with("alameda, California")

def test_get_county_coordinates_not_found():
    """Test geocoding when county is not found."""
    with patch("step7_get_weather_files.Nominatim") as mock_nominatim:
        mock_geolocator = MagicMock()
        mock_nominatim.return_value = mock_geolocator
        mock_geolocator.geocode.return_value = None
        
        coordinates = get_county_coordinates("nonexistent_county")
        assert coordinates is None

def test_fetch_weather_data():
    """Test weather data fetching from NREL API."""
    with patch("step7_get_weather_files.requests.get") as mock_get:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "weather data"
        mock_get.return_value = mock_response
        
        response = fetch_weather_data(37.8, -122.3, "alameda")
        
        assert response.status_code == 200
        assert response.text == "weather data"
        mock_get.assert_called_once()

def test_process_county_weather_skip_existing(tmp_path):
    """Test that process_county_weather skips when both files exist and force_recompute is False."""
    output_dir = tmp_path / "output"
    county_dir = output_dir / "baseline" / "single-family-detached" / "alameda"
    county_dir.mkdir(parents=True)
    
    raw_file = county_dir / "weather_TMY_alameda.csv"
    year_file = county_dir / "weather_TMY_alameda_2018.csv"
    raw_file.write_text("raw data")
    year_file.write_text("year data")
    
    with patch("step7_get_weather_files.log") as mock_log:
        process_county_weather("alameda", str(output_dir), "baseline", "single-family-detached", 2018, force_recompute=False)
        
        # Should log that processing was skipped
        mock_log.assert_called_once_with(
            at="process", 
            county="alameda", 
            status="skipped_existing", 
            files_at=str(raw_file)
        )

def test_process_county_weather_existing_raw_file(tmp_path):
    """Test that process_county_weather generates year file when raw file exists but year file doesn't."""
    output_dir = tmp_path / "output"
    county_dir = output_dir / "baseline" / "single-family-detached" / "alameda"
    county_dir.mkdir(parents=True)
    
    raw_file = county_dir / "weather_TMY_alameda.csv"
    raw_file.write_text("Year,Month,Day,Hour,DNI\\n2018,1,1,0,100\\n2019,1,1,0,120")
    
    with patch("step7_get_weather_files.log") as mock_log, \
         patch("step7_get_weather_files.data_only_for_year") as mock_data_filter:
        
        process_county_weather("alameda", str(output_dir), "baseline", "single-family-detached", 2018, force_recompute=False)
        
        # Should call data_only_for_year to generate year-specific file
        mock_data_filter.assert_called_once_with(2018, "alameda", str(raw_file))

def test_data_only_for_year(tmp_path):
    """Test filtering weather data for a specific year."""
    input_file = tmp_path / "weather_full.csv"
    input_file.write_text("Year,Month,Day,Hour,DNI\\n2017,12,31,23,50\\n2018,1,1,0,100\\n2018,1,1,1,120\\n2019,1,1,0,80")
    
    output_file = data_only_for_year(2018, "alameda", str(input_file))
    
    # Check that output file was created
    assert os.path.exists(output_file)
    
    # Check that output file contains only 2018 data
    with open(output_file, 'r') as f:
        content = f.read()
        assert "2018,1,1,0,100" in content
        assert "2018,1,1,1,120" in content
        assert "2017,12,31,23,50" not in content
        assert "2019,1,1,0,80" not in content
    file_path = os.path.join(output_dir, "baseline", "single-family-detached", "alameda", "weather_TMY_alameda.csv")
    assert os.path.exists(file_path)

def test_get_tmy_weather_data_missing_county_centroid(mock_geolocator, mock_fetch_weather, setup_dirs):
    base_input_dir, output_dir = setup_dirs
    mock_geolocator.return_value = None

    process(
        base_input_dir=base_input_dir,
        output_dir=output_dir,
        scenario="baseline",
        housing_types=["single-family-detached"],
        year=2018,
        counties=["missing_county"],
        force_recompute=True
    )
    assert mock_fetch_weather.call_count == 0

def test_get_tmy_weather_data_failed_request(mock_geolocator, mock_fetch_weather, setup_dirs):
    base_input_dir, output_dir = setup_dirs
    mock_geolocator.return_value = (37.8, -122.3)
    mock_response = MagicMock()
    mock_response.status_code = 404
    mock_response.text = "Not found"
    mock_fetch_weather.return_value = mock_response

    process(
        base_input_dir=base_input_dir,
        output_dir=output_dir,
        scenario="baseline",
        housing_types=["single-family-detached"],
        year=2018,
        counties=["alameda"],
        force_recompute=True
    )
    assert mock_fetch_weather.call_count == 1

def test_should_skip_processing_force_recompute_true():
    """Test that should_skip_processing returns False when force_recompute is True."""
    assert should_skip_processing("existing_file.csv", "existing_year_file.csv", force_recompute=True) == False

def test_should_skip_processing_force_recompute_false_both_exist(tmp_path):
    """Test that should_skip_processing returns True when both files exist and force_recompute is False."""
    raw_file = tmp_path / "weather_raw.csv"
    year_file = tmp_path / "weather_2018.csv"
    
    # Create both files
    raw_file.write_text("raw weather data")
    year_file.write_text("2018 weather data")
    
    assert should_skip_processing(str(raw_file), str(year_file), force_recompute=False) == True

def test_should_skip_processing_force_recompute_false_missing_files(tmp_path):
    """Test that should_skip_processing returns False when files are missing."""
    raw_file = tmp_path / "weather_raw.csv"
    year_file = tmp_path / "weather_2018.csv"
    
    # Test with no files
    assert should_skip_processing(str(raw_file), str(year_file), force_recompute=False) == False
    
    # Test with only raw file
    raw_file.write_text("raw weather data")
    assert should_skip_processing(str(raw_file), str(year_file), force_recompute=False) == False
    
    # Test with only year file
    raw_file.unlink()
    year_file.write_text("2018 weather data")
    assert should_skip_processing(str(raw_file), str(year_file), force_recompute=False) == False

def test_get_county_coordinates_success():
    """Test successful geocoding of county coordinates."""
    with patch("step7_get_weather_files.Nominatim") as mock_nominatim:
        mock_geolocator = MagicMock()
        mock_nominatim.return_value = mock_geolocator
        mock_location = MagicMock()
        mock_location.latitude = 37.8
        mock_location.longitude = -122.3
        mock_geolocator.geocode.return_value = mock_location
        
        coordinates = get_county_coordinates("alameda")
        assert coordinates == (37.8, -122.3)
        mock_geolocator.geocode.assert_called_once_with("alameda, California")

def test_get_county_coordinates_not_found():
    """Test geocoding when county is not found."""
    with patch("step7_get_weather_files.Nominatim") as mock_nominatim:
        mock_geolocator = MagicMock()
        mock_nominatim.return_value = mock_geolocator
        mock_geolocator.geocode.return_value = None
        
        coordinates = get_county_coordinates("nonexistent_county")
        assert coordinates is None

def test_fetch_weather_data():
    """Test weather data fetching from NREL API."""
    with patch("step7_get_weather_files.requests.get") as mock_get:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "weather data"
        mock_get.return_value = mock_response
        
        response = fetch_weather_data(37.8, -122.3, "alameda")
        
        assert response.status_code == 200
        assert response.text == "weather data"
        mock_get.assert_called_once()

def test_process_county_weather_skip_existing(tmp_path):
    """Test that process_county_weather skips when both files exist and force_recompute is False."""
    output_dir = tmp_path / "output"
    county_dir = output_dir / "baseline" / "single-family-detached" / "alameda"
    county_dir.mkdir(parents=True)
    
    raw_file = county_dir / "weather_TMY_alameda.csv"
    year_file = county_dir / "weather_TMY_alameda_2018.csv"
    raw_file.write_text("raw data")
    year_file.write_text("year data")
    
    with patch("step7_get_weather_files.log") as mock_log:
        process_county_weather("alameda", str(output_dir), "baseline", "single-family-detached", 2018, force_recompute=False)
        
        # Should log that processing was skipped
        mock_log.assert_called_once_with(
            at="process", 
            county="alameda", 
            status="skipped_existing", 
            files_at=str(raw_file)
        )

def test_process_county_weather_existing_raw_file(tmp_path):
    """Test that process_county_weather generates year file when raw file exists but year file doesn't."""
    output_dir = tmp_path / "output"
    county_dir = output_dir / "baseline" / "single-family-detached" / "alameda"
    county_dir.mkdir(parents=True)
    
    raw_file = county_dir / "weather_TMY_alameda.csv"
    raw_file.write_text("Year,Month,Day,Hour,DNI\\n2018,1,1,0,100\\n2019,1,1,0,120")
    
    with patch("step7_get_weather_files.log") as mock_log, \
         patch("step7_get_weather_files.data_only_for_year") as mock_data_filter:
        
        process_county_weather("alameda", str(output_dir), "baseline", "single-family-detached", 2018, force_recompute=False)
        
        # Should call data_only_for_year to generate year-specific file
        mock_data_filter.assert_called_once_with(2018, "alameda", str(raw_file))

def test_data_only_for_year(tmp_path):
    """Test filtering weather data for a specific year."""
    input_file = tmp_path / "weather_full.csv"
    input_file.write_text("Year,Month,Day,Hour,DNI\\n2017,12,31,23,50\\n2018,1,1,0,100\\n2018,1,1,1,120\\n2019,1,1,0,80")
    
    output_file = data_only_for_year(2018, "alameda", str(input_file))
    
    # Check that output file was created
    assert os.path.exists(output_file)
    
    # Check that output file contains only 2018 data
    with open(output_file, 'r') as f:
        content = f.read()
        assert "2018,1,1,0,100" in content
        assert "2018,1,1,1,120" in content
        assert "2017,12,31,23,50" not in content
        assert "2019,1,1,0,80" not in content
    file_path = os.path.join(output_dir, "baseline", "single-family-detached", "alameda", "weather_TMY_alameda.csv")
    assert not os.path.exists(file_path)

def test_get_tmy_weather_data_no_counties(mock_geolocator, mock_fetch_weather, setup_dirs):
    base_input_dir, output_dir = setup_dirs
    mock_geolocator.return_value = (37.8, -122.3)
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.text = "Year,Month,Day,Hour,DNI\n2018,1,1,0,100"
    mock_fetch_weather.return_value = mock_response

    with patch("step7_get_weather_files.data_only_for_year") as mock_data_filter:
        process(
            base_input_dir=base_input_dir,
            output_dir=output_dir,
            scenario="baseline",
            housing_types=["single-family-detached"],
            year=2018,
            counties=None,
            force_recompute=True
        )

    assert mock_fetch_weather.call_count == 1

def test_should_skip_processing_force_recompute_true():
    """Test that should_skip_processing returns False when force_recompute is True."""
    assert should_skip_processing("existing_file.csv", "existing_year_file.csv", force_recompute=True) == False

def test_should_skip_processing_force_recompute_false_both_exist(tmp_path):
    """Test that should_skip_processing returns True when both files exist and force_recompute is False."""
    raw_file = tmp_path / "weather_raw.csv"
    year_file = tmp_path / "weather_2018.csv"
    
    # Create both files
    raw_file.write_text("raw weather data")
    year_file.write_text("2018 weather data")
    
    assert should_skip_processing(str(raw_file), str(year_file), force_recompute=False) == True

def test_should_skip_processing_force_recompute_false_missing_files(tmp_path):
    """Test that should_skip_processing returns False when files are missing."""
    raw_file = tmp_path / "weather_raw.csv"
    year_file = tmp_path / "weather_2018.csv"
    
    # Test with no files
    assert should_skip_processing(str(raw_file), str(year_file), force_recompute=False) == False
    
    # Test with only raw file
    raw_file.write_text("raw weather data")
    assert should_skip_processing(str(raw_file), str(year_file), force_recompute=False) == False
    
    # Test with only year file
    raw_file.unlink()
    year_file.write_text("2018 weather data")
    assert should_skip_processing(str(raw_file), str(year_file), force_recompute=False) == False

def test_get_county_coordinates_success():
    """Test successful geocoding of county coordinates."""
    with patch("step7_get_weather_files.Nominatim") as mock_nominatim:
        mock_geolocator = MagicMock()
        mock_nominatim.return_value = mock_geolocator
        mock_location = MagicMock()
        mock_location.latitude = 37.8
        mock_location.longitude = -122.3
        mock_geolocator.geocode.return_value = mock_location
        
        coordinates = get_county_coordinates("alameda")
        assert coordinates == (37.8, -122.3)
        mock_geolocator.geocode.assert_called_once_with("alameda, California")

def test_get_county_coordinates_not_found():
    """Test geocoding when county is not found."""
    with patch("step7_get_weather_files.Nominatim") as mock_nominatim:
        mock_geolocator = MagicMock()
        mock_nominatim.return_value = mock_geolocator
        mock_geolocator.geocode.return_value = None
        
        coordinates = get_county_coordinates("nonexistent_county")
        assert coordinates is None

def test_fetch_weather_data():
    """Test weather data fetching from NREL API."""
    with patch("step7_get_weather_files.requests.get") as mock_get:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "weather data"
        mock_get.return_value = mock_response
        
        response = fetch_weather_data(37.8, -122.3, "alameda")
        
        assert response.status_code == 200
        assert response.text == "weather data"
        mock_get.assert_called_once()

def test_process_county_weather_skip_existing(tmp_path):
    """Test that process_county_weather skips when both files exist and force_recompute is False."""
    output_dir = tmp_path / "output"
    county_dir = output_dir / "baseline" / "single-family-detached" / "alameda"
    county_dir.mkdir(parents=True)
    
    raw_file = county_dir / "weather_TMY_alameda.csv"
    year_file = county_dir / "weather_TMY_alameda_2018.csv"
    raw_file.write_text("raw data")
    year_file.write_text("year data")
    
    with patch("step7_get_weather_files.log") as mock_log:
        process_county_weather("alameda", str(output_dir), "baseline", "single-family-detached", 2018, force_recompute=False)
        
        # Should log that processing was skipped
        mock_log.assert_called_once_with(
            at="process", 
            county="alameda", 
            status="skipped_existing", 
            files_at=str(raw_file)
        )

def test_process_county_weather_existing_raw_file(tmp_path):
    """Test that process_county_weather generates year file when raw file exists but year file doesn't."""
    output_dir = tmp_path / "output"
    county_dir = output_dir / "baseline" / "single-family-detached" / "alameda"
    county_dir.mkdir(parents=True)
    
    raw_file = county_dir / "weather_TMY_alameda.csv"
    raw_file.write_text("Year,Month,Day,Hour,DNI\\n2018,1,1,0,100\\n2019,1,1,0,120")
    
    with patch("step7_get_weather_files.log") as mock_log, \
         patch("step7_get_weather_files.data_only_for_year") as mock_data_filter:
        
        process_county_weather("alameda", str(output_dir), "baseline", "single-family-detached", 2018, force_recompute=False)
        
        # Should call data_only_for_year to generate year-specific file
        mock_data_filter.assert_called_once_with(2018, "alameda", str(raw_file))

def test_data_only_for_year(tmp_path):
    """Test filtering weather data for a specific year."""
    input_file = tmp_path / "weather_full.csv"
    input_file.write_text("Year,Month,Day,Hour,DNI\\n2017,12,31,23,50\\n2018,1,1,0,100\\n2018,1,1,1,120\\n2019,1,1,0,80")
    
    output_file = data_only_for_year(2018, "alameda", str(input_file))
    
    # Check that output file was created
    assert os.path.exists(output_file)
    
    # Check that output file contains only 2018 data
    with open(output_file, 'r') as f:
        content = f.read()
        assert "2018,1,1,0,100" in content
        assert "2018,1,1,1,120" in content
        assert "2017,12,31,23,50" not in content
        assert "2019,1,1,0,80" not in content