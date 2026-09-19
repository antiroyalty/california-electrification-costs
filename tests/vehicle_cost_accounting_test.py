"""Vehicle operating costs remain itemized from the appliance to the ledger."""

from types import SimpleNamespace

import pytest

from appliances import ice_vehicle
from appliances.electric_base import IncentiveScenario
from appliances.electric_vehicle import ElectricVehicleAppliance
from appliances.gas_heating import GasHeatingAppliance
from evaluations.vehicles import vehicle_annual_adders_from_ledger
from helpers import gasoline_cost_helper
from pipeline.steps.step14_build_capital_costs_lifetimes_incentives import (
    build_capex_ledger_df,
)


@pytest.fixture
def fuel_prices_and_mileage(monkeypatch):
    # At 24.25 mpg: 9,700 miles / 24.25 * $5 = $2,000; 4,850 / 24.25 * $4 = $800.
    for county, miles, price in [("alameda", 9700, 5), ("los-angeles", 4850, 4)]:
        monkeypatch.setitem(gasoline_cost_helper.COUNTY_ANNUAL_VMT, county, miles)
        monkeypatch.setitem(gasoline_cost_helper.COUNTY_GASOLINE_COSTS, county, price)


def _vehicle_ledger(vehicle):
    return build_capex_ledger_df(
        scenario="baseline_ice_car_coopt", housing_type="single-family-detached",
        counties=["Alameda County", "Los Angeles County"], electric_appliances={},
        gas_appliances={"vehicle_fuel": lambda county: vehicle},
        incentive_scenarios=list(IncentiveScenario),
    )


@pytest.mark.parametrize("maintenance,insurance", [(283.65, 1836), (700, 1500), (0, 0)])
def test_ledger_and_reporting_use_the_itemized_vehicle_cost(
    fuel_prices_and_mileage, maintenance, insurance,
):
    vehicle = ice_vehicle.ICEVehicleAppliance(
        base_cost=30000, lifetime_years=10,
        annual_maintenance_cost=maintenance, annual_insurance_cost=insurance,
    )
    ledger = _vehicle_ledger(vehicle)
    assert len(ledger) == 2 * len(IncentiveScenario)
    for row in ledger.to_dict("records"):
        fuel = {"alameda": 2000, "los-angeles": 800}[row["county_slug"]]
        expected = {
            "annual_fuel_cost": fuel,
            "annual_maintenance_cost": maintenance,
            "annual_insurance_cost": insurance,
            "annual_operating_cost": fuel + maintenance + insurance,
            "total_operating_cost_over_lifetime": 10 * (fuel + maintenance + insurance),
            "total_cost_of_ownership": 30000 + 10 * (fuel + maintenance + insurance),
        }
        itemized = vehicle.get_cost_breakdown(row["county"])
        for field, value in expected.items():
            assert itemized[field] == pytest.approx(value)
            assert row[field] == pytest.approx(value)
        # The original default ledger used $5,036 here, including $916.35 of
        # maintenance mislabeled as fuel. Custom and zero costs must work too.
        if maintenance == 283.65 and row["county_slug"] == "alameda":
            assert 5036 - row["annual_operating_cost"] == pytest.approx(916.35)

    for incentive in IncentiveScenario:
        alameda = vehicle_annual_adders_from_ledger(
            ledger,
            county_slug="alameda",
            incentive_scenario=incentive.value,
        )
        los_angeles = vehicle_annual_adders_from_ledger(
            ledger,
            county_slug="los-angeles",
            incentive_scenario=incentive.value,
        )
        assert alameda.ice_operating_usd_per_year == pytest.approx(
            2000 + maintenance + insurance)
        assert los_angeles.ice_operating_usd_per_year == pytest.approx(
            800 + maintenance + insurance)


@pytest.mark.parametrize("failure", ["lookup_error", "missing_fuel_field"])
def test_vehicle_fuel_errors_are_not_replaced_with_zero(monkeypatch, failure):
    def fuel_lookup(county, mpg):
        if failure == "lookup_error":
            raise ValueError("Fuel data unavailable for Alameda County")
        return {}

    monkeypatch.setattr(ice_vehicle, "calculate_annual_fuel_cost", fuel_lookup)
    error, message = ((ValueError, "Fuel data unavailable") if failure == "lookup_error"
                      else (KeyError, "annual_fuel_cost"))
    with pytest.raises(error, match=message):
        _vehicle_ledger(ice_vehicle.ICEVehicleAppliance())


def test_vehicle_without_an_itemized_cost_cannot_silently_have_free_fuel():
    vehicle = SimpleNamespace(base_cost=30000, lifetime_years=10,
                              annual_maintenance_cost=100, annual_insurance_cost=200)
    with pytest.raises(AttributeError, match="get_cost_breakdown"):
        _vehicle_ledger(vehicle)


def test_other_appliances_keep_their_operating_costs(monkeypatch):
    def unused_fuel_lookup(*args):
        raise AssertionError("Only an ICE vehicle should request gasoline costs")

    monkeypatch.setattr(ice_vehicle, "calculate_annual_fuel_cost", unused_fuel_lookup)
    ledger = build_capex_ledger_df(
        scenario="fixture", housing_type="single-family-detached", counties=["Alameda County"],
        electric_appliances={"vehicle_charging": lambda county: ElectricVehicleAppliance(
            annual_maintenance_cost=120, annual_insurance_cost=1800)},
        gas_appliances={"heating": lambda county: GasHeatingAppliance()},
        incentive_scenarios=[IncentiveScenario.FULL_INCENTIVES],
    ).set_index("appliance_type")
    assert ledger.loc["vehicle_charging", "annual_operating_cost"] == 1920
    assert ledger.loc["heating", "annual_fuel_cost"] == 0
    assert ledger.loc["heating", "annual_operating_cost"] == 0
