"""Regression tests for source-derived values in Claim-1 figure captions."""

from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
import pytest

from figure_builder.charts import (
    plot_marginal_solar_value_ladder,
    solar_generation_weighted_export_rate,
)
from figure_builder.recipes import (
    _installer_rule_fragment,
    _mechanism_fragment,
    build_installer_rule_figure,
)


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
            "before": {"pv_flat": 2.0, "pv_max": 4.0},
            "after": {"pv_flat": 1.5, "pv_max": 3.0},
        },
        {
            "v_export": 0.057469,
            "peak_import_rate": 0.48,
            "v_peak": 0.432,
            "pv_lcoe": 0.196,
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
    assert "2-3" not in html
    assert "2&ndash;3" not in html
    assert "~$0.40/kWh" not in html
    assert "~$0.05/kWh" not in html


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
