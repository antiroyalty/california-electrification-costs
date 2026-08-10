import pandas as pd
import pytest

from tariffs import EnergyFlows, NBTScenario, TariffCatalog, calculate_nbt_bill
from pipeline.steps.step12_evaluate_electricity_rates import process_county_scenario_nem3


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


def test_acc_plus_is_separate_from_base_eec_and_can_offset_fixed_charges():
    tariff = TariffCatalog().bundle("SCE", NBTScenario(nbt_vintage=2026))
    flows = _single_month_flows([0.0], [100.0])
    ledger = calculate_nbt_bill(flows, tariff)
    month = ledger.months[0]
    assert month.base_export_credit_earned > 0
    assert month.acc_plus_credit_earned == pytest.approx(1.60)
    assert month.base_credit_applied == 0
    assert month.acc_plus_credit_applied == pytest.approx(month.fixed_charge)
    assert month.amount_due == 0


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
    month = ledger.months[0]
    assert month.non_bypassable_charge == pytest.approx(2.099)
    assert month.base_export_credit_earned > month.import_energy_charge
    assert month.amount_due == pytest.approx(month.non_bypassable_charge + month.fixed_charge)


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
