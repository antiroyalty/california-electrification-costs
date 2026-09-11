"""Independent dollar examples and boundaries for the annual research assumption."""

import math

import pytest

from tariffs.accounting import settle_annual_credits


@pytest.mark.parametrize(
    "charges,credits,expected_due,expected_applied,expected_unused",
    [
        ((60,), (35,), 54, 35, 0),          # SCE Example 5: one eligible pool.
        ((20, 40), (30, 5), 64, 25, 10),   # PG&E / SDG&E: restricted components.
        ((20, 40), (0, 0), 89, 0, 0),
        ((20, 40), (20, 40), 29, 60, 0),
        ((20, 40), (200, 400), 29, 60, 540),
        ((0, 0), (20, 40), 29, 0, 60),
        ((0, 40), (20, 0), 69, 0, 20),
    ],
)
def test_credits_pay_only_their_eligible_charges(
    charges, credits, expected_due, expected_applied, expected_unused,
):
    result = settle_annual_credits(charges, credits, 4, 25)
    assert result.amount_due_usd == expected_due
    assert result.applied_credit_usd == expected_applied
    assert result.unused_credit_usd == expected_unused
    assert result.applied_credit_usd + result.unused_credit_usd == result.earned_credit_usd
    assert result.gross_charge_usd - result.applied_credit_usd == result.amount_due_usd


@pytest.mark.parametrize("delta", [-0.01, 0.0, 0.01])
def test_saturation_boundary_preserves_cents_without_rounding(delta):
    result = settle_annual_credits((10,), (10 + delta,), 1, 2)
    assert result.amount_due_usd == pytest.approx(3 + max(-delta, 0))
    assert result.unused_credit_usd == pytest.approx(max(delta, 0))


@pytest.mark.parametrize("field", ["eligible_charge_usd", "earned_base_credit_usd",
                                   "non_bypassable_charge_usd", "fixed_charge_usd"])
@pytest.mark.parametrize("invalid", [-1, math.nan, math.inf])
def test_invalid_dollars_cannot_produce_a_research_cost(field, invalid):
    values = dict(eligible_charge_usd=(20, 40), earned_base_credit_usd=(30, 5),
                  non_bypassable_charge_usd=4, fixed_charge_usd=25)
    values[field] = (invalid, 1) if field in ("eligible_charge_usd", "earned_base_credit_usd") else invalid
    with pytest.raises(ValueError, match="finite and non-negative"):
        settle_annual_credits(**values)


@pytest.mark.parametrize("charges,credits", [((), ()), ((10,), (10, 20))])
def test_mismatched_or_empty_pools_fail(charges, credits):
    with pytest.raises(ValueError, match="same nonempty pools"):
        settle_annual_credits(charges, credits, 0, 0)
