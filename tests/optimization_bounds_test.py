"""Search bounds preserve independently evaluated feasible household choices."""

from math import sqrt

import pulp
import pytest

from evaluations.federal_credits import FederalCreditCase, PVStorageCreditPolicy
from pipeline.optimization_bounds import (
    maximum_meter_export_kwh, pv_only_nbt_cost, tighten_nbt_battery_bound,
)
from pipeline.solver import CostCertificate, SolverOptions, SolverRun
from pipeline.steps.step9b_cooptimize_core import CooptInputs, _solve_lp
from tariffs import NBTAnnualTerms, Utility


def _terms():
    return NBTAnnualTerms(
        billing_year=2026, billing_months=(1, 1),
        eligible_rates_usd_per_kwh=((.38,), (.38,)),
        base_export_rates_usd_per_kwh=((.04,), (.04,)),
        nbc_rate_usd_per_kwh=.02, fixed_charges_usd=((1, 10.0),), utility=Utility.SCE,
    )


def test_solar_only_upper_cost_uses_weighted_export_cap_and_actual_credit_pools():
    # Four daytime PV kWh serve one kWh of load. Curtail one of the three
    # surplus kWh, so exports equal the two weighted nighttime import kWh.
    cost = pv_only_nbt_cost(
        pv_kw=2, pv_gen_per_kw=[2, 0], load_kwh=[1, 1], weights=[1, 2],
        terms=_terms(), pv_annual_cost_per_kw=10,
    )
    assert cost == pytest.approx(20 + 10 + .38 * 2 - .04 * 2 + .02 * 2)


@pytest.mark.parametrize("pv", [0, 1])
def test_solar_only_upper_cost_handles_no_surplus_without_division(pv):
    cost = pv_only_nbt_cost(
        pv_kw=pv, pv_gen_per_kw=[1, 0], load_kwh=[1, 1], weights=[1, 1],
        terms=_terms(), pv_annual_cost_per_kw=10,
    )
    assert cost == pytest.approx(10 * pv + 10 + .4 * (2 - pv))


@pytest.mark.parametrize("override", [
    {"pv_kw": float("nan")}, {"load_kwh": [1, float("inf")]},
    {"pv_gen_per_kw": [1]}, {"weights": [1]}, {"weights": [1, 0]},
])
def test_upper_cost_rejects_invalid_inputs(override):
    inputs = dict(pv_kw=1, pv_gen_per_kw=[1, 0], load_kwh=[1, 1], weights=[1, 1],
                  terms=_terms(), pv_annual_cost_per_kw=10)
    with pytest.raises(ValueError):
        pv_only_nbt_cost(**(inputs | override))


def test_capacity_ceiling_uses_the_proof_bound_not_the_candidate(monkeypatch):
    problem = pulp.LpProblem("capacity_bound", pulp.LpMinimize)
    pv = pulp.LpVariable("PV", 0, 0)
    battery = pulp.LpVariable("battery", 0, 40)
    eligible = pulp.LpVariable("eligible", cat=pulp.LpBinary)
    problem += 10 * pv + 10 * battery
    certificates = iter([CostCertificate(10.8, 10.8, "optimal"),
                         CostCertificate(-10, -30, "time_limit")])
    run = SolverRun(SolverOptions())
    monkeypatch.setattr(run, "solve_auxiliary", lambda *args, **kwargs: next(certificates))
    bound = tighten_nbt_battery_bound(
        problem, solver_run=run, pv_size=pv, battery_size=battery,
        credit_eligible=eligible, pv_gen_per_kw=[1, 0], load_kwh=[1, 1],
        weights=[1, 1], terms=_terms(), pv_annual_cost_per_kw=10,
        battery_annual_cost_per_kwh=10, minimum_credited_kwh=3,
    )
    # Negating the -$30 bound permits 3 kWh; using the -$10 candidate would
    # incorrectly restrict the search to 1 kWh.
    assert bound.maximum_kwh == pytest.approx(3.000001)
    assert "feasible_household_cost_ceiling" not in problem.constraints


@pytest.mark.parametrize("solar,load,battery", [(0, .5, 2), (3, .5, 2), (0, 2, 1), (3, 1, 0)])
def test_export_bound_accounts_for_usable_energy_losses_and_household_load(solar, load, battery):
    bound = maximum_meter_export_kwh(
        pv_available_kwh=solar, load_kwh=load, battery_kwh=battery,
        usable_soc_fraction=.7, discharge_efficiency=sqrt(.96),
    )
    # Emptying the usable SOC range gives 0.7 B sqrt(RTE) AC kWh.
    assert bound == pytest.approx(max(0, solar + .7 * battery * sqrt(.96) - load))


def _storage_case(required_kwh=2.5):
    terms = _terms()
    return CooptInputs(
        [0, required_kwh * .7 * sqrt(.96)], [.8 * required_kwh, 0],
        list(terms.import_rates), list(terms.export_rates), nbt_terms=terms,
    )


@pytest.mark.parametrize("backend", ["highs", "cbc"])
@pytest.mark.parametrize("capture,price,required,expected", [
    (.5, 100, 2.5, 2.5), (1, 100, 2.5, 3), (1, 100, 4, 4), (1, 10000, 2.5, 0),
])
def test_bounded_sizing_matches_fixed_choices_including_credit_threshold(
    backend, capture, price, required, expected,
):
    kwargs = dict(
        fixed_pv_kw=1, c_pv_kw=0, c_batt_kwh=price, weights=[365, 365],
        federal_credit_policy=PVStorageCreditPolicy(FederalCreditCase.PV_STORAGE, 0, capture),
        solver_options=SolverOptions(backend=backend, annual_cost_gap_usd=1e-6),
    )
    free = _solve_lp(_storage_case(required), max_battery_kwh=40, **kwargs)
    # Fixed capacities bypass bound tightening. Include both sides of eligibility.
    reference = kwargs | {"solver_options": SolverOptions(annual_cost_gap_usd=1e-6)}
    choices = [_solve_lp(_storage_case(required), fixed_batt_kwh=size, **reference)
               for size in (0, 2.5, 2.999, 3, 3.001, 4, 5)]
    assert free.batt_kwh == pytest.approx(expected, abs=1e-6)
    assert free.total_cost == pytest.approx(min(c.total_cost for c in choices), abs=1e-5)
    assert free.solver.auxiliary_solves
    assert all(not c.solver.auxiliary_solves for c in choices)
    if expected:
        # A no-battery objective is NOT a lower bound on the optimized household.
        assert free.solver.auxiliary_solves[0].certificate.lower_bound_usd > free.total_cost
    else:
        assert len(free.solver.auxiliary_solves) == 3


@pytest.mark.parametrize("grid_charging,exports", [(False, False), (True, False), (True, True)])
def test_bound_preserves_storage_choices_with_each_dispatch_permission(grid_charging, exports):
    kwargs = dict(
        fixed_pv_kw=1, c_pv_kw=0, c_batt_kwh=100, c_batt_kw=25, weights=[365, 365],
        allow_grid_charging=grid_charging, allow_batt_export=exports,
        federal_credit_policy=PVStorageCreditPolicy(FederalCreditCase.PV_STORAGE, 0, 1),
        solver_options=SolverOptions(annual_cost_gap_usd=1e-6),
    )
    free = _solve_lp(_storage_case(), **kwargs)
    fixed = _solve_lp(_storage_case(), fixed_batt_kwh=3, **kwargs)
    assert free.batt_kwh == pytest.approx(3)
    assert free.total_cost == pytest.approx(fixed.total_cost)


@pytest.mark.parametrize("failed_purpose", [
    "solar_only_meter_relaxation", "negative_gross_battery_capacity_annual_cost",
    "negative_uncredited_battery_capacity_annual_cost",
])
def test_failed_preprocessing_restores_the_model_and_accepts_no_result(monkeypatch, failed_purpose):
    original = SolverRun.solve_auxiliary
    captured = {}

    def fail(self, problem, *, purpose):
        captured.setdefault("objective", problem.objective)
        captured["problem"] = problem
        if purpose == failed_purpose:
            raise RuntimeError("deliberate auxiliary failure")
        return original(self, problem, purpose=purpose)

    monkeypatch.setattr(SolverRun, "solve_auxiliary", fail)
    with pytest.raises(RuntimeError, match="deliberate auxiliary failure"):
        _solve_lp(_storage_case(), federal_credit_policy=PVStorageCreditPolicy(
            FederalCreditCase.PV_STORAGE, 0, 1,
        ))
    variables = captured["problem"].variablesDict()
    assert (variables["B_E_kWh"].lowBound, variables["B_E_kWh"].upBound) == (0, 40)
    eligible = variables["storage_credit_eligible"]
    assert eligible.cat == pulp.LpInteger and (eligible.lowBound, eligible.upBound) == (0, 1)
    assert captured["problem"].objective is captured["objective"]


@pytest.mark.parametrize("capture,ceiling,capacity_price", [(0, 40, 100), (1, 2.9, 100), (1, 40, 0)])
def test_cases_without_a_priced_eligibility_decision_keep_the_original_solve_sequence(
    capture, ceiling, capacity_price,
):
    result = _solve_lp(
        _storage_case(), c_batt_kwh=capacity_price, c_batt_kw=25, max_battery_kwh=ceiling,
        federal_credit_policy=PVStorageCreditPolicy(FederalCreditCase.PV_STORAGE, 0, capture),
    )
    assert not result.solver.auxiliary_solves
