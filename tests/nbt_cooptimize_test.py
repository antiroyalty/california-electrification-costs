"""Physical sizing and dispatch must minimize the independently checked NBT bill."""

from dataclasses import replace

import pandas as pd
import pytest

from evaluations.eac import compute_eac_from_inputs, crf
from pipeline.steps.step9b_cooptimize_core import (
    CooptInputs, _solve_lp, build_monthly_hourly_inputs,
)
from tariffs import EnergyFlows, NBTScenario, TariffCatalog, calculate_nbt_bill
from tariffs.models import TariffBundle, Utility
from tariffs.optimization import NBTOptimizationTerms
from tariffs.accounting_equations import NumericArithmetic
from tariffs.accounting_scip import ScipArithmetic
from tariffs.true_up import AverageRetailExportCompensationRate, NetSurplusCompensationRate


class ImportPrices:
    generation_non_offsettable_rate = 0.0
    delivery_non_offsettable_rate = 0.02

    def __init__(self, generation=0.10, delivery=0.22, fixed=25):
        self.generation, self.delivery, self.fixed = generation, delivery, fixed

    def rates_for(self, timestamps, component=None):
        value = {None: self.generation + self.delivery,
                 "generation": self.generation, "delivery": self.delivery}[component]
        return [value] * len(timestamps)

    def daily_fixed_charge(self, day):
        return self.fixed


class ExportPrices:
    def __init__(self, generation=0.30, delivery=0.05):
        self.generation, self.delivery = generation, delivery

    def rates_for(self, timestamps, component="total"):
        value = {"total": self.generation + self.delivery,
                 "generation": self.generation, "delivery": self.delivery}[component]
        return [value] * len(timestamps)


class RateSchedule:
    def __init__(self, rate):
        self.rate = rate

    def resolve(self, utility, month):
        if self.rate is None:
            raise KeyError("No teaching adjustment rate")
        assert self.rate.utility is utility
        assert self.rate.true_up_month == month
        return self.rate


def _case(utility="PG&E", *, bonus=0, adjustment=True, imports=None, exports=None):
    utility = Utility.parse(utility)
    tariff = TariffBundle(
        utility=utility, scenario=NBTScenario(include_acc_plus=bonus > 0),
        import_schedule=imports or ImportPrices(), export_schedule=exports or ExportPrices(),
        acc_plus_rate=bonus, acc_plus_source_id="teaching-bonus" if bonus else None,
    )
    adjustment_schedule = RateSchedule(
        AverageRetailExportCompensationRate(utility, "2026-08", 0.05, 0.01, "teaching-adjustment")
        if adjustment else None
    )
    nsc_schedule = RateSchedule(
        NetSurplusCompensationRate(utility, "2026-08", 0.03, "teaching-nsc")
    )
    timestamps = pd.date_range("2026-01-01", periods=2, freq="h")
    terms = NBTOptimizationTerms.from_tariff(
        tariff, timestamps, adjustment_schedule=adjustment_schedule, nsc_schedule=nsc_schedule,
    )
    inputs = CooptInputs(
        [200, 0], [0, 100], list(terms.import_rates), list(terms.export_rates), nbt_terms=terms,
    )
    return inputs, tariff, timestamps, adjustment_schedule, nsc_schedule


def _replay(case, result):
    _, tariff, timestamps, adjustment_schedule, nsc_schedule = case
    flows = result.flows
    ledger = calculate_nbt_bill(
        EnergyFlows(
            timestamps,
            [a + b for a, b in zip(flows.grid_to_load, flows.grid_to_batt)],
            [a + b for a, b in zip(flows.pv_to_grid, flows.batt_to_grid)],
        ), tariff, adjustment_schedule=adjustment_schedule, nsc_schedule=nsc_schedule,
    )
    assert result.nbt_settlement.amount_due_usd == pytest.approx(ledger.annual_amount_due)
    assert result.import_cost - result.export_credit == pytest.approx(ledger.annual_amount_due)
    assert result.total_cost == pytest.approx(
        result.capex_annual + ledger.annual_amount_due + result.degradation_cost
    )
    assert result.nbt_settlement.earned_credit_usd == pytest.approx(ledger.annual_credit_earned)
    assert sum(result.nbt_settlement.annual.closing_base) == pytest.approx(
        ledger.ending_base_credit_bank
    )
    assert sum(result.nbt_settlement.annual.forfeited_base) == pytest.approx(
        ledger.expired_base_credit
    )
    return ledger


@pytest.mark.parametrize("utility,payment", [("PG&E", 64), ("SCE", 54), ("SDG&E", 64)])
def test_example_5_fixed_physical_system_uses_the_billing_rules(utility, payment):
    case = _case(utility)
    result = _solve_lp(case[0], fixed_pv_kw=1, fixed_batt_kwh=0)
    assert _replay(case, result).annual_amount_due == pytest.approx(payment)


@pytest.mark.parametrize("utility", ["PG&E", "SCE", "SDG&E"])
def test_nbt_optimizer_and_reporting_share_battery_remaining_value(utility):
    case = _case(utility)
    result = _solve_lp(
        case[0], fixed_pv_kw=1, fixed_batt_kwh=10, c_pv_kw=0, c_batt_kwh=1000,
    )
    bill = _replay(case, result).annual_amount_due
    report = compute_eac_from_inputs(
        None, {"storage_capex": 10000}, annual_bill_electric=bill,
    )

    assert result.capex_annual == pytest.approx(1116.42, abs=0.01)
    assert report.capex_storage == pytest.approx(result.capex_annual)
    assert report.total() == pytest.approx(result.total_cost)


@pytest.mark.parametrize("utility,pv_kw,bill", [("PG&E", 2 / 3, 29 + 110 / 3), ("SCE", 12 / 7, 29)])
def test_sizing_stops_when_extra_credits_cannot_repay_extra_equipment(utility, pv_kw, bill):
    case = _case(utility)
    result = _solve_lp(case[0], fixed_batt_kwh=0, c_pv_kw=20 / crf(0.07, 25))
    assert result.pv_kw == pytest.approx(pv_kw)
    assert _replay(case, result).annual_amount_due == pytest.approx(bill)
    # The previous full-earned-credit objective drives PV to the 3 kW sizing cap.
    proxy = _solve_lp(replace(case[0], nbt_terms=None), fixed_batt_kwh=0,
                      c_pv_kw=20 / crf(0.07, 25))
    assert proxy.pv_kw == pytest.approx(3)
    assert result.pv_kw < proxy.pv_kw


@pytest.mark.parametrize("utility,battery_delivery", [("PG&E", 0.7 * 0.96 ** 0.5), ("SCE", 0)])
def test_dispatch_stores_energy_when_export_credit_cannot_pay_the_remaining_bill(
    utility, battery_delivery,
):
    imports = ImportPrices(generation=0, delivery=1, fixed=0)
    imports.delivery_non_offsettable_rate = 0
    case = _case(utility, imports=imports, exports=ExportPrices(1, 0))
    inputs = replace(case[0], load_kwh=[0, 1], pv_gen_per_kw=[1, 0])
    result = _solve_lp(inputs, fixed_pv_kw=1, fixed_batt_kwh=1,
                       c_pv_kw=0, c_batt_kwh=0)
    assert result.flows.batt_to_load[1] == pytest.approx(battery_delivery)
    _replay(case, result)


def test_cap_curtails_the_old_surplus_example_and_preserves_its_reference_bill():
    case = _case("SCE", exports=ExportPrices(0.30, 0.45))
    inputs = replace(case[0], load_kwh=[100, 0])
    # Preserve the old $26.70 example as a detailed tariff reference. Its
    # 110 exported kWh against 100 imported kWh are outside the research domain.
    ledger = calculate_nbt_bill(
        EnergyFlows(case[2], [100, 0], [0, 110]), case[1],
        adjustment_schedule=case[3], nsc_schedule=case[4],
    )
    assert ledger.true_up_settlement.net_surplus_kwh == pytest.approx(10)
    assert ledger.true_up_settlement.total_eec_adjustment_charge == pytest.approx(0.6)
    assert ledger.true_up_settlement.nsc_credit == pytest.approx(0.3)
    assert ledger.annual_amount_due == pytest.approx(26.7)
    result = _solve_lp(inputs, fixed_pv_kw=1.1, fixed_batt_kwh=0)
    capped = _replay(case, result)
    assert capped.annual_export_kwh <= capped.annual_import_kwh + 1e-6
    assert capped.true_up_settlement.net_surplus_kwh == 0
    assert capped.annual_amount_due == pytest.approx(27)


def test_missing_adjustment_is_accepted_only_when_lower_bound_has_no_surplus():
    case = _case(adjustment=False)
    result = _solve_lp(case[0], fixed_pv_kw=1, fixed_batt_kwh=0)
    assert result.nbt_settlement.net_surplus_kwh == 0
    assert _replay(case, result).annual_amount_due == pytest.approx(64)


def test_export_cap_makes_missing_surplus_rate_irrelevant_to_optimization():
    case = _case(adjustment=False, bonus=0.10)
    inputs = replace(case[0], load_kwh=[100, 0])
    with pytest.raises(ValueError, match="cannot be certified.*positive annual net exports"):
        inputs.nbt_terms.bill([100, 0], [0, 150], [1, 1], NumericArithmetic())
    result = _solve_lp(inputs, fixed_pv_kw=1.5, fixed_batt_kwh=0)
    assert _replay(case, result).true_up_settlement.net_surplus_kwh == 0


@pytest.mark.parametrize("utility", ["PG&E", "SCE", "SDG&E"])
@pytest.mark.parametrize("weights", [[1, 1], [31, 28], [0.3, 0.1]])
def test_annual_export_cap_uses_weights_and_curtails_fixed_pv(utility, weights):
    prices = ImportPrices(generation=1, delivery=0, fixed=0)
    prices.delivery_non_offsettable_rate = 0
    case = _case(utility, imports=prices, exports=ExportPrices(0.1, 0))
    inputs = replace(case[0], load_kwh=[100, 0])
    fixed_pv_kw = 1.5 * weights[0] / weights[1]
    result = _solve_lp(inputs, weights=weights, fixed_pv_kw=fixed_pv_kw, fixed_batt_kwh=0)
    annual_imports = sum(w * v for w, v in zip(weights, result.flows.grid_to_load))
    annual_exports = sum(w * v for w, v in zip(weights, result.flows.pv_to_grid))
    assert result.pv_kw == pytest.approx(fixed_pv_kw)
    assert annual_exports == pytest.approx(annual_imports)
    assert result.flows.pv_to_grid[1] == pytest.approx(100 * weights[0] / weights[1])
    assert result.nbt_settlement.net_surplus_kwh == pytest.approx(0, abs=1e-8)
    # Available generation remains 150% of load. Only actual meter exports are capped.
    assert fixed_pv_kw * 100 * weights[1] == pytest.approx(1.5 * annual_imports)


def test_annual_export_cap_applies_when_pv_capacity_is_optimized():
    prices = ImportPrices(generation=1, delivery=0, fixed=0)
    prices.delivery_non_offsettable_rate = 0
    case = _case("SCE", imports=prices, exports=ExportPrices(0.1, 0))
    inputs = replace(case[0], load_kwh=[100, 0])
    result = _solve_lp(inputs, fixed_batt_kwh=0, c_pv_kw=1 / crf(0.07, 25))
    assert result.pv_kw == pytest.approx(1)
    assert result.flows.pv_to_grid[1] == pytest.approx(100)


def test_annual_export_cap_counts_battery_exports():
    class EveningExports(ExportPrices):
        def rates_for(self, timestamps, component="total"):
            return [rate if t.hour == 2 else 0 for t, rate in
                    zip(timestamps, super().rates_for(timestamps, component))]

    case = _case("SCE", exports=EveningExports(0.30, 0.45))
    timestamps = pd.date_range("2026-01-01", periods=3, freq="h")
    terms = NBTOptimizationTerms.from_tariff(
        case[1], timestamps, adjustment_schedule=case[3], nsc_schedule=case[4],
    )
    inputs = CooptInputs(
        [0, 100, 0], [100, 0, 0], list(terms.import_rates), list(terms.export_rates),
        nbt_terms=terms,
    )
    result = _solve_lp(inputs, fixed_pv_kw=1.5, fixed_batt_kwh=250)
    flows = result.flows
    annual_imports = sum(flows.grid_to_load) + sum(flows.grid_to_batt)
    annual_exports = sum(flows.pv_to_grid) + sum(flows.batt_to_grid)
    assert annual_exports <= annual_imports + 1e-6
    assert result.nbt_settlement.net_surplus_kwh == pytest.approx(0, abs=1e-6)


def test_annual_export_cap_preserves_the_zero_system():
    case = _case()
    result = _solve_lp(case[0], fixed_pv_kw=0, fixed_batt_kwh=0)
    assert _replay(case, result).annual_export_kwh == 0


@pytest.mark.parametrize("utility", ["PG&E", "SCE", "SDG&E"])
def test_real_tariff_and_weighted_monthly_inputs_preserve_accounting(utility):
    tariff = TariffCatalog().bundle(utility, NBTScenario())
    timestamps = pd.date_range("2026-01-01", periods=8760, freq="h")
    terms = NBTOptimizationTerms.from_tariff(tariff, timestamps)
    inputs = CooptInputs([1] * 8760, [0.5] * 8760,
                         list(terms.import_rates), list(terms.export_rates), nbt_terms=terms)
    grouped, weights = build_monthly_hourly_inputs(inputs, year=2026)
    assert len(grouped.nbt_terms.billing_months) == 288
    assert grouped.nbt_terms.fixed_charges_usd == terms.fixed_charges_usd
    assert grouped.nbt_terms.adjustment_rate == terms.adjustment_rate
    assert grouped.nbt_terms.nsc_rate == terms.nsc_rate
    result = _solve_lp(grouped, weights=weights, cycle_monthly=True,
                       fixed_pv_kw=0, fixed_batt_kwh=0)
    ledger = calculate_nbt_bill(EnergyFlows(timestamps, [1] * 8760, [0] * 8760), tariff)
    assert result.nbt_settlement.amount_due_usd == pytest.approx(ledger.annual_amount_due)


@pytest.mark.parametrize("utility", ["PG&E", "SCE", "SDG&E"])
def test_excluded_bonus_leaves_linear_accounting_with_exact_bill_replay(utility):
    from pyscipopt import Model

    tariff = TariffCatalog().bundle(utility, NBTScenario(include_acc_plus=False))
    timestamps = pd.DatetimeIndex([
        "2026-01-01 00:00", "2026-01-01 12:00",
        "2026-02-01 00:00", "2026-02-01 12:00",
    ])
    imports, exports = [200, 0, 200, 0], [0, 100, 0, 100]
    terms = NBTOptimizationTerms.from_tariff(tariff, timestamps)
    assert terms.export_rates == pytest.approx(tariff.export_schedule.rates_for(timestamps))
    model = Model()
    model.hideOutput()
    try:
        bill = terms.bill(
            [model.addVar(lb=v, ub=v) for v in imports],
            [model.addVar(lb=v, ub=v) for v in exports],
            [1] * len(timestamps), ScipArithmetic(model),
            missing_rate_lower_bound=terms.adjustment_rate is None,
        )
        assert all(c.getConshdlrName() != "nonlinear" for c in model.getConss())
        model.setObjective(bill.amount_due_usd)
        model.optimize()
        assert model.getStatus() == "optimal"
        ledger = calculate_nbt_bill(EnergyFlows(timestamps, imports, exports), tariff)
        assert ledger.true_up_settlement.net_surplus_kwh == 0
        assert model.getObjVal() == pytest.approx(ledger.annual_amount_due)
        assert ledger.annual_acc_plus_credit == 0
        assert ledger.ending_acc_plus_credit_bank == 0
    finally:
        model.freeProb()


@pytest.mark.parametrize("backend", ["highs", "cbc"])
def test_nbt_terms_cannot_silently_use_a_linear_price_objective(backend):
    with pytest.raises(ValueError, match="NBT accounting requires SCIP"):
        _solve_lp(_case()[0], solver_backend=backend)


def test_mismatched_prices_cannot_override_nbt_accounting():
    inputs = replace(_case()[0], export_rates=[100, 100])
    with pytest.raises(ValueError, match="do not match the NBT"):
        _solve_lp(inputs)


def test_optimistic_missing_rate_bound_cannot_be_reported_as_a_numeric_bill():
    terms = _case(adjustment=False)[0].nbt_terms
    with pytest.raises(ValueError, match="lower-bound bill cannot be reported"):
        terms.bill([200, 0], [0, 300], [1, 1], NumericArithmetic(),
                   missing_rate_lower_bound=True)


@pytest.mark.parametrize("weights", [[1, 0], [1, -1], [1, float("nan")]])
def test_invalid_interval_weights_stop_before_optimization(weights):
    with pytest.raises(ValueError, match="weights must be finite and positive"):
        _solve_lp(_case()[0], weights=weights)


@pytest.mark.parametrize("timestamps", [[], ["2026-01-01", "2026-01-01"],
                                         ["2026-02-01", "2026-01-01"]])
def test_invalid_calendar_cannot_change_monthly_accounting(timestamps):
    with pytest.raises(ValueError, match="nonempty, unique, and ordered"):
        NBTOptimizationTerms.from_tariff(_case()[1], timestamps)


def test_rate_from_another_utility_cannot_enter_the_objective():
    terms = _case()[0].nbt_terms
    wrong_rate = AverageRetailExportCompensationRate(
        Utility.SCE, "2026-08", 0.05, 0.01, "wrong-utility-source"
    )
    with pytest.raises(ValueError, match="must match the utility"):
        replace(terms, adjustment_rate=wrong_rate)


def test_nonfinite_total_rate_is_rejected_even_when_components_are_finite():
    class InvalidTotal(ImportPrices):
        def rates_for(self, timestamps, component=None):
            if component is None:
                return [float("nan")] * len(timestamps)
            return super().rates_for(timestamps, component)

    with pytest.raises(ValueError, match="total import rates must be finite"):
        _case(imports=InvalidTotal())
