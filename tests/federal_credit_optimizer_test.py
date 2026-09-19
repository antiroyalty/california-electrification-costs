"""Credit eligibility, sizing decisions, and independent capital reconciliation."""

from math import fsum, sqrt

import pytest

from evaluations.eac import compute_eac_from_inputs
from evaluations.federal_credits import FederalCreditCase, PVStorageCreditPolicy
from pipeline.solver import SolverOptions, SolverRun
from pipeline.steps.step9b_cooptimize_core import CooptInputs, _solve_lp
from tariffs import NBTAnnualTerms, NEM2OptimizationTerms, Utility


PRECISE = SolverOptions(annual_cost_gap_usd=1e-6)


def _policy(case=FederalCreditCase.PV_STORAGE, time=0, capture=1):
    return PVStorageCreditPolicy(case, receipt_year=time, realization_fraction=capture)


def _fixed_inputs(tariff):
    if tariff == "nbt":
        terms = NBTAnnualTerms(
            billing_year=2026, billing_months=(1, 1),
            eligible_rates_usd_per_kwh=((.38,), (.38,)),
            base_export_rates_usd_per_kwh=((.04,), (.04,)),
            nbc_rate_usd_per_kwh=.02, fixed_charges_usd=((1, 10.0),),
            utility=Utility.SCE,
        )
        return CooptInputs([1, 1], [3, 0], list(terms.import_rates),
                           list(terms.export_rates), nbt_terms=terms)
    if tariff == "nem2":
        terms = NEM2OptimizationTerms(
            offsettable_rates_usd_per_kwh=(.4, .4), billing_months=(1, 1),
            interval_nbc_rate_usd_per_kwh=.02, monthly_net_consumption_rate_usd_per_kwh=.01,
            nsc_rate_usd_per_kwh=.03, nsc_rate_source_id="test_only",
        )
        return CooptInputs([1, 1], [3, 0], [.4, .4], [.4, .4], nem2_terms=terms)
    return CooptInputs([1, 1], [3, 0], [.4, .4], [.04, .04])


@pytest.mark.parametrize("tariff", ["linear", "nbt", "nem2"])
@pytest.mark.parametrize("capacity", [0.0, 2.999, 3.0, 3.001])
@pytest.mark.parametrize("receipt_year,capture", [(0, 1), (1, 1), (1, .5)])
def test_fixed_sizes_match_cash_flows_and_reporting(tariff, capacity, receipt_year, capture):
    result = _solve_lp(
        _fixed_inputs(tariff), fixed_pv_kw=1, fixed_batt_kwh=capacity,
        c_pv_kw=3300, c_batt_kwh=1000, c_batt_kw=25, weights=[365, 365],
        federal_credit_policy=_policy(time=receipt_year, capture=capture), solver_options=PRECISE,
    )
    receipts = result.federal_credit_receipts
    storage_cost = result.batt_kwh * 1000 + result.batt_kw * 25
    expected_pv_credit = 990 * capture
    assert receipts.amounts.pv_25d_usd == pytest.approx(expected_pv_credit)
    expected_storage_credit = .30 * storage_cost * capture if capacity >= 3 else 0
    assert receipts.amounts.storage_25d_usd == pytest.approx(expected_storage_credit)
    assert receipts.amounts.heat_pumps_25c_usd == receipts.amounts.vehicle_30d_usd == 0
    schedule = [
        (0, 3300 + storage_cost), (15, storage_cost), (25, -storage_cost / 3),
        (receipt_year, -expected_pv_credit - expected_storage_credit),
    ]
    expected = fsum(cost / 1.07**year for year, cost in schedule) / fsum(
        1.07**-year for year in range(1, 26)
    )
    assert result.capex_annual == pytest.approx(expected)
    reported = compute_eac_from_inputs(
        None, {"pv_capex": 3300, "storage_capex": storage_cost},
        federal_credit_receipts=receipts,
        annual_bill_electric=result.import_cost - result.export_credit,
    )
    assert reported.total() == pytest.approx(result.total_cost)
    assert result.solver.lower_bound_usd <= result.total_cost + 1e-6
    assert result.solver.optimality_gap_usd <= 2e-6


def _storage_inputs():
    # At 70% usable SOC and sqrt(96%) discharge efficiency, 2.5 kWh
    # exactly covers this nightly load. Additional capacity has no bill benefit.
    return CooptInputs([0, 2.5 * .7 * sqrt(.96)], [2, 0], [.4, .4], [0, 0])


@pytest.mark.parametrize("capture,ceiling,expected_kwh", [
    (0, 5, 2.5), (.5, 5, 2.5), (1, 5, 3.0), (1, 2.9, 2.5), (1, 3, 3.0),
])
def test_sizing_compares_smaller_uncredited_and_eligible_batteries(capture, ceiling, expected_kwh):
    result = _solve_lp(
        _storage_inputs(), fixed_pv_kw=1, weights=[365, 365],
        c_pv_kw=0, c_batt_kwh=100, max_battery_kwh=ceiling,
        federal_credit_policy=_policy(capture=capture), solver_options=PRECISE,
    )
    assert result.batt_kwh == pytest.approx(expected_kwh)
    expected_credit = 90 if expected_kwh == 3 else 0
    assert result.federal_credit_receipts.amounts.storage_25d_usd == pytest.approx(expected_credit)


def test_free_sizing_is_no_worse_than_each_fixed_candidate():
    kwargs = dict(
        fixed_pv_kw=1, weights=[365, 365], c_pv_kw=0, c_batt_kwh=100,
        federal_credit_policy=_policy(), solver_options=PRECISE,
    )
    free = _solve_lp(_storage_inputs(), max_battery_kwh=5, **kwargs)
    fixed = [_solve_lp(_storage_inputs(), fixed_batt_kwh=size, **kwargs)
             for size in (0, 1, 2.5, 2.999, 3, 3.5, 5)]
    assert free.total_cost == pytest.approx(min(result.total_cost for result in fixed))


def test_solar_credit_changes_the_purchase_decision():
    inputs = CooptInputs([1, 1], [1, 0], [.4, .4], [0, 0])
    kwargs = dict(c_pv_kw=2000, c_batt_kwh=1000, max_battery_kwh=0,
                  weights=[365, 365], solver_options=PRECISE)
    no_credit = _solve_lp(inputs, federal_credit_policy=_policy(FederalCreditCase.NONE), **kwargs)
    credited = _solve_lp(inputs, federal_credit_policy=_policy(), **kwargs)
    assert no_credit.pv_kw == 0
    assert credited.pv_kw == pytest.approx(1)
    assert credited.total_cost < no_credit.total_cost


def test_expensive_storage_can_still_be_declined():
    result = _solve_lp(
        _storage_inputs(), fixed_pv_kw=1, c_pv_kw=0, c_batt_kwh=10000,
        weights=[365, 365], federal_credit_policy=_policy(), solver_options=PRECISE,
    )
    assert result.batt_kwh == 0
    assert result.federal_credit_receipts.amounts.storage_25d_usd == 0


def test_all_credits_and_pv_storage_case_have_the_same_sizing_objective():
    kwargs = dict(fixed_pv_kw=1, c_pv_kw=3300, c_batt_kwh=100,
                  weights=[365, 365], solver_options=PRECISE)
    solar = _solve_lp(_storage_inputs(), federal_credit_policy=_policy(), **kwargs)
    all_credits = _solve_lp(
        _storage_inputs(), federal_credit_policy=_policy(FederalCreditCase.ALL), **kwargs,
    )
    assert all_credits.total_cost == pytest.approx(solar.total_cost)
    assert all_credits.batt_kwh == pytest.approx(solar.batt_kwh)


def test_no_credit_case_preserves_existing_gross_price_result():
    kwargs = dict(fixed_pv_kw=1, c_pv_kw=3300, c_batt_kwh=100,
                  weights=[365, 365], solver_options=PRECISE)
    legacy = _solve_lp(_storage_inputs(), **kwargs)
    explicit = _solve_lp(
        _storage_inputs(), federal_credit_policy=_policy(FederalCreditCase.NONE), **kwargs,
    )
    assert legacy.federal_credit_receipts is None
    assert explicit.federal_credit_receipts.amounts.total_usd == 0
    assert explicit.total_cost == pytest.approx(legacy.total_cost)
    assert explicit.batt_kwh == pytest.approx(legacy.batt_kwh)


def test_fixed_subthreshold_capacity_does_not_gain_credit_from_solver_tolerance():
    result = _solve_lp(
        _fixed_inputs("linear"), fixed_pv_kw=1, fixed_batt_kwh=3 - 1e-8,
        c_pv_kw=3300, c_batt_kwh=1000, federal_credit_policy=_policy(),
        solver_options=PRECISE,
    )
    assert result.federal_credit_receipts.amounts.storage_25d_usd == 0


@pytest.mark.parametrize("fixed,ceiling,capture,expected", [
    (3, 40, 1, 0), (2.9, 40, 1, 0), (None, 2.9, 1, 0),
    (None, 5, 0, 0), (None, 5, 1, 1),
])
def test_eligibility_adds_only_one_binary_when_needed(monkeypatch, fixed, ceiling, capture, expected):
    original = SolverRun.solve_round
    counts = []

    def inspect_model(self, problem):
        counts.append(sum(variable.isBinary() for variable in problem.variables()
                          if variable.name == "storage_credit_eligible"))
        return original(self, problem)

    monkeypatch.setattr(SolverRun, "solve_round", inspect_model)
    _solve_lp(
        _storage_inputs(), fixed_pv_kw=1, fixed_batt_kwh=fixed,
        max_battery_kwh=ceiling, c_pv_kw=0, c_batt_kwh=100,
        weights=[365, 365], federal_credit_policy=_policy(capture=capture),
        solver_options=PRECISE,
    )
    assert counts and all(count == expected for count in counts)


@pytest.mark.parametrize("field,value", [
    ("case", "invalid"), ("receipt_year", -1), ("receipt_year", float("nan")),
    ("realization_fraction", -0.1), ("realization_fraction", 1.01),
    ("realization_fraction", None), ("realization_fraction", True),
])
def test_credit_policy_rejects_invalid_declarations(field, value):
    kwargs = dict(case=FederalCreditCase.PV_STORAGE, receipt_year=1, realization_fraction=1)
    kwargs[field] = value
    with pytest.raises(ValueError, match=field):
        PVStorageCreditPolicy(**kwargs)


def test_credit_receipt_must_be_within_the_study():
    with pytest.raises(ValueError, match="receipt_year"):
        _solve_lp(_storage_inputs(), federal_credit_policy=_policy(time=26))


@pytest.mark.parametrize("field", ["c_pv_kw", "c_batt_kwh", "c_batt_kw"])
@pytest.mark.parametrize("value", [-1, float("nan"), None])
def test_credit_mode_requires_valid_gross_unit_costs(field, value):
    with pytest.raises(ValueError, match=field):
        _solve_lp(_storage_inputs(), federal_credit_policy=_policy(), **{field: value})


def test_credit_mode_requires_a_finite_battery_cost_bound():
    with pytest.raises(ValueError, match="finite battery capacity bound"):
        _solve_lp(_storage_inputs(), max_battery_kwh=float("inf"), federal_credit_policy=_policy())


@pytest.mark.parametrize("residue,accepted", [(1e-8, True), (2e-6, False)])
def test_only_solver_scale_residue_can_be_normalized_to_eligible_boundary(monkeypatch, residue, accepted):
    original = SolverRun.solve_round

    def perturb_boundary(self, problem):
        certificate = original(self, problem)
        variables = problem.variablesDict()
        assert variables["storage_credit_eligible"].value() == pytest.approx(1)
        assert variables["B_E_kWh"].value() == pytest.approx(3)
        variables["B_E_kWh"].varValue = 3 - residue
        return certificate

    monkeypatch.setattr(SolverRun, "solve_round", perturb_boundary)
    kwargs = dict(
        fixed_pv_kw=1, c_pv_kw=0, c_batt_kwh=100, weights=[365, 365],
        federal_credit_policy=_policy(), solver_options=PRECISE,
    )
    if accepted:
        result = _solve_lp(_storage_inputs(), **kwargs)
        assert result.batt_kwh == 3
        assert result.federal_credit_receipts.amounts.storage_25d_usd == 90
    else:
        with pytest.raises(RuntimeError, match="below the eligibility minimum"):
            _solve_lp(_storage_inputs(), **kwargs)


@pytest.mark.parametrize("backend", ["highs", "cbc"])
def test_free_storage_includes_power_equipment_in_the_initial_credit(backend):
    result = _solve_lp(
        _storage_inputs(), fixed_pv_kw=1, c_pv_kw=0, c_batt_kwh=100,
        c_batt_kw=25, weights=[365, 365], federal_credit_policy=_policy(),
        solver_options=SolverOptions(backend=backend, annual_cost_gap_usd=.01),
    )
    assert result.batt_kwh == pytest.approx(3)
    gross_cost = result.batt_kwh * 100 + result.batt_kw * 25
    assert result.federal_credit_receipts.amounts.storage_25d_usd == pytest.approx(.3 * gross_cost)
    report = compute_eac_from_inputs(
        None, {"pv_capex": 0, "storage_capex": gross_cost},
        federal_credit_receipts=result.federal_credit_receipts,
        annual_bill_electric=result.import_cost - result.export_credit,
    )
    assert report.total() == pytest.approx(result.total_cost)
