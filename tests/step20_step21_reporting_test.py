from pathlib import Path

import pandas as pd
import pytest

from pipeline.steps.step20_no_solar_storage_electrification import (
    collect_eac_no_pv,
    collect_eac_no_pv_by_county,
)
from pipeline.steps import step21_compare_eac_with_vs_without as step21


HOUSING_TYPE = "single-family-detached"
SCENARIO = "baseline_coopt"
PLAN_PREFERENCES = ["E-TOU-D", "TOU-D-4-9PM", "TOU-DR1"]


def _write_bill_results(
    base_dir: Path,
    county_slug: str,
    electricity_values: dict[str, float],
    gas_bill: float,
) -> None:
    results_dir = base_dir / SCENARIO / HOUSING_TYPE / county_slug / "results"
    electricity_dir = results_dir / "electricity"
    gas_dir = results_dir / "gas"
    electricity_dir.mkdir(parents=True)
    gas_dir.mkdir(parents=True)

    electricity_row = {"scenario": SCENARIO, **electricity_values}
    pd.DataFrame([electricity_row]).to_csv(
        electricity_dir
        / f"RESULTS_electricity_annual_costs_{county_slug}_20260814_11.csv",
        index=False,
    )
    pd.DataFrame(
        [{"scenario": SCENARIO, "gas.default": gas_bill}]
    ).to_csv(
        gas_dir / f"RESULTS_gas_annual_costs_{county_slug}_20260814_11.csv",
        index=False,
    )


def test_step20_uses_configured_retail_plan_for_aggregate_and_county(
    tmp_path: Path,
) -> None:
    _write_bill_results(
        tmp_path,
        "alameda",
        {
            "electricity.PG&E.E-TOU-C": 900.0,
            "electricity.PG&E.E-TOU-D": 300.0,
            "electricity.PG&E.E-ELEC_NEM3": 200.0,
        },
        gas_bill=100.0,
    )
    _write_bill_results(
        tmp_path,
        "los-angeles",
        {
            "electricity.SCE.TOU-D-5-8PM": 800.0,
            "electricity.SCE.TOU-D-4-9PM": 500.0,
            "electricity.SCE.TOU-D-PRIME_NEM3": 350.0,
        },
        gas_bill=200.0,
    )

    aggregate = collect_eac_no_pv(
        str(tmp_path),
        HOUSING_TYPE,
        [SCENARIO],
        ["Alameda County", "Los Angeles County"],
        electricity_plan_preference=PLAN_PREFERENCES,
    )
    by_county = collect_eac_no_pv_by_county(
        str(tmp_path),
        HOUSING_TYPE,
        [SCENARIO],
        ["Alameda County", "Los Angeles County"],
        electricity_plan_preference=PLAN_PREFERENCES,
    ).set_index("county_slug")

    assert aggregate.loc[0, "annual_bill_electric"] == pytest.approx(400.0)
    assert aggregate.loc[0, "annual_bill_gas"] == pytest.approx(150.0)
    assert by_county.loc["alameda", "annual_bill_electric"] == pytest.approx(300.0)
    assert by_county.loc["los-angeles", "annual_bill_electric"] == pytest.approx(
        500.0
    )
    assert by_county.loc["alameda", "annual_bill_gas"] == pytest.approx(100.0)
    assert by_county.loc["los-angeles", "annual_bill_gas"] == pytest.approx(200.0)


def _with_county_rows() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "scenario": SCENARIO,
                "county_slug": county,
                "capex_pv": 100.0,
                "capex_storage": 0.0,
                "capex_electric": 0.0,
                "capex_gas": 0.0,
                "vehicle_om": 0.0,
                "annual_bill_electric": bill,
                "annual_bill_gas": 100.0,
            }
            for county, bill in (("alameda", 600.0), ("los-angeles", 800.0))
        ]
    )


def _no_county_rows() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "scenario": SCENARIO,
                "county_slug": county,
                "capex_electric": 0.0,
                "capex_gas": 0.0,
                "vehicle_om": 0.0,
                "annual_bill_electric": bill,
                "annual_bill_gas": 100.0,
            }
            for county, bill in (("alameda", 700.0), ("los-angeles", 950.0))
        ]
    )


def test_step21_process_writes_reconciled_county_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with_aggregate = _with_county_rows().drop(columns="county_slug").mean(
        numeric_only=True
    ).to_frame().T
    with_aggregate["scenario"] = SCENARIO
    no_aggregate = _no_county_rows().drop(columns="county_slug").mean(
        numeric_only=True
    ).to_frame().T
    no_aggregate["scenario"] = SCENARIO

    captured: dict[str, dict] = {}

    def collect_with(*args, **kwargs):
        captured["with"] = kwargs
        return with_aggregate

    def collect_without(*args, **kwargs):
        captured["without"] = kwargs
        return no_aggregate

    monkeypatch.setattr(step21, "collect_eac_components", collect_with)
    monkeypatch.setattr(step21, "collect_eac_no_pv", collect_without)
    monkeypatch.setattr(
        step21,
        "collect_eac_components_by_county",
        lambda *args, **kwargs: _with_county_rows(),
    )
    monkeypatch.setattr(
        step21,
        "collect_eac_no_pv_by_county",
        lambda *args, **kwargs: _no_county_rows(),
    )
    monkeypatch.setattr(step21, "git_short_sha", lambda: "testsha")

    step21.process(
        "unused",
        str(tmp_path),
        HOUSING_TYPE,
        SCENARIO,
        ["Alameda County", "Los Angeles County"],
        plan_preference=PLAN_PREFERENCES,
        electricity_variant="nem3",
    )

    output_path = tmp_path / "step21_with_vs_without_by_county_gtestsha.csv"
    result = pd.read_csv(output_path).set_index("county_slug")
    assert len(result) == 2
    assert result.loc["alameda", "total_eac"] == pytest.approx(800.0)
    assert result.loc["alameda", "total_eac_no_pv"] == pytest.approx(800.0)
    assert result.loc["alameda", "delta_with_minus_without"] == pytest.approx(0.0)
    assert result.loc["los-angeles", "delta_with_minus_without"] == pytest.approx(
        -50.0
    )
    assert captured["with"]["electricity_plan_preference"] == PLAN_PREFERENCES
    assert captured["with"]["electricity_variant"] == "nem3"
    assert captured["without"]["electricity_plan_preference"] == PLAN_PREFERENCES


def test_step21_rejects_nonmatching_county_coverage() -> None:
    no_rows = _no_county_rows().query("county_slug == 'alameda'")

    with pytest.raises(ValueError, match="do not cover the same rows"):
        step21._build_county_comparison(_with_county_rows(), no_rows)
