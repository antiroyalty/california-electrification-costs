import pandas as pd
import pytest

from figure_builder.charts import (
    plot_case_study_eac,
    plot_policy_matrix_optimal_sizes,
    plot_pv_batt_vs_capex_compare,
    plot_statewide_cooptimization_savings,
    plot_statewide_electrification_savings,
)
from figure_builder.datasets import (
    EAC_COMPONENT_COLUMNS,
    POLICY_MATRIX_COLUMNS,
    SWEEP_COLUMNS,
)
from figure_builder.policy_cases import POLICY_CASES


def _sweep() -> pd.DataFrame:
    return pd.DataFrame(
        [
            [25.0, 4.0, 10.0, 1_000.0, 0.8, 40.0, 2, 2],
            [500.0, 3.0, 5.0, 1_500.0, 0.7, 40.0, 1, 2],
            [1_022.448, 2.5, 0.0, 2_000.0, 0.6, 40.0, 0, 1],
            [1_460.64, 2.0, 0.0, 2_500.0, 0.5, 40.0, 0, 1],
        ],
        columns=SWEEP_COLUMNS,
    )


def test_market_annotation_uses_exact_observation_not_hardcoded_zero():
    sweep = _sweep()
    before = sweep.loc[2].copy()
    before["batt_kwh"] = 5.5329
    after = sweep.loc[3].copy()
    after["batt_kwh"] = 0.0001515

    fig, meta = plot_pv_batt_vs_capex_compare(
        sweep,
        sweep,
        batt_before=1_022.448,
        batt_after=1_460.64,
        market_before=before,
        market_after=after,
        market_before_resolution="12×24",
        market_after_resolution="8,760 h",
        title="test",
        panel_labels=("before", "after"),
    )
    try:
        text = "\n".join(
            artist.get_text()
            for axis in fig.axes
            for artist in axis.texts
        )
        assert "12×24: battery = 5.53 kWh" in text
        assert "8,760 h: battery = <0.01 kWh" in text
        assert meta["before"]["market_batt_kwh"] == pytest.approx(5.5329)
        assert meta["after"]["market_batt_kwh"] == pytest.approx(0.0001515)
    finally:
        import matplotlib.pyplot as plt

        plt.close(fig)


def test_market_annotation_rejects_wrong_price():
    sweep = _sweep()
    before = sweep.loc[1]
    after = sweep.loc[3]

    with pytest.raises(ValueError, match="does not match marker price"):
        plot_pv_batt_vs_capex_compare(
            sweep,
            sweep,
            batt_before=1_022.448,
            batt_after=1_460.64,
            market_before=before,
            market_after=after,
            market_before_resolution="12×24",
            market_after_resolution="8,760 h",
            title="test",
            panel_labels=("before", "after"),
        )


def _case_study_eac() -> pd.DataFrame:
    rows = []
    for county_index, county in enumerate(
        ["alameda", "fresno", "los-angeles", "san-diego"]
    ):
        for case_index, case in enumerate(
            ["gas_ice_reference", "fixed_pv_electric", "cooptimized_electric"]
        ):
            values = {column: 100.0 for column in EAC_COMPONENT_COLUMNS}
            values["annual_bill_electric"] = 5_000.0 + county_index * 100
            values["annual_bill_gas"] = 500.0 if case == "gas_ice_reference" else 0.0
            rows.append(
                {
                    "county_slug": county,
                    "case": case,
                    **values,
                    "total_eac": sum(values.values()),
                }
            )
    return pd.DataFrame(rows)


def test_case_study_eac_uses_one_shared_legend_outside_panels():
    fig, meta = plot_case_study_eac(_case_study_eac())
    try:
        assert len(fig.legends) == 1
        assert all(axis.get_legend() is None for axis in fig.axes)
        assert meta["case_study_count"] == 4
        assert meta["maximum_total_eac"] > 5_000.0
    finally:
        import matplotlib.pyplot as plt

        plt.close(fig)


def test_statewide_savings_charts_report_exact_distribution_metrics():
    summary = pd.DataFrame(
        {
            "county_slug": ["alpha", "beta", "gamma"],
            "gas_to_coopt_pct": [10.0, -2.0, 5.0],
            "fixed_to_coopt_savings": [600.0, 0.0, 300.0],
        }
    )
    fig2, meta2 = plot_statewide_electrification_savings(summary)
    fig3, meta3 = plot_statewide_cooptimization_savings(summary)
    try:
        assert meta2["positive_count"] == 2
        assert meta2["negative_count"] == 1
        assert meta2["median"] == pytest.approx(5.0)
        assert meta3["positive_count"] == 2
        assert meta3["zero_count"] == 1
        assert meta3["mean"] == pytest.approx(300.0)
    finally:
        import matplotlib.pyplot as plt

        plt.close(fig2)
        plt.close(fig3)


def test_policy_matrix_chart_uses_four_complete_common_resolution_panels():
    rows = []
    counties = (("alpha", "Alpha County"), ("beta", "Beta County"))
    for case_index, case in enumerate(POLICY_CASES):
        for county_index, (slug, name) in enumerate(counties):
            limit = case.export_compensation_regime.max_pv_to_annual_load_ratio
            rows.append(
                {
                    "county_slug": slug,
                    "county_name": name,
                    "utility": "SCE",
                    "case_id": case.case_id,
                    "export_compensation_regime": (
                        case.export_compensation_regime.value
                    ),
                    "capital_policy_regime": case.capital_policy_regime.value,
                    "temporal_resolution": "weighted_12x24_monthly_hour",
                    "interval_count": 288,
                    "pv_capex_usd_per_kw": 3_300.0,
                    "battery_capex_usd_per_kwh": 1_460.64,
                    "pv_kw": 4.0 + case_index + county_index,
                    "battery_kwh": float(case_index),
                    "annual_generation_coverage": limit,
                    "pv_sizing_limit_ratio": limit,
                    "at_pv_sizing_limit": True,
                    "total_cost_usd_per_year": 2_500.0,
                    "max_battery_kwh": 40.0,
                    "meter_binary_count": 0,
                    "solver_rounds": 1,
                }
            )
    frame = pd.DataFrame(rows, columns=POLICY_MATRIX_COLUMNS)

    fig, meta = plot_policy_matrix_optimal_sizes(frame)
    try:
        assert len(fig.axes) == 8
        assert meta["county_count"] == 2
        assert len(meta["case_summaries"]) == 4
        assert meta["temporal_resolution"] == "weighted_12x24_monthly_hour"
        text = "\n".join(axis.get_title(loc="left") for axis in fig.axes)
        assert "NEM 2 at 2026 retail rates" in text
        assert "NBT 2026" in text
        assert "2025 ITC capital costs" in text
        assert "Post-ITC 2026 capital costs" in text
    finally:
        import matplotlib.pyplot as plt

        plt.close(fig)
