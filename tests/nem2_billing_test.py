from __future__ import annotations

import copy
import json

import pandas as pd
import pytest

from tariffs import (
    DEFAULT_NEM2_DECISION_SOURCE_ID,
    EnergyFlows,
    ImportRateSchedule,
    NEM2RateTreatment,
    NEM2RateTreatmentSchedule,
    NEM2Scenario,
    NEM2TariffBundle,
    NetSurplusCompensationRate,
    TariffCatalog,
    Utility,
    calculate_nem2_bill,
)
from tariffs.calendar import full_year_hourly_index


def _day_rates() -> dict:
    return {
        "peak": 0.32,
        "offPeak": 0.22,
        "peakHours": [16],
        "offPeakHours": [hour for hour in range(24) if hour != 16],
        "fixedCharge": 0.50,
    }


def _constant_fixture_schedule() -> ImportRateSchedule:
    return ImportRateSchedule(
        utility=Utility.SCE,
        plan_name="FIXTURE-TOU",
        plan_details={
            "summer_end_month": 9,
            "summer": {
                "weekdays": _day_rates(),
                "weekends": _day_rates(),
            },
            "winter": {
                "weekdays": _day_rates(),
                "weekends": _day_rates(),
            },
        },
        non_bypassable_rate=0.02,
        snapshot_as_of="2026-08-09",
        effective_date="2026-01-01",
        source_id="fixture_import_source",
    )


def _fixture_treatment() -> NEM2RateTreatment:
    return NEM2RateTreatment(
        utility=Utility.SCE,
        snapshot_as_of="2026-08-09",
        interval_nbc_components=(("fixture_interval_nbc", 0.01),),
        interval_nbc_rate_usd_per_kwh=0.01,
        monthly_net_consumption_components=(("fixture_recovery", 0.01),),
        monthly_net_consumption_rate_usd_per_kwh=0.01,
        retail_credit_exclusion_rate_usd_per_kwh=0.02,
        monthly_net_consumption_basis="positive_monthly_net_kwh",
        import_source_id="fixture_import_source",
        regulatory_decision_source_id="fixture_decision_source",
        utility_rules_source_id="fixture_rules_source",
        billing_method_source_id="fixture_billing_guide_source",
    )


def _fixture_bundle(
    *,
    nsc_rate_usd_per_kwh: float | None = None,
) -> NEM2TariffBundle:
    nsc_rate = None
    if nsc_rate_usd_per_kwh is not None:
        nsc_rate = NetSurplusCompensationRate(
            utility=Utility.SCE,
            true_up_month="2026-08",
            rate_usd_per_kwh=nsc_rate_usd_per_kwh,
            source_id="fixture_nsc_source",
        )
    return NEM2TariffBundle(
        utility=Utility.SCE,
        scenario=NEM2Scenario(),
        import_schedule=_constant_fixture_schedule(),
        rate_treatment=_fixture_treatment(),
        nsc_rate=nsc_rate,
    )


def test_nem2_scenario_is_explicitly_a_current_rate_counterfactual():
    scenario = NEM2Scenario()

    assert scenario.research_label == "nem2_at_2026_retail_rates"
    assert scenario.tariff_snapshot_date == "2026-08-09"
    assert scenario.true_up_month == "2026-08"


@pytest.mark.parametrize("true_up_month", ["2026-8", "2025-08"])
def test_nem2_scenario_requires_true_up_month_in_billing_year(true_up_month):
    with pytest.raises(ValueError, match="true_up_month"):
        NEM2Scenario(true_up_month=true_up_month)


def test_current_rate_treatment_reconciles_exact_source_components():
    schedule = NEM2RateTreatmentSchedule()
    expected = {
        Utility.PGE: (0.01230, 0.00391, 0.01621),
        Utility.SCE: (0.00779, 0.00619, 0.01398),
        Utility.SDGE: (0.02099, 0.00000, 0.02099),
    }

    for utility, expected_rates in expected.items():
        treatment = schedule.resolve(utility, snapshot_as_of="2026-08-09")
        actual = (
            treatment.interval_nbc_rate_usd_per_kwh,
            treatment.monthly_net_consumption_rate_usd_per_kwh,
            treatment.retail_credit_exclusion_rate_usd_per_kwh,
        )
        assert actual == pytest.approx(expected_rates, abs=1e-12)

    assert schedule.resolve(
        Utility.PGE, snapshot_as_of="2026-08-09"
    ).interval_nbc_component_rates == {
        "public_purpose_program": 0.00614,
        "nuclear_decommissioning": -0.00002,
        "competition_transition": 0.00027,
        "wildfire_fund": 0.00591,
    }
    assert schedule.resolve(
        Utility.SCE, snapshot_as_of="2026-08-09"
    ).monthly_net_consumption_component_rates == {
        "fixed_recovery": 0.00619
    }


def test_rate_treatment_rejects_component_total_that_does_not_reconcile(tmp_path):
    source_path = NEM2RateTreatmentSchedule().data_path
    payload = json.loads(source_path.read_text(encoding="utf-8"))
    payload = copy.deepcopy(payload)
    payload["rates"][0]["interval_nbc_components"][0][
        "rate_usd_per_kwh"
    ] = 0.10614
    data_path = tmp_path / "bad_nem2_rates.json"
    data_path.write_text(json.dumps(payload), encoding="utf-8")

    schedule = NEM2RateTreatmentSchedule(data_path=data_path)
    with pytest.raises(ValueError, match="interval NBC components do not reconcile"):
        schedule.resolve(Utility.PGE, snapshot_as_of="2026-08-09")


def test_rate_treatment_rejects_an_unavailable_snapshot():
    with pytest.raises(KeyError, match="source-locked snapshot"):
        NEM2RateTreatmentSchedule().resolve(
            Utility.SCE,
            snapshot_as_of="2025-01-01",
        )


def test_monthly_bill_separates_energy_nbc_recovery_and_fixed_charges():
    flows = EnergyFlows(
        pd.DatetimeIndex(["2026-01-05 00:00", "2026-01-05 01:00"]),
        [10.0, 0.0],
        [0.0, 4.0],
    )
    ledger = calculate_nem2_bill(flows, _fixture_bundle())
    month = ledger.months[0]

    assert month.offsettable_import_charge_usd == pytest.approx(2.00)
    assert month.retail_export_credit_usd == pytest.approx(0.80)
    assert month.net_energy_balance_usd == pytest.approx(1.20)
    assert month.interval_nbc_charge_usd == pytest.approx(0.10)
    assert month.monthly_net_consumption_kwh == pytest.approx(6.0)
    assert month.monthly_net_consumption_charge_usd == pytest.approx(0.06)
    assert month.fixed_charge_usd == pytest.approx(0.50)
    assert ledger.energy_charge_due_at_true_up_usd == pytest.approx(1.20)
    assert ledger.annual_amount_due_usd == pytest.approx(1.86)


def test_retail_credits_carry_across_months_then_expire_at_true_up():
    flows = EnergyFlows(
        pd.DatetimeIndex(["2026-01-05 16:00", "2026-02-05 00:00"]),
        [0.0, 11.0],
        [10.0, 0.0],
    )
    ledger = calculate_nem2_bill(flows, _fixture_bundle())

    assert ledger.months[0].ending_energy_balance_usd == pytest.approx(-3.0)
    assert ledger.months[1].ending_energy_balance_usd == pytest.approx(-0.8)
    assert ledger.annual_import_kwh == pytest.approx(11.0)
    assert ledger.annual_export_kwh == pytest.approx(10.0)
    assert ledger.energy_charge_due_at_true_up_usd == 0.0
    assert ledger.expired_retail_credit_usd == pytest.approx(0.8)
    assert ledger.nsc_credit_usd == 0.0


def test_interval_nbc_uses_imports_and_recovery_charge_uses_monthly_net_kwh():
    flows = EnergyFlows(
        pd.DatetimeIndex(
            [
                "2026-01-05 00:00",
                "2026-01-05 16:00",
                "2026-02-05 00:00",
                "2026-02-05 16:00",
            ]
        ),
        [5.0, 0.0, 2.0, 0.0],
        [0.0, 2.0, 0.0, 5.0],
    )
    ledger = calculate_nem2_bill(flows, _fixture_bundle(nsc_rate_usd_per_kwh=0.03))

    january, february = ledger.months
    assert january.interval_nbc_charge_usd == pytest.approx(0.05)
    assert january.monthly_net_consumption_kwh == pytest.approx(3.0)
    assert january.monthly_net_consumption_charge_usd == pytest.approx(0.03)
    assert february.interval_nbc_charge_usd == pytest.approx(0.02)
    assert february.monthly_net_consumption_kwh == 0.0
    assert february.monthly_net_consumption_charge_usd == 0.0


def test_annual_net_exporter_receives_nsc_not_retail_credit_cashout():
    flows = EnergyFlows(
        pd.DatetimeIndex(["2026-01-05 00:00", "2026-01-05 16:00"]),
        [2.0, 0.0],
        [0.0, 10.0],
    )
    ledger = calculate_nem2_bill(
        flows,
        _fixture_bundle(nsc_rate_usd_per_kwh=0.03),
    )

    assert ledger.net_surplus_kwh == pytest.approx(8.0)
    assert ledger.expired_retail_credit_usd == pytest.approx(2.6)
    assert ledger.nsc_credit_usd == pytest.approx(0.24)
    assert ledger.nsc_rate_source_id == "fixture_nsc_source"
    assert ledger.annual_amount_due_usd == pytest.approx(0.28)


def test_annual_net_exporter_requires_source_selected_nsc_rate():
    flows = EnergyFlows(
        pd.DatetimeIndex(["2026-01-05 00:00", "2026-01-05 16:00"]),
        [1.0, 0.0],
        [0.0, 2.0],
    )

    with pytest.raises(ValueError, match="requires a source-selected NSC rate"):
        calculate_nem2_bill(flows, _fixture_bundle())


def test_zero_exports_exactly_matches_import_only_retail_bill():
    timestamps = pd.DatetimeIndex(
        ["2026-01-05 00:00", "2026-01-05 16:00", "2026-02-05 00:00"]
    )
    imports = [2.0, 3.0, 4.0]
    tariff = _fixture_bundle()
    ledger = calculate_nem2_bill(
        EnergyFlows(timestamps, imports, [0.0, 0.0, 0.0]),
        tariff,
    )
    expected_energy_usd = sum(
        load * rate
        for load, rate in zip(
            imports,
            tariff.import_schedule.rates_for(timestamps),
        )
    )
    expected_fixed_usd = 1.0

    assert ledger.annual_retail_export_credit_usd == 0.0
    assert ledger.expired_retail_credit_usd == 0.0
    assert ledger.annual_amount_due_usd == pytest.approx(
        expected_energy_usd + expected_fixed_usd
    )


def test_representative_annual_nem2_intermediates_stay_in_ballpark():
    timestamps = pd.date_range("2026-01-01", "2026-12-31 23:00", freq="h")
    imports = [
        0.8 if timestamp.hour <= 7 or timestamp.hour >= 17 else 0.0
        for timestamp in timestamps
    ]
    exports = [
        1.0 if 10 <= timestamp.hour <= 15 else 0.0
        for timestamp in timestamps
    ]
    scenario = NEM2Scenario()
    treatment = NEM2RateTreatmentSchedule().resolve(
        Utility.SCE,
        snapshot_as_of=scenario.tariff_snapshot_date,
    )
    tariff = NEM2TariffBundle(
        utility=Utility.SCE,
        scenario=scenario,
        import_schedule=ImportRateSchedule.resolve(
            Utility.SCE,
            snapshot_as_of=scenario.tariff_snapshot_date,
        ),
        rate_treatment=treatment,
    )
    ledger = calculate_nem2_bill(
        EnergyFlows(timestamps, imports, exports),
        tariff,
    )

    # Assumption-based research guardrails. Exact source-component tests above
    # carry the rate fidelity; these ranges detect broken units or aggregation.
    assert 4_000 < ledger.annual_import_kwh < 5_000
    assert 2_000 < ledger.annual_export_kwh < 2_300
    assert 1_200 < ledger.annual_offsettable_import_charge_usd < 1_600
    assert 400 < ledger.annual_retail_export_credit_usd < 650
    assert 25 < ledger.annual_interval_nbc_charge_usd < 50
    assert 250 < ledger.annual_fixed_charge_usd < 350
    assert 1_000 < ledger.annual_amount_due_usd < 1_500
    assert ledger.annual_amount_due_usd == pytest.approx(
        ledger.annual_interval_nbc_charge_usd
        + ledger.annual_monthly_net_consumption_charge_usd
        + ledger.annual_fixed_charge_usd
        + ledger.energy_charge_due_at_true_up_usd
        - ledger.nsc_credit_usd
    )


def test_real_bundle_inputs_preserve_source_ids_and_reconcile_exclusion_rates():
    treatment_schedule = NEM2RateTreatmentSchedule()
    for utility in Utility:
        scenario = NEM2Scenario()
        import_schedule = ImportRateSchedule.resolve(
            utility,
            snapshot_as_of=scenario.tariff_snapshot_date,
        )
        treatment = treatment_schedule.resolve(
            utility,
            snapshot_as_of=scenario.tariff_snapshot_date,
        )
        bundle = NEM2TariffBundle(
            utility=utility,
            scenario=scenario,
            import_schedule=import_schedule,
            rate_treatment=treatment,
        )

        assert bundle.import_schedule.source_id == treatment.import_source_id
        assert treatment.regulatory_decision_source_id == (
            DEFAULT_NEM2_DECISION_SOURCE_ID
        )
        assert bundle.import_schedule.non_bypassable_rate == pytest.approx(
            treatment.retail_credit_exclusion_rate_usd_per_kwh,
            abs=1e-12,
        )


def test_catalog_builds_source_complete_nem2_optimizer_terms():
    scenario = NEM2Scenario()
    bundle = TariffCatalog().nem2_bundle(Utility.SCE, scenario)
    terms = bundle.optimization_terms_for(
        full_year_hourly_index(scenario.billing_year)
    )

    assert bundle.import_schedule.source_id == "sce_tou_d_prime_2026-06-01"
    assert len(terms.offsettable_rates_usd_per_kwh) == 8760
    assert terms.billing_months.count(1) == 31 * 24
    assert terms.billing_months.count(2) == 28 * 24
    assert terms.interval_nbc_rate_usd_per_kwh == pytest.approx(0.00779)
    assert terms.monthly_net_consumption_rate_usd_per_kwh == pytest.approx(
        0.00619
    )
    assert terms.nsc_rate_usd_per_kwh == pytest.approx(0.01697)
    assert terms.nsc_rate_source_id == "sce_monthly_nsc_rates_2026-08-10"
    retail_rates = bundle.import_schedule.rates_for(
        full_year_hourly_index(scenario.billing_year)
    )
    assert terms.offsettable_rates_usd_per_kwh[0] == pytest.approx(
        retail_rates[0] - 0.01398
    )


def test_nem2_optimizer_terms_reject_the_wrong_billing_year():
    bundle = TariffCatalog().nem2_bundle(Utility.PGE, NEM2Scenario())

    with pytest.raises(ValueError, match="billing year 2026"):
        bundle.optimization_terms_for(full_year_hourly_index(2018))
