"""Solver decisions checked against independent dollar examples and numeric billing.

These teaching problems verify credit accounting, not physical battery dispatch
or county economics. Fixed inputs are SCIP variables so constraints are exercised.
"""

from numbers import Real

import pytest
from pyscipopt import Model

from tariffs.accounting import ComponentAmounts, CreditBalances, PooledAmount, settle_month
from tariffs.accounting_equations import annual_accounting, monthly_accounting
from tariffs.accounting_scip import ScipArithmetic


@pytest.fixture
def model():
    model = Model()
    model.hideOutput()
    model.setRealParam("numerics/feastol", 1e-9)
    model.setRealParam("limits/gap", 0.0)
    yield model
    model.freeProb()


def _fixed(model, value):
    return model.addVar(lb=value, ub=value)


def _values(model, expressions):
    return tuple(float(v) if isinstance(v, Real) else model.getVal(v) for v in expressions)


def _solve(model, objective, sense="minimize"):
    model.setObjective(objective, sense)
    model.optimize()
    assert model.getStatus() == "optimal"


def _pools(pooled, generation, delivery):
    return (generation + delivery,) if pooled else (generation, delivery)


def _month(model, generation, delivery=5, *, pooled=False, bonus=0.88, opening=None):
    if opening is None:
        opening = (_pools(pooled, 0, 0), 0)
    return monthly_accounting(
        eligible=tuple(_fixed(model, v) for v in _pools(pooled, 20, 40)),
        nbc=_fixed(model, 4),
        fixed=_fixed(model, 25),
        opening_base=opening[0],
        opening_bonus=opening[1],
        earned_base=tuple(_fixed(model, v) for v in _pools(pooled, generation, delivery)),
        earned_bonus=_fixed(model, bonus),
        arithmetic=ScipArithmetic(model),
    )


def _year(model, generation_credits, delivery=5, *, utility="PG&E", opening=None, bonus=0.88):
    months = []
    for generation in generation_credits:
        month = _month(
            model, generation, delivery, pooled=utility == "SCE", bonus=bonus, opening=opening
        )
        months.append(month)
        opening = (month.closing_base, month.closing_bonus)
    annual = annual_accounting(
        opening_base=opening[0], opening_bonus=opening[1],
        prior_paid=tuple(sum(m.paid_eligible[i] for m in months) for i in range(len(opening[0]))),
        adjustment=_pools(utility == "SCE", 0, 0), nsc=0,
        offset_prior_payments=utility in ("PG&E", "SCE"),
        carry_base_credit=utility == "PG&E", arithmetic=ScipArithmetic(model),
    )
    return sum(m.payment for m in months) + annual.bill_adjustment, annual


@pytest.mark.parametrize(
    "generation,expected_payment,expected_bank", [(10, 877.44, 0), (20, 757.44, 10)]
)
def test_examples_1_and_2_unused_bank_is_not_current_savings(
    model, generation, expected_payment, expected_bank
):
    credits = [10] * 12 if generation == 10 else [20] * 11 + [30]
    payment, annual = _year(model, credits)
    _solve(model, payment)
    assert model.getObjVal() == pytest.approx(expected_payment)
    assert _values(model, annual.closing_base) == pytest.approx((expected_bank, 0))


def test_example_3_carryover_pays_next_year_once(model):
    first_payment, first = _year(model, [20] * 11 + [30])
    next_payment, following = _year(
        model, [20] * 11 + [10], opening=(first.closing_base, first.closing_bonus)
    )
    _solve(model, first_payment + next_payment)
    assert _values(model, (first_payment, next_payment)) == pytest.approx((757.44, 757.44))
    assert model.getObjVal() == pytest.approx(1514.88)
    assert _values(model, following.closing_base) == pytest.approx((0, 0))


@pytest.mark.parametrize(
    "utility,forfeited,next_payment",
    [("PG&E", 0, 348), ("SCE", 120, 468), ("SDG&E", 120, 468)],
)
def test_example_4_expiry_changes_future_payments(model, utility, forfeited, next_payment):
    first_payment, first = _year(model, [25] * 12, 45, utility=utility, bonus=0)
    second_payment, _ = _year(
        model, [15] * 12, 35, utility=utility, bonus=0,
        opening=(first.closing_base, first.closing_bonus),
    )
    _solve(model, first_payment + second_payment)
    assert _values(model, (first_payment, second_payment)) == pytest.approx((348, next_payment))
    assert sum(_values(model, first.forfeited_base)) == pytest.approx(forfeited)


@pytest.mark.parametrize("pooled,payment,bank", [(True, 54, 0), (False, 64, 10)])
def test_example_5_credit_application_is_mandatory_even_if_objective_opposes_it(
    model, pooled, payment, bank
):
    month = _month(model, 30, pooled=pooled, bonus=0)
    # A loose upper bound on applied credits would let this objective withhold them.
    _solve(model, month.payment + sum(month.closing_base), "maximize")
    assert _values(model, (month.payment, sum(month.closing_base))) == pytest.approx(
        (payment, bank)
    )


@pytest.mark.parametrize("utility", ["PG&E", "SCE", "SDG&E"])
def test_example_6_bonus_bank_pays_other_charges_after_true_up(model, utility):
    first_payment, annual = _year(model, [20], 40, utility=utility, bonus=35)
    second = _month(
        model, 20, 40, pooled=utility == "SCE", bonus=0,
        opening=(annual.closing_base, annual.closing_bonus),
    )
    _solve(model, first_payment + second.payment)
    assert _values(
        model, (first_payment, annual.closing_bonus, second.payment, second.closing_bonus)
    ) == pytest.approx((0, 6, 23, 0))


@pytest.mark.parametrize("pooled", [True, False])
def test_example_7_adjustment_precedes_expiry_and_nsc_stays_separate(model, pooled):
    annual = annual_accounting(
        opening_base=tuple(_fixed(model, v) for v in _pools(pooled, 0.8, 0.2)),
        opening_bonus=_fixed(model, 7), prior_paid=_pools(pooled, 0, 0),
        adjustment=tuple(_fixed(model, v) for v in _pools(pooled, 0.5, 0.1)),
        nsc=0.3, offset_prior_payments=pooled, carry_base_credit=False,
        arithmetic=ScipArithmetic(model),
    )
    _solve(model, annual.bill_adjustment + sum(annual.forfeited_base), "maximize")
    assert sum(_values(model, annual.applied_adjustment)) == pytest.approx(0.6)
    assert sum(_values(model, annual.forfeited_base)) == pytest.approx(0.4)
    assert _values(model, (annual.bill_adjustment, annual.closing_bonus)) == pytest.approx(
        (-0.3, 7)
    )


@pytest.mark.parametrize("pooled,capacity,payment,total", [(False, 20, 64, 74), (True, 30, 54, 69)])
def test_credit_saturation_changes_the_economic_decision(model, pooled, capacity, payment, total):
    # Each unit earns $1 generation credit and costs $0.50. Full earned-credit
    # valuation selects 30 in both cases; restricted usable credits select 20.
    credit_capacity = model.addVar(lb=0, ub=30)
    month = monthly_accounting(
        eligible=_pools(pooled, 20, 40), nbc=4, fixed=25,
        opening_base=_pools(pooled, 0, 0), opening_bonus=0,
        earned_base=_pools(pooled, credit_capacity, 5), earned_bonus=0,
        arithmetic=ScipArithmetic(model),
    )
    annual = annual_accounting(
        opening_base=month.closing_base, opening_bonus=month.closing_bonus,
        prior_paid=month.paid_eligible, adjustment=_pools(pooled, 0, 0), nsc=0,
        offset_prior_payments=True, carry_base_credit=not pooled,
        arithmetic=ScipArithmetic(model),
    )
    # Close this teaching period with zero terminal value for any retained bank.
    _solve(model, month.payment + annual.bill_adjustment + 0.5 * credit_capacity)
    assert _values(model, (credit_capacity, month.payment)) == pytest.approx((capacity, payment))
    assert model.getObjVal() == pytest.approx(total)


@pytest.mark.parametrize("pooled", [True, False])
def test_all_monthly_components_match_numeric_billing(model, pooled):
    month = _month(model, 10, bonus=9, pooled=pooled)
    _solve(model, month.payment)
    amounts = PooledAmount if pooled else ComponentAmounts
    numeric = settle_month(
        eligible_energy=amounts(*_pools(pooled, 20, 40)),
        non_bypassable_charge_usd=4, fixed_charge_usd=25,
        opening=CreditBalances(amounts(*_pools(pooled, 0, 0)), 0),
        earned=CreditBalances(amounts(*_pools(pooled, 10, 5)), 9),
    )

    def values(amount):
        return (amount.energy_usd,) if pooled else (amount.generation_usd, amount.delivery_usd)

    for expressions, expected in (
        (month.applied_base, values(numeric.base_applied)),
        (month.bonus_to_energy, values(numeric.bonus_applied_to_energy)),
        (month.paid_eligible, values(numeric.paid_eligible_energy)),
        (month.closing_base, values(numeric.closing.base)),
        ((month.applied_bonus, month.closing_bonus, month.payment),
         (numeric.bonus_applied_usd, numeric.closing.bonus_usd, numeric.payment_usd)),
    ):
        assert _values(model, expressions) == pytest.approx(expected)
    assert _values(model, month.bonus_to_energy) == pytest.approx((9,) if pooled else (2, 7))
    assert model.getObjVal() == pytest.approx(65)


def test_bonus_allocation_remains_proportional_when_charges_are_decisions(model):
    generation = model.addVar(lb=10, ub=20)
    delivery = model.addVar(lb=30, ub=40)
    model.addCons(generation + delivery == 50)
    shares = ScipArithmetic(model).proportional(12, (generation, delivery))
    # Maximizing the first share cannot allocate all $12 to generation.
    _solve(model, shares[0], "maximize")
    assert _values(model, (generation, delivery)) == pytest.approx((20, 30))
    assert _values(model, shares) == pytest.approx((4.8, 7.2))


def test_annual_offset_excludes_bonus_paid_energy(model):
    month = _month(model, 10, bonus=9)
    annual = annual_accounting(
        opening_base=tuple(_fixed(model, v) for v in (20, 40)), opening_bonus=0,
        prior_paid=month.paid_eligible, adjustment=(3, 1), nsc=0.3,
        offset_prior_payments=True, carry_base_credit=True,
        arithmetic=ScipArithmetic(model),
    )
    _solve(model, annual.bill_adjustment, "maximize")
    assert _values(model, annual.applied_adjustment) == pytest.approx((3, 1))
    assert _values(model, annual.applied_prior) == pytest.approx((8, 28))
    assert _values(model, annual.closing_base) == pytest.approx((9, 11))
    assert model.getObjVal() == pytest.approx(-36.3)


def test_proportional_allocation_is_defined_at_zero_charges(model):
    shares = ScipArithmetic(model).proportional(
        _fixed(model, 0), (_fixed(model, 0), _fixed(model, 0))
    )
    _solve(model, sum(shares), "maximize")
    assert _values(model, shares) == pytest.approx((0, 0))


@pytest.mark.parametrize("left,right", [(19.999999, 20), (20, 20), (20.000001, 20)])
@pytest.mark.parametrize("sense", ["minimize", "maximize"])
def test_minimum_is_exact_on_both_sides_of_credit_exhaustion(model, left, right, sense):
    applied = ScipArithmetic(model).minimum(_fixed(model, left), _fixed(model, right))
    _solve(model, applied, sense)
    assert model.getObjVal() == pytest.approx(min(left, right), abs=1e-9, rel=0)


@pytest.mark.parametrize("bad", [-1, float("nan"), float("inf"), True])
def test_adapter_rejects_invalid_constants(model, bad):
    with pytest.raises(ValueError, match="finite non-negative"):
        ScipArithmetic(model).minimum(bad, _fixed(model, 1))


@pytest.mark.parametrize("eligible", [(), (1, 2, 3)])
def test_adapter_rejects_unsupported_pools(model, eligible):
    with pytest.raises(ValueError, match="one or two"):
        ScipArithmetic(model).proportional(0, eligible)


@pytest.mark.parametrize("eligible", [(0, 0), (1,), (1, 2)])
def test_adapter_rejects_constant_allocation_exceeding_charges(model, eligible):
    with pytest.raises(ValueError, match="cannot exceed"):
        ScipArithmetic(model).proportional(sum(eligible) + 1, eligible)
