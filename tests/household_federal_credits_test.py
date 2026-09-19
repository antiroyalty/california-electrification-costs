"""Dollar examples and failure rules for the conditional household credit model."""

from dataclasses import FrozenInstanceError

import pytest

from evaluations.federal_credits import (
    FederalCreditCase,
    evaluate_federal_purchase_credits,
)


@pytest.fixture
def eligible_bundle():
    # All purchases meet the relevant dates and other legal requirements.
    return {
        "pv_eligible_basis_usd": 20000.0,
        "storage_eligible_basis_usd": 10000.0,
        "storage_capacity_kwh": 10.0,
        "space_heat_pump_eligible_basis_usd": 12000.0,
        "water_heat_pump_eligible_basis_usd": 4000.0,
        "eligible_vehicle_credit_usd": 7500.0,
    }


@pytest.mark.parametrize("case,expected", [
    (FederalCreditCase.NONE, (0.0, 0.0, 0.0, 0.0, 0.0)),
    (FederalCreditCase.PV_STORAGE, (6000.0, 3000.0, 0.0, 0.0, 9000.0)),
    (FederalCreditCase.ALL, (6000.0, 3000.0, 2000.0, 7500.0, 18500.0)),
])
def test_worked_household_comparison(eligible_bundle, case, expected):
    credits = evaluate_federal_purchase_credits(case=case, **eligible_bundle)
    assert (
        credits.pv_25d_usd, credits.storage_25d_usd,
        credits.heat_pumps_25c_usd, credits.vehicle_30d_usd, credits.total_usd,
    ) == pytest.approx(expected)
    assert credits.total_usd == pytest.approx(
        credits.pv_25d_usd + credits.storage_25d_usd
        + credits.heat_pumps_25c_usd + credits.vehicle_30d_usd
    )


@pytest.mark.parametrize("space,water,expected", [
    (0.0, 0.0, 0.0),
    (1000.0, 0.0, 300.0),
    (0.0, 4000.0, 1200.0),
    (3000.0, 3000.0, 1800.0),
    (4000.0, 4000.0, 2000.0),  # Independent caps would wrongly give $2,400.
    (12000.0, 4000.0, 2000.0),  # Independent caps would wrongly give $3,200.
    (4000.0, 12000.0, 2000.0),
])
def test_heat_pumps_share_one_annual_cap(eligible_bundle, space, water, expected):
    eligible_bundle.update(
        space_heat_pump_eligible_basis_usd=space,
        water_heat_pump_eligible_basis_usd=water,
    )
    credits = evaluate_federal_purchase_credits(case=FederalCreditCase.ALL, **eligible_bundle)
    assert credits.heat_pumps_25c_usd == pytest.approx(expected)


@pytest.mark.parametrize("capacity,expected", [(2.999, 0.0), (3.0, 900.0), (3.001, 900.0)])
@pytest.mark.parametrize("case", [FederalCreditCase.PV_STORAGE, FederalCreditCase.ALL])
def test_battery_capacity_boundary(eligible_bundle, capacity, expected, case):
    eligible_bundle.update(storage_capacity_kwh=capacity, storage_eligible_basis_usd=3000.0)
    credits = evaluate_federal_purchase_credits(case=case, **eligible_bundle)
    assert credits.storage_25d_usd == pytest.approx(expected)
    assert credits.pv_25d_usd == pytest.approx(6000.0)


@pytest.mark.parametrize("amount", [0.0, 3750.0, 7500.0])
def test_vehicle_credit_requires_an_explicit_eligible_amount(eligible_bundle, amount):
    eligible_bundle["eligible_vehicle_credit_usd"] = amount
    credits = evaluate_federal_purchase_credits(case=FederalCreditCase.ALL, **eligible_bundle)
    assert credits.vehicle_30d_usd == amount


@pytest.mark.parametrize("case", list(FederalCreditCase))
def test_explicit_zero_bundle_is_valid(eligible_bundle, case):
    inputs = {name: 0.0 for name in eligible_bundle}
    assert evaluate_federal_purchase_credits(case=case, **inputs).total_usd == 0.0


def test_ineligible_battery_can_have_capacity_but_no_eligible_basis(eligible_bundle):
    eligible_bundle["storage_eligible_basis_usd"] = 0.0
    credits = evaluate_federal_purchase_credits(case=FederalCreditCase.ALL, **eligible_bundle)
    assert credits.storage_25d_usd == 0.0


@pytest.mark.parametrize("bad_value", [-1.0, float("nan"), float("inf"), None, True, "1000"])
def test_invalid_inputs_fail_even_when_credits_are_excluded(eligible_bundle, bad_value):
    for field in eligible_bundle:
        inputs = {**eligible_bundle, field: bad_value}
        with pytest.raises(ValueError, match=field):
            evaluate_federal_purchase_credits(case=FederalCreditCase.NONE, **inputs)


@pytest.mark.parametrize("case", list(FederalCreditCase))
def test_positive_battery_basis_requires_positive_capacity(eligible_bundle, case):
    eligible_bundle["storage_capacity_kwh"] = 0.0
    with pytest.raises(ValueError, match="requires positive storage_capacity_kwh"):
        evaluate_federal_purchase_credits(case=case, **eligible_bundle)


@pytest.mark.parametrize("case", list(FederalCreditCase))
def test_vehicle_amount_cannot_exceed_legal_maximum(eligible_bundle, case):
    eligible_bundle["eligible_vehicle_credit_usd"] = 7500.01
    with pytest.raises(ValueError, match="per-vehicle maximum"):
        evaluate_federal_purchase_credits(case=case, **eligible_bundle)


@pytest.mark.parametrize("case", [None, "all_modeled_federal_credits", "typo"])
def test_case_must_be_explicit_and_typed(eligible_bundle, case):
    with pytest.raises(ValueError, match="FederalCreditCase"):
        evaluate_federal_purchase_credits(case=case, **eligible_bundle)


def test_missing_cost_is_not_treated_as_zero(eligible_bundle):
    del eligible_bundle["pv_eligible_basis_usd"]
    with pytest.raises(TypeError, match="pv_eligible_basis_usd"):
        evaluate_federal_purchase_credits(case=FederalCreditCase.ALL, **eligible_bundle)


def test_evaluation_does_not_mutate_inputs_and_result_is_immutable(eligible_bundle):
    before = eligible_bundle.copy()
    credits = evaluate_federal_purchase_credits(case=FederalCreditCase.ALL, **eligible_bundle)
    assert eligible_bundle == before
    with pytest.raises(FrozenInstanceError):
        credits.heat_pumps_25c_usd = 4000.0
