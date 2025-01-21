"""
Test suite for step4_build_gas_load_profiles.py

Covers:
- process_building_data
- update_county_totals
- sum_county_gas_profiles
- average_county_gas_profiles
- save_county_gas_profiles
- build_county_gas_profile
- process
"""

import pytest
import os
import pandas as pd
from unittest.mock import patch, MagicMock
import sys

# Add parent directory to path so I can import the module
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../')))

from step4_build_gas_load_profiles import (
    process_building_data,
    update_county_totals,
    sum_county_gas_profiles,
    average_county_gas_profiles,
    save_county_gas_profiles,
    build_county_gas_profile,
    process,
    KWH_TO_THERMS,
    END_USE_COLUMNS
)


@pytest.fixture
def sample_dataframe():
    """
    A fixture that returns a sample DataFrame containing the columns needed
    to test building-level gas usage calculations.
    """
    return pd.DataFrame({
        "timestamp": pd.date_range("2022-01-01", periods=3, freq="H"),
        "out.natural_gas.heating.energy_consumption": [1.0, 2.0, 3.0],
        "out.natural_gas.hot_water.energy_consumption": [0.5, 0.6, 0.7],
        "out.natural_gas.range_oven.energy_consumption": [0.1, 0.2, 0.3],
        "out.natural_gas.clothes_dryer.energy_consumption": [0.05, 0.06, 0.07],
        "out.natural_gas.fireplace.energy_consumption": [0.0, 0.1, 0.2],
    })


# ------------------------------------------------------------------------------
# process_building_data Tests
# ------------------------------------------------------------------------------

def test_process_building_data_ok(sample_dataframe):
    """
    process_building_data should group data properly for the columns provided.
    """
    end_uses = [
        "out.natural_gas.heating.energy_consumption",
        "out.natural_gas.hot_water.energy_consumption"
    ]
    grouped = process_building_data(sample_dataframe, end_uses)
    assert len(grouped) == 3
    assert "load.gas.total.kwh" in grouped.columns
    # first row sum
    assert grouped.loc[0, "load.gas.total.kwh"] == 1.0 + 0.5


def test_process_building_data_missing_columns(sample_dataframe):
    """
    If a required column is missing, process_building_data should raise ValueError.
    """
    end_uses = [
        "out.natural_gas.heating.energy_consumption",
        "out.natural_gas.hot_water.energy_consumption"
    ]
    df_missing = sample_dataframe.drop(columns="out.natural_gas.hot_water.energy_consumption")

    with pytest.raises(ValueError, match="Missing required columns"):
        process_building_data(df_missing, end_uses)


# ------------------------------------------------------------------------------
# update_county_totals Tests
# ------------------------------------------------------------------------------

def test_update_county_totals_initialize(sample_dataframe):
    """
    When county_gas_totals is None, update_county_totals should init new columns
    and compute 'load.gas.total.therms'.
    """
    end_uses = [
        "out.natural_gas.heating.energy_consumption",
        "out.natural_gas.hot_water.energy_consumption"
    ]
    building_df = process_building_data(sample_dataframe, end_uses)
    county_totals = update_county_totals(None, building_df, 1, end_uses)

    for col in end_uses:
        assert f"{col}.gas.total.kwh" in county_totals.columns
    assert "load.gas.total.therms" in county_totals.columns
    assert county_totals["building_count"].iloc[0] == 1


def test_update_county_totals_aggregate(sample_dataframe):
    """
    If I have an existing county_gas_totals, update_county_totals should
    add the new building's usage to the existing columns.
    """
    end_uses = [
        "out.natural_gas.heating.energy_consumption",
        "out.natural_gas.hot_water.energy_consumption"
    ]
    building1 = process_building_data(sample_dataframe.iloc[:2], end_uses)
    county_totals = update_county_totals(None, building1, 1, end_uses)

    building2 = process_building_data(sample_dataframe, end_uses)
    county_totals = update_county_totals(county_totals, building2, 2, end_uses)

    assert county_totals["building_count"].iloc[0] == 2
    total_kwh_county = county_totals["load.gas.total.kwh"].sum()
    total_kwh_b2 = building2["load.gas.total.kwh"].sum()
    assert total_kwh_county > total_kwh_b2


# ------------------------------------------------------------------------------
# sum_county_gas_profiles Tests
# ------------------------------------------------------------------------------

def test_sum_county_gas_profiles_no_files(mocker):
    """
    If directory has no .parquet files, sum_county_gas_profiles returns (None, 0).
    """
    mocker.patch("os.listdir", return_value=[])
    county_totals, building_count = sum_county_gas_profiles("/fake/dir", ["some_col"])
    assert county_totals is None
    assert building_count == 0


def test_sum_county_gas_profiles_reads_files(mocker, sample_dataframe):
    """
    sum_county_gas_profiles should read each .parquet file with valid columns
    and accumulate them.
    """
    mocker.patch("os.listdir", return_value=["b1.parquet", "b2.parquet", "not_parquet.txt"])
    mock_read = mocker.patch("pandas.read_parquet", return_value=sample_dataframe)
    end_uses = list(sample_dataframe.columns.drop("timestamp"))

    county_totals, building_count = sum_county_gas_profiles("/fake/dir", end_uses)
    assert mock_read.call_count == 2
    assert building_count == 2
    assert county_totals is not None
    assert "load.gas.total.kwh" in county_totals.columns


# ------------------------------------------------------------------------------
# average_county_gas_profiles Tests
# ------------------------------------------------------------------------------

def test_average_county_gas_profiles(sample_dataframe):
    """
    average_county_gas_profiles should create average columns for total & each end use,
    dividing by building_count.
    """
    end_uses = list(sample_dataframe.columns.drop("timestamp"))
    building_df = process_building_data(sample_dataframe, end_uses)
    # rename
    county_df = building_df.rename(columns={col: f"{col}.gas.total.kwh" for col in end_uses})

    updated = average_county_gas_profiles(county_df, 2, end_uses)
    assert "load.gas.avg.kwh" in updated.columns


# ------------------------------------------------------------------------------
# save_county_gas_profiles Tests
# ------------------------------------------------------------------------------

def test_save_county_gas_profiles(mocker):
    """
    Ensure I write a CSV to 'gas_loads_{county}.csv' under the given output dir.
    """
    mock_to_csv = mocker.patch("pandas.DataFrame.to_csv")
    mock_makedirs = mocker.patch("os.makedirs")

    df = pd.DataFrame({"test_col": [1, 2, 3]})
    save_county_gas_profiles(df, "mycounty", "/fake/dir")

    mock_makedirs.assert_called_once_with("/fake/dir", exist_ok=True)
    mock_to_csv.assert_called_once()
    out_path = mock_to_csv.call_args[0][0]
    assert out_path.endswith("gas_loads_mycounty.csv")


# ------------------------------------------------------------------------------
# build_county_gas_profile Tests
# ------------------------------------------------------------------------------

def test_build_county_gas_profile_no_data(mocker):
    """
    If sum_county_gas_profiles returns (None, 0), I skip averaging and saving.
    """
    mock_sum = mocker.patch("step4_build_gas_load_profiles.sum_county_gas_profiles", return_value=(None, 0))
    mock_avg = mocker.patch("step4_build_gas_load_profiles.average_county_gas_profiles")
    mock_save = mocker.patch("step4_build_gas_load_profiles.save_county_gas_profiles")

    build_county_gas_profile("baseline", "sfd", "test", "/fake/dir", "/fake/out", [])
    mock_sum.assert_called_once()
    mock_avg.assert_not_called()
    mock_save.assert_not_called()


def test_build_county_gas_profile_with_data(mocker):
    """
    If sum_county_gas_profiles returns valid data, I call average_county_gas_profiles
    and save_county_gas_profiles.
    """
    mock_sum = mocker.patch(
        "step4_build_gas_load_profiles.sum_county_gas_profiles",
        return_value=(pd.DataFrame({"load.gas.total.kwh": [10, 20]}), 2)
    )
    mock_avg = mocker.patch(
        "step4_build_gas_load_profiles.average_county_gas_profiles",
        return_value=pd.DataFrame({"some_final_col": [10, 20]})
    )
    mock_save = mocker.patch("step4_build_gas_load_profiles.save_county_gas_profiles")

    build_county_gas_profile("baseline", "sfd", "test", "/fake/dir", "/fake/out", [])
    mock_sum.assert_called_once()
    mock_avg.assert_called_once()
    mock_save.assert_called_once()


# ------------------------------------------------------------------------------
# process Tests
# ------------------------------------------------------------------------------

def test_process_no_scenario_path(mocker):
    mocker.patch("os.path.exists", return_value=False)
    mock_listdir = mocker.patch("os.listdir")

    scenarios = {"baseline": ["heating"]}
    process(scenarios, ["sfd"], "/base/in", "/base/out", counties=["cty"])
    mock_listdir.assert_not_called()


def test_process_county_dir_missing(mocker):
    """
    If the county folder doesn't have 'buildings', I skip that county.
    """
    def side_exists(path):
        if "buildings" in path:
            return False
        return True
    
    mocker.patch("os.path.exists", side_effect=side_exists)
    mocker.patch("os.listdir", return_value=["cty"])
    mock_bld = mocker.patch("step4_build_gas_load_profiles.build_county_gas_profile")

    scenarios = {"baseline": ["heating"]}
    process(scenarios, ["sfd"], "/base/in", "/base/out")
    mock_bld.assert_not_called()


def test_process_county_ok(mocker):
    """
    If scenario path and county_dir exist, I call build_county_gas_profile.
    """
    def side_exists(path):
        return True  # everything exists
    mocker.patch("os.path.exists", side_effect=side_exists)
    mocker.patch("os.path.isdir", return_value=True)
    mocker.patch("os.listdir", return_value=["ctyA", "ctyB"])
    mock_bld = mocker.patch("step4_build_gas_load_profiles.build_county_gas_profile")

    scenarios = {"baseline": ["heating"]}
    process(scenarios, ["sfd"], "/base/in", "/base/out")
    # Expect 2 calls, for ctyA and ctyB
    assert mock_bld.call_count == 2

def test_convert_county_name_to_slug(mocker):
    """
    Pass multiple counties like 'Riverside County' and 'Santa Clara County' to step4's process()
    and ensure they're each slugified (e.g. 'riverside', 'santa-clara') for build_county_gas_profile.
    """
    mocker.patch("os.path.exists", return_value=True)
    mocker.patch("os.path.isdir", return_value=True)
    mocker.patch("os.listdir", return_value=[])

    # Spy on build_county_gas_profile to see how it's invoked
    mock_build = mocker.patch("step4_build_gas_load_profiles.build_county_gas_profile")

    scenarios = {"baseline": ["heating"]}
    housing_types = ["single-family-detached"]
    # Two counties that need slug conversion
    input_counties = ["Riverside County", "Santa Clara County"]

    # Call the process function
    process(
        scenarios=scenarios,
        housing_types=housing_types,
        base_input_dir="data",
        base_output_dir="data",
        counties=input_counties,
    )

    assert mock_build.call_count == 2, "Should invoke build_county_gas_profile twice (once per county)."

    # Grab each call in turn
    first_call_args = mock_build.call_args_list[0][0]
    second_call_args = mock_build.call_args_list[1][0]

    # Each call's signature is: (scenario, housing_type, county, county_dir, output_dir, end_uses)
    # -----------------------------
    # 1) Riverside County -> 'riverside'
    scenario_1, housing_1, county_1, county_dir_1, output_dir_1, end_uses_1 = first_call_args

    assert scenario_1 == "baseline"
    assert housing_1 == "single-family-detached"
    # County is slugified to "riverside"
    assert county_1 == "riverside", f"Expected 'riverside', got {county_1}"
    # Directories must also contain "riverside"
    assert county_dir_1 == "data/baseline/single-family-detached/riverside/buildings"
    assert output_dir_1 == "data/baseline/single-family-detached/riverside"

    # -----------------------------
    # 2) Santa Clara County -> 'santa-clara'
    scenario_2, housing_2, county_2, county_dir_2, output_dir_2, end_uses_2 = second_call_args

    assert scenario_2 == "baseline"
    assert housing_2 == "single-family-detached"
    # County is slugified to "santa-clara"
    assert county_2 == "santa-clara", f"Expected 'santa-clara', got {county_2}"
    # Directories must also contain "santa-clara"
    assert county_dir_2 == "data/baseline/single-family-detached/santa-clara/buildings"
    assert output_dir_2 == "data/baseline/single-family-detached/santa-clara"