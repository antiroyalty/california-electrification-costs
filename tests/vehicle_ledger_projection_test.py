"""Vehicle operating costs select one explicit county and incentive case."""

import importlib
import sys
from types import ModuleType

import pandas as pd
import pytest

from evaluations.vehicles import (
    VehicleLedgerValidationError,
    vehicle_annual_adders_from_ledger,
)
from pipeline.steps import step15_payback_periods as step15


INCENTIVES = ["full_incentives", "half_incentives", "no_incentives"]


def _vehicle_ledger(appliance_type, category, annual_costs):
    return pd.DataFrame([
        {
            "county_slug": "alameda",
            "incentive_scenario": incentive,
            "appliance_category": category,
            "appliance_type": appliance_type,
            "annual_operating_cost": annual_cost,
        }
        for incentive, annual_cost in zip(INCENTIVES, annual_costs)
    ])


@pytest.mark.parametrize(
    "incentive,expected",
    [("full_incentives", -25), ("half_incentives", 0), ("no_incentives", 75)],
)
def test_projection_selects_one_incentive_and_preserves_signed_costs(
    incentive, expected,
):
    """Alternative incentive rows are selected, not summed or fixed to one case."""
    ledger = _vehicle_ledger(
        "vehicle_charging", "electric", [-25, 0, 75]
    )

    adders = vehicle_annual_adders_from_ledger(
        ledger,
        county_slug="Alameda",
        incentive_scenario=incentive,
    )

    assert adders.ev_operating_usd_per_year == expected
    assert adders.ice_operating_usd_per_year == 0


@pytest.mark.parametrize(
    "problem,message",
    [
        ("missing_column", "missing columns"),
        ("missing_county", "no rows for county 'los-angeles'"),
        ("missing_incentive", "incentive 'missing'"),
        ("duplicate", "duplicate rows"),
        ("wrong_category", "must have category 'electric'"),
        ("text_cost", "must be numeric"),
        ("infinite_cost", "must be finite"),
    ],
)
def test_projection_rejects_missing_or_invalid_selected_data(problem, message):
    ledger = _vehicle_ledger("vehicle_charging", "electric", [10, 20, 30])
    county = "alameda"
    incentive = "full_incentives"
    if problem == "missing_column":
        ledger = ledger.drop(columns="annual_operating_cost")
    elif problem == "missing_county":
        county = "los-angeles"
    elif problem == "missing_incentive":
        incentive = "missing"
    elif problem == "duplicate":
        ledger = pd.concat([ledger, ledger.iloc[[0]]], ignore_index=True)
    elif problem == "wrong_category":
        ledger.loc[0, "appliance_category"] = "gas"
    elif problem == "text_cost":
        ledger["annual_operating_cost"] = ledger["annual_operating_cost"].astype(object)
        ledger.loc[0, "annual_operating_cost"] = "unknown"
    elif problem == "infinite_cost":
        ledger["annual_operating_cost"] = ledger["annual_operating_cost"].astype(float)
        ledger.loc[0, "annual_operating_cost"] = float("inf")

    with pytest.raises(VehicleLedgerValidationError, match=message):
        vehicle_annual_adders_from_ledger(
            ledger,
            county_slug=county,
            incentive_scenario=incentive,
        )


def test_step15_selects_matching_vehicle_cost_for_each_payback_case(monkeypatch):
    """Step 15 savings and payback use the matching alternative evaluation."""
    baseline = _vehicle_ledger("vehicle_fuel", "gas", [300, 200, 100])
    scenario = _vehicle_ledger("vehicle_charging", "electric", [30, 20, 10])

    def load_capital_costs(_base_dir, scenario_name, _housing_type):
        return baseline if scenario_name == "baseline_ice_car" else scenario

    monkeypatch.setattr(step15, "load_capital_costs", load_capital_costs)
    monkeypatch.setattr(
        step15,
        "calculate_annual_savings",
        lambda *_args: (1000, 700, 600, 300, 400),
    )
    monkeypatch.setattr(
        step15,
        "summarize_incremental_capex_against_baseline",
        lambda *_args: pd.DataFrame([{"validated": True}]),
    )
    monkeypatch.setattr(
        step15,
        "load_pv_net_adders",
        lambda *_args: pd.DataFrame(),
    )
    monkeypatch.setattr(
        step15,
        "_capital_summary_details",
        lambda *_args: {
            "net_outlay_full": 5000,
            "net_outlay_full_with_pv": 6700,
            "net_outlay_half": 9000,
            "net_outlay_half_with_pv": 11600,
            "net_outlay_none": 12000,
            "net_outlay_none_with_pv": 14700,
        },
    )
    monkeypatch.setattr(step15, "_should_log_diagnostic", lambda *_args: False)
    monkeypatch.setattr(step15, "log", lambda **_kwargs: None)

    result = step15.calculate_payback_periods(
        "unused",
        "full_electric_ev",
        "single-family-detached",
        ["Alameda County"],
    ).set_index("incentive_scenario")

    assert result.loc["full_incentives", "baseline_annual_cost"] == 1300
    assert result.loc["half_incentives", "baseline_annual_cost"] == 1200
    assert result.loc["no_incentives", "baseline_annual_cost"] == 1100
    assert result["scenario_solar_annual_cost"].tolist() == [630, 620, 610]
    assert result["annual_savings_used"].tolist() == [670, 580, 490]
    assert result["payback_period_years"].tolist() == [10, 20, 30]


@pytest.mark.parametrize(
    "scenario,baseline",
    [
        ("full_electric_ev_coopt", "baseline_ice_car_coopt"),
        ("full_electric_ev", "baseline_ice_car"),
        ("baseline_ev_car", "baseline_ice_car"),
        ("heat_pump", "baseline"),
    ],
)
def test_step15_bill_savings_use_the_declared_household_baseline(
    monkeypatch, scenario, baseline,
):
    bills = {(baseline, False): 1000, (scenario, False): 700, (scenario, True): 600}

    def load_bill(_base_dir, _county, scenario_name, _housing, with_solar=False):
        return bills[(scenario_name, with_solar)]

    monkeypatch.setattr(step15, "load_annual_costs", load_bill)

    assert step15.calculate_annual_savings(
        "unused", "Alameda County", scenario, "single-family-detached"
    ) == (1000, 700, 600, 300, 400)


@pytest.mark.parametrize("include_plain_baseline", [False, True])
def test_step15_matched_payback_reads_the_same_household_for_bills_and_vehicles(
    tmp_path, monkeypatch, include_plain_baseline,
):
    """Real saved-file lookups must ignore an unrelated baseline, even if present."""
    scenario = "full_electric_ev_coopt"
    baseline = "baseline_ice_car_coopt"
    housing = "single-family-detached"
    cap_dir = tmp_path / "capital_costs"
    cap_dir.mkdir()

    def write_ledger(name, vehicle_type, category, costs):
        ledger = _vehicle_ledger(vehicle_type, category, costs)
        ledger["county"] = "Alameda County"
        ledger["base_cost"] = ledger["net_cost"] = 6000 if category == "electric" else 1000
        ledger.to_csv(
            cap_dir / f"capital_costs_{name}_{housing.replace('-', '_')}.csv",
            index=False,
        )

    def write_bill(name, cost, with_solar=False):
        variant = "solarstorage" if with_solar else "totals"
        directory = tmp_path / name / housing / "alameda" / "results" / variant
        directory.mkdir(parents=True)
        pd.DataFrame([{
            "scenario": f"{name}.solarstorage" if with_solar else name,
            "total.PG&E.fixture+PG&E.G-1": cost,
        }]).to_csv(directory / "RESULTS_total_annual_costs_alameda_20260914_16.csv", index=False)

    write_ledger(baseline, "vehicle_fuel", "gas", [300, 200, 100])
    write_ledger(scenario, "vehicle_charging", "electric", [30, 20, 10])
    write_bill(baseline, 1000)
    write_bill(scenario, 700)
    write_bill(scenario, 600, with_solar=True)
    if include_plain_baseline:
        write_ledger("baseline", "vehicle_fuel", "gas", [9000, 9000, 9000])
        write_bill("baseline", 10000)

    summary = pd.DataFrame([{
        "county_slug": "alameda",
        "net_outlay_full": 5000,
        "net_outlay_half": 9000,
        "net_outlay_none": 12000,
        "net_outlay_full_with_pv": 6700,
        "net_outlay_half_with_pv": 11600,
        "net_outlay_none_with_pv": 14700,
        "pv_storage_net_full": 1700,
        "pv_storage_net_half": 2600,
        "pv_storage_net_none": 2700,
    }])
    for prefix in ("capital_costs_summary", "capital_costs_summary_with_pv"):
        summary.to_csv(
            cap_dir / f"{prefix}_{scenario}_{housing.replace('-', '_')}.csv", index=False
        )
    monkeypatch.setattr(step15, "_should_log_diagnostic", lambda _county: False)

    result = step15.calculate_payback_periods(
        str(tmp_path), scenario, housing, ["Alameda County"]
    )

    assert len(result) == 3
    assert result["incentive_scenario"].tolist() == INCENTIVES
    assert result["baseline_annual_cost"].tolist() == [1300, 1200, 1100]
    assert result["scenario_annual_cost"].tolist() == [730, 720, 710]
    assert result["scenario_solar_annual_cost"].tolist() == [630, 620, 610]
    assert result["annual_savings_scenario_only"].tolist() == [570, 480, 390]
    assert result["annual_savings_used"].tolist() == [670, 580, 490]
    assert result["payback_period_years"].tolist() == [10, 20, 30]


@pytest.mark.parametrize(
    "module_name",
    [
        "experiments.solar_size_sweep",
        "experiments.battery_size_sweep",
        "experiments.combined_sweep",
    ],
)
def test_sweep_vehicle_validation_errors_reach_callers(
    monkeypatch, module_name,
):
    """Sweep accounting must not replace an invalid vehicle ledger with zero."""
    monkeypatch.setitem(sys.modules, "step9_my_own_solar_storage", ModuleType("diy"))
    module = importlib.import_module(module_name)
    invalid_ledger = pd.DataFrame([{"county_slug": "alameda"}])

    with pytest.raises(VehicleLedgerValidationError, match="missing columns"):
        module._eac_baseline_components(
            invalid_ledger,
            "full_electric_ev",
            "alameda",
        )
