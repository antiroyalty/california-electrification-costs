import json
from pathlib import Path

import pandas as pd
import pytest

from tariffs import EnergyFlows, NBTScenario, TariffCatalog, calculate_nbt_bill
from pipeline.steps.step12_evaluate_electricity_rates import process_county_scenario_nem3
from tariffs.models import TariffBundle, Utility
from tariffs.models import annual_net_surplus_kwh, require_annual_export_cap


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
    utility, generation_credits_usd, delivery_credit_usd=5,
    *, billing_year=2026,
):
    timestamps = pd.DatetimeIndex([
        f"{billing_year}-{month:02d}-01 {hour:02d}:00"
        for month in range(1, len(generation_credits_usd) + 1)
        for hour in (0, 1)
    ])
    tariff = TariffBundle(
        utility=Utility.parse(utility),
        scenario=NBTScenario(
            billing_year=billing_year,
        ),
        import_schedule=TeachingImportSchedule(),
        export_schedule=TeachingExportSchedule(generation_credits_usd, delivery_credit_usd),
    )
    return calculate_nbt_bill(
        EnergyFlows(
            timestamps,
            [200, 0] * len(generation_credits_usd),
            [0, 100] * len(generation_credits_usd),
        ),
        tariff,
    )


@pytest.mark.parametrize("utility,expected_usd", [("SCE", 54), ("PG&E", 64)])
def test_worked_example_5_uses_utility_credit_eligibility(utility, expected_usd):
    # SCE NBT 3.a.i/ii and 4.b permit all $35 to offset the combined $60.
    ledger = _teaching_bill(utility, [30])
    assert ledger.annual_amount_due == pytest.approx(expected_usd, abs=1e-10, rel=0)


def test_sce_pooling_prevents_unused_generation_credit_while_delivery_is_paid():
    # Twelve Example 5 months save $120; no eligible generation was paid earlier.
    ledger = _teaching_bill("SCE", [30] * 12)
    assert ledger.annual_amount_due == pytest.approx(648, abs=1e-10, rel=0)
    assert ledger.unused_credit == 0


def test_sce_monthly_pooling_can_change_timing_without_changing_annual_payment():
    # Old billing charged $84 + $64 and refunded $10 at settlement: also $138.
    ledger = _teaching_bill("SCE", [0, 30], delivery_credit_usd=5)
    assert ledger.annual_amount_due == 138


def test_zero_eligible_component_does_not_fail_from_monthly_roundoff():
    schedule = TeachingImportSchedule()
    schedule.generation_non_offsettable_rate = 0.10
    tariff = TariffBundle(
        utility=Utility.PGE,
        scenario=NBTScenario(),
        import_schedule=schedule,
        export_schedule=TeachingExportSchedule([0], 0),
    )
    flows = EnergyFlows(
        pd.date_range("2026-01-01", periods=3, freq="h"), [0.1, 0.2, 0.3], [0, 0, 0]
    )
    # Generation's entire $0.10/kWh rate is non-offsettable: eligible charge is zero.
    # Subtracting separately summed monthly charges introduces a tiny negative.
    ledger = calculate_nbt_bill(flows, tariff)
    assert ledger.accounting.eligible_charge_usd[0] == 0
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
    with pytest.raises(ValueError, match="match the tariff billing year"):
        calculate_nbt_bill(flows, tariff)


def test_sdge_nbc_is_not_offset_by_base_export_credit():
    tariff = TariffCatalog().bundle("SDG&E", NBTScenario(nbt_vintage=2026))
    # Import during super-off-peak and export during the exceptionally valuable
    # August evening period. Annual import and export energy remain equal.
    flows = EnergyFlows(
        pd.DatetimeIndex(["2026-08-03 00:00", "2026-08-03 18:00"]),
        [100.0, 0.0],
        [0.0, 100.0],
    )
    ledger = calculate_nbt_bill(flows, tariff)
    month = ledger.accounting
    assert month.non_bypassable_charge_usd == pytest.approx(2.099)
    assert month.earned_credit_usd > sum(month.eligible_charge_usd)
    assert month.amount_due_usd == pytest.approx(
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
    assert 50 < ledger.annual_credit_earned < 500
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

    assert ledger.annual_credit_earned == 0.0
    assert ledger.annual_amount_due == pytest.approx(hourly_charge + daily_charge, abs=1e-6)


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


@pytest.mark.parametrize("utility,plan", [("PG&E", "E-ELEC"), ("SCE", "TOU-D-PRIME"),
                                         ("SDG&E", "EV-TOU-5")])
@pytest.mark.parametrize("annual_export_kwh,accepted", [(99, True), (100, True),
                                                      (100 + 5e-7, True), (101, False)])
def test_county_reporting_checks_the_annual_export_cap(
    tmp_path, utility, plan, annual_export_kwh, accepted,
):
    county_dir = tmp_path / "teaching-county"
    county_dir.mkdir()
    pd.DataFrame({
        "timestamp": ["2026-01-01 00:00", "2026-01-01 12:00"],
        "nem3.imports.kwh": [100, 0], "nem3.exports.kwh": [0, annual_export_kwh],
    }).to_csv(county_dir / "loadprofiles_for_rates_teaching-county.csv", index=False)
    if not accepted:
        with pytest.raises(ValueError, match="annual exported kWh <= annual imported kWh"):
            process_county_scenario_nem3(str(tmp_path), "teaching-county", utility, plan)
    else:
        result = process_county_scenario_nem3(str(tmp_path), "teaching-county", utility, plan)
        assert result[plan] >= 0


@pytest.mark.parametrize("imports,exports", [(0, 0), (100, 99), (100, 100),
                                            (0, 1e-6), (100, 100 + 5e-7)])
def test_annual_energy_equality_tolerance_is_numeric_only(imports, exports):
    require_annual_export_cap(imports, exports)
    assert annual_net_surplus_kwh(imports, exports) == 0


@pytest.mark.parametrize("imports,exports", [(0, 1.01e-6), (100, 100 + 2e-6), (100, 101)])
def test_annual_export_cap_rejects_excess_above_numeric_tolerance(imports, exports):
    assert annual_net_surplus_kwh(imports, exports) > 0
    with pytest.raises(ValueError, match="annual exported kWh <= annual imported kWh"):
        require_annual_export_cap(imports, exports)


@pytest.mark.parametrize("imports,exports", [(float("nan"), 1), (1, float("inf")),
                                            (-1, 1), (1, -1)])
def test_annual_export_cap_rejects_invalid_energy(imports, exports):
    with pytest.raises(ValueError, match="finite and non-negative"):
        require_annual_export_cap(imports, exports)


# These outputs were captured before removing the monthly accounting engine.
# They remain old-method evidence; new expected values do not replace them.
MONTHLY_REFERENCE = json.loads(
    (Path(__file__).parent / "fixtures/nbt_monthly_reference.json").read_text()
)


@pytest.mark.parametrize("case", MONTHLY_REFERENCE["cases"],
                         ids=lambda c: f"{c['utility']}-{c['name']}")
def test_annual_settlement_against_frozen_monthly_examples(case):
    ledger = _teaching_bill(case["utility"], case["generation_credit_usd"],
                           case["delivery_credit_usd"])
    # Only SDG&E's late-credit example changes: $10 now offsets January's
    # generation charge. PG&E/SCE already applied that credit within the year.
    expected_change = 10 if case["utility"] == "SDG&E" and case["name"] == "late_credit" else 0
    assert ledger.annual_amount_due == pytest.approx(case["old_bill_usd"] - expected_change)
    assert ledger.unused_credit == pytest.approx(case["old_unused_credit_usd"] - expected_change)


@pytest.mark.parametrize("utility", ["PG&E", "SCE", "SDG&E"])
def test_credit_timing_does_not_change_annual_pool_totals(utility):
    early = _teaching_bill(utility, [30, 0])
    late = _teaching_bill(utility, [0, 30])
    assert early.annual_amount_due == late.annual_amount_due == 138
    assert early.annual_credit_applied == late.annual_credit_applied == 40


@pytest.mark.parametrize("utility", ["PG&E", "SCE", "SDG&E"])
def test_unused_credit_has_no_next_year_value(utility):
    # Example 4 formerly gave PG&E a $120 advantage in the second year.
    # Every modeled year now starts independently, without an opening bank.
    first = _teaching_bill(utility, [25] * 12, 45)
    following = _teaching_bill(utility, [15] * 12, 35, billing_year=2027)
    assert first.annual_amount_due == 348
    assert first.unused_credit == pytest.approx(120, abs=1e-10, rel=0)
    assert following.annual_amount_due == pytest.approx(468, abs=1e-10, rel=0)


@pytest.mark.parametrize("utility", ["PG&E", "SCE", "SDG&E"])
def test_numeric_research_bill_rejects_annual_net_exports(utility):
    tariff = TariffCatalog().bundle(utility, NBTScenario())
    with pytest.raises(ValueError, match="annual exported kWh <= annual imported kWh"):
        calculate_nbt_bill(_single_month_flows([100, 0], [0, 101]), tariff)


def test_archived_bonus_example_explains_the_excluded_current_year_benefit():
    example = next(c for c in MONTHLY_REFERENCE["excluded_reference_examples"]
                   if c["name"] == "example_1_bonus")
    ledger = _teaching_bill("PG&E", [10] * 12)
    assert ledger.annual_amount_due == example["base_only_bill_usd"]
    assert ledger.annual_amount_due - example["old_bill_usd"] == pytest.approx(
        example["exports_kwh"] * example["bonus_rate"]
    )


@pytest.mark.parametrize("invalid", [float("nan"), float("inf")])
def test_nonfinite_meter_values_stop_numeric_reporting(invalid):
    tariff = TariffCatalog().bundle("SCE", NBTScenario())
    with pytest.raises(ValueError, match="finite and non-negative"):
        calculate_nbt_bill(_single_month_flows([invalid, 0], [0, 0]), tariff)
