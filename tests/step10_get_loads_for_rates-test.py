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
        # Since to_csv is a method of DataFrame, I need to access the 'self' parameter
        # However, unittest.mock doesn't provide a straightforward way to capture 'self'
        # Instead, I can inspect the calls to read_csv and reconstruct the DataFrame
        # Alternatively, use a wrapper or a different mocking strategy
        pass  # We'll handle verification differently

    # Assign the side_effect to capture_to_csv
    mock_to_csv.side_effect = lambda file_path, index=False: captured_dfs.append(file_path)

    # Call the actual function
    process(
        base_input_dir=base_input_dir,
        base_output_dir=base_output_dir,
        scenario="baseline",
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


def test_get_file_path():
    """Test the get_file_path helper function."""
    path = "/base/path"
    county = "alameda"
    file_prefix = "electricity_loads_"
    
    expected = "/base/path/alameda/electricity_loads_alameda.csv"
    actual = get_file_path(path, county, file_prefix)
    
    assert actual == expected


def test_aggregate_to_hourly():
    """Test the aggregate_to_hourly function."""
    import tempfile
    import os
    
    # Create a temporary CSV file with test data
    test_data = pd.DataFrame({
        'timestamp': pd.date_range('2021-01-01 00:00', periods=4, freq='15T'),
        'load.gas.building_avg.therms': [0.1, 0.2, 0.3, 0.4]
    })
    
    with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
        test_data.to_csv(f.name, index=False)
        temp_file = f.name
    
    try:
        # Test aggregation
        result = aggregate_to_hourly(temp_file, 'load.gas.building_avg.therms')
        
        # Should sum the 4 15-minute intervals into 1 hour
        expected_sum = 0.1 + 0.2 + 0.3 + 0.4
        assert len(result) == 1
        assert result.iloc[0] == expected_sum
        
    finally:
        os.unlink(temp_file)


def test_aggregate_to_hourly_missing_column():
    """Test aggregate_to_hourly with missing column raises ValueError."""
    import tempfile
    import os
    
    test_data = pd.DataFrame({
        'timestamp': pd.date_range('2021-01-01 00:00', periods=2, freq='15T'),
        'other_column': [1, 2]
    })
    
    with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
        test_data.to_csv(f.name, index=False)
        temp_file = f.name
    
    try:
        with pytest.raises(ValueError, match="Column 'missing_column' not found"):
            aggregate_to_hourly(temp_file, 'missing_column')
    finally:
        os.unlink(temp_file)


def test_read_load_profile():
    """Test the read_load_profile function."""
    import tempfile
    import os
    
    test_data = pd.DataFrame({
        'timestamp': pd.date_range('2021-01-01', periods=3, freq='H'),
        'total_load': [10, 20, 30],
        'other_column': [1, 2, 3]
    })
    
    with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
        test_data.to_csv(f.name, index=False)
        temp_file = f.name
    
    try:
        result = read_load_profile(temp_file, 'total_load')
        
        assert len(result) == 3
        assert list(result) == [10, 20, 30]
        
    finally:
        os.unlink(temp_file)


def test_read_load_profile_missing_file():
    """Test read_load_profile with missing file raises RuntimeError."""
    with pytest.raises(RuntimeError, match="Error reading file"):
        read_load_profile('/nonexistent/file.csv', 'column')


@pytest.mark.parametrize("scenario", [
    "baseline",
    "heat_pump", 
    "induction_stove",
    "heat_pump_and_induction_stove",
    "water_heating",
    "heat_pump_and_induction_stove_and_water_heating"
])
def test_scenario_data_map_completeness(scenario):
    """Test that all scenarios have required data structure."""
    assert scenario in SCENARIO_DATA_MAP
    
    scenario_data = SCENARIO_DATA_MAP[scenario]
    assert "default" in scenario_data
    assert "solar_storage" in scenario_data
    
    for config_type in ["default", "solar_storage"]:
        config = scenario_data[config_type]
        assert "electricity" in config
        assert "gas" in config
        
        elec_config = config["electricity"]
        assert "file_prefix" in elec_config
        assert "column" in elec_config
        
        gas_config = config["gas"]
        assert "file_prefix" in gas_config
        assert "column" in gas_config


@patch("step9_get_loads_for_rates.get_counties", return_value=["alameda", "santa-clara"])
def test_process_multiple_counties(mock_counties):
    """Test processing multiple counties."""
    with patch("step9_get_loads_for_rates.prepare_for_rates_analysis") as mock_prepare:
        process(
            base_input_dir="data",
            base_output_dir="data", 
            scenario="heat_pump",
            housing_types=["single-family-detached"]
        )
        
        # Should call prepare_for_rates_analysis for each county
        assert mock_prepare.call_count == 2
        
        # Check the calls were made with correct parameters
        calls = mock_prepare.call_args_list
        expected_counties = ["alameda", "santa-clara"]
        actual_counties = [call[0][3] for call in calls]  # county is 4th argument
        
        assert set(actual_counties) == set(expected_counties)


@patch("step9_get_loads_for_rates.get_counties", return_value=["alameda"])
def test_process_multiple_housing_types(mock_counties):
    """Test processing multiple housing types."""
    with patch("step9_get_loads_for_rates.prepare_for_rates_analysis") as mock_prepare:
        process(
            base_input_dir="data",
            base_output_dir="data",
            scenario="heat_pump", 
            housing_types=["single-family-detached", "single-family-attached"]
        )
        
        # Should call prepare_for_rates_analysis for each housing type
        assert mock_prepare.call_count == 2
        
        # Check the calls were made with correct housing types
        calls = mock_prepare.call_args_list
        housing_types = [call[0][2] for call in calls]  # housing_type is 3rd argument
        
        assert "single-family-detached" in housing_types
        assert "single-family-attached" in housing_types


def test_scenario_data_map_baseline_structure():
    """Test specific structure of baseline scenario data."""
    baseline = SCENARIO_DATA_MAP["baseline"]
    
    # Test default configuration
    default = baseline["default"]
    assert default["electricity"]["file_prefix"] == "electricity_loads_"
    assert default["electricity"]["column"] == "total_load"
    assert default["gas"]["file_prefix"] == "gas_loads_"
    assert default["gas"]["column"] == "load.gas.building_avg.therms"
    
    # Test solar_storage configuration  
    solar_storage = baseline["solar_storage"]
    assert solar_storage["electricity"]["file_prefix"] == "sam_optimized_load_profiles_"
    assert solar_storage["electricity"]["column"] == "Grid to Load"
    assert solar_storage["gas"]["file_prefix"] == "gas_loads_"
    assert solar_storage["gas"]["column"] == "load.gas.building_avg.therms"


def test_output_columns_constant():
    """Test that OUTPUT_COLUMNS constant has expected structure."""
    from step9_get_loads_for_rates import OUTPUT_COLUMNS
    
    expected_columns = [
        "timestamp", 
        "default.electricity.kwh", 
        "default.gas.therms", 
        "solarstorage.electricity.kwh", 
        "solarstorage.gas.therms"
    ]
    
    assert OUTPUT_COLUMNS == expected_columns