"""Hand-calculated checks for optional grid charging under annual NBT billing."""

from math import sqrt

import pandas as pd
import pytest

from pipeline.solver import SolverOptions
from pipeline.steps.step9b_cooptimize_core import CooptInputs, _solve_lp
from tariffs import (
    EnergyFlows, NBTAnnualTerms, NBTScenario, TariffBundle, Utility,
    calculate_nbt_bill,
)

# These short analytical examples need cent-scale distinctions resolved. The
# production $1/year stopping rule would not guarantee these exact toy optima.
PRECISE_SOLVER = SolverOptions(annual_cost_gap_usd=1e-7)


class ImportPrices:
    generation_non_offsettable_rate = 0.0
    delivery_non_offsettable_rate = 0.02

    def __init__(self, prices):
        self.prices = prices

    def rates_for(self, timestamps, component=None):
        if component == "generation":
            return [price - 0.02 for price in self.prices]
        if component == "delivery":
            return [0.02] * len(timestamps)
        return self.prices

    def daily_fixed_charge(self, day):
        return 0.0


class ExportPrices:
    def __init__(self, prices):
        self.prices = prices

    def rates_for(self, timestamps, component="total"):
        return [0.0] * len(timestamps) if component == "delivery" else self.prices


def case(utility, load, pv, imports, exports):
    timestamps = pd.date_range("2026-01-01", periods=len(load), freq="h")
    tariff = TariffBundle(
        utility=utility, scenario=NBTScenario(),
        import_schedule=ImportPrices(imports), export_schedule=ExportPrices(exports),
    )
    terms = NBTAnnualTerms.from_tariff(tariff, timestamps)
    return CooptInputs(load, pv, imports, exports, nbt_terms=terms), tariff, timestamps


def replay(result, tariff, timestamps):
    flows = result.flows
    ledger = calculate_nbt_bill(EnergyFlows(
        timestamps,
        [a + b for a, b in zip(flows.grid_to_load, flows.grid_to_batt)],
        [a + b for a, b in zip(flows.pv_to_grid, flows.batt_to_grid)],
    ), tariff)
    assert result.total_cost == pytest.approx(
        result.capex_annual + ledger.annual_amount_due + result.degradation_cost,
    )
    return ledger


@pytest.mark.parametrize("utility", list(Utility))
def test_grid_charging_saves_the_hand_calculated_spread_and_pays_for_losses(utility):
    inputs, tariff, timestamps = case(utility, [0, 2], [0, 0], [0.1, 0.5], [0, 0])
    settings = dict(fixed_pv_kw=0, fixed_batt_kwh=1, c_batt_kwh=0,
                    solver_options=PRECISE_SOLVER)
    off = _solve_lp(inputs, allow_grid_charging=False, **settings)
    on = _solve_lp(inputs, allow_grid_charging=True, **settings)
    # A 1 kWh battery moves 0.7 kWh internally between 20% and 90% charge.
    charged, delivered = 0.7 / sqrt(0.96), 0.7 * sqrt(0.96)
    assert sum(off.flows.grid_to_batt) == 0
    assert replay(off, tariff, timestamps).annual_amount_due == pytest.approx(1)
    assert on.flows.grid_to_batt == pytest.approx([charged, 0])
    assert on.flows.batt_to_load == pytest.approx([0, delivered])
    assert replay(on, tariff, timestamps).annual_amount_due == pytest.approx(
        charged * 0.1 + (2 - delivered) * 0.5,
    )


@pytest.mark.parametrize("utility", list(Utility))
def test_grid_charged_energy_cannot_earn_export_credits_without_solar(utility):
    inputs, tariff, timestamps = case(utility, [0, 2], [0, 0], [0.1, 0.5], [0, 10])
    result = _solve_lp(inputs, fixed_pv_kw=0, fixed_batt_kwh=1,
                       c_batt_kwh=0, allow_grid_charging=True, allow_batt_export=True,
                       solver_options=PRECISE_SOLVER)
    assert sum(result.flows.grid_to_batt) > 0
    assert sum(result.flows.batt_to_grid) == 0
    assert replay(result, tariff, timestamps).annual_credit_earned == 0


@pytest.mark.parametrize("utility", list(Utility))
def test_solar_exports_and_grid_charging_can_share_one_battery(utility):
    inputs, tariff, timestamps = case(
        utility, [0, 0, 5], [1, 0, 0], [0.1, 0.1, 0.5], [0, 1, 0],
    )
    result = _solve_lp(inputs, fixed_pv_kw=1, fixed_batt_kwh=4,
                       c_pv_kw=0, c_batt_kwh=0, allow_grid_charging=True,
                       solver_options=PRECISE_SOLVER)
    assert sum(result.flows.grid_to_batt) > 0
    assert result.flows.pv_to_batt == pytest.approx([1, 0, 0])
    assert result.flows.batt_to_grid == pytest.approx([0, 0.96, 0])
    assert sum(result.flows.batt_to_load) == pytest.approx(
        0.96 * sum(result.flows.grid_to_batt),
    )
    replay(result, tariff, timestamps)


@pytest.mark.parametrize("utility", list(Utility))
def test_expensive_storage_can_be_declined_when_grid_charging_is_allowed(utility):
    inputs, tariff, timestamps = case(utility, [0, 2], [0, 0], [0.1, 0.5], [0, 0])
    result = _solve_lp(inputs, fixed_pv_kw=0, allow_grid_charging=True,
                       solver_options=PRECISE_SOLVER)
    assert result.batt_kwh == pytest.approx(0)
    assert replay(result, tariff, timestamps).annual_amount_due == pytest.approx(1)
