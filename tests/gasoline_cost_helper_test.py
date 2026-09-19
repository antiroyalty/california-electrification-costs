"""Missing gasoline prices must not become free vehicle fuel."""

import pytest

from appliances.electric_base import IncentiveScenario
from appliances.ice_vehicle import ICEVehicleAppliance
from helpers import gasoline_cost_helper as fuel
from pipeline.steps.step14_build_capital_costs_lifetimes_incentives import (
    build_capex_ledger_df,
)


@pytest.mark.parametrize("county", ["alameda", "Alameda County", " ALAMEDA COUNTY "])
def test_price_lookup_normalizes_county_names(county):
    assert fuel.get_gasoline_cost_for_county(county) == 4.581


def test_alpine_uses_the_declared_price_and_has_nonzero_fuel_cost():
    costs = fuel.calculate_annual_fuel_cost("Alpine County", 24.25)

    assert costs["gas_price_per_gallon"] == 4.589
    assert costs["annual_miles"] == 12000
    # 12,000 / 24.25 = 48,000 / 97 gallons; multiply by $4.589/gallon.
    assert costs["annual_gallons"] == pytest.approx(48000 / 97)
    assert costs["annual_fuel_cost"] == pytest.approx(220272 / 97)
    assert costs["fuel_cost_per_mile"] == pytest.approx(220272 / 97 / 12000)


def test_all_declared_counties_have_valid_prices():
    for county in fuel.COUNTY_GASOLINE_COSTS:
        assert fuel.get_gasoline_cost_for_county(county) > 0


def test_alpine_fuel_reaches_each_incentive_case_in_the_ledger():
    vehicle = ICEVehicleAppliance()
    ledger = build_capex_ledger_df(
        scenario="fuel_fixture",
        housing_type="single-family-detached",
        counties=["Alpine County"],
        electric_appliances={},
        gas_appliances={"vehicle_fuel": lambda county: vehicle},
        incentive_scenarios=list(IncentiveScenario),
    )

    assert len(ledger) == 3
    assert set(ledger["incentive_scenario"]) == {case.value for case in IncentiveScenario}
    expected_fuel = 220272 / 97
    expected_operating = expected_fuel + 7876 / 12 + 1836
    for row in ledger.to_dict("records"):
        assert row["annual_fuel_cost"] == pytest.approx(expected_fuel)
        assert row["annual_operating_cost"] == pytest.approx(expected_operating)
        assert row["total_operating_cost_over_lifetime"] == pytest.approx(
            12 * expected_operating
        )


@pytest.mark.parametrize(
    "price", [0, -1, float("nan"), float("inf"), -float("inf"), None, "4.50", True]
)
def test_invalid_price_fails_before_calculating_fuel(monkeypatch, price):
    monkeypatch.setitem(fuel.COUNTY_GASOLINE_COSTS, "alameda", price)

    with pytest.raises(ValueError, match="alameda.*finite positive"):
        fuel.calculate_annual_fuel_cost("Alameda County", 24.25)


def test_missing_price_fails_instead_of_using_zero(monkeypatch):
    monkeypatch.delitem(fuel.COUNTY_GASOLINE_COSTS, "alameda")

    with pytest.raises(ValueError, match="Missing gasoline price.*alameda"):
        fuel.calculate_annual_fuel_cost("Alameda County", 24.25)


def test_unknown_county_has_no_price_fallback():
    with pytest.raises(ValueError, match="Missing gasoline price.*unknown"):
        fuel.get_gasoline_cost_for_county("Unknown County")


@pytest.mark.parametrize("price", [0, None])
def test_invalid_price_reaches_the_ledger_as_an_error(monkeypatch, price):
    monkeypatch.setitem(fuel.COUNTY_GASOLINE_COSTS, "alameda", price)

    with pytest.raises(ValueError, match="alameda.*finite positive"):
        build_capex_ledger_df(
            scenario="fuel_fixture",
            housing_type="single-family-detached",
            counties=["Alameda County"],
            electric_appliances={},
            gas_appliances={"vehicle_fuel": lambda county: ICEVehicleAppliance()},
            incentive_scenarios=list(IncentiveScenario),
        )
