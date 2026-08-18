import numpy as np
import pytest

from appliances.incentive_policy import PolicyRegime
from figure_builder.dispatch import DispatchInputs
from figure_builder.policy_cases import (
    FULL_HOURLY_POLICY_CASES,
    POLICY_CASES,
    policy_case,
)
from tariffs import ExportCompensationRegime, NEM2OptimizationTerms


def test_policy_matrix_has_exactly_four_unique_cases():
    assert len(POLICY_CASES) == 4
    assert len({case.case_id for case in POLICY_CASES}) == 4
    assert {
        (
            case.export_compensation_regime,
            case.capital_policy_regime,
        )
        for case in POLICY_CASES
    } == {
        (export_regime, capital_regime)
        for export_regime in ExportCompensationRegime
        for capital_regime in PolicyRegime
    }


def test_full_hourly_cases_exclude_only_the_known_slow_nbt_itc_case():
    excluded = set(POLICY_CASES) - set(FULL_HOURLY_POLICY_CASES)

    assert excluded == {
        policy_case(
            ExportCompensationRegime.NBT_2026,
            PolicyRegime.ITC_2025,
        )
    }


def test_export_regimes_apply_their_documented_pv_sizing_limits():
    assert (
        ExportCompensationRegime.NBT_2026.max_pv_to_annual_load_ratio
        == pytest.approx(1.5)
    )
    assert (
        ExportCompensationRegime.NEM2_AT_2026_RETAIL_RATES
        .max_pv_to_annual_load_ratio
        == pytest.approx(1.0)
    )


def test_nem2_dispatch_inputs_preserve_exact_settlement_terms():
    terms = NEM2OptimizationTerms(
        offsettable_rates_usd_per_kwh=(0.25, 0.30),
        billing_months=(1, 1),
        interval_nbc_rate_usd_per_kwh=0.01,
        monthly_net_consumption_rate_usd_per_kwh=0.005,
        nsc_rate_usd_per_kwh=0.02,
        nsc_rate_source_id="fixture_nsc_source",
    )
    dispatch = DispatchInputs(
        slug="fixture",
        util="SCE",
        load=np.array([1.0, 2.0]),
        pv_gen_per_kw=np.array([0.0, 0.5]),
        p_imp=np.array([0.25, 0.30]),
        p_exp=np.array([0.25, 0.30]),
        export_compensation_regime=(
            ExportCompensationRegime.NEM2_AT_2026_RETAIL_RATES
        ),
        nem2_terms=terms,
    )

    inputs = dispatch.coopt_inputs()

    assert inputs.nem2_terms is terms
    assert inputs.max_pv_to_annual_load_ratio == pytest.approx(1.0)
    assert inputs.import_rates == [0.25, 0.30]
    assert inputs.export_rates == [0.25, 0.30]


def test_export_regime_parser_rejects_an_unlabeled_case():
    with pytest.raises(ValueError, match="Unsupported export-compensation"):
        ExportCompensationRegime.parse("nem2-ish")
