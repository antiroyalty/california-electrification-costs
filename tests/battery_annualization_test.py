"""Independent cash-flow examples for shared battery capital accounting."""

import math

import pandas as pd
import pytest

from evaluations.eac import alpha_batt_npv, compute_eac_from_inputs
from helpers.plot_scenario_comparison_helper import (
    collect_eac_components,
    collect_eac_components_by_county,
)
from pipeline.steps.step9b_cooptimize_core import CooptInputs, _solve_lp


def _annual_cost(cash_flows, rate, years):
    """Discount an explicit cash-flow schedule, then spread it over the study."""
    present_cost = math.fsum(cost / (1 + rate) ** year for year, cost in cash_flows)
    discounted_years = math.fsum((1 + rate) ** -year for year in range(1, years + 1))
    return present_cost / discounted_years


def test_25_year_battery_example_includes_discounted_remaining_value():
    """The $10,000 example gives a $614.16 present credit and $1,116.42/year."""
    cash_flows = [(0, 10000), (15, 10000), (25, -10000 / 3)]
    assert round((10000 / 3) / 1.07 ** 25, 2) == 614.16
    expected = _annual_cost(cash_flows, 0.07, 25)
    assert round(expected, 2) == 1116.42
    assert 10000 * alpha_batt_npv(0.07, 15, 25) == pytest.approx(expected)


@pytest.mark.parametrize(
    "life,years,cash_flows",
    [
        (15, 10, [(0, 1), (10, -1 / 3)]),
        (15, 15, [(0, 1)]),
        (15, 25, [(0, 1), (15, 1), (25, -1 / 3)]),
        (15, 30, [(0, 1), (15, 1)]),
        (8, 20, [(0, 1), (8, 1), (16, 1), (20, -0.5)]),
    ],
)
@pytest.mark.parametrize("rate", [0.0, 0.07])
def test_replacements_and_remaining_value_follow_service_life(life, years, cash_flows, rate):
    """Buy only within the study and credit the last battery's unused life."""
    assert alpha_batt_npv(rate, life, years) == pytest.approx(
        _annual_cost(cash_flows, rate, years)
    )


def test_battery_cost_is_continuous_at_a_replacement_boundary():
    """A purchase just before study end is offset by its almost-full remaining value."""
    at_boundary = alpha_batt_npv(0.07, 15, 15)
    assert alpha_batt_npv(0.07, 15, 15 - 1e-6) == pytest.approx(at_boundary)
    assert alpha_batt_npv(0.07, 15, 15 + 1e-6) == pytest.approx(at_boundary)


@pytest.mark.parametrize("field", ["discount_rate", "batt_life_yrs", "horizon_yrs"])
@pytest.mark.parametrize("invalid", [float("nan"), float("inf"), -1.0])
def test_invalid_accounting_parameters_fail(field, invalid):
    params = dict(discount_rate=0.07, batt_life_yrs=15, horizon_yrs=25)
    params[field] = invalid
    with pytest.raises(ValueError, match=field):
        alpha_batt_npv(**params)


@pytest.mark.parametrize("field", ["batt_life_yrs", "horizon_yrs"])
def test_zero_lifetime_or_horizon_fails(field):
    params = dict(discount_rate=0.07, batt_life_yrs=15, horizon_yrs=25)
    params[field] = 0
    with pytest.raises(ValueError, match=field):
        alpha_batt_npv(**params)


@pytest.mark.parametrize("incentive,net_cost", [
    ("full_incentives", 7000), ("half_incentives", 8500), ("no_incentives", 10000),
])
def test_reporting_uses_the_same_cost_basis_for_purchases_and_remaining_value(incentive, net_cost):
    result = compute_eac_from_inputs(
        None, {"storage_capex": 10000, "storage_incentives_full": 3000},
        incentive=incentive, annual_bill_electric=1200, annual_bill_gas=100,
    )
    expected = _annual_cost([(0, net_cost), (15, net_cost), (25, -net_cost / 3)], 0.07, 25)
    assert result.capex_storage == pytest.approx(expected)
    assert result.total() == pytest.approx(expected + 1300)


@pytest.mark.parametrize("asset", ["solar", "storage"])
@pytest.mark.parametrize("invalid", ["unknown", float("nan"), 0])
def test_reporting_does_not_replace_invalid_lifetimes_with_defaults(asset, invalid):
    with pytest.raises(ValueError):
        compute_eac_from_inputs(None, {"storage_capex": 10000}, lifetimes={asset: invalid})


@pytest.mark.parametrize("rate,years,life,purchases,remaining", [
    (0.07, 25, 15, [0, 15], 1 / 3),
    (0.05, 20, 8, [0, 8, 16], 0.5),
    (0.0, 15, 15, [0], 0.0),
])
def test_optimizer_and_reporting_match_independent_capital_cash_flows(
    rate, years, life, purchases, remaining,
):
    inputs = CooptInputs(
        load_kwh=[1, 1], pv_gen_per_kw=[2, 0],
        import_rates=[0.4, 0.4], export_rates=[0.05, 0.05],
    )
    result = _solve_lp(
        inputs, fixed_pv_kw=1, fixed_batt_kwh=10,
        c_pv_kw=3300, c_batt_kwh=1000, c_batt_kw=25,
        discount_rate=rate, pv_life_yrs=years, batt_life_yrs=life,
        weights=[4380, 4380],
    )
    storage_cost = 10000 + 25 * result.batt_kw
    cash_flows = [(0, 3300), *[(year, storage_cost) for year in purchases],
                  (years, -remaining * storage_cost)]
    expected = _annual_cost(cash_flows, rate, years)
    report = compute_eac_from_inputs(
        None, {"pv_capex": 3300, "storage_capex": storage_cost},
        discount_rate=rate, lifetimes={"solar": years, "storage": life},
        annual_bill_electric=result.import_cost - result.export_credit,
    )
    assert result.capex_annual == pytest.approx(expected)
    assert report.capex_pv + report.capex_storage == pytest.approx(expected)
    assert result.total_cost == pytest.approx(report.total())


@pytest.mark.parametrize("collector", [collect_eac_components, collect_eac_components_by_county])
def test_county_and_aggregate_reporting_use_corrected_annualization(tmp_path, collector):
    """Exercise the public collectors with real capital and bill files."""
    scenario, housing, county = "baseline_coopt", "single-family-detached", "alameda"
    capital_dir = tmp_path / "capital_costs"
    capital_dir.mkdir()
    suffix = f"{scenario}_{housing.replace('-', '_')}.csv"
    pd.DataFrame([{
        "county_slug": county, "incentive_scenario": "full_incentives",
        "appliance_category": "electric", "appliance_type": "storage",
        "net_cost": 10000, "base_cost": 10000, "lifetime_years": 15,
        "annual_operating_cost": 0,
    }]).to_csv(capital_dir / f"capital_costs_{suffix}", index=False)
    pd.DataFrame([{
        "county_slug": county, "pv_capex": 3300, "storage_capex": 10000,
        "pv_incentives_full": 0, "storage_incentives_full": 0,
    }]).to_csv(capital_dir / f"capital_costs_summary_with_pv_{suffix}", index=False)
    for fuel, column, bill in [
        ("electricity", "electricity.PG&E.E-ELEC_NEM3", 1200),
        ("gas", "gas.PG&E.G-1", 100),
    ]:
        directory = tmp_path / scenario / housing / county / "results" / fuel
        directory.mkdir(parents=True)
        pd.DataFrame([{"scenario": f"{scenario}.solarstorage", column: bill}]).to_csv(
            directory / f"RESULTS_{fuel}_annual_costs_{county}_20260910_11.csv", index=False,
        )

    row = collector(str(tmp_path), housing, [scenario], ["Alameda County"]).iloc[0]
    expected = _annual_cost([(0, 10000), (15, 10000), (25, -10000 / 3)], 0.07, 25)
    assert row["capex_storage"] == pytest.approx(expected)
    assert row["capex_electric"] == 0  # Storage must not also enter appliance capital costs.
    assert row["annual_bill_electric"] == 1200
    assert row["annual_bill_gas"] == 100
