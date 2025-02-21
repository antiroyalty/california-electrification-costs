# tests/test_step10_evaluate_gas_rates_integration.py

import pytest
import pandas as pd
import os
from unittest.mock import patch, MagicMock, call
from datetime import datetime

# Import the processing functions from the script
# Adjust the import path based on your project structure
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../')))

from step10_evaluate_gas_rates import (
    categorize_season,
    process,
    OUTPUT_FILE_NAME,
    INPUT_FILE_NAME,
    BASELINE_ALLOWANCES,
    RATE_PLANS
)

@pytest.fixture
def sample_load_profile():
    """Fixture to provide a sample load profile DataFrame for Alameda."""
    # Create a DataFrame with entries for different months to cover all seasons
    data = {
        "timestamp": pd.to_datetime([
            "2021-01-15",  # January - winter_onpeak
            "2021-02-15",  # February - winter_offpeak
            "2021-03-15",  # March - winter_offpeak
            "2021-04-15",  # April - summer
            "2021-05-15",  # May - summer
            "2021-06-15",  # June - summer
            "2021-07-15",  # July - summer
            "2021-08-15",  # August - summer
            "2021-09-15",  # September - summer
            "2021-10-15",  # October - summer
            "2021-11-15",  # November - winter_offpeak
            "2021-12-15",  # December - winter_onpeak
        ]),
        "default.gas.therms": [
            1.0,  # January
            1.0,  # February
            1.0,  # March
            1.0,  # April
            1.0,  # May
            1.0,  # June
            1.0,  # July
            1.0,  # August
            1.0,  # September
            1.0,  # October
            1.0,  # November
            1.0,  # December
        ],
    }
    return pd.DataFrame(data)

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
def test_categorize_season(month, expected_season):
    """
    Test that categorize_season correctly categorizes each month.
    
    Parameters:
    - month (int): The month number (1-12).
    - expected_season (str): The expected season category.
    """
    assert categorize_season(month) == expected_season, f"Month {month} should be categorized as {expected_season}."


@pytest.mark.parametrize("invalid_month", [
    0,    # Below valid range
    13,   # Above valid range
    -1,   # Negative month
    100,  # Far above valid range
    1.5,  # Non-integer input
    "June", # String input
    None, # NoneType input
])
def test_categorize_season_invalid_month(invalid_month):
    """
    Test that categorize_season raises ValueError for invalid month inputs.
    
    Parameters:
    - invalid_month: An invalid month input (e.g., 0, 13, negative numbers, non-integers).
    """
    with pytest.raises(ValueError, match=f"Unexpected month provided: {invalid_month}"):
        categorize_season(invalid_month)
