"""Behavior and API regression tests for the isolated SAM experiment."""

import importlib.metadata
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
import PySAM.Battwatts as Battwatts
import PySAM.Battery as Battery

from experiments.sam_parallel import (
    HOURS, hourly, load_inputs, score, simulate_battery, validate_flows,
)


@pytest.mark.parametrize("values", [[1.0]*8759, [1.0]*17520, [np.nan]*HOURS,
                                    [np.inf]*HOURS, [-0.1]*HOURS])
def test_invalid_hourly_series_fail(values):
    with pytest.raises(ValueError):
        hourly(values, "load")


def test_only_solver_residue_is_normalized():
    values = np.zeros(HOURS)
    values[0] = -1e-7
    assert hourly(values, "flow")[0] == 0
    assert hourly(values, "signed", nonnegative=False)[0] == -1e-7


def test_zero_battery_conserves_energy_without_sam_defaults():
    load = np.ones(HOURS)
    pv = np.tile([0]*12 + [2]*12, 365)
    flows, details = simulate_battery(load, pv, 0, 0, [0.4]*HOURS, [0.05]*HOURS)
    imports, exports, residual = validate_flows(load, pv, flows)
    assert imports.sum() == exports.sum() == 4380
    assert residual == 0
    assert details["actual_battery_kwh_dc"] == 0


def test_positive_power_requires_capacity():
    with pytest.raises(ValueError, match="zero-capacity"):
        simulate_battery([1]*HOURS, [0]*HOURS, 0, 5, [0.4]*HOURS, [0.05]*HOURS)


def test_legacy_battwatts_does_not_expose_detailed_battery_dispatch():
    with pytest.raises(AttributeError):
        Battwatts.new().BatteryDispatch.batt_dispatch_choice = 4
    # SOC belongs to BatteryCell, not BatteryDispatch in the detailed model.
    with pytest.raises(AttributeError):
        Battery.default("CustomGenerationBatteryResidential").BatteryDispatch.batt_minimum_SOC = 20


def test_custom_dispatch_sign_units_and_detailed_physics():
    load = np.ones(HOURS)
    pv = np.zeros(HOURS)
    pv[12:16] = 4
    schedule = np.zeros(HOURS)
    schedule[12:16] = -1  # Charge at 1 kW AC for four hours.
    schedule[18:22] = 1   # Discharge at 1 kW AC, subject to physical limits.
    flows, details = simulate_battery(load, pv, 10, 5, [0.4]*HOURS, [0.05]*HOURS,
                                      custom_dispatch_kw=schedule)
    assert 10 <= details["actual_battery_kwh_dc"] <= 10.5
    assert sum(flows.grid_to_batt) == pytest.approx(0, abs=1e-7)
    assert sum(flows.pv_to_batt) == pytest.approx(4, abs=.01)
    assert 0 < sum(flows.batt_to_load) < 4
    assert sum(flows.batt_to_load[:18]) == pytest.approx(0, abs=1e-7)
    validate_flows(load, pv, flows)


def test_load_reader_rejects_timezone_mismatch_before_model_execution(tmp_path):
    weather = tmp_path / "weather.csv"
    weather.write_text("Time Zone,Local Time Zone\n-8,-8\n")
    with pytest.raises(ValueError, match="UTC weather"):
        load_inputs(weather, tmp_path / "missing_load.csv")


def test_duplicate_load_timestamps_fail(tmp_path):
    clock = pd.date_range("2018-01-01", periods=HOURS, freq="h")
    weather = tmp_path / "weather.csv"
    weather.write_text("Time Zone,Local Time Zone\n0,-8\n")
    frame = pd.DataFrame({"Year": clock.year, "Month": clock.month, "Day": clock.day,
                          "Hour": clock.hour, "Minute": 30, "DNI": 0, "DHI": 0,
                          "GHI": 0, "Temperature": 20, "Wind Speed": 1})
    frame.to_csv(weather, mode="a", index=False)
    load = tmp_path / "load.csv"
    pd.DataFrame({"timestamp": [clock[0]]*HOURS}).to_csv(load, index=False)
    with pytest.raises(ValueError, match="unique"):
        load_inputs(weather, load)


def test_retail_dispatch_can_export_at_high_prices():
    if importlib.metadata.version("NREL-PySAM") == "6.0.1":
        pytest.skip("SSC 298 predates battery exports for retail-rate dispatch")
    load = np.full(HOURS, .1)
    pv = np.tile([0]*10 + [3]*6 + [0]*8, 365)
    sell = np.tile([.02]*19 + [3]*2 + [.02]*3, 365)
    flows, _ = simulate_battery(load, pv, 10, 5, [.4]*HOURS, sell)
    assert sum(flows.batt_to_grid) > 1000
    assert sum(flows.grid_to_batt) == pytest.approx(0, abs=1e-7)


def test_cost_components_reconcile(monkeypatch):
    monkeypatch.setattr("experiments.sam_parallel.calculate_nbt_bill",
                        lambda *args: SimpleNamespace(annual_amount_due=1200.0))
    load = np.ones(HOURS)
    pv = np.zeros(HOURS)
    flows, _ = simulate_battery(load, pv, 0, 0, [.4]*HOURS, [.05]*HOURS)
    row = score(load, pv, flows, pd.date_range("2026-01-01", periods=HOURS, freq="h"),
                None, 2, 10, 3300, 600)
    assert row["annual_electricity_and_der_capital_usd"] == (
        row["annual_bill_usd"] + row["annual_pv_capital_usd"]
        + row["annual_battery_capital_usd"])


@pytest.mark.parametrize("message,unavailable", [
    ("Expected one EEC adjustment rate for PG&E", True),
    ("Unexpected missing import plan", False),
])
def test_missing_bill_is_explicit_and_other_errors_propagate(monkeypatch, message, unavailable):
    def fail(*args):
        raise KeyError(message)
    monkeypatch.setattr("experiments.sam_parallel.calculate_nbt_bill", fail)
    load, pv = np.ones(HOURS), np.zeros(HOURS)
    flows, _ = simulate_battery(load, pv, 0, 0, [.4]*HOURS, [.05]*HOURS)
    args = (load, pv, flows, pd.date_range("2026-01-01", periods=HOURS, freq="h"),
            None, 0, 0, 3300, 600)
    if unavailable:
        row = score(*args)
        assert row["billing_status"] == "unavailable"
        assert row["annual_electricity_and_der_capital_usd"] is None
        assert message in row["billing_error"]
    else:
        with pytest.raises(KeyError, match=message):
            score(*args)
