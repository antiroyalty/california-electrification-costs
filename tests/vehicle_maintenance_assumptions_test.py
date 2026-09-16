"""Repair and maintenance allowances represent a full vehicle ownership period."""

import pytest

from appliances import ice_vehicle
from appliances.electric_base import IncentiveScenario
from appliances.electric_vehicle import ElectricVehicleAppliance
from evaluations.vehicles import vehicle_annual_adders_from_ledger
from helpers.gasoline_cost_helper import get_annual_vmt_for_county
from pipeline.steps.step14_build_capital_costs_lifetimes_incentives import (
    build_capex_ledger_df,
)


@pytest.mark.parametrize(
    "vehicle_class,appliance_type,lifetime_maintenance,insurance,fuel",
    [
        (ice_vehicle.ICEVehicleAppliance, "vehicle_fuel", 7876, 1836, 2000),
        (ElectricVehicleAppliance, "vehicle_charging", 3892, 2040, 0),
    ],
)
def test_default_allowance_covers_144000_miles_and_reaches_reporting(
    monkeypatch, vehicle_class, appliance_type, lifetime_maintenance, insurance, fuel,
):
    # Independent totals from CR Table 2.1 at 12,000 miles/year for 12 years:
    # ICE: $1,400 for the first 50k + $3,000 for the next 50k + $3,476 for 44k.
    # BEV: $600 for the first 50k + $1,400 for the next 50k + $1,892 for 44k.
    monkeypatch.setattr(
        ice_vehicle, "calculate_annual_fuel_cost",
        lambda county, mpg: {"annual_fuel_cost": 2000},
    )
    vehicle = vehicle_class()
    assert vehicle.lifetime_years == 12
    assert get_annual_vmt_for_county("Alameda County") == 12000
    expected_maintenance = lifetime_maintenance / 12
    assert vehicle.annual_maintenance_cost == pytest.approx(expected_maintenance)
    expected_operating = expected_maintenance + insurance + fuel
    is_ice = appliance_type == "vehicle_fuel"
    breakdown = vehicle.get_cost_breakdown("Alameda County") if is_ice else (
        vehicle.get_cost_breakdown(IncentiveScenario.NO_INCENTIVES)
    )
    assert breakdown["annual_operating_cost"] == pytest.approx(expected_operating)
    assert breakdown["total_operating_cost_over_lifetime"] == pytest.approx(
        lifetime_maintenance + 12 * (insurance + fuel)
    )

    appliances = {appliance_type: lambda county: vehicle}
    ledger = build_capex_ledger_df(
        scenario="maintenance_fixture", housing_type="single-family-detached",
        counties=["Alameda County"],
        electric_appliances={} if is_ice else appliances,
        gas_appliances=appliances if is_ice else {},
        incentive_scenarios=list(IncentiveScenario),
    )
    for row in ledger.to_dict("records"):
        assert row["annual_maintenance_cost"] == pytest.approx(expected_maintenance)
        assert row["annual_operating_cost"] == pytest.approx(expected_operating)
        assert row["total_operating_cost_over_lifetime"] == pytest.approx(
            lifetime_maintenance + 12 * (insurance + fuel)
        )
        assert row["total_cost_of_ownership"] == pytest.approx(
            row["net_cost"] + lifetime_maintenance + 12 * (insurance + fuel)
        )
    for incentive in IncentiveScenario:
        selected = ledger[ledger.incentive_scenario == incentive.value]
        reported = vehicle_annual_adders_from_ledger(selected)
        column = "ice_operating" if is_ice else "ev_operating"
        assert reported.loc["alameda", column] == pytest.approx(expected_operating)


@pytest.mark.parametrize("vehicle_class", [ice_vehicle.ICEVehicleAppliance, ElectricVehicleAppliance])
@pytest.mark.parametrize("maintenance", [0, 125])
def test_explicit_allowance_is_preserved_with_custom_service_life(
    monkeypatch, vehicle_class, maintenance,
):
    monkeypatch.setattr(
        ice_vehicle, "calculate_annual_fuel_cost",
        lambda county, mpg: {"annual_fuel_cost": 0},
    )
    vehicle = vehicle_class(
        lifetime_years=10, annual_maintenance_cost=maintenance, annual_insurance_cost=0,
    )
    costs = vehicle.get_cost_breakdown("Alameda County") if (
        vehicle_class is ice_vehicle.ICEVehicleAppliance
    ) else vehicle.get_cost_breakdown()
    assert costs["annual_maintenance_cost"] == maintenance
    assert costs["annual_operating_cost"] == maintenance
    assert costs["total_operating_cost_over_lifetime"] == 10 * maintenance
