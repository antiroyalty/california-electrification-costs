"""Federal-only reporting from saved gross costs and declared initial credits."""

from dataclasses import replace
from math import fsum

import pandas as pd
import pytest

from evaluations.eac import compute_eac_from_inputs
from evaluations.federal_credits import (
    FederalCreditCase, FederalCreditReceipts, HouseholdFederalCredits,
    evaluate_federal_purchase_credits,
)
from helpers.plot_scenario_comparison_helper import (
    collect_eac_components, collect_eac_components_by_county,
)


SCENARIO = "full_electric_ev_coopt"
HOUSING = "single-family-detached"
KEY = (SCENARIO, "alameda")


def _annualize(cost, life, rate):
    return cost / fsum((1 + rate) ** -year for year in range(1, life + 1))


def _receipts(case=FederalCreditCase.ALL, with_solar=True):
    amounts = evaluate_federal_purchase_credits(
        case=case, pv_eligible_basis_usd=20000 if with_solar else 0,
        storage_eligible_basis_usd=10000 if with_solar else 0,
        storage_capacity_kwh=10 if with_solar else 0,
        space_heat_pump_eligible_basis_usd=12000,
        water_heat_pump_eligible_basis_usd=4000, eligible_vehicle_credit_usd=7500,
    )
    return FederalCreditReceipts(amounts, home_receipt_year=1, vehicle_receipt_year=0)


@pytest.fixture
def saved_household(tmp_path):
    capital = tmp_path / "capital_costs"
    capital.mkdir()
    suffix = f"{SCENARIO}_{HOUSING.replace('-', '_')}.csv"
    rows = []
    for incentive, fraction in (("full_incentives", 1), ("half_incentives", .5),
                                ("no_incentives", 0)):
        for kind, gross, rebate, life, operating in (
            ("heating", 12000, 1000, 15, 0),
            ("hot_water", 4000, 1500, 15, 0),
            ("cooking", 2000, 840, 15, 0),
            ("vehicle_charging", 50000, 3000, 12, 2100),
        ):
            rows.append(dict(
                county_slug="alameda", incentive_scenario=incentive,
                appliance_category="electric", appliance_type=kind,
                base_cost=gross, net_cost=gross - fraction * rebate,
                lifetime_years=life, annual_operating_cost=operating,
            ))
    ledger = pd.DataFrame(rows)
    ledger.to_csv(capital / f"capital_costs_{suffix}", index=False)
    summary = dict(county_slug="alameda", pv_capex=20000, storage_capex=10000,
                   pv_incentives_full=6000, storage_incentives_full=3000)
    summary_path = capital / f"capital_costs_summary_with_pv_{suffix}"
    pd.DataFrame([summary]).to_csv(summary_path, index=False)
    for fuel, values in (
        ("electricity", {"electricity.PG&E.E-TOU-D": 1500,
                         "electricity.PG&E.E-ELEC_NEM3": 900}),
        ("gas", {"gas.PG&E.G-1": 0}),
    ):
        directory = tmp_path / SCENARIO / HOUSING / "alameda" / "results" / fuel
        directory.mkdir(parents=True)
        pd.DataFrame([
            {"scenario": SCENARIO, **values},
            {"scenario": f"{SCENARIO}.solarstorage", **values},
        ]).to_csv(directory / f"RESULTS_{fuel}_annual_costs_alameda_20260919_11.csv", index=False)
    return tmp_path, ledger, summary, summary_path


@pytest.mark.parametrize("case", list(FederalCreditCase))
@pytest.mark.parametrize("with_solar", [False, True])
@pytest.mark.parametrize("rate", [0.0, 0.07])
def test_public_reports_reconcile_to_gross_costs_and_one_time_credits(
    saved_household, case, with_solar, rate,
):
    root, _, _, summary_path = saved_household
    if not with_solar:
        summary_path.unlink()  # No-solar reporting must not require this file.
    receipts = _receipts(case, with_solar)
    args = (str(root), HOUSING, [SCENARIO], ["Alameda County"])
    kwargs = dict(
        discount_rate=rate, with_solar=with_solar,
        electricity_variant="nem3" if with_solar else "retail",
        electricity_plan_preference=["E-ELEC", "E-TOU-D"],
        federal_credit_receipts_by_household={KEY: receipts},
    )
    row = collect_eac_components_by_county(*args, **kwargs).iloc[0]
    expected_pv = expected_storage = 0
    if with_solar:
        expected_pv = _annualize(20000 - receipts.amounts.pv_25d_usd / (1 + rate), 25, rate)
        storage_present_cost = (
            10000 + 10000 / (1 + rate) ** 15 - (10000 / 3) / (1 + rate) ** 25
            - receipts.amounts.storage_25d_usd / (1 + rate)
        )
        expected_storage = _annualize(storage_present_cost, 25, rate)
    expected_electric = (
        _annualize(18000, 15, rate) + _annualize(50000, 12, rate)
        - _annualize(receipts.amounts.heat_pumps_25c_usd / (1 + rate), 25, rate)
        - _annualize(receipts.amounts.vehicle_30d_usd, 25, rate)
    )
    assert row["capex_pv"] == pytest.approx(expected_pv)
    assert row["capex_storage"] == pytest.approx(expected_storage)
    assert row["capex_electric"] == pytest.approx(expected_electric)
    assert row["vehicle_om"] == 2100  # One selected row, not all three incentive rows.
    assert row.drop(["scenario", "county_slug"]).sum() == pytest.approx(
        expected_pv + expected_storage + expected_electric + 2100 + (900 if with_solar else 1500)
    )
    aggregate = collect_eac_components(*args, **kwargs).iloc[0]
    pd.testing.assert_series_equal(aggregate, row.drop("county_slug"))


def test_federal_only_result_does_not_depend_on_legacy_rebate_selection(saved_household):
    root, _, _, _ = saved_household
    rows = [collect_eac_components_by_county(
        str(root), HOUSING, [SCENARIO], ["Alameda County"], incentive=incentive,
        federal_credit_receipts_by_household={KEY: _receipts()},
    ).iloc[0] for incentive in ("full_incentives", "half_incentives", "no_incentives")]
    for row in rows[1:]:
        pd.testing.assert_series_equal(row, rows[0])


def test_default_reporting_keeps_existing_incentive_treatment(saved_household):
    root, _, _, _ = saved_household
    args = (str(root), HOUSING, [SCENARIO], ["Alameda County"])
    legacy = collect_eac_components_by_county(*args).iloc[0]
    assert legacy["capex_electric"] == pytest.approx(
        _annualize(18000 - 3340, 15, .07) + _annualize(47000, 12, .07)
    )
    federal_zero = collect_eac_components_by_county(
        *args, federal_credit_receipts_by_household={KEY: _receipts(FederalCreditCase.NONE)},
    ).iloc[0]
    assert federal_zero["capex_electric"] > legacy["capex_electric"]
    assert federal_zero["capex_storage"] > legacy["capex_storage"]


@pytest.mark.parametrize("mapping", [
    {}, {KEY: None}, {(SCENARIO, "wrong_county"): _receipts()},
    {KEY: _receipts(), (SCENARIO, "extra_county"): _receipts()}, [],
])
def test_receipts_must_cover_each_requested_household_explicitly(tmp_path, mapping):
    with pytest.raises(ValueError, match="[Ff]ederal-only"):
        collect_eac_components_by_county(
            str(tmp_path), HOUSING, [SCENARIO], ["Alameda County"],
            federal_credit_receipts_by_household=mapping,
        )


def test_direct_eac_preserves_input_frames_and_ignores_mixed_net_prices(saved_household):
    _, ledger, summary, _ = saved_household
    selected = ledger[ledger.incentive_scenario == "full_incentives"].copy()
    before = selected.copy(deep=True)
    compute_eac_from_inputs(selected, summary, federal_credit_receipts=_receipts())
    pd.testing.assert_frame_equal(selected, before)
    selected["net_cost"] = -99999  # It cannot affect this explicit gross-cost path.
    first = compute_eac_from_inputs(before, summary, federal_credit_receipts=_receipts())
    second = compute_eac_from_inputs(selected, summary, federal_credit_receipts=_receipts())
    assert first == second
    assert summary["pv_incentives_full"] == 6000


@pytest.mark.parametrize("field", [
    "pv_25d_usd", "storage_25d_usd", "heat_pumps_25c_usd", "vehicle_30d_usd",
])
def test_credit_cannot_be_applied_without_its_purchase(field):
    amounts = replace(HouseholdFederalCredits(0, 0, 0, 0), **{field: 1})
    with pytest.raises(ValueError, match="gross purchase cost"):
        compute_eac_from_inputs(
            None, None, federal_credit_receipts=FederalCreditReceipts(amounts, 1, 0),
        )


@pytest.mark.parametrize("problem", ["missing_cost", "nan_cost", "negative_cost", "duplicate", "unselected"])
def test_federal_path_rejects_malformed_gross_ledger(saved_household, problem):
    _, ledger, summary, _ = saved_household
    selected = ledger[ledger.incentive_scenario == "full_incentives"].copy()
    if problem == "missing_cost":
        selected = selected.drop(columns="base_cost")
    elif problem == "nan_cost":
        selected.loc[selected.index[0], "base_cost"] = float("nan")
    elif problem == "negative_cost":
        selected.loc[selected.index[0], "base_cost"] = -1
    elif problem == "duplicate":
        selected = pd.concat([selected, selected.iloc[[0]]])
    else:
        selected = ledger
    with pytest.raises(ValueError, match="Federal-only"):
        compute_eac_from_inputs(selected, summary, federal_credit_receipts=_receipts())


@pytest.mark.parametrize("field", ["home_receipt_year", "vehicle_receipt_year"])
def test_reporting_validates_receipt_times_even_for_zero_credits(field):
    receipts = replace(_receipts(FederalCreditCase.NONE), **{field: float("nan")})
    with pytest.raises(ValueError, match="receipt_year"):
        compute_eac_from_inputs(None, None, federal_credit_receipts=receipts)


def test_gas_household_retains_gross_appliances_and_vehicle_operating_costs():
    ledger = pd.DataFrame([
        dict(appliance_category="gas", appliance_type="heating", base_cost=1000,
             net_cost=1000, lifetime_years=15),
        dict(appliance_category="gas", appliance_type="vehicle_fuel", base_cost=30000,
             net_cost=30000, lifetime_years=12),
    ])
    receipts = FederalCreditReceipts(HouseholdFederalCredits(6000, 0, 0, 0), 1, 0)
    costs = compute_eac_from_inputs(
        ledger, {"pv_capex": 20000, "storage_capex": 0},
        federal_credit_receipts=receipts, annual_bill_electric=900,
        annual_bill_gas=600, vehicle_om=5000,
    )
    assert costs.capex_electric == 0
    assert costs.capex_gas == pytest.approx(
        _annualize(1000, 15, .07) + _annualize(30000, 12, .07)
    )
    assert costs.total() == pytest.approx(
        costs.capex_gas + _annualize(20000 - 6000 / 1.07, 25, .07) + 900 + 600 + 5000
    )
