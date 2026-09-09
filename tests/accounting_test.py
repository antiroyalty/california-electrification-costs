"""Independent answers from docs/HOUSEHOLD_COST_RECONCILIATION.md.

Prices are teaching inputs, not actual retail tariffs. Utility choices below
state the adjudicated SCE pooling rule and the retained annual conventions.
"""

import pytest

from tariffs.accounting import (
    ComponentAmounts,
    CreditBalances,
    PooledAmount,
    settle_month,
    settle_year,
)


def _amounts(utility, generation_usd, delivery_usd):
    if utility == "SCE":
        return PooledAmount(generation_usd + delivery_usd)
    if utility in ("PG&E", "SDG&E"):
        return ComponentAmounts(generation_usd, delivery_usd)
    raise ValueError(f"Unknown teaching utility: {utility}")


def _month(
    generation_credit_usd,
    delivery_credit_usd=5,
    *,
    bonus_usd=0.88,
    utility="PG&E",
    opening=None,
):
    if opening is None:
        opening = CreditBalances(_amounts(utility, 0, 0), 0)
    return settle_month(
        eligible_energy=_amounts(utility, 20, 40),
        non_bypassable_charge_usd=4,
        fixed_charge_usd=25,
        opening=opening,
        earned=CreditBalances(
            _amounts(utility, generation_credit_usd, delivery_credit_usd), bonus_usd
        ),
    )


def _close_year(months, utility):
    paid = [month.paid_eligible_energy for month in months]
    if utility == "SCE":
        prior_paid = PooledAmount(sum(amount.total_usd for amount in paid))
    else:
        prior_paid = _amounts(
            utility,
            sum(amount.generation_usd for amount in paid),
            sum(amount.delivery_usd for amount in paid),
        )
    return settle_year(
        opening=months[-1].closing,
        prior_paid_eligible_energy=prior_paid,
        surplus_adjustment=_amounts(utility, 0, 0),
        nsc_entitlement_usd=0,
        offset_prior_payments=utility in ("PG&E", "SCE"),
        carry_base_credit=utility == "PG&E",
    )


def _year(generation_credits, delivery_credit_usd=5, *, utility="PG&E", **kwargs):
    months = []
    for generation_credit_usd in generation_credits:
        month = _month(
            generation_credit_usd, delivery_credit_usd, utility=utility, **kwargs
        )
        months.append(month)
        kwargs["opening"] = month.closing
    return months, _close_year(months, utility)


def _annual_payment(months, settlement):
    return sum(month.payment_usd for month in months) + settlement.net_bill_adjustment_usd


def test_example_1_all_earned_credits_are_used():
    months, annual = _year([10] * 12)
    assert [month.payment_usd for month in months] == pytest.approx([73.12] * 12)
    assert _annual_payment(months, annual) == pytest.approx(877.44)
    assert annual.closing == CreditBalances(ComponentAmounts(0, 0), 0)
    assert sum(month.base_applied.total_usd for month in months) == 180
    assert sum(month.bonus_applied_usd for month in months) == pytest.approx(10.56)


def test_example_2_unused_credit_is_carried_separately_from_current_savings():
    months, annual = _year([20] * 11 + [30])
    assert [month.payment_usd for month in months] == pytest.approx([63.12] * 12)
    assert _annual_payment(months, annual) == pytest.approx(757.44)
    assert sum(month.earned.base.generation_usd for month in months) == 250
    assert sum(month.base_applied.generation_usd for month in months) == 240
    assert annual.closing == CreditBalances(ComponentAmounts(10, 0), 0)
    assert annual.net_bill_adjustment_usd == 0


def test_example_3_opening_balance_pays_next_year_without_double_counting():
    first_months, first_year = _year([20] * 11 + [30])
    next_months, next_year = _year([20] * 11 + [10], opening=first_year.closing)
    no_bank_months, no_bank_year = _year([20] * 11 + [10])

    assert _annual_payment(next_months, next_year) == pytest.approx(757.44)
    assert _annual_payment(no_bank_months, no_bank_year) == pytest.approx(767.44)
    assert next_months[-1].payment_usd == pytest.approx(63.12)
    assert next_year.closing == CreditBalances(ComponentAmounts(0, 0), 0)
    assert (
        _annual_payment(first_months, first_year)
        + _annual_payment(next_months, next_year)
    ) == pytest.approx(1514.88)


@pytest.mark.parametrize(
    "utility,forfeited_usd,second_year_usd,two_year_usd",
    [("PG&E", 0, 348, 696), ("SCE", 120, 468, 816), ("SDG&E", 120, 468, 816)],
)
def test_example_4_carryover_or_expiry_changes_future_payments(
    utility, forfeited_usd, second_year_usd, two_year_usd
):
    first_months, first_year = _year([25] * 12, 45, utility=utility, bonus_usd=0)
    next_months, next_year = _year(
        [15] * 12, 35, utility=utility, bonus_usd=0, opening=first_year.closing
    )
    assert _annual_payment(first_months, first_year) == 348
    assert first_year.opening.base.total_usd == 120
    assert first_year.forfeited_base.total_usd == forfeited_usd
    assert first_year.closing.base.total_usd == 120 - forfeited_usd
    assert _annual_payment(next_months, next_year) == second_year_usd
    assert 348 + second_year_usd == two_year_usd
    assert next_year.closing.base.total_usd == 0


@pytest.mark.parametrize(
    "utility,payment_usd,bank_usd", [("SCE", 54, 0), ("PG&E", 64, 10)]
)
def test_example_5_sce_bundled_credits_offset_combined_energy(
    utility, payment_usd, bank_usd
):
    # SCE Schedule NBT 3.a.i/ii and 4.b: bundled Energy Charges include both
    # components. The current production calculator incorrectly returns $64.
    month = _month(30, 5, utility=utility, bonus_usd=0)
    assert month.payment_usd == payment_usd
    assert month.closing.base.total_usd == bank_usd


@pytest.mark.parametrize("utility", ["PG&E", "SCE", "SDG&E"])
def test_example_6_bonus_pays_other_charges_and_carries_separately(utility):
    first = _month(20, 40, bonus_usd=35, utility=utility)
    annual = _close_year([first], utility)
    following = _month(20, 40, bonus_usd=0, utility=utility, opening=annual.closing)
    assert first.payment_usd == 0
    assert first.closing.bonus_usd == 6
    assert annual.closing.bonus_usd == 6
    assert first.bonus_applied_to_energy.total_usd == 0
    assert following.payment_usd == 23
    assert following.closing.bonus_usd == 0


@pytest.mark.parametrize("utility", ["SCE", "SDG&E"])
def test_example_7_surplus_adjustment_precedes_expiry_and_nsc_is_separate(utility):
    # Synthetic source-normalized dollars: 10 surplus kWh * adjustment/NSC rates.
    annual = settle_year(
        opening=CreditBalances(_amounts(utility, 0.80, 0.20), 7),
        prior_paid_eligible_energy=_amounts(utility, 0, 0),
        surplus_adjustment=_amounts(utility, 10 * 0.05, 10 * 0.01),
        nsc_entitlement_usd=10 * 0.03,
        offset_prior_payments=utility == "SCE",
        carry_base_credit=False,
    )
    assert annual.base_applied_to_adjustment.total_usd == pytest.approx(0.60)
    assert annual.forfeited_base.total_usd == pytest.approx(0.40)
    assert annual.nsc_entitlement_usd == pytest.approx(0.30)
    assert annual.net_bill_adjustment_usd == pytest.approx(-0.30)
    assert annual.closing == CreditBalances(_amounts(utility, 0, 0), 7)


@pytest.mark.parametrize("utility,prior_offset_usd", [("PG&E", 30), ("SCE", 30), ("SDG&E", 0)])
def test_annual_offsets_exclude_energy_already_paid_with_bonus(utility, prior_offset_usd):
    first = _month(0, 0, bonus_usd=30, utility=utility)
    last = _month(35, 70, bonus_usd=0, utility=utility, opening=first.closing)
    annual = _close_year([first, last], utility)
    assert first.paid_eligible_energy == _amounts(utility, 10, 20)
    assert first.bonus_applied_to_energy == _amounts(utility, 10, 20)
    assert annual.base_applied_to_prior_payments.total_usd == prior_offset_usd
    assert annual.net_bill_adjustment_usd == -prior_offset_usd
    assert annual.opening.base.total_usd == (
        annual.base_applied_to_prior_payments.total_usd
        + annual.forfeited_base.total_usd
        + annual.closing.base.total_usd
    )


def test_annual_adjustment_and_prior_offsets_preserve_component_restrictions():
    annual = settle_year(
        opening=CreditBalances(ComponentAmounts(3, 7), 11),
        prior_paid_eligible_energy=ComponentAmounts(100, 2),
        surplus_adjustment=ComponentAmounts(5, 1),
        nsc_entitlement_usd=0.30,
        offset_prior_payments=True,
        carry_base_credit=True,
    )
    assert annual.base_applied_to_adjustment == ComponentAmounts(3, 1)
    assert annual.base_applied_to_prior_payments == ComponentAmounts(0, 2)
    assert annual.closing == CreditBalances(ComponentAmounts(0, 4), 11)
    assert annual.net_bill_adjustment_usd == pytest.approx(-0.30)


def test_sce_annual_adjustment_and_prior_offsets_use_the_same_combined_pool():
    # The preceding component case leaves $2 of adjustment unpaid and carries $4.
    # SCE can use all $10: $6 against the adjustment and $4 against prior payments.
    annual = settle_year(
        opening=CreditBalances(PooledAmount(10), 11),
        prior_paid_eligible_energy=PooledAmount(102),
        surplus_adjustment=PooledAmount(6),
        nsc_entitlement_usd=0.30,
        offset_prior_payments=True,
        carry_base_credit=False,
    )
    assert annual.base_applied_to_adjustment == PooledAmount(6)
    assert annual.base_applied_to_prior_payments == PooledAmount(4)
    assert annual.forfeited_base == PooledAmount(0)
    assert annual.closing == CreditBalances(PooledAmount(0), 11)
    assert annual.net_bill_adjustment_usd == pytest.approx(-4.30)


def test_bonus_allocation_uses_energy_remaining_after_base_credits():
    month = _month(10, 5, bonus_usd=9)
    # Remaining generation/delivery charges are $10/$35. A $9 bonus pays $2/$7.
    assert month.bonus_applied_to_energy == ComponentAmounts(2, 7)
    assert month.paid_eligible_energy == ComponentAmounts(8, 28)
    assert month.payment_usd == 65
    assert month.opening.bonus_usd + month.earned.bonus_usd == (
        month.bonus_applied_usd + month.closing.bonus_usd
    )


@pytest.mark.parametrize("credit_usd", [19.999999, 20, 20.000001])
@pytest.mark.parametrize("utility", ["PG&E", "SCE"])
def test_monthly_charge_and_credit_balances_reconcile_at_credit_exhaustion(
    utility, credit_usd
):
    month = _month(credit_usd, 40, bonus_usd=0, utility=utility)
    assert month.payment_usd == pytest.approx(29 + max(20 - credit_usd, 0))
    assert month.closing.base.total_usd == pytest.approx(max(credit_usd - 20, 0))
    assert month.earned.base.total_usd == pytest.approx(
        month.base_applied.total_usd + month.closing.base.total_usd
    )
    assert 89 == pytest.approx(
        month.payment_usd + month.base_applied.total_usd + month.bonus_applied_usd
    )


@pytest.mark.parametrize("zero", [PooledAmount(0), ComponentAmounts(0, 0)])
def test_zero_bill_preserves_credits_without_creating_a_payment(zero):
    opening = CreditBalances(zero, 5)
    month = settle_month(
        eligible_energy=zero,
        non_bypassable_charge_usd=0,
        fixed_charge_usd=0,
        opening=opening,
        earned=CreditBalances(zero, 0),
    )
    assert month.payment_usd == 0
    assert month.bonus_applied_usd == 0
    assert month.closing == opening


@pytest.mark.parametrize("bad", [-1, float("nan"), float("inf")])
@pytest.mark.parametrize(
    "construct",
    [
        lambda value: ComponentAmounts(value, 0),
        lambda value: ComponentAmounts(0, value),
        PooledAmount,
        lambda value: CreditBalances(PooledAmount(0), value),
    ],
    ids=["generation", "delivery", "pooled", "bonus"],
)
def test_balances_reject_negative_or_nonfinite_dollars(construct, bad):
    with pytest.raises(ValueError, match="finite and non-negative"):
        construct(bad)


@pytest.mark.parametrize("bad", [None, "1.00", True])
def test_dollars_require_numbers_without_implicit_input_repair(bad):
    with pytest.raises(TypeError, match="real number in USD"):
        PooledAmount(bad)


@pytest.mark.parametrize("field", ["non_bypassable_charge_usd", "fixed_charge_usd"])
def test_monthly_charges_reject_invalid_dollars(field):
    charges = {"non_bypassable_charge_usd": 4, "fixed_charge_usd": 25}
    charges[field] = -1
    with pytest.raises(ValueError, match=field):
        settle_month(
            eligible_energy=PooledAmount(60),
            opening=CreditBalances(PooledAmount(0), 0),
            earned=CreditBalances(PooledAmount(0), 0),
            **charges,
        )


@pytest.mark.parametrize("field", ["eligible_energy", "opening", "earned"])
def test_month_rejects_mixed_credit_restrictions(field):
    arguments = dict(
        eligible_energy=PooledAmount(60),
        opening=CreditBalances(PooledAmount(0), 0),
        earned=CreditBalances(PooledAmount(35), 0),
    )
    arguments[field] = (
        ComponentAmounts(20, 40)
        if field == "eligible_energy"
        else CreditBalances(ComponentAmounts(0, 0), 0)
    )
    with pytest.raises(ValueError, match="cannot be mixed"):
        settle_month(non_bypassable_charge_usd=4, fixed_charge_usd=25, **arguments)


@pytest.mark.parametrize("offset_prior_payments", [True, False])
@pytest.mark.parametrize("field", ["prior_paid_eligible_energy", "surplus_adjustment"])
def test_year_rejects_mixed_credit_restrictions_even_without_prior_offsets(
    field, offset_prior_payments
):
    arguments = dict(
        prior_paid_eligible_energy=PooledAmount(0), surplus_adjustment=PooledAmount(0)
    )
    arguments[field] = ComponentAmounts(0, 0)
    with pytest.raises(ValueError, match="cannot be mixed"):
        settle_year(
            opening=CreditBalances(PooledAmount(0), 0),
            nsc_entitlement_usd=0,
            offset_prior_payments=offset_prior_payments,
            carry_base_credit=False,
            **arguments,
        )


@pytest.mark.parametrize(
    "override,error,match",
    [
        ({"nsc_entitlement_usd": -1}, ValueError, "nsc_entitlement_usd"),
        ({"offset_prior_payments": "false"}, TypeError, "must be boolean"),
        ({"carry_base_credit": 1}, TypeError, "must be boolean"),
    ],
)
def test_year_rejects_invalid_entitlement_or_rules(override, error, match):
    arguments = dict(
        opening=CreditBalances(PooledAmount(0), 0),
        prior_paid_eligible_energy=PooledAmount(0),
        surplus_adjustment=PooledAmount(0),
        nsc_entitlement_usd=0,
        offset_prior_payments=False,
        carry_base_credit=False,
    )
    arguments.update(override)
    with pytest.raises(error, match=match):
        settle_year(**arguments)
