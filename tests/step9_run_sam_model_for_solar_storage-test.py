import os
import pytest
import pandas as pd
from unittest.mock import patch, MagicMock

import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../')))

from step8_run_sam_model_for_solar_storage import (
    get_counties,
    prepare_data_and_compute_system_capacity,
    create_solar_model,
    create_battery_model,
    run_models_and_extract_outputs,
    # configure_rate_plan,
    validate_and_save_results,
    process
)

@pytest.fixture
def mock_data_dir(tmp_path):
    w = tmp_path / "weather_TMY_test.csv"
    l = tmp_path / "electricity_loads_test.csv"
    w.write_text("gh\n100\n200\n300\n")
    l.write_text("total_load\n1\n2\n3\n")
    return str(w), str(l)

def test_get_counties_no_explicit_counties(tmp_path):
    (tmp_path / "county1").mkdir()
    (tmp_path / "county2").mkdir()
    c = get_counties(str(tmp_path), None)
    assert len(c) == 2

def test_get_counties_explicit():
    c = get_counties("test_path", ["Alameda", "Riverside"])
    assert "alameda" in c
    assert "riverside" in c

@patch("pandas.read_csv")
@patch("statistics.mean")
@patch("PySAM.ResourceTools.SAM_CSV_to_solar_data")
def test_prepare_data_and_compute_system_capacity(mock_solar_data, mock_mean, mock_read_csv, mock_data_dir):
    w, l = mock_data_dir
    mock_solar_data.return_value = {"gh": [100,200,300]}
    mock_mean.return_value = 200
    df = pd.DataFrame({"total_load": [1, 2, 3]})
    mock_read_csv.return_value = df
    s, lp, cap = prepare_data_and_compute_system_capacity(w, l, 1)
    assert "gh" in s
    assert len(lp) == 3
    assert cap > 0

@patch("PySAM.Pvwattsv8.default")
def test_create_solar_model(mock_default):
    m = MagicMock()
    mock_default.return_value = m
    r = create_solar_model({"gh":[100]}, 5, 1)
    assert r == m

@patch("PySAM.Battery.from_existing")
def test_create_battery_model(mock_battery):
    m = MagicMock()
    mock_battery.return_value = m
    b = create_battery_model(MagicMock(), [1,2,3], 1)
    assert b == m
    assert b.Load.load == [1,2,3]

def test_run_models_and_extract_outputs():
    s = MagicMock()
    b = MagicMock()
    b.Outputs.system_to_load = [1,1]
    b.Outputs.batt_to_load = [2,2]
    b.Outputs.grid_to_load = [3,3]
    stl, btl, gtl, sbtl, ts, diff = run_models_and_extract_outputs(s, b, [6,6])
    assert stl == [1,1]
    assert btl == [2,2]
    assert gtl == [3,3]
    assert sbtl == [3,3]
    assert ts == [6,6]
    assert diff == [0,0]

# def test_configure_rate_plan():
#     b = MagicMock()
#     configure_rate_plan(b, {"rate":"plan"})
#     assert True

def test_validate_and_save_results(tmp_path):
    o = tmp_path / "output.csv"
    validate_and_save_results(
        "test_county",
        [1]*8760,
        [1]*8760,
        [0]*8760,
        [0]*8760,
        [1]*8760,
        [1]*8760,
        [0]*8760,
        str(o)
    )
    assert o.exists()
    df = pd.read_csv(o)
    assert len(df) == 8760

@patch("os.path.exists", side_effect=lambda x: True)
@patch("os.makedirs")
@patch("PySAM.ResourceTools.SAM_CSV_to_solar_data", return_value={"gh": [100]*8760})
@patch("pandas.read_csv", return_value=pd.DataFrame({"total_load": [1]*8760}))
@patch("PySAM.Pvwattsv8.default")
@patch("PySAM.Battery.from_existing")
def test_process(
    mock_battery,
    mock_solar,
    mock_read_csv,
    mock_solar_data,
    mock_makedirs,
    mock_exists,
    tmp_path
):
    s = MagicMock()
    b = MagicMock()
    mock_solar.return_value = s
    mock_battery.return_value = b
    base_input_dir = str(tmp_path / "in")
    base_output_dir = str(tmp_path / "out")
    (tmp_path / "in/scen/htype/cnty").mkdir(parents=True)
    process(base_input_dir, base_output_dir, ["scen"], ["htype"], ["cnty"], 1)
    assert s.execute.called
    assert b.execute.called