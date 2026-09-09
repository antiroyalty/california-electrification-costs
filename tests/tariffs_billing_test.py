import pandas as pd
import pytest

from tariffs import EnergyFlows, NBTScenario, TariffCatalog, calculate_nbt_bill
from pipeline.steps.step12_evaluate_electricity_rates import process_county_scenario_nem3
from tariffs.models import TariffBundle, Utility
from tariffs.accounting import ComponentAmounts, CreditBalances, PooledAmount


class TeachingImportSchedule:
    """200 imported kWh give $20/$40 eligible charges and $4 NBCs."""

    generation_non_offsettable_rate = 0.0
    delivery_non_offsettable_rate = 0.02

    def rates_for(self, timestamps, component=None):
        return [{None: 0.32, "generation": 0.10, "delivery": 0.22}[component]] * len(timestamps)

    def daily_fixed_charge(self, day):
        return 25.0


class TeachingExportSchedule:
    def __init__(self, generation_credits_usd, delivery_credit_usd):
        self.generation_credits_usd = generation_credits_usd
        self.delivery_credit_usd = delivery_credit_usd

    def rates_for(self, timestamps, component):
        if component == "generation":
            return [self.generation_credits_usd[t.month - 1] / 100 for t in timestamps]
        if component == "delivery":
            return [self.delivery_credit_usd / 100] * len(timestamps)
        raise ValueError(f"Unknown teaching component: {component}")


def _teaching_bill(
    utility, generation_credits_usd, delivery_credit_usd=5, bonus_rate=0,
    *, billing_year=2026, **kwargs,
):
    timestamps = pd.DatetimeIndex([
        f"{billing_year}-{month:02d}-01 {hour:02d}:00"
        for month in range(1, len(generation_credits_usd) + 1)
        for hour in (0, 1)
    ])
    tariff = TariffBundle(
        utility=Utility.parse(utility),
        scenario=NBTScenario(
            billing_year=billing_year, true_up_month=f"{billing_year}-08",
            include_acc_plus=bonus_rate > 0,
        ),
        import_schedule=TeachingImportSchedule(),
        export_schedule=TeachingExportSchedule(generation_credits_usd, delivery_credit_usd),
        acc_plus_rate=bonus_rate,
        acc_plus_source_id="teaching-bonus" if bonus_rate > 0 else None,
    )
    return calculate_nbt_bill(
        EnergyFlows(
            timestamps,
            [200, 0] * len(generation_credits_usd),
            [0, 100] * len(generation_credits_usd),
        ),
        tariff,
        **kwargs,
    )


@pytest.mark.parametrize("utility,expected_usd", [("SCE", 54), ("PG&E", 64)])
def test_worked_example_5_uses_utility_credit_eligibility(utility, expected_usd):
    # SCE NBT 3.a.i/ii and 4.b permit all $35 to offset the combined $60.
    ledger = _teaching_bill(utility, [30])
    assert ledger.months[0].amount_due == expected_usd
    assert ledger.annual_amount_due == expected_usd


def test_sce_pooling_prevents_unused_generation_credit_while_delivery_is_paid():
    # Twelve Example 5 months save $120; no eligible generation was paid earlier.
    ledger = _teaching_bill("SCE", [30] * 12)
    assert ledger.annual_amount_due == 648
    assert ledger.expired_base_credit == 0


def test_worked_examples_1_to_3_through_hourly_billing_and_next_year_opening():
    all_used = _teaching_bill("PG&E", [10] * 12, bonus_rate=0.0088)
    first = _teaching_bill("PG&E", [20] * 11 + [30], bonus_rate=0.0088)
    following = _teaching_bill(
        "PG&E", [20] * 11 + [10], bonus_rate=0.0088,
        billing_year=2027, opening=first.closing,
    )
    without_bank = _teaching_bill(
        "PG&E", [20] * 11 + [10], bonus_rate=0.0088, billing_year=2027,
    )
    assert all_used.annual_amount_due == pytest.approx(877.44)
    assert first.annual_amount_due == pytest.approx(757.44)
    assert first.closing == CreditBalances(ComponentAmounts(10, 0), 0)
    assert first.unused_credit == pytest.approx(10)
    assert following.annual_amount_due == pytest.approx(757.44)
    assert without_bank.annual_amount_due == pytest.approx(767.44)
    assert following.annual_credit_applied > following.annual_credit_earned
    assert following.unused_credit == pytest.approx(0)
    assert following.credit_saturation_ratio == pytest.approx(0)
    assert following.closing == CreditBalances(ComponentAmounts(0, 0), 0)


@pytest.mark.parametrize("utility,second_year_usd", [("PG&E", 348), ("SCE", 468), ("SDG&E", 468)])
def test_worked_example_4_carries_only_the_balance_that_survives_settlement(
    utility, second_year_usd,
):
    first = _teaching_bill(utility, [25] * 12, 45)
    following = _teaching_bill(utility, [15] * 12, 35, billing_year=2027, opening=first.closing)
    assert first.annual_amount_due == 348
    assert first.unused_credit == pytest.approx(120)
    assert first.closing.base.total_usd + first.expired_base_credit == pytest.approx(120)
    assert following.annual_amount_due == second_year_usd
    assert following.unused_credit == pytest.approx(0)


@pytest.mark.parametrize("utility", ["PG&E", "SCE", "SDG&E"])
def test_bonus_opening_balance_remains_available_after_annual_settlement(utility):
    first = _teaching_bill(utility, [20], 40, bonus_rate=0.35)
    following = _teaching_bill(utility, [20], 40, billing_year=2027, opening=first.closing)
    assert first.annual_amount_due == 0
    assert first.closing.bonus_usd == 6
    assert following.annual_amount_due == 23
    assert following.unused_credit == pytest.approx(0)


def test_sce_monthly_pooling_can_change_timing_without_changing_annual_payment():
    # Old billing charged $84 + $64 and refunded $10 at settlement: also $138.
    ledger = _teaching_bill("SCE", [0, 30], delivery_credit_usd=5)
    assert [month.amount_due for month in ledger.months] == [84, 54]
    assert ledger.annual_amount_due == 138
    assert ledger.true_up_settlement.net_bill_adjustment == 0


@pytest.mark.parametrize(
    "utility,wrong", [("SCE", ComponentAmounts(0, 0)), ("PG&E", PooledAmount(0))]
)
def test_billing_rejects_an_opening_bank_with_the_wrong_credit_restrictions(utility, wrong):
    with pytest.raises(ValueError, match="requires"):
        _teaching_bill(utility, [30], opening=CreditBalances(wrong, 0))


def test_zero_eligible_component_does_not_fail_from_monthly_roundoff():
    schedule = TeachingImportSchedule()
    schedule.generation_non_offsettable_rate = 0.10
    tariff = TariffBundle(
        utility=Utility.PGE,
        scenario=NBTScenario(include_acc_plus=False),
        import_schedule=schedule,
        export_schedule=TeachingExportSchedule([0], 0),
        acc_plus_rate=0,
        acc_plus_source_id=None,
    )
    flows = EnergyFlows(
        pd.date_range("2026-01-01", periods=3, freq="h"), [0.1, 0.2, 0.3], [0, 0, 0]
    )
    # Generation's entire $0.10/kWh rate is non-offsettable: eligible charge is zero.
    # Subtracting separately summed monthly charges introduces a tiny negative.
    ledger = calculate_nbt_bill(flows, tariff)
    assert ledger.months[0].accounting.eligible_energy.generation_usd == 0
    assert ledger.annual_amount_due == pytest.approx(25 + 0.6 * 0.32)


def _single_month_flows(import_kwh, export_kwh):
    timestamps = pd.date_range("2026-01-01", periods=len(import_kwh), freq="h")
    return EnergyFlows(timestamps, import_kwh, export_kwh)


def test_energy_flows_reject_simultaneous_interval_import_and_export():
    flows = _single_month_flows([1.0], [0.1])
    with pytest.raises(ValueError, match="simultaneously import and export"):
        flows.validated_frame()


def test_energy_flows_reject_length_mismatch_instead_of_reindexing_or_filling():
    flows = EnergyFlows(pd.date_range("2026-01-01", periods=2, freq="h"), [1.0], [0.0, 0.0])
    with pytest.raises(ValueError, match="identical lengths"):
        flows.validated_frame()


def test_billing_rejects_profile_year_that_differs_from_explicit_billing_year():
    tariff = TariffCatalog().bundle("SCE", NBTScenario(billing_year=2026, nbt_vintage=2026))
    flows = EnergyFlows(pd.date_range("2018-01-01", periods=2, freq="h"), [1.0, 0.0], [0.0, 1.0])
    with pytest.raises(ValueError, match="calendarized to billing year 2026"):
        calculate_nbt_bill(flows, tariff)


@pytest.mark.parametrize("true_up_month", ["2026-8", "2025-08"])
def test_nbt_scenario_requires_canonical_true_up_month_in_billing_year(
    true_up_month,
):
    with pytest.raises(ValueError, match="true_up_month"):
        NBTScenario(billing_year=2026, true_up_month=true_up_month)


def test_acc_plus_is_separate_from_base_eec_and_can_offset_fixed_charges():
    tariff = TariffCatalog().bundle("SCE", NBTScenario(nbt_vintage=2026))
    flows = _single_month_flows([0.0], [100.0])
    ledger = calculate_nbt_bill(flows, tariff)
    month = ledger.months[0].accounting
    assert month.earned.base.total_usd > 0
    assert month.earned.bonus_usd == pytest.approx(1.60)
    assert month.base_applied.total_usd == 0
    assert month.bonus_applied_usd == pytest.approx(month.fixed_charge_usd)
    assert month.payment_usd == 0


def test_true_up_only_recredits_energy_charges_paid_after_acc_plus():
    tariff = TariffCatalog().bundle("SCE", NBTScenario(nbt_vintage=2026))
    flows = EnergyFlows(
        pd.DatetimeIndex(
            ["2026-01-05 12:00", "2026-02-05 18:00", "2026-08-05 18:00"]
        ),
        [0.0, 130.0, 0.0],
        [60.0, 0.0, 60.0],
    )

    ledger = calculate_nbt_bill(flows, tariff)
    settlement = ledger.true_up_settlement
    expected_cash_paid_eligible_energy = 0.0
    acc_plus_applied_to_energy = 0.0
    for month in ledger.months:
        accounting = month.accounting
        remaining_energy = accounting.eligible_energy.total_usd - accounting.base_applied.total_usd
        month_acc_plus_to_energy = min(
            accounting.bonus_applied_usd,
            remaining_energy,
        )
        acc_plus_applied_to_energy += month_acc_plus_to_energy
        expected_cash_paid_eligible_energy += (
            remaining_energy - month_acc_plus_to_energy
        )

    true_up_eligible_energy = settlement.accounting.prior_paid_eligible_energy.total_usd
    assert acc_plus_applied_to_energy > 0.0
    assert true_up_eligible_energy == pytest.approx(
        expected_cash_paid_eligible_energy
    )


def test_sdge_nbc_is_not_offset_by_base_export_credit():
    tariff = TariffCatalog().bundle("SDG&E", NBTScenario(nbt_vintage=2026, include_acc_plus=False))
    # Import during super-off-peak and export during the exceptionally valuable
    # August evening period. Annual import and export energy remain equal.
    flows = EnergyFlows(
        pd.DatetimeIndex(["2026-08-03 00:00", "2026-08-03 18:00"]),
        [100.0, 0.0],
        [0.0, 100.0],
    )
    ledger = calculate_nbt_bill(flows, tariff)
    month = ledger.months[0].accounting
    assert month.non_bypassable_charge_usd == pytest.approx(2.099)
    assert month.earned.base.total_usd > month.eligible_energy.total_usd
    assert month.payment_usd == pytest.approx(
        month.non_bypassable_charge_usd + month.fixed_charge_usd
    )


def test_representative_annual_bill_and_credit_intermediates_stay_in_ballpark():
    timestamps = pd.date_range("2026-01-01", "2026-12-31 23:00", freq="h")
    imports = []
    exports = []
    for timestamp in timestamps:
        if timestamp.hour <= 7 or timestamp.hour >= 17:
            imports.append(0.8)
            exports.append(0.0)
        elif 10 <= timestamp.hour <= 15:
            imports.append(0.0)
            exports.append(1.0)
        else:
            imports.append(0.0)
            exports.append(0.0)

    tariff = TariffCatalog().bundle("SCE", NBTScenario(nbt_vintage=2026))
    ledger = calculate_nbt_bill(EnergyFlows(timestamps, imports, exports), tariff)

    # Assumption-based research guardrails. These intentionally leave room for
    # tariff updates while catching cents/dollars errors and broken aggregation.
    assert 4_000 < ledger.annual_import_kwh < 5_000
    assert 2_000 < ledger.annual_export_kwh < 2_300
    assert 50 < ledger.annual_base_export_credit < 500
    assert 30 < ledger.annual_acc_plus_credit < 50
    assert 1_000 < ledger.annual_amount_due < 4_000


@pytest.mark.parametrize("utility", ["PG&E", "SCE", "SDG&E"])
def test_zero_exports_exactly_matches_import_only_tariff_bill(utility):
    """Paper-critical: NBT adds no billing asymmetry when exports are zero."""

    timestamps = pd.date_range("2026-01-01", "2026-12-31 23:00", freq="h")
    imports = [0.35 + 0.45 * (timestamp.hour < 8 or timestamp.hour >= 17) for timestamp in timestamps]
    tariff = TariffCatalog().bundle(utility, NBTScenario())

    ledger = calculate_nbt_bill(
        EnergyFlows(timestamps, imports, [0.0] * len(timestamps)),
        tariff,
    )
    hourly_charge = sum(
        load * rate
        for load, rate in zip(imports, tariff.import_schedule.rates_for(timestamps))
    )
    daily_charge = sum(
        tariff.import_schedule.daily_fixed_charge(day)
        for day in timestamps.normalize().unique()
    )

    assert ledger.annual_base_export_credit == 0.0
    assert ledger.annual_acc_plus_credit == 0.0
    assert ledger.true_up_settlement.net_surplus_kwh == 0.0
    assert ledger.true_up_settlement.adjustment_rate_source_id is None
    assert ledger.true_up_settlement.nsc_rate_source_id is None
    assert ledger.annual_amount_due == pytest.approx(hourly_charge + daily_charge, abs=1e-6)


@pytest.mark.parametrize(
    "utility,expected_adjustment_source,expected_nsc_source,expected_rates",
    [
        (
            "SCE",
            "sce_monthly_eec_adjustment_rates_2026-08-11",
            "sce_monthly_nsc_rates_2026-08-10",
            (0.04576, 0.01291, 0.01697),
        ),
        (
            "SDG&E",
            "sdge_annual_true_up_methodology_2026-08-10",
            "sdge_monthly_nsc_rates_2026-08-10",
            (0.08672, 0.02427, 0.01306),
        ),
    ],
)
def test_net_exporter_bill_uses_exact_source_locked_august_true_up_rates(
    utility,
    expected_adjustment_source,
    expected_nsc_source,
    expected_rates,
):
    tariff = TariffCatalog().bundle(
        utility,
        NBTScenario(include_acc_plus=False, true_up_month="2026-08"),
    )
    flows = EnergyFlows(
        pd.DatetimeIndex(["2026-08-03 00:00", "2026-08-03 12:00"]),
        [1.0, 0.0],
        [0.0, 10.0],
    )
    ledger = calculate_nbt_bill(flows, tariff)
    settlement = ledger.true_up_settlement

    generation_rate, delivery_rate, nsc_rate = expected_rates
    assert settlement.net_surplus_kwh == pytest.approx(9.0)
    assert settlement.generation_adjustment_rate_usd_per_kwh == pytest.approx(
        generation_rate
    )
    assert settlement.delivery_adjustment_rate_usd_per_kwh == pytest.approx(
        delivery_rate
    )
    assert settlement.nsc_rate_usd_per_kwh == pytest.approx(nsc_rate)
    assert settlement.generation_eec_adjustment_charge == pytest.approx(
        9.0 * generation_rate
    )
    assert settlement.delivery_eec_adjustment_charge == pytest.approx(
        9.0 * delivery_rate
    )
    assert settlement.nsc_credit == pytest.approx(9.0 * nsc_rate)
    assert settlement.adjustment_rate_source_id == expected_adjustment_source
    assert settlement.nsc_rate_source_id == expected_nsc_source
    assert ledger.annual_amount_due == pytest.approx(
        ledger.monthly_amount_due + settlement.net_bill_adjustment
    )
    assert ledger.unused_credit == pytest.approx(
        ledger.ending_base_credit_bank + ledger.expired_base_credit
    )


def test_pge_net_exporter_fails_loudly_until_adjustment_rate_is_source_locked():
    tariff = TariffCatalog().bundle(
        "PG&E",
        NBTScenario(include_acc_plus=False, true_up_month="2026-08"),
    )
    flows = EnergyFlows(
        pd.DatetimeIndex(["2026-08-03 00:00", "2026-08-03 12:00"]),
        [1.0, 0.0],
        [0.0, 10.0],
    )

    with pytest.raises(KeyError, match=r"PG&E.*found 0.*Available: \[\]"):
        calculate_nbt_bill(flows, tariff)


def test_step12_file_integration_calendarizes_tmy_to_explicit_tariff_year(tmp_path):
    county = "alameda"
    county_dir = tmp_path / county
    county_dir.mkdir()
    timestamps = pd.date_range("2018-01-01", periods=8760, freq="h")
    imports = [0.6 if hour.hour < 8 or hour.hour >= 17 else 0.0 for hour in timestamps]
    exports = [0.8 if 10 <= hour.hour <= 15 else 0.0 for hour in timestamps]
    pd.DataFrame(
        {
            "timestamp": timestamps,
            "nem3.imports.kwh": imports,
            "nem3.exports.kwh": exports,
        }
    ).to_csv(county_dir / "loadprofiles_for_rates_alameda.csv", index=False)

    result = process_county_scenario_nem3(
        str(tmp_path),
        county,
        "PG&E",
        "E-ELEC",
        nbt_scenario=NBTScenario(billing_year=2026, nbt_vintage=2026),
    )
    assert 500 < result["E-ELEC"] < 3_000
