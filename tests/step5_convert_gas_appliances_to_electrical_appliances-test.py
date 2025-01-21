import pytest
import os
import pandas as pd
from unittest.mock import patch, MagicMock
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../')))

from step5_convert_gas_appliances_to_electrical_appliances import (
    EFFICIENCY_GAS_STOVE,
    EFFICIENCY_INDUCTION_STOVE,
    COP_HEAT_PUMP,
    EFFICIENCY_GAS_HEATING,
    COP_HPWH,
    EFFICIENCY_GAS_WATER_HEATER,
    convert_gas_heating_to_electric_heatpump,
    convert_gas_stove_to_induction_stove,
    convert_gas_water_heater_to_electric_waterheater,
    convert_appliances_for_county,
    process
)

# ------------------------------------------------------------------------------
# 1. Conversion Functions / Unit Tests
# ------------------------------------------------------------------------------

def test_convert_gas_heating_to_electric_heatpump_typical():
    """
    Verify the function uses the ratio gas_heating / COP * gas_furnace_eff for
    a typical input (e.g. 10 kWh gas).
    """
    gas_heating_kwh = 10.0
    expected = gas_heating_kwh / COP_HEAT_PUMP * EFFICIENCY_GAS_HEATING
    result = convert_gas_heating_to_electric_heatpump(gas_heating_kwh)
    assert pytest.approx(result, 1e-6) == expected

def test_convert_gas_heating_to_electric_heatpump_zero():
    """
    Zero gas usage => zero electric usage.
    """
    result = convert_gas_heating_to_electric_heatpump(0.0)
    assert result == 0.0

def test_convert_gas_stove_to_induction_stove_typical():
    """
    Check ratio of gas -> induction = gas_stove_kwh * (EFF_GAS / EFF_INDUCTION).
    """
    gas_stove_kwh = 5.0
    expected = gas_stove_kwh * (EFFICIENCY_GAS_STOVE / EFFICIENCY_INDUCTION_STOVE)
    result = convert_gas_stove_to_induction_stove(gas_stove_kwh)
    assert pytest.approx(result, 1e-6) == expected

def test_convert_gas_stove_to_induction_stove_negative():
    """
    If input is negative (bad data?), confirm I get a negative as well or check behavior.
    Here I simply verify the formula is consistent, even though real data might filter it out.
    """
    gas_stove_kwh = -10.0
    result = convert_gas_stove_to_induction_stove(gas_stove_kwh)
    expected = gas_stove_kwh * (EFFICIENCY_GAS_STOVE / EFFICIENCY_INDUCTION_STOVE)
    assert pytest.approx(result, 1e-6) == expected

def test_convert_gas_water_heater_to_electric_waterheater_typical():
    """
    gasWH -> electric = gasWH / HPWH_COP * gasWH_eff
    """
    gas_wh_kwh = 8.0
    expected = gas_wh_kwh / COP_HPWH * EFFICIENCY_GAS_WATER_HEATER
    result = convert_gas_water_heater_to_electric_waterheater(gas_wh_kwh)
    assert pytest.approx(result, 1e-6) == expected

# ------------------------------------------------------------------------------
# 2. convert_appliances_for_county
# ------------------------------------------------------------------------------

@pytest.fixture
def mock_gas_loads_df():
    """
    Returns a sample DataFrame that matches expected columns from 'gas_loads_{county}.csv'.
    """
    return pd.DataFrame({
        "timestamp": pd.date_range("2022-01-01", periods=3, freq="H"),
        "out.natural_gas.heating.energy_consumption.gas.total.kwh": [10.0, 11.0, 12.0],
        "out.natural_gas.range_oven.energy_consumption.gas.total.kwh": [3.0, 2.5, 2.0],
        "out.natural_gas.hot_water.energy_consumption.gas.total.kwh": [5.0, 5.5, 6.0]
    })

def test_convert_appliances_for_county_no_file(mocker):
    """
    If the input_file doesn't exist, function should skip with a print.
    """
    # Mock os.path.exists to return False so it thinks the file's missing
    mock_exists = mocker.patch("os.path.exists", return_value=False)
    mock_read_csv = mocker.patch("pandas.read_csv")
    mock_to_csv = mocker.patch("pandas.DataFrame.to_csv")

    convert_appliances_for_county(
        county="alameda_test",
        base_input_dir="/data",
        base_output_dir="/data",
        scenarios=["baseline"],
        housing_type="single-family-detached"
    )
    mock_read_csv.assert_not_called()
    mock_to_csv.assert_not_called()

def test_convert_appliances_for_county_missing_column(mocker, mock_gas_loads_df):
    """
    If the gas loads CSV is missing a required column, I catch a KeyError and skip.
    """
    # Remove a required column
    mock_gas_loads_df.drop(
        columns=["out.natural_gas.hot_water.energy_consumption.gas.total.kwh"],
        inplace=True
    )

    mock_exists = mocker.patch("os.path.exists", return_value=True)
    mock_read_csv = mocker.patch("pandas.read_csv", return_value=mock_gas_loads_df)
    mock_to_csv = mocker.patch("pandas.DataFrame.to_csv")

    convert_appliances_for_county(
        county="alameda_test",
        base_input_dir="/data",
        base_output_dir="/data",
        scenarios=["baseline"],
        housing_type="sfd"
    )

    # Because 'out.natural_gas.hot_water.energy_consumption.gas.total.kwh' is missing
    # expect a KeyError to be caught, so no .to_csv call.
    mock_to_csv.assert_not_called()

def test_convert_appliances_for_county_success(mocker, mock_gas_loads_df):
    """
    Normal scenario: Have all the necessary columns, so I do the conversions and write a new CSV.
    """
    mock_exists = mocker.patch("os.path.exists", return_value=True)
    mock_read_csv = mocker.patch("pandas.read_csv", return_value=mock_gas_loads_df)
    mock_makedirs = mocker.patch("os.makedirs")

    # Capture the DataFrame passed to `to_csv`
    saved_dataframes = []

    def to_csv_side_effect(self, path, **kwargs):
        saved_dataframes.append(self)  # Use `self` to capture the DataFrame
        print("Captured DataFrame content:\n", self)
        
    mock_to_csv = mocker.patch("pandas.DataFrame.to_csv", new=to_csv_side_effect)

    convert_appliances_for_county(
        county="alameda_test",
        base_input_dir="data",
        base_output_dir="data",
        scenarios=["baseline"],
        housing_type="single-family-detached"
    )

    mock_read_csv.assert_called_once()

    assert len(saved_dataframes) == 1, "No DataFrame was captured from to_csv"
    written_df = saved_dataframes[0]

    # Confirm the new columns exist
    assert "simulated.electricity.heat_pump.energy_consumption.electricity.total.kwh" in written_df.columns
    assert "simulated.electricity.induction_stove.energy_consumption.electricity.total.kwh" in written_df.columns
    assert "simulated.electricity.hot_water.energy_consumption.electricity.total.kwh" in written_df.columns

# ------------------------------------------------------------------------------
# 3. process
# ------------------------------------------------------------------------------

def test_process_no_counties(mocker):
    """
    If counties=None, code tries to discover counties from the folder structure.
    This test won't define that folder structure; just ensure no crash.
    """
    def side_effect_exists(path):
        return True

    # Patch functions and methods
    mock_exists = mocker.patch("os.path.exists", side_effect=side_effect_exists)
    mock_listdir = mocker.patch("os.listdir", return_value=["alameda", "riverside"])
    mock_isdir = mocker.patch(
        "os.path.isdir",
        side_effect=lambda path: path in [
            "data/baseline/single-family-detached/alameda",
            "data/baseline/single-family-detached/riverside"
        ]
    )

    # Patch convert_appliances_for_county where it is used
    mock_convert_county = mocker.patch("step5_convert_gas_appliances_to_electrical_appliances.convert_appliances_for_county")

    scenarios = ["baseline"]
    housing_types = ["single-family-detached"]
    process("data", "data", counties=None, scenarios=scenarios, housing_types=housing_types)

    assert mock_convert_county.call_count == 2

    calls = mock_convert_county.call_args_list
    found_counties = [args[0] for args, kwargs in calls]
    print("Calls to mock_convert_county:", calls)
    print("Found counties:", found_counties)
    assert sorted(found_counties) == ["alameda", "riverside"]

def test_process_explicit_counties(mocker):
    """
    If I specify counties, it uses them directly.
    """
    mock_convert_county = mocker.patch("step5_convert_gas_appliances_to_electrical_appliances.convert_appliances_for_county")
    mock_exists = mocker.patch("os.path.exists", return_value=True)

    scenarios = ["baseline"]
    housing_types = ["sfd"]
    process(
        "data", "data",
        counties=["alameda", "riverside"],
        scenarios=scenarios,
        housing_types=housing_types
    )
    # Should call convert_appliances_for_county for alameda + riverside
    assert mock_convert_county.call_count == 2

    calls = mock_convert_county.call_args_list
    cty1_args = calls[0][0]
    cty2_args = calls[1][0]
    assert cty1_args[0] == "alameda" or cty1_args[0] == "riverside"

def test_process_scenario_path_missing(mocker):
    """
    If the discovered scenario path doesn't exist, it might skip discovering counties
    or raise an error. We'll see how the code handles it.
    """
    mock_exists = mocker.patch("os.path.exists", return_value=False)
    mock_listdir = mocker.patch("os.listdir")
    mock_convert_county = mocker.patch("step5_convert_gas_appliances_to_electrical_appliances.convert_appliances_for_county")

    scenarios = ["baseline"]
    housing_types = ["sfd"]
    process("/base/in", "/base/out", counties=None, scenarios=scenarios, housing_types=housing_types)

    # Because the scenario path is missing, it tries to do:
    #   scenario_path = /base/in/baseline/sfd
    #   but that doesn't exist => it won't find counties => won't call convert_appliances_for_county
    mock_convert_county.assert_not_called()
    mock_listdir.assert_not_called()

@pytest.mark.parametrize("county_in, expected_slug", [
    ("Riverside County", "riverside"),
    ("Santa Clara County", "santa-clara"),
])
def test_convert_county_name_to_slug(mocker, county_in, expected_slug):
    """
    Pass multiple counties like 'Riverside County' and 'Santa Clara County'
    to step5's process(), verifying they're each slugified when calling 
    convert_appliances_for_county.
    """
    mocker.patch("os.path.exists", return_value=True)
    mocker.patch("os.path.isdir", return_value=True)
    # No auto county discovery since I supply counties explicitly
    mocker.patch("os.listdir", return_value=[])

    # Patch read_csv so I don't fail on missing CSV or missing columns
    dummy_df = pd.DataFrame({
        "timestamp": [1,2],
        "out.natural_gas.heating.energy_consumption.gas.total.kwh": [5.0, 6.0],
        "out.natural_gas.range_oven.energy_consumption.gas.total.kwh": [1.0, 2.0],
        "out.natural_gas.hot_water.energy_consumption.gas.total.kwh": [2.5, 3.0],
    })
    mocker.patch("pandas.read_csv", return_value=dummy_df)

    mock_convert = mocker.patch(
        "step5_convert_gas_appliances_to_electrical_appliances.convert_appliances_for_county"
    )

    scenarios = ["baseline"]
    housing_types = ["single-family-detached"]

    # Now call the step5 process function
    process(
        base_input_dir="data",
        base_output_dir="data",
        counties=[county_in],  # e.g. "Riverside County" or "Santa Clara County"
        scenarios=scenarios,
        housing_types=housing_types
    )

    # Expect a single call to convert_appliances_for_county
    mock_convert.assert_called_once()
    # The call signature is: (county, base_input_dir, base_output_dir, scenarios, housing_type)
    (actual_county_arg, actual_in, actual_out, actual_scen, actual_htype) = mock_convert.call_args[0]

    # Confirm the county got slugified
    assert actual_county_arg == expected_slug, f"Expected {expected_slug}, got {actual_county_arg}"
    assert actual_in == "data"
    assert actual_out == "data"
    assert actual_scen == scenarios
    assert actual_htype == "single-family-detached"