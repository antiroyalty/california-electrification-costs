"""Model-assumption validation and legacy solver-boundary equivalence."""

from dataclasses import FrozenInstanceError, replace

import pytest

from evaluations.federal_credits import FederalCreditCase, PVStorageCreditPolicy
from pipeline.cooptimization import CooptimizationAssumptions
from pipeline.solver import SolverOptions
from pipeline.steps.step9b_cooptimize_core import CooptInputs, _solve_lp


CBC = SolverOptions(backend="cbc", annual_cost_gap_usd=1e-6)
INPUTS = CooptInputs([0, 2], [1, 0], [.1, .5], [0, 0])


@pytest.mark.parametrize("field,value", [
    ("allow_grid_charging", 1),
    ("allow_battery_export", None),
    ("pv_capex_usd_per_kw", -1),
    ("battery_capex_usd_per_kwh", float("nan")),
    ("battery_power_capex_usd_per_kw", True),
    ("discount_rate", float("inf")),
    ("battery_degradation_usd_per_kwh", -0.01),
    ("max_battery_kwh", float("inf")),
    ("max_pv_to_annual_load_ratio", 0),
    ("pv_lifetime_years", 0),
    ("battery_lifetime_years", float("inf")),
    ("federal_credit_policy", "automatic"),
])
def test_assumptions_reject_invalid_or_ambiguous_values(field, value):
    with pytest.raises(ValueError, match=field):
        CooptimizationAssumptions(**{field: value})


def test_assumptions_are_immutable_and_sensitivity_changes_are_explicit():
    central = CooptimizationAssumptions()
    with pytest.raises(FrozenInstanceError):
        central.allow_grid_charging = True
    sensitivity = replace(central, allow_grid_charging=True)
    assert central.allow_grid_charging is False
    assert sensitivity.allow_grid_charging is True
    assert sensitivity.battery_capex_usd_per_kwh == central.battery_capex_usd_per_kwh
    assert replace(central, battery_lifetime_years=15.5).battery_lifetime_years == 15.5


@pytest.mark.parametrize("grid_charging", [False, True])
def test_explicit_assumptions_match_legacy_dispatch_and_cost(grid_charging):
    assumptions = CooptimizationAssumptions(
        allow_grid_charging=grid_charging,
        pv_capex_usd_per_kw=0,
        battery_capex_usd_per_kwh=0,
        max_battery_kwh=1,
        max_pv_to_annual_load_ratio=1,
    )
    options = dict(fixed_pv_kw=0, fixed_batt_kwh=1, solver_options=CBC)
    legacy = _solve_lp(
        INPUTS, allow_grid_charging=grid_charging, c_pv_kw=0, c_batt_kwh=0,
        max_battery_kwh=1, max_pv_to_annual_load_ratio=1, **options,
    )
    explicit = _solve_lp(INPUTS, assumptions=assumptions, **options)
    assert explicit.total_cost == pytest.approx(legacy.total_cost)
    assert explicit.flows.grid_to_batt == pytest.approx(legacy.flows.grid_to_batt)
    assert explicit.flows.batt_to_load == pytest.approx(legacy.flows.batt_to_load)


def test_explicit_federal_policy_matches_legacy_credit_and_capital_cost():
    policy = PVStorageCreditPolicy(FederalCreditCase.PV_STORAGE, 1, 1)
    assumptions = CooptimizationAssumptions(
        pv_capex_usd_per_kw=3300, battery_capex_usd_per_kwh=1000,
        max_battery_kwh=3, federal_credit_policy=policy,
    )
    options = dict(fixed_pv_kw=1, fixed_batt_kwh=3, solver_options=CBC)
    legacy = _solve_lp(
        INPUTS, c_pv_kw=3300, c_batt_kwh=1000, max_battery_kwh=3,
        federal_credit_policy=policy, **options,
    )
    explicit = _solve_lp(INPUTS, assumptions=assumptions, **options)
    assert explicit.capex_annual == pytest.approx(legacy.capex_annual)
    assert explicit.federal_credit_receipts == legacy.federal_credit_receipts


def test_explicit_assumptions_cannot_silently_override_legacy_options():
    with pytest.raises(ValueError, match="Do not combine assumptions"):
        _solve_lp(INPUTS, assumptions=CooptimizationAssumptions(), allow_grid_charging=False)
    with pytest.raises(ValueError, match="Do not combine assumptions"):
        _solve_lp(INPUTS, assumptions=CooptimizationAssumptions(), federal_credit_policy=None)
