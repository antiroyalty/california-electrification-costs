import pytest
import pandas as pd
import os
import tempfile
from unittest.mock import patch, MagicMock, mock_open
from datetime import datetime

import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../')))

from step10_evaluate_gas_rates import (
    categorize_season,
    sum_therms_by_season,
    calculate_annual_costs_gas,
    get_territory_for_county,
    utility_to_rate_plans,
    utility_to_county_territory_mapping,
    process_county_scenario,
    get_output_file_path,
    update_csv_with_results,
    update_df_with_results,
    build_results_df,
    process,
    OUTPUT_FILE_NAME,
    INPUT_FILE_NAME,
    OUTPUT_COLUMNS,
    LOAD_FOR_RATE_GAS_COLUMN_SUFFIX
)


class TestCategorizeSeasonFunction:
    """Test the categorize_season function."""
    
    @pytest.mark.parametrize("month, expected_season", [
        (1, 'winter_onpeak'),   # January
        (2, 'winter_offpeak'),  # February
        (3, 'winter_offpeak'),  # March
        (4, 'summer'),          # April
        (5, 'summer'),          # May
        (6, 'summer'),          # June
        (7, 'summer'),          # July
        (8, 'summer'),          # August
        (9, 'summer'),          # September
        (10, 'summer'),         # October
        (11, 'winter_offpeak'), # November
        (12, 'winter_onpeak'),  # December
    ])
    def test_categorize_season_valid_months(self, month, expected_season):
        """Test that categorize_season correctly categorizes each valid month."""
        assert categorize_season(month) == expected_season

    @pytest.mark.parametrize("invalid_month", [
        0, 13, -1, 100, 1.5, "June", None
    ])
    def test_categorize_season_invalid_month(self, invalid_month):
        """Test that categorize_season raises ValueError for invalid month inputs."""
        with pytest.raises(ValueError, match="Unexpected month provided"):
            categorize_season(invalid_month)


class TestUtilityFunctions:
    """Test utility mapping functions."""
    
    def test_utility_to_rate_plans_valid_utilities(self):
        """Test that utility_to_rate_plans returns expected data for valid utilities."""
        for utility in ["PG&E", "SCE", "SDG&E"]:
            result = utility_to_rate_plans(utility)
            assert isinstance(result, dict)
            assert len(result) > 0

    def test_utility_to_rate_plans_invalid_utility(self):
        """Test that utility_to_rate_plans raises ValueError for invalid utility."""
        with pytest.raises(ValueError, match="Unknown utility: INVALID"):
            utility_to_rate_plans("INVALID")

    def test_utility_to_county_territory_mapping_valid_utilities(self):
        """Test that utility_to_county_territory_mapping returns expected data."""
        for utility in ["PG&E", "SCE", "SDG&E"]:
            result = utility_to_county_territory_mapping(utility)
            assert isinstance(result, dict)
            assert len(result) > 0

    def test_utility_to_county_territory_mapping_invalid_utility(self):
        """Test that utility_to_county_territory_mapping raises ValueError for invalid utility."""
        with pytest.raises(ValueError, match="Unknown utility: INVALID"):
            utility_to_county_territory_mapping("INVALID")


class TestSumThermsBySeasonFunction:
    """Test the sum_therms_by_season function."""
    
    @pytest.fixture
    def sample_gas_data(self):
        """Create sample gas data for testing."""
        return pd.DataFrame({
            'month': [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12],
            'default.gas.therms': [10, 8, 6, 4, 3, 2, 2, 3, 4, 6, 8, 10]
        })
    
    def test_sum_therms_by_season(self, sample_gas_data):
        """Test that sum_therms_by_season correctly aggregates therms by season."""
        therms_by_season, total_therms = sum_therms_by_season(sample_gas_data, 'default')
        
        # Check total therms
        assert total_therms == 66
        
        # Check seasonal sums
        # winter_onpeak: Jan (10) + Dec (10) = 20
        # winter_offpeak: Feb (8) + Mar (6) + Nov (8) = 22  
        # summer: Apr (4) + May (3) + Jun (2) + Jul (2) + Aug (3) + Sep (4) + Oct (6) = 24
        assert therms_by_season['winter_onpeak'] == 20
        assert therms_by_season['winter_offpeak'] == 22
        assert therms_by_season['summer'] == 24


class TestGetTerritoryForCounty:
    """Test the get_territory_for_county function."""
    
    @patch('step10_evaluate_gas_rates.utility_to_county_territory_mapping')
    def test_get_territory_for_county_found(self, mock_mapping):
        """Test get_territory_for_county when county is found."""
        mock_mapping.return_value = {
            'territory1': ['alameda', 'santa-clara'],
            'territory2': ['los-angeles', 'orange']
        }
        
        result = get_territory_for_county('alameda', 'PG&E')
        assert result == 'territory1'

    @patch('step10_evaluate_gas_rates.utility_to_county_territory_mapping')
    def test_get_territory_for_county_not_found(self, mock_mapping):
        """Test get_territory_for_county when county is not found."""
        mock_mapping.return_value = {
            'territory1': ['alameda', 'santa-clara']
        }
        
        with pytest.raises(ValueError, match="County to gas territory mapping not specified"):
            get_territory_for_county('unknown-county', 'PG&E')


class TestCalculateAnnualCostsGas:
    """Test the calculate_annual_costs_gas function."""
    
    @pytest.fixture
    def mock_load_profile(self):
        """Create mock load profile data."""
        return pd.DataFrame({
            'month': [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12],
            'default.gas.therms': [50, 40, 30, 20, 15, 10, 10, 15, 20, 30, 40, 50]
        })

    @patch('step10_evaluate_gas_rates.BASELINE_ALLOWANCES')
    @patch('step10_evaluate_gas_rates.GAS_RATE_PLANS')
    def test_calculate_annual_costs_gas(self, mock_rate_plans, mock_allowances, mock_load_profile):
        """Test calculate_annual_costs_gas calculation."""
        # Mock the baseline allowances and rate plans
        mock_allowances = {
            'PG&E': {
                'residential': {
                    'territories': {
                        'territory1': {
                            'winter_onpeak': 30,
                            'winter_offpeak': 40, 
                            'summer': 20
                        }
                    }
                }
            }
        }
        
        mock_rate_plans = {
            'PG&E': {
                'residential': {
                    'baseline': {'total_charge': 1.0},
                    'excess': {'total_charge': 1.5}
                }
            }
        }
        
        with patch('step10_evaluate_gas_rates.BASELINE_ALLOWANCES', mock_allowances), \
             patch('step10_evaluate_gas_rates.GAS_RATE_PLANS', mock_rate_plans):
            
            result = calculate_annual_costs_gas(
                mock_load_profile, 'territory1', 'default', 'PG&E', 'residential'
            )
            
            # Should return a positive float
            assert isinstance(result, float)
            assert result > 0


class TestHelperFunctions:
    """Test various helper functions."""
    
    def test_get_output_file_path(self):
        """Test get_output_file_path constructs correct path."""
        with patch('os.makedirs') as mock_makedirs:
            result = get_output_file_path(
                "/base/output", "heat_pump", "single-family-detached", 
                "alameda", "20240101_120000"
            )
            
            expected_path = "/base/output/heat_pump/single-family-detached/alameda/results/gas/RESULTS_gas_annual_costs_alameda_20240101_120000.csv"
            assert result == expected_path
            mock_makedirs.assert_called_once()

    def test_build_results_df(self):
        """Test build_results_df creates correct DataFrame structure."""
        result = build_results_df("heat_pump", 100.0, 80.0, "PG&E", "residential")
        
        assert isinstance(result, pd.DataFrame)
        assert result.shape == (2, 1)
        assert "gas.PG&E.residential" in result.columns
        assert "heat_pump" in result.index
        assert "heat_pump.solarstorage" in result.index
        assert result.loc["heat_pump", "gas.PG&E.residential"] == 100.0
        assert result.loc["heat_pump.solarstorage", "gas.PG&E.residential"] == 80.0

    def test_update_df_with_results(self):
        """Test update_df_with_results merges DataFrames correctly."""
        # Create original DataFrame
        orig_df = pd.DataFrame({
            'col1': [1, 2]
        }, index=['row1', 'row2'])
        
        # Create new DataFrame  
        new_df = pd.DataFrame({
            'col2': [3, 4]
        }, index=['row1', 'row2'])
        
        result = update_df_with_results(orig_df, new_df)
        
        assert 'col2' in result.columns
        assert result.loc['row1', 'col2'] == 3
        assert result.loc['row2', 'col2'] == 4

    def test_update_csv_with_results_new_file(self):
        """Test update_csv_with_results when file doesn't exist."""
        test_df = pd.DataFrame({'test_col': [1, 2]}, index=['test_row1', 'test_row2'])
        
        result = update_csv_with_results('/nonexistent/file.csv', test_df)
        
        # Should return the input DataFrame unchanged
        pd.testing.assert_frame_equal(result, test_df)

    def test_update_csv_with_results_existing_file(self):
        """Test update_csv_with_results when file exists."""
        # Create existing DataFrame
        existing_df = pd.DataFrame({
            'existing_col': [10, 20]
        }, index=['scenario1', 'scenario2'])
        
        # Create new results DataFrame
        new_df = pd.DataFrame({
            'new_col': [30, 40]
        }, index=['scenario1', 'scenario2'])
        
        with patch('os.path.exists', return_value=True), \
             patch('pandas.read_csv', return_value=existing_df):
            
            result = update_csv_with_results('/fake/file.csv', new_df)
            
            # Should have both columns
            assert 'existing_col' in result.columns
            assert 'new_col' in result.columns


class TestProcessCountyScenario:
    """Test the process_county_scenario function."""
    
    @patch('step10_evaluate_gas_rates.calculate_annual_costs_gas')
    @patch('step10_evaluate_gas_rates.get_territory_for_county')
    @patch('pandas.read_csv')
    @patch('os.path.exists')
    def test_process_county_scenario_success(self, mock_exists, mock_read_csv, 
                                           mock_get_territory, mock_calculate_costs):
        """Test process_county_scenario with successful processing."""
        mock_exists.return_value = True
        mock_df = pd.DataFrame({
            'timestamp': pd.to_datetime(['2021-01-01', '2021-02-01']),
            'default.gas.therms': [10, 15]
        })
        mock_read_csv.return_value = mock_df
        mock_get_territory.return_value = 'territory1'
        mock_calculate_costs.return_value = 100.0
        
        result = process_county_scenario(
            '/path/to/scenario', 'alameda', 'default', 'PG&E', 'residential'
        )
        
        assert result == 100.0
        mock_calculate_costs.assert_called_once()

    @patch('os.path.exists')
    def test_process_county_scenario_file_not_found(self, mock_exists):
        """Test process_county_scenario when file doesn't exist."""
        mock_exists.return_value = False
        
        result = process_county_scenario(
            '/path/to/scenario', 'alameda', 'default', 'PG&E', 'residential'
        )
        
        assert result is None


class TestConstants:
    """Test that constants have expected values."""
    
    def test_constants_exist(self):
        """Test that required constants are defined."""
        assert INPUT_FILE_NAME == "loadprofiles_for_rates"
        assert OUTPUT_FILE_NAME == "RESULTS_gas_annual_costs"
        assert LOAD_FOR_RATE_GAS_COLUMN_SUFFIX == ".gas.therms"
        
        assert isinstance(OUTPUT_COLUMNS, list)
        assert len(OUTPUT_COLUMNS) > 0
        assert "county" in OUTPUT_COLUMNS
        assert "scenario" in OUTPUT_COLUMNS


class TestProcessIntegration:
    """Integration tests for the main process function."""
    
    @patch('step10_evaluate_gas_rates.get_timestamp')
    @patch('step10_evaluate_gas_rates.get_utility_for_county')
    @patch('step10_evaluate_gas_rates.get_counties')
    @patch('step10_evaluate_gas_rates.get_scenario_path')
    @patch('step10_evaluate_gas_rates.process_county_scenario')
    def test_process_integration(self, mock_process_county, mock_scenario_path,
                               mock_get_counties, mock_get_utility, mock_timestamp):
        """Test the main process function integration."""
        # Setup mocks
        mock_timestamp.return_value = "20240101_120000"
        mock_scenario_path.return_value = "/path/to/scenario"
        mock_get_counties.return_value = ["alameda"]
        mock_get_utility.return_value = "PG&E"
        mock_process_county.return_value = 100.0
        
        with patch('step10_evaluate_gas_rates.utility_to_rate_plans', 
                   return_value={"residential": {}}), \
             patch('step10_evaluate_gas_rates.get_output_file_path',
                   return_value="/fake/output/path.csv"), \
             patch('step10_evaluate_gas_rates.update_csv_with_results',
                   return_value=pd.DataFrame()), \
             patch('pandas.DataFrame.to_csv') as mock_to_csv:
            
            process(
                base_input_dir="/input",
                base_output_dir="/output", 
                scenario="heat_pump",
                housing_types=["single-family-detached"],
                counties=["alameda"]
            )
            
            # Verify that CSV was written
            mock_to_csv.assert_called()
            
    @patch('step10_evaluate_gas_rates.get_utility_for_county')
    def test_process_utility_assertion_failure(self, mock_get_utility):
        """Test that process raises AssertionError when utility is None."""
        mock_get_utility.return_value = None
        
        with patch('step10_evaluate_gas_rates.get_counties', return_value=["alameda"]), \
             patch('step10_evaluate_gas_rates.get_scenario_path', return_value="/path"):
            
            with pytest.raises(AssertionError, match="Utility not found for county"):
                process(
                    base_input_dir="/input",
                    base_output_dir="/output",
                    scenario="heat_pump", 
                    housing_types=["single-family-detached"],
                    counties=["alameda"]
                )