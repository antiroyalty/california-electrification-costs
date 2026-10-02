"""Small independently calculated examples for the pilot cost breakdown."""
import pandas as pd
import pytest

from scripts.analyze_federal_credit_pilot import (
    annual_factor, fixed_battery_lower_bound, household_components,
)


@pytest.fixture
def electric_household():
    # One-year equipment: $1 at purchase is $1.07 of end-year expense.
    ledger = pd.DataFrame([
        dict(county_slug="alameda", scenario="full_electric_ev_coopt",
             incentive_scenario="full_incentives", appliance_category="electric",
             appliance_type=kind, base_cost=float(cost), lifetime_years=1,
             annual_maintenance_cost=100, annual_insurance_cost=200,
             annual_operating_cost=300)
        for kind, cost in [("heating", 1000), ("hot_water", 2000),
                           ("cooking", 3000), ("vehicle_charging", 4000),
                           ("misc", 0), ("appliances", 0)]
    ])
    row = dict(case="electric_optimized", county_slug="alameda",
               scenario="full_electric_ev_coopt", vehicle_om=300,
               capex_gas=0, capex_electric=10700, capex_pv=80, capex_storage=20,
               annual_bill_electric=500, annual_bill_gas=0,
               heat_pumps_25c_usd=0, vehicle_30d_usd=0, total_eac=11600)
    return row, ledger


def test_components_reconcile_to_independent_cash_flow(electric_household):
    row, ledger = electric_household
    parts = household_components(row, ledger)
    assert parts["heating"] == pytest.approx(1070)
    assert parts["vehicle"] == pytest.approx(4280)
    assert parts["gasoline"] == 0
    assert sum(parts.values()) == pytest.approx(11600)


def test_selects_one_incentive_instead_of_summing_three(electric_household):
    row, ledger = electric_household
    three = pd.concat([ledger.assign(incentive_scenario=case) for case in
                       ["full_incentives", "half_incentives", "no_incentives"]])
    assert household_components(row, three) == household_components(row, ledger)


def test_initial_credit_is_not_repeated_over_appliance_life(electric_household):
    row, ledger = electric_household
    annuity = sum(1.07 ** -year for year in range(1, 26))
    reduction = (7500 + 2000 / 1.07) / annuity
    row.update(heat_pumps_25c_usd=2000, vehicle_30d_usd=7500,
               capex_electric=10700-reduction, total_eac=11600-reduction)
    parts = household_components(row, ledger)
    assert parts["heat_pump_credit"] + parts["ev_credit"] == pytest.approx(-803.972369287)
    assert sum(parts.values()) == pytest.approx(11600-reduction)


def test_gasoline_is_separate_from_maintenance_and_insurance(electric_household):
    row, ledger = electric_household
    ledger["scenario"] = "baseline_ice_car_coopt"
    ledger["appliance_category"] = "gas"
    ledger.loc[ledger.appliance_type == "vehicle_charging", "appliance_type"] = "vehicle_fuel"
    ledger["annual_fuel_cost"] = 600
    ledger["annual_operating_cost"] = 900
    row.update(case="gas_optimized", scenario="baseline_ice_car_coopt",
               vehicle_om=900, capex_gas=10700, capex_electric=0, total_eac=12200)
    parts = household_components(row, ledger)
    assert parts["gasoline"] == 600
    assert parts["maintenance"] == 100
    assert sum(parts.values()) == pytest.approx(12200)


@pytest.mark.parametrize("fault", ["duplicate", "missing_vehicle", "missing_heating"])
def test_incomplete_or_duplicate_ledger_fails(electric_household, fault):
    row, ledger = electric_household
    if fault == "duplicate":
        ledger = pd.concat([ledger, ledger.iloc[:1]])
    else:
        kind = "vehicle_charging" if fault == "missing_vehicle" else "heating"
        ledger = ledger[ledger.appliance_type != kind]
    with pytest.raises(ValueError, match="exactly one"):
        household_components(row, ledger)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -1])
def test_bad_equipment_cost_fails(electric_household, value):
    row, ledger = electric_household
    ledger.loc[0, "base_cost"] = value
    with pytest.raises(ValueError, match="gross equipment"):
        household_components(row, ledger)


@pytest.mark.parametrize("field", ["total_eac", "vehicle_om", "capex_electric"])
def test_unexplained_report_difference_fails(electric_household, field):
    row, ledger = electric_household
    row[field] += 1
    with pytest.raises(ValueError, match="reconcile"):
        household_components(row, ledger)


def test_missing_cost_column_fails(electric_household):
    row, ledger = electric_household
    with pytest.raises(KeyError, match="base_cost"):
        household_components(row, ledger.drop(columns="base_cost"))


@pytest.mark.parametrize("years", [0, -1, 12.5, float("nan")])
def test_invalid_service_life_fails(years):
    with pytest.raises(ValueError):
        annual_factor(years)


def test_annual_factor_with_zero_discount():
    assert annual_factor(25, rate=0) == .04
    assert 7500 * annual_factor(25) == pytest.approx(643.58, abs=.005)


def test_relaxed_certificate_bounds_cost_and_restores_solver():
    from evaluations.federal_credits import FederalCreditCase, PVStorageCreditPolicy
    from pipeline.solver import SolverOptions, SolverRun
    from pipeline.steps.step9b_cooptimize_core import CooptInputs, _solve_lp

    original = SolverRun.solve_round
    inputs = CooptInputs([2., 2.], [1., 0.], [.1, .4], [.05, .1])
    bound = fixed_battery_lower_bound(inputs)
    assert SolverRun.solve_round is original
    result = _solve_lp(inputs, fixed_batt_kwh=3, c_pv_kw=3300, c_batt_kwh=1460.64,
                       federal_credit_policy=PVStorageCreditPolicy(FederalCreditCase.PV_STORAGE, 1, 1),
                       solver_options=SolverOptions(annual_cost_gap_usd=.001))
    assert bound.lower_bound_usd <= result.total_cost + 1e-6


def test_invalid_bound_run_does_not_leave_solver_hook_installed():
    from pipeline.solver import SolverRun
    from pipeline.steps.step9b_cooptimize_core import CooptInputs

    original = SolverRun.solve_round
    with pytest.raises(ValueError):
        fixed_battery_lower_bound(CooptInputs([1.], [1.], [.1], [.1]), battery_usd_per_kwh=-1)
    assert SolverRun.solve_round is original
