"""Regression tests for source-derived values in Claim-1 figure captions."""

from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

from figure_builder.charts import (
    plot_marginal_solar_value_ladder,
    solar_generation_weighted_export_rate,
)
from figure_builder.recipes import (
    _claim1_summary_fragment,
    _claim1_cost_scope_fragment,
    _claim2_fragment,
    _claim3_fragment,
    _installer_rule_fragment,
    _limitations_fragment,
    _mechanism_fragment,
    _policy_matrix_fragment,
    _tariff_status_fragment,
    build_installer_rule_figure,
    build_policy_matrix_figure,
    build_publication_scope,
    build_statewide_claims,
    build_tariff_status_block,
)
from figure_builder.policy_cases import POLICY_CASES


def test_marginal_value_meta_preserves_peak_rate_and_storage_adjustment():
    dispatch = SimpleNamespace(
        p_imp=[0.20] * 9 + [0.50],
        p_exp=[0.08] * 5 + [0.12] * 5,
        pv_gen_per_kw=[0.0] * 5 + [1.0] * 5,
        yield_per_kw=1_500.0,
    )
    prices = SimpleNamespace(pv_lcoe=lambda *_args: 0.19)

    fig, meta = plot_marginal_solar_value_ladder(dispatch, prices)
    import matplotlib.pyplot as plt

    plt.close(fig)

    # The annual mean is $0.10, but solar is generated only in the $0.12 hours.
    assert meta["v_export"] == pytest.approx(0.12)
    assert meta["peak_import_rate"] == pytest.approx(0.50)
    assert meta["v_peak"] == pytest.approx(0.45)
    assert meta["pv_lcoe"] == pytest.approx(0.19)
    assert meta["storage_margin_after_solar"] == pytest.approx(0.26)
    assert meta["peak_share_pct"] == pytest.approx(10.0)
    assert meta["round_trip_eff"] == pytest.approx(0.90)


@pytest.mark.parametrize(
    "dispatch,message",
    [
        (
            SimpleNamespace(p_exp=[0.05], pv_gen_per_kw=[1.0, 2.0]),
            "identical non-zero lengths",
        ),
        (
            SimpleNamespace(p_exp=[0.05, 0.06], pv_gen_per_kw=[0.0, 0.0]),
            "positive annual total",
        ),
        (
            SimpleNamespace(p_exp=[0.05, float("nan")], pv_gen_per_kw=[1.0, 1.0]),
            "finite values",
        ),
    ],
)
def test_solar_weighted_export_rate_rejects_malformed_inputs(dispatch, message):
    with pytest.raises(ValueError, match=message):
        solar_generation_weighted_export_rate(dispatch)


def test_mechanism_caption_uses_metrics_instead_of_stale_rate_literals():
    prices_now = SimpleNamespace(
        batt_net_per_kwh=1_460.64,
        pv_net_per_kw=3_300.0,
    )
    prices_2025 = SimpleNamespace(
        batt_net_per_kwh=1_022.448,
        pv_net_per_kw=2_310.0,
    )
    html = _mechanism_fragment(
        prices_now,
        prices_2025,
        {
            "before": {
                "pv_flat": 2.0,
                "pv_max": 4.0,
                "market_batt_kwh": 5.53,
            },
            "after": {
                "pv_flat": 1.5,
                "pv_max": 3.0,
                "market_batt_kwh": 0.0,
            },
        },
        {
            "v_export": 0.057469,
            "peak_import_rate": 0.48,
            "v_peak": 0.432,
            "pv_lcoe": 0.196,
            "storage_margin_after_solar": 0.236,
            "peak_share_pct": 10.0,
            "round_trip_eff": 0.90,
        },
        {
            "pv_100": 4.0,
            "pv_100_rte": 4.4,
            "batt_min": 40.0,
            "pv_min": 4.2,
            "cover_min": 1.05,
        },
        "image-a",
        "image-b",
        "image-c",
        "test resolution",
    )

    assert "~$0.480/kWh across the top 10% of modeled import-price hours" in html
    assert "~$0.057/kWh when hourly prices are weighted by modeled PV generation" in html
    assert "solar-coincident export value of <strong>$0.057/kWh</strong>" in html
    assert "effective avoided-import value of <strong>$0.432/kWh</strong>" in html
    assert "<strong>$0.236/kWh</strong>" in html
    assert "not profit" in html
    assert "not a solar-plus-storage LCOE" in html
    assert "today&rsquo;s modeled <strong>$1,461/kWh net</strong>" in html
    assert "12&times;24 sensitivity chooses 5.53&nbsp;kWh" in html
    assert "full 8,760-hour current-law solve chooses 0.00&nbsp;kWh" in html
    assert "2025 market diamond is a weighted 12&times;24" in html
    assert "current-law market diamond is a separate full 8,760-hour" in html
    assert "2-3" not in html
    assert "2&ndash;3" not in html
    assert "~$0.40/kWh" not in html
    assert "~$0.05/kWh" not in html


def test_claim1_summary_is_derived_from_exact_market_observations():
    before = [
        {"market_batt_kwh": 0.0},
        {"market_batt_kwh": 0.0},
        {"market_batt_kwh": 5.5329},
        {"market_batt_kwh": 7.4963},
    ]
    after = [
        {"market_batt_kwh": 0.0},
        {"market_batt_kwh": 0.0},
        {"market_batt_kwh": 0.0},
        {"market_batt_kwh": 0.0001515},
    ]

    html = _claim1_summary_fragment(before, after, [500.0, 500.0, 800.0, 1_200.0])

    assert "0 of 4 above 0.1&nbsp;kWh" in html
    assert "5.53&ndash;7.50&nbsp;kWh" in html
    assert "weighted 12&times;24 sensitivity" in html
    assert '<span class="num">0 of 4</span>' in html
    assert '<span class="num">2 of 4</span>' in html
    assert '<span class="num">$500&ndash;$1,200</span>' in html
    assert "0&ndash;0.2 kWh" not in html


def test_claim1_cost_scope_uses_both_policy_regime_prices():
    prices_now = SimpleNamespace(
        batt_net_per_kwh=1_460.64,
        pv_net_per_kw=3_300.0,
    )
    prices_2025 = SimpleNamespace(
        batt_net_per_kwh=1_022.448,
        pv_net_per_kw=2_310.0,
    )

    html = _claim1_cost_scope_fragment(prices_now, prices_2025)

    assert "$2,310/kW with the 2025 ITC" in html
    assert "$3,300/kW under current law" in html
    assert "$25&ndash;$1,500/kWh" in html
    assert "$1,022.448/kWh and $1,460.64/kWh" in html
    assert "dedicated 8,760-hour solve" in html
    assert "across the whole sweep" not in html


def test_installer_rule_caption_uses_county_export_schedule_mean():
    prices = SimpleNamespace(
        batt_net_per_kwh=1_460.64,
        pv_net_per_kw=3_300.0,
    )

    html = _installer_rule_fragment(
        prices,
        5.4,
        0.057469,
        {"thr_fix": 800.0, "thr_free": 500.0},
        "image",
    )

    assert "PV-generation-weighted export credit is ~$0.057/kWh" in html
    assert "~$0.05/kWh" not in html


def test_policy_matrix_fragment_reports_dynamic_results_and_counterfactual_scope():
    rows = []
    summaries = {}
    for case in POLICY_CASES:
        summaries[case.case_id] = {
            "median_pv_kw": 7.25,
            "median_battery_kwh": 0.0,
            "nontrivial_battery_count": 0,
            "pv_sizing_limit_count": 4,
        }
        for county in ("a", "b", "c", "d"):
            rows.append(
                {
                    "export_compensation_regime": (
                        case.export_compensation_regime.value
                    ),
                    "battery_kwh": 0.0,
                    "at_pv_sizing_limit": True,
                    "county_slug": county,
                }
            )
    html = _policy_matrix_fragment(
        pd.DataFrame(rows),
        {"case_summaries": summaries, "county_count": 4},
        {
            "exact_pv_kw": 7.317,
            "exact_battery_kwh": 0.0,
            "pv_difference_kw": 0.0001,
            "battery_difference_kwh": 0.0,
        },
        "image",
    )

    assert "not a historical reconstruction" in html
    assert "8 of 8" in html
    assert "only <strong>0</strong>" in html
    assert "7.317&nbsp;kW PV" in html
    assert "0.0001&nbsp;kW PV" in html
    assert "weighted 12&times;24 resolution" in html


def test_publication_scope_removes_inherited_draft_claims(tmp_path):
    doc = tmp_path / "claims.html"
    doc.write_text(
        '<div class="buildinfo"><span>commit <b>c459506</b></span>'
        '<span>branch <b>main</b></span><span><b>260</b> tests passing</span></div>'
        '<section class="claim" id="claim-1">\n'
        '<!-- INSTALLER-RULE-END -->\n'
        '<!-- POLICY-MATRIX-START -->\n'
        '<figure>current NEM 2 comparison</figure>\n'
        '<!-- POLICY-MATRIX-END -->\n'
        '<figure>stale discount-rate result</figure>\n'
        '<div class="fig-pending">Figure TBD</div>\n'
        '</section>\n<!-- ============ CLAIM 2 ============ -->\n'
        '<section class="claim" id="limitations">old NBC limitation</section>\n'
        '<footer>Generated from commit c459506 &middot; x</footer>'
    )
    prices_now = SimpleNamespace(pv_net_per_kw=3_300.0, batt_net_per_kwh=1_460.64)
    prices_2025 = SimpleNamespace(pv_net_per_kw=2_310.0, batt_net_per_kwh=1_022.448)

    with (
        patch("figure_builder.recipes.live_prices", side_effect=[prices_now, prices_2025]),
        patch("figure_builder.recipes.tariff_metadata", return_value=_tariff_metadata_fixture()),
        patch("figure_builder.recipes.expected_claim_counties", return_value={"a", "b"}),
        patch("figure_builder.recipes.git_short_sha", return_value="74e2f33"),
    ):
        build_publication_scope(doc=doc)

    html = doc.read_text()
    assert "stale discount-rate result" not in html
    assert "current NEM 2 comparison" in html
    assert "Figure TBD" not in html
    assert "old NBC limitation" not in html
    assert "$1,460.64/kWh" in html
    assert "weighted 12&times;24 sensitivity model" in html
    assert "unweighted across 2 modeled counties" in html
    assert "branch" not in html
    assert "tests passing" not in html
    assert "Generated from commit 74e2f33" in html

    with (
        patch("figure_builder.recipes.live_prices", side_effect=[prices_now, prices_2025]),
        patch("figure_builder.recipes.tariff_metadata", return_value=_tariff_metadata_fixture()),
        patch("figure_builder.recipes.expected_claim_counties", return_value={"a", "b"}),
        patch("figure_builder.recipes.git_short_sha", return_value="74e2f33"),
    ):
        build_publication_scope(doc=doc)
    assert doc.read_text() == html


def test_installer_rule_builder_passes_county_schedule_mean_to_caption(tmp_path):
    doc = tmp_path / "claims.html"
    doc.write_text("before\n<!-- MECH-BLOCK-END -->\nafter")
    prices = SimpleNamespace(
        regime="post_itc_2026",
        batt_net_per_kwh=1_460.64,
        pv_net_per_kw=3_300.0,
    )
    dispatch = SimpleNamespace(
        annual_load=10.0,
        yield_per_kw=2.0,
        p_exp=np.array([0.08, 0.12]),
        pv_gen_per_kw=np.array([1.0, 3.0]),
    )

    with (
        patch("figure_builder.recipes.live_prices", return_value=prices),
        patch(
            "figure_builder.recipes.county_dispatch_inputs",
            return_value=dispatch,
        ),
        patch("figure_builder.recipes.collect_battery_capex_sweep", return_value="free"),
        patch("figure_builder.recipes._installer_rule_fixed_pv_sweep", return_value="fixed"),
        patch(
            "figure_builder.recipes._plot_installer_rule",
            return_value=("figure", {"thr_fix": 800.0, "thr_free": 500.0}),
        ),
        patch("figure_builder.recipes.docio.embed_png", return_value="image"),
        patch(
            "figure_builder.recipes._installer_rule_fragment",
            return_value="fragment",
        ) as fragment,
    ):
        build_installer_rule_figure(doc=doc)

    assert fragment.call_args.args[2] == pytest.approx(0.11)


def _tariff_metadata_fixture():
    return {
        "scenario": {
            "billing_year": 2026,
            "nbt_vintage": 2026,
            "customer_segment": "standard_non_equity",
            "tariff_snapshot_date": "2026-08-09",
        },
        "utilities": [
            {
                "utility": "PG&E",
                "import": {"plan_name": "E-ELEC", "source_id": "pge-import"},
                "export": {"source_ids": ["pge-export"]},
                "acc_plus": {"source_id": "pge-adder"},
            },
            {
                "utility": "SCE",
                "import": {"plan_name": "TOU-D-PRIME", "source_id": "sce-import"},
                "export": {"source_ids": ["sce-export"]},
                "acc_plus": {"source_id": "sce-adder"},
            },
            {
                "utility": "SDG&E",
                "import": {"plan_name": "EV-TOU-5", "source_id": "sdge-import"},
                "export": {"source_ids": ["sdge-export"]},
                "acc_plus": {"source_id": "sdge-adder"},
            },
        ],
        "comparison": {
            "nem2_scenario": {
                "research_label": "nem2_at_2026_retail_rates",
                "tariff_snapshot_date": "2026-08-09",
                "utilities": [
                    {
                        "utility": utility,
                        "settlement": {
                            "utility_rules_source_id": f"{slug}-rules",
                            "billing_method_source_id": f"{slug}-billing",
                            "nsc_rate_source_id": f"{slug}-nsc",
                        },
                    }
                    for utility, slug in (
                        ("PG&E", "pge"),
                        ("SCE", "sce"),
                        ("SDG&E", "sdge"),
                    )
                ],
            }
        },
    }


def test_tariff_status_fragment_uses_current_model_source_identity():
    html = _tariff_status_fragment(_tariff_metadata_fixture())

    assert "billing year 2026, NBT 2026 application vintage" in html
    assert "PG&amp;E E-ELEC (<code>pge-import</code>)" in html
    assert "SCE TOU-D-PRIME (<code>sce-import</code>)" in html
    assert "SDG&amp;E EV-TOU-5 (<code>sdge-import</code>)" in html
    assert "<code>pge-export</code> plus ACC Plus <code>pge-adder</code>" in html
    assert "Annual NSC settlement is not part of the NBT sizing-sweep objective" in html
    assert "nem2_at_2026_retail_rates" in html
    assert "pge-rules" in html


def test_tariff_status_builder_replaces_legacy_text_and_is_idempotent(tmp_path):
    doc = tmp_path / "claims.html"
    doc.write_text(
        "before\n"
        "    <li>Retail rate and export-credit data have a mix of resolved and "
        "open staleness gaps.\n"
        "      <ul class=\"sub-limitations\">\n"
        "        <li>obsolete tariff text</li>\n"
        "      </ul>\n"
        "    </li>\n"
        "after"
    )

    with patch(
        "figure_builder.recipes.tariff_metadata",
        return_value=_tariff_metadata_fixture(),
    ):
        build_tariff_status_block(doc=doc)
        first = doc.read_text()
        build_tariff_status_block(doc=doc)

    assert doc.read_text() == first
    assert "<!-- TARIFF-STATUS-START -->" in first
    assert "obsolete tariff text" not in first
    assert "sdge-export" in first


def test_claim2_fragment_reports_distribution_without_overstating_unanimity():
    html = _claim2_fragment(
        "analysis_results/step18.csv",
        "case-image",
        "statewide-image",
        {
            "county_count": 47,
            "positive_count": 46,
            "median": 14.6,
            "minimum": -1.2,
            "maximum": 24.8,
        },
    )

    assert "in 46 of 47 counties" in html
    assert "14.6%" in html
    assert "-1.2% to 24.8%" in html
    assert "not</strong> a no-solar household" in html
    assert "nem3_billing_test.py" not in html
    assert "total_annual_costs_test.py" in html


def test_claim3_fragment_uses_paired_fixed_vs_cooptimized_metrics():
    html = _claim3_fragment(
        "analysis_results/step18.csv",
        "statewide-image",
        {
            "county_count": 47,
            "positive_count": 47,
            "mean": 646.4,
            "median": 625.0,
            "minimum": 271.0,
            "maximum": 826.0,
        },
    )

    assert "in all 47 counties" in html
    assert "$646/yr" in html
    assert "$271 to $826" in html
    assert "full_electric_ev_coopt" in html


def test_statewide_claims_builder_replaces_both_stale_sections(tmp_path):
    doc = tmp_path / "claims.html"
    source = tmp_path / "step18.csv"
    source.write_text("fixture")
    doc.write_text(
        '<section class="claim" id="claim-2">stale claim 2</section>\n'
        '<section class="claim" id="claim-3">stale claim 3</section>\n'
        '<section class="claim" id="limitations">keep limitations</section>'
    )
    eac = SimpleNamespace()
    summary = SimpleNamespace()
    meta2 = {
        "county_count": 47,
        "positive_count": 46,
        "median": 14.6,
        "minimum": -1.2,
        "maximum": 24.8,
    }
    meta3 = {
        "county_count": 47,
        "positive_count": 47,
        "mean": 646.4,
        "median": 625.0,
        "minimum": 271.0,
        "maximum": 826.0,
    }

    with (
        patch("figure_builder.recipes.collect_claims_eac_results", return_value=eac),
        patch("figure_builder.recipes.summarize_claims_eac", return_value=summary),
        patch("figure_builder.recipes.plot_case_study_eac", return_value=("case", {})),
        patch(
            "figure_builder.recipes.plot_statewide_electrification_savings",
            return_value=("claim2", meta2),
        ),
        patch(
            "figure_builder.recipes.plot_statewide_cooptimization_savings",
            return_value=("claim3", meta3),
        ),
        patch(
            "figure_builder.recipes.docio.embed_png",
            side_effect=["case-image", "claim2-image", "claim3-image"],
        ),
    ):
        build_statewide_claims(doc, source=source)

    html = doc.read_text()
    assert "stale claim 2" not in html
    assert "stale claim 3" not in html
    assert "CLAIM 2" in html
    assert "CLAIM 3" in html
    assert "keep limitations" in html
