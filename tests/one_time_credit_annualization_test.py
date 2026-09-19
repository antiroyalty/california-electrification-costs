"""Independent cash-flow checks for a credit received once in the study."""

from math import fsum

import pytest

from evaluations.eac import alpha_batt_npv, annualized_one_time_credit
from evaluations.federal_credits import FederalCreditCase, evaluate_federal_purchase_credits


def _annual_cash_flow_value(cash_flows, rate, years):
    present_value = fsum(amount / (1 + rate) ** year for year, amount in cash_flows)
    discounted_years = fsum(1 / (1 + rate) ** year for year in range(1, years + 1))
    return present_value / discounted_years


@pytest.mark.parametrize("rate", [0.0, 0.07])
@pytest.mark.parametrize("years", [10, 25])
@pytest.mark.parametrize("receipt_fraction", [0.0, 0.02, 0.04, 1.0])
def test_credit_matches_an_independent_receipt_schedule(rate, years, receipt_fraction):
    receipt_year = years * receipt_fraction
    actual = annualized_one_time_credit(
        credit_usd=7500, receipt_year=receipt_year,
        discount_rate=rate, horizon_years=years,
    )
    expected = _annual_cash_flow_value([(receipt_year, 7500)], rate, years)
    assert actual == pytest.approx(expected)


def test_delay_reduces_value_without_changing_the_study_horizon():
    immediate = annualized_one_time_credit(
        credit_usd=7500, receipt_year=0, discount_rate=0.07, horizon_years=25,
    )
    delayed = annualized_one_time_credit(
        credit_usd=7500, receipt_year=1, discount_rate=0.07, horizon_years=25,
    )
    assert round(immediate, 2) == 643.58
    assert delayed == pytest.approx(immediate / 1.07)
    assert delayed < immediate


def test_zero_rate_spreads_one_credit_over_the_study():
    assert annualized_one_time_credit(
        credit_usd=3000, receipt_year=1, discount_rate=0, horizon_years=25,
    ) == 120.0


def test_zero_credit_has_zero_value():
    assert annualized_one_time_credit(
        credit_usd=0, receipt_year=1, discount_rate=0.07, horizon_years=25,
    ) == 0.0


@pytest.mark.parametrize("receipt_year", [0, 1])
def test_initial_credit_preserves_gross_battery_replacement_and_remaining_value(receipt_year):
    # $10,000 at years 0 and 15, $3,333.33 remaining value at year 25,
    # and exactly one $3,000 credit. No replacement receives a second credit.
    gross_annual_cost = 10000 * alpha_batt_npv(0.07, 15, 25)
    credit_reduction = annualized_one_time_credit(
        credit_usd=3000, receipt_year=receipt_year,
        discount_rate=0.07, horizon_years=25,
    )
    expected = _annual_cash_flow_value(
        [(0, 10000), (15, 10000), (25, -10000 / 3), (receipt_year, -3000)],
        0.07, 25,
    )
    assert gross_annual_cost - credit_reduction == pytest.approx(expected)
    # Discounting all purchases by 30% would incorrectly subsidize replacement.
    assert gross_annual_cost - credit_reduction > 7000 * alpha_batt_npv(0.07, 15, 25)


def test_itemized_household_credits_keep_their_distinct_receipt_times():
    credits = evaluate_federal_purchase_credits(
        case=FederalCreditCase.ALL,
        pv_eligible_basis_usd=20000, storage_eligible_basis_usd=10000,
        storage_capacity_kwh=10, space_heat_pump_eligible_basis_usd=12000,
        water_heat_pump_eligible_basis_usd=4000, eligible_vehicle_credit_usd=7500,
    )
    # Declared example: vehicle credit at purchase; home credits one year later.
    schedule = [
        (1, credits.pv_25d_usd), (1, credits.storage_25d_usd),
        (1, credits.heat_pumps_25c_usd), (0, credits.vehicle_30d_usd),
    ]
    actual = sum(
        annualized_one_time_credit(
            credit_usd=amount, receipt_year=year, discount_rate=0.07, horizon_years=25,
        )
        for year, amount in schedule
    )
    assert actual == pytest.approx(_annual_cash_flow_value(schedule, 0.07, 25))


@pytest.mark.parametrize("field", [
    "credit_usd", "receipt_year", "discount_rate", "horizon_years",
])
@pytest.mark.parametrize("invalid", [None, True, "1", float("nan"), float("inf"), -1])
def test_invalid_inputs_fail_even_for_zero_credit(field, invalid):
    inputs = dict(credit_usd=0, receipt_year=1, discount_rate=0.07, horizon_years=25)
    inputs[field] = invalid
    with pytest.raises(ValueError, match=field):
        annualized_one_time_credit(**inputs)


def test_zero_horizon_is_not_replaced_with_a_default():
    with pytest.raises(ValueError, match="horizon_years"):
        annualized_one_time_credit(
            credit_usd=3000, receipt_year=0, discount_rate=0.07, horizon_years=0,
        )


def test_receipt_beyond_study_end_requires_an_explicit_model_change():
    with pytest.raises(ValueError, match="receipt_year"):
        annualized_one_time_credit(
            credit_usd=3000, receipt_year=25.01, discount_rate=0.07, horizon_years=25,
        )


@pytest.mark.parametrize("field", ["receipt_year", "discount_rate", "horizon_years"])
def test_accounting_assumptions_cannot_be_omitted(field):
    inputs = dict(credit_usd=3000, receipt_year=0, discount_rate=0.07, horizon_years=25)
    del inputs[field]
    with pytest.raises(TypeError, match=field):
        annualized_one_time_credit(**inputs)
