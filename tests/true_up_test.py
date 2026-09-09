import json
from pathlib import Path

import pandas as pd
import pytest

from tariffs.accounting import ComponentAmounts, CreditBalances, PooledAmount

from tariffs import (
    AverageRetailExportCompensationRate,
    NetSurplusCompensationRate,
    NetSurplusCompensationSchedule,
    TrueUpPolicy,
    Utility,
    calculate_true_up_settlement,
)


ROOT = Path(__file__).resolve().parents[1]
DATA_PATH = ROOT / "data" / "tariffs" / "nsc_rates.csv"
MANIFEST_PATH = ROOT / "data" / "tariffs" / "true_up_source_manifest.json"


def _data() -> pd.DataFrame:
    return pd.read_csv(DATA_PATH)


def _write_data(tmp_path: Path, mutator) -> Path:
    data = _data()
    mutated = mutator(data)
    if mutated is not None:
        data = mutated
    path = tmp_path / "nsc_rates.csv"
    data.to_csv(path, index=False)
    return path


@pytest.mark.parametrize(
    "utility,expected_rate,expected_source",
    [
        ("PG&E", 0.02684, "pge_monthly_nsc_rates_2026-08-10"),
        ("SCE", 0.01697, "sce_monthly_nsc_rates_2026-08-10"),
        ("SDG&E", 0.01306, "sdge_monthly_nsc_rates_2026-08-10"),
    ],
)
def test_resolve_returns_exact_rate_and_source_identity(
    utility,
    expected_rate,
    expected_source,
):
    resolved = NetSurplusCompensationSchedule.from_csv().resolve(utility, "2026-08")
    assert resolved.utility.value == utility
    assert resolved.true_up_month == "2026-08"
    assert resolved.rate_usd_per_kwh == pytest.approx(expected_rate, abs=1e-12)
    assert resolved.source_id == expected_source


def test_resolve_accepts_canonical_utility_aliases():
    resolved = NetSurplusCompensationSchedule.from_csv().resolve("sdge", "2026-08")
    assert resolved.utility is Utility.SDGE


def test_resolve_requires_an_explicit_canonical_available_month():
    schedule = NetSurplusCompensationSchedule.from_csv()
    with pytest.raises(ValueError, match="canonical YYYY-MM"):
        schedule.resolve("PG&E", "2026-8")
    with pytest.raises(KeyError, match=r"true_up_month=2026-09.*Available"):
        schedule.resolve("PG&E", "2026-09")
    with pytest.raises(ValueError, match="Unsupported utility"):
        schedule.resolve("SMUD", "2026-08")


@pytest.mark.parametrize(
    "mutator,message",
    [
        (lambda data: data.drop(columns="rate_unit"), "missing columns"),
        (lambda data: data.iloc[0:0], "data is empty"),
        (
            lambda data: pd.concat([data, data.iloc[[0]]], ignore_index=True),
            "duplicate utility/true_up_month",
        ),
        (
            lambda data: data.assign(true_up_month="2026-8"),
            "canonical YYYY-MM",
        ),
        (lambda data: data.assign(utility="PGE"), "non-canonical utility"),
        (lambda data: data.assign(rate_unit="cents/kWh"), "rate_unit"),
        (lambda data: data.assign(rate_usd_per_kwh="not-a-rate"), "non-numeric"),
        (lambda data: data.assign(rate_usd_per_kwh=float("nan")), "missing"),
        (lambda data: data.assign(rate_usd_per_kwh=float("inf")), "non-finite"),
        (lambda data: data.assign(rate_usd_per_kwh=-0.01), "negative"),
        (lambda data: data.assign(rate_usd_per_kwh=2.684), "magnitude guardrail"),
        (lambda data: data.assign(source_id="missing-source"), "absent from the manifest"),
        (
            lambda data: data.assign(
                source_id="sce_monthly_nsc_rates_2026-08-10"
            ),
            "belongs to SCE, not PG&E",
        ),
    ],
)
def test_schedule_rejects_malformed_or_unlinked_data(
    tmp_path,
    mutator,
    message,
):
    path = _write_data(tmp_path, mutator)
    with pytest.raises(ValueError, match=message):
        NetSurplusCompensationSchedule.from_csv(path)


def test_schedule_rejects_missing_normalized_data(tmp_path):
    with pytest.raises(FileNotFoundError, match="Normalized NSC rate data"):
        NetSurplusCompensationSchedule.from_csv(tmp_path / "missing.csv")


def test_schedule_rejects_missing_source_manifest(tmp_path):
    with pytest.raises(FileNotFoundError, match="True-up source manifest"):
        NetSurplusCompensationSchedule.from_csv(
            DATA_PATH,
            tmp_path / "missing-manifest.json",
        )


def test_schedule_rejects_duplicate_monthly_source_ids(tmp_path):
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    monthly_source = next(
        source
        for source in manifest["sources"]
        if source["source_type"] == "monthly_nsc_rates"
    )
    manifest["sources"].append(dict(monthly_source))
    manifest_path = tmp_path / "duplicate-source-manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ValueError, match="duplicate monthly NSC source IDs"):
        NetSurplusCompensationSchedule.from_csv(DATA_PATH, manifest_path)


def _adjustment_rate(
    utility: Utility,
) -> AverageRetailExportCompensationRate:
    return AverageRetailExportCompensationRate(
        utility=utility,
        true_up_month="2026-08",
        generation_rate_usd_per_kwh=0.05,
        delivery_rate_usd_per_kwh=0.01,
        source_id="synthetic-adjustment-rate-for-arithmetic-test",
    )


def _nsc_rate(utility: Utility) -> NetSurplusCompensationRate:
    return NetSurplusCompensationRate(
        utility=utility,
        true_up_month="2026-08",
        rate_usd_per_kwh=0.03,
        source_id="synthetic-nsc-rate-for-arithmetic-test",
    )


@pytest.mark.parametrize(
    "utility,apply_to_prior,carry,source_id",
    [
        (Utility.PGE, True, True, "pge_nbt_rules_2026-08-10"),
        (Utility.SCE, True, False, "sce_nbt_rules_2026-08-10"),
        (Utility.SDGE, False, False, "sdge_nbt_rules_2026-08-10"),
    ],
)
def test_true_up_policy_is_explicit_and_source_linked(
    utility,
    apply_to_prior,
    carry,
    source_id,
):
    policy = TrueUpPolicy.for_utility(utility)
    assert policy.apply_remaining_eec_to_prior_charges is apply_to_prior
    assert policy.carry_remaining_eec_forward is carry
    assert policy.source_id == source_id


def test_pge_settlement_recoups_surplus_then_refunds_prior_charges_and_carries():
    settlement = calculate_true_up_settlement(
        policy=TrueUpPolicy.for_utility(Utility.PGE),
        annual_import_kwh=4_000,
        annual_export_kwh=5_000,
        opening=CreditBalances(ComponentAmounts(70, 12), 9),
        prior_paid_eligible_energy=ComponentAmounts(15, 5),
        adjustment_rate=_adjustment_rate(Utility.PGE),
        nsc_rate=_nsc_rate(Utility.PGE),
    )

    assert settlement.net_surplus_kwh == 1_000
    assert settlement.annual_import_kwh == 4_000
    assert settlement.annual_export_kwh == 5_000
    assert settlement.generation_adjustment_rate_usd_per_kwh == pytest.approx(0.05)
    assert settlement.delivery_adjustment_rate_usd_per_kwh == pytest.approx(0.01)
    assert settlement.nsc_rate_usd_per_kwh == pytest.approx(0.03)
    assert settlement.generation_eec_adjustment_charge == pytest.approx(50)
    assert settlement.delivery_eec_adjustment_charge == pytest.approx(10)
    assert settlement.accounting.base_applied_to_adjustment.generation_usd == pytest.approx(50)
    assert settlement.accounting.base_applied_to_adjustment.delivery_usd == pytest.approx(10)
    assert settlement.accounting.base_applied_to_prior_payments.generation_usd == pytest.approx(15)
    assert settlement.accounting.base_applied_to_prior_payments.delivery_usd == pytest.approx(2)
    assert settlement.nsc_credit == pytest.approx(30)
    assert settlement.net_bill_adjustment == pytest.approx(-47)
    assert settlement.accounting.closing.base.generation_usd == pytest.approx(5)
    assert settlement.accounting.closing.base.delivery_usd == pytest.approx(0)
    assert settlement.accounting.closing.bonus_usd == pytest.approx(9)
    assert settlement.total_forfeited_credit == pytest.approx(0)


def test_sce_settlement_forfeits_only_credit_left_after_annual_offsets():
    settlement = calculate_true_up_settlement(
        policy=TrueUpPolicy.for_utility(Utility.SCE),
        annual_import_kwh=4_000,
        annual_export_kwh=5_000,
        opening=CreditBalances(PooledAmount(70 + 12), 9),
        prior_paid_eligible_energy=PooledAmount(15 + 5),
        adjustment_rate=_adjustment_rate(Utility.SCE),
        nsc_rate=_nsc_rate(Utility.SCE),
    )

    # SCE NBT 4.b/4.e use one pool: $82 - $60 adjustment - $20 prior payments
    # leaves $2 to forfeit. The $20 offset plus $30 NSC gives a $50 credit.
    # The old $47/$5 answers incorrectly restricted the delivery pool to $2.
    assert settlement.accounting.base_applied_to_adjustment == PooledAmount(60)
    assert settlement.accounting.base_applied_to_prior_payments == PooledAmount(20)
    assert settlement.net_bill_adjustment == pytest.approx(-50)
    assert settlement.accounting.closing.base == PooledAmount(0)
    assert settlement.accounting.forfeited_base.total_usd == pytest.approx(2)
    assert settlement.accounting.closing.bonus_usd == pytest.approx(9)


def test_sdge_settlement_does_not_retroactively_apply_or_carry_excess_eec():
    settlement = calculate_true_up_settlement(
        policy=TrueUpPolicy.for_utility(Utility.SDGE),
        annual_import_kwh=4_000,
        annual_export_kwh=5_000,
        opening=CreditBalances(ComponentAmounts(70, 12), 9),
        prior_paid_eligible_energy=ComponentAmounts(15, 5),
        adjustment_rate=_adjustment_rate(Utility.SDGE),
        nsc_rate=_nsc_rate(Utility.SDGE),
    )

    assert settlement.accounting.base_applied_to_prior_payments.generation_usd == 0
    assert settlement.accounting.base_applied_to_prior_payments.delivery_usd == 0
    assert settlement.net_bill_adjustment == pytest.approx(-30)
    assert settlement.accounting.forfeited_base.generation_usd == pytest.approx(20)
    assert settlement.accounting.forfeited_base.delivery_usd == pytest.approx(2)
    assert settlement.accounting.closing.bonus_usd == pytest.approx(9)


def test_insufficient_banks_leave_a_true_up_charge_after_nsc_credit():
    settlement = calculate_true_up_settlement(
        policy=TrueUpPolicy.for_utility(Utility.PGE),
        annual_import_kwh=4_000,
        annual_export_kwh=5_000,
        opening=CreditBalances(ComponentAmounts(10, 2), 0),
        prior_paid_eligible_energy=ComponentAmounts(0, 0),
        adjustment_rate=_adjustment_rate(Utility.PGE),
        nsc_rate=_nsc_rate(Utility.PGE),
    )

    assert settlement.total_eec_adjustment_charge == pytest.approx(60)
    assert settlement.nsc_credit == pytest.approx(30)
    assert settlement.net_bill_adjustment == pytest.approx(18)


def test_non_net_exporter_has_no_recoupment_or_nsc_but_still_reconciles_bank():
    settlement = calculate_true_up_settlement(
        policy=TrueUpPolicy.for_utility(Utility.SCE),
        annual_import_kwh=5_000,
        annual_export_kwh=4_000,
        opening=CreditBalances(PooledAmount(10 + 4), 2),
        prior_paid_eligible_energy=PooledAmount(8 + 1),
        adjustment_rate=_adjustment_rate(Utility.SCE),
        nsc_rate=_nsc_rate(Utility.SCE),
    )

    assert settlement.net_surplus_kwh == 0
    assert settlement.total_eec_adjustment_charge == 0
    assert settlement.nsc_credit == 0
    assert settlement.net_bill_adjustment == pytest.approx(-9)
    assert settlement.total_forfeited_credit == pytest.approx(5)


@pytest.mark.parametrize(
    "field,value,message",
    [
        ("annual_import_kwh", -1, "annual_import_kwh must be non-negative"),
        ("annual_export_kwh", float("nan"), "annual_export_kwh must be finite"),
        (
            "opening",
            lambda: CreditBalances(ComponentAmounts(float("inf"), 2), 0),
            "generation_usd must be finite",
        ),
        (
            "prior_paid_eligible_energy",
            lambda: ComponentAmounts(0, -0.01),
            "delivery_usd must be finite and non-negative",
        ),
    ],
)
def test_settlement_rejects_invalid_energy_and_account_state(field, value, message):
    kwargs = {
        "policy": TrueUpPolicy.for_utility(Utility.PGE),
        "annual_import_kwh": 4_000,
        "annual_export_kwh": 5_000,
        "opening": CreditBalances(ComponentAmounts(10, 2), 0),
        "prior_paid_eligible_energy": ComponentAmounts(0, 0),
        "adjustment_rate": _adjustment_rate(Utility.PGE),
        "nsc_rate": _nsc_rate(Utility.PGE),
    }
    with pytest.raises(ValueError, match=message):
        # Typed account inputs reject malformed dollars during construction.
        kwargs[field] = value() if callable(value) else value
        calculate_true_up_settlement(**kwargs)


def test_settlement_requires_rate_identity_to_match_policy_and_month():
    kwargs = {
        "policy": TrueUpPolicy.for_utility(Utility.PGE),
        "annual_import_kwh": 4_000,
        "annual_export_kwh": 5_000,
        "opening": CreditBalances(ComponentAmounts(0, 0), 0),
        "prior_paid_eligible_energy": ComponentAmounts(0, 0),
        "adjustment_rate": _adjustment_rate(Utility.PGE),
        "nsc_rate": _nsc_rate(Utility.PGE),
    }
    with pytest.raises(ValueError, match="adjustment_rate utility"):
        calculate_true_up_settlement(
            **{**kwargs, "adjustment_rate": _adjustment_rate(Utility.SCE)}
        )
    with pytest.raises(ValueError, match="nsc_rate utility"):
        calculate_true_up_settlement(
            **{**kwargs, "nsc_rate": _nsc_rate(Utility.SCE)}
        )
    with pytest.raises(ValueError, match="true-up months"):
        calculate_true_up_settlement(
            **{
                **kwargs,
                "nsc_rate": NetSurplusCompensationRate(
                    utility=Utility.PGE,
                    true_up_month="2026-07",
                    rate_usd_per_kwh=0.03,
                    source_id="synthetic-nsc-rate-for-arithmetic-test",
                ),
            }
        )


@pytest.mark.parametrize(
    "rate_factory,kwargs,message",
    [
        (
            NetSurplusCompensationRate,
            {
                "utility": Utility.PGE,
                "true_up_month": "2026-08",
                "rate_usd_per_kwh": 2.684,
                "source_id": "test-source",
            },
            "NSC magnitude guardrail",
        ),
        (
            AverageRetailExportCompensationRate,
            {
                "utility": Utility.SDGE,
                "true_up_month": "2026-08",
                "generation_rate_usd_per_kwh": 8.672,
                "delivery_rate_usd_per_kwh": 0.02427,
                "source_id": "test-source",
            },
            "generation_rate_usd_per_kwh exceeds the 1 USD/kWh guardrail",
        ),
    ],
)
def test_direct_rate_primitives_reject_likely_cents_per_kwh(rate_factory, kwargs, message):
    with pytest.raises(ValueError, match=message):
        rate_factory(**kwargs)


def test_net_importer_settlement_does_not_require_net_surplus_rate_inputs():
    settlement = calculate_true_up_settlement(
        policy=TrueUpPolicy.for_utility(Utility.SCE),
        annual_import_kwh=5_000,
        annual_export_kwh=4_000,
        opening=CreditBalances(PooledAmount(10 + 4), 2),
        prior_paid_eligible_energy=PooledAmount(8 + 1),
        true_up_month="2026-08",
    )

    assert settlement.net_surplus_kwh == 0
    assert settlement.total_eec_adjustment_charge == 0
    assert settlement.nsc_credit == 0
    assert settlement.adjustment_rate_source_id is None
    assert settlement.nsc_rate_source_id is None


def test_net_exporter_settlement_requires_both_source_rate_inputs():
    kwargs = {
        "policy": TrueUpPolicy.for_utility(Utility.SCE),
        "annual_import_kwh": 4_000,
        "annual_export_kwh": 5_000,
        "opening": CreditBalances(PooledAmount(10 + 4), 2),
        "prior_paid_eligible_energy": PooledAmount(8 + 1),
        "true_up_month": "2026-08",
    }
    with pytest.raises(ValueError, match="Positive annual net exports require"):
        calculate_true_up_settlement(**kwargs)
    with pytest.raises(ValueError, match="must be supplied together"):
        calculate_true_up_settlement(
            **kwargs,
            adjustment_rate=_adjustment_rate(Utility.SCE),
        )


@pytest.mark.parametrize("utility", [Utility.PGE, Utility.SCE, Utility.SDGE])
@pytest.mark.parametrize("field", ["opening", "prior_paid_eligible_energy"])
def test_settlement_rejects_credit_pools_that_do_not_match_the_utility(utility, field):
    policy = TrueUpPolicy.for_utility(utility)
    wrong = ComponentAmounts(0, 0) if utility is Utility.SCE else PooledAmount(0)
    kwargs = dict(
        policy=policy,
        annual_import_kwh=1,
        annual_export_kwh=0,
        opening=CreditBalances(policy.energy_amounts(0, 0), 0),
        prior_paid_eligible_energy=policy.energy_amounts(0, 0),
        true_up_month="2026-08",
    )
    kwargs[field] = CreditBalances(wrong, 0) if field == "opening" else wrong
    with pytest.raises(ValueError, match="requires"):
        calculate_true_up_settlement(**kwargs)


def test_sce_pooling_validates_each_component_before_combining():
    with pytest.raises(ValueError, match="generation_usd"):
        TrueUpPolicy.for_utility(Utility.SCE).energy_amounts(-1, 2)
