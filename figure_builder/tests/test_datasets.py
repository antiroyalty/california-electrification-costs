"""Guard for the claim-figure PV price.

The 2026-07-27 investigation found an old claim figure had been drawn at an
unlabeled $4,000/kW PV price (the top of a sensitivity sweep) instead of the
model's sourced net price. No model-default test caught it, because $4,000 was a
figure parameter, not a model value. These tests bind the figure data path to
the model's tested price by default, so the class of bug can't recur silently.
"""
import json

import pandas as pd
import pytest
import numpy as np
from types import SimpleNamespace
from unittest.mock import patch

from figure_builder import REPO, market_observation_csv_path, sweep_csv_path
from figure_builder.datasets import (
    CLAIMS_EAC_SCENARIOS,
    EAC_COMPONENT_COLUMNS,
    MARKET_OBSERVATION_COLUMNS,
    SWEEP_COLUMNS,
    canonical_battery_capex_points,
    build_claims_eac_source,
    claims_eac_manifest_path,
    collect_battery_capex_sweep,
    collect_claims_eac_results,
    collect_market_price_observation,
    load_claims_eac_manifest,
    _manifest_display_path,
    normalize_battery_capex_points,
    resolve_pv_capex,
    select_market_observation,
    summarize_claims_eac,
    sweep_cache_is_compatible,
)
from figure_builder.pricing import live_prices
from figure_builder.dispatch import CLAIM1_COUNTIES, DispatchInputs
from tariffs import ExportCompensationRegime


def _eac_source_fixture(counties=("alpha", "beta")) -> pd.DataFrame:
    totals = {
        "alpha": {
            "baseline_ice_car": 14_000.0,
            "full_electric_ev": 13_500.0,
            "full_electric_ev_coopt": 12_000.0,
        },
        "beta": {
            "baseline_ice_car": 10_000.0,
            "full_electric_ev": 11_000.0,
            "full_electric_ev_coopt": 10_500.0,
        },
    }
    rows = []
    for county in counties:
        for scenario in CLAIMS_EAC_SCENARIOS:
            components = {column: 0.0 for column in EAC_COMPONENT_COLUMNS}
            components["annual_bill_electric"] = totals[county][scenario]
            rows.append(
                {
                    "scenario": scenario,
                    "county_slug": county,
                    **components,
                }
            )
    return pd.DataFrame(rows)


def test_default_pv_capex_is_the_model_net_price():
    """With no override, a sweep fixes PV at the live net price for the regime,
    which IS the appliance-sourced, separately-tested price."""
    from appliances.electric_base import IncentiveScenario
    from appliances.solar_system import SolarSystemAppliance

    resolved = resolve_pv_capex()  # default regime (current law)
    assert resolved == pytest.approx(live_prices().pv_net_per_kw)
    assert resolved == pytest.approx(
        SolarSystemAppliance.per_kw_cost_net(IncentiveScenario.FULL_INCENTIVES))
    assert resolved == pytest.approx(3300.0)  # no ITC under current law


def test_default_pv_capex_tracks_regime():
    from appliances.incentive_policy import PolicyRegime

    assert resolve_pv_capex(regime=PolicyRegime.ITC_2025) == pytest.approx(2310.0)


def test_default_pv_capex_is_never_the_stale_4000_endpoint():
    """The specific regression: the default must not be the $4,000/kW sweep
    endpoint (or any figure-only constant). It stays pinned to the model price."""
    resolved = resolve_pv_capex()
    assert resolved != pytest.approx(4000.0)
    assert 2000.0 <= resolved <= 3500.0  # sane installed-cost band, model-sourced


def test_explicit_override_is_respected_for_sensitivity_sweeps():
    """Sensitivity analysis may still pin PV to any price on purpose."""
    assert resolve_pv_capex(4000.0) == 4000.0
    assert resolve_pv_capex(1500.0) == 1500.0


def test_canonical_sweep_includes_exact_live_price_once_for_each_regime():
    from appliances.incentive_policy import PolicyRegime

    current = canonical_battery_capex_points()
    itc = canonical_battery_capex_points(PolicyRegime.ITC_2025)

    assert current == sorted(current)
    assert itc == sorted(itc)
    assert current.count(1460.64) == 1
    assert itc.count(1022.448) == 1
    assert 1460.64 not in itc
    assert 1022.448 not in current


def test_explicit_sweep_points_are_sorted_and_deduplicated():
    assert normalize_battery_capex_points([500, 100.0, 500.0]) == [100.0, 500.0]


@pytest.mark.parametrize(
    "points,message",
    [
        ([], "cannot be empty"),
        ([100, float("nan")], "must be finite"),
        ([100, float("inf")], "must be finite"),
        ([100, 0], "must be positive"),
        ([100, -1], "must be positive"),
    ],
)
def test_sweep_points_reject_invalid_values(points, message):
    with pytest.raises(ValueError, match=message):
        normalize_battery_capex_points(points)


def test_sweep_cache_requires_schema_bound_and_complete_requested_grid():
    current = pd.DataFrame(
        [
            [500.0, 3.0, 10.0, 2_000.0, 0.8, 40.0, 2, 2],
            [1460.64, 2.0, 0.0, 2_500.0, 0.5, 40.0, 0, 1],
        ],
        columns=SWEEP_COLUMNS,
    )
    old_unbounded = current.drop(
        columns=["max_battery_kwh", "meter_binary_count", "solver_rounds"]
    )
    missing_live_price = current.iloc[[0]].copy()
    duplicate = pd.concat([current, current.iloc[[0]]], ignore_index=True)

    assert sweep_cache_is_compatible(
        current,
        40.0,
        expected_points=[1460.64, 500.0],
    )
    assert not sweep_cache_is_compatible(
        current,
        55.0,
        expected_points=[500.0, 1460.64],
    )
    assert not sweep_cache_is_compatible(
        old_unbounded,
        40.0,
        expected_points=[500.0, 1460.64],
    )
    assert not sweep_cache_is_compatible(
        missing_live_price,
        40.0,
        expected_points=[500.0, 1460.64],
    )
    assert not sweep_cache_is_compatible(
        duplicate,
        40.0,
        expected_points=[500.0, 1460.64],
    )


def test_sweep_cache_path_separates_coarse_and_full_resolution():
    assert sweep_csv_path("alameda").name == (
        "sweep_288_alameda_nbt_2026_post_itc_2026.csv"
    )
    assert sweep_csv_path("alameda", resolution="8760").name == (
        "sweep_8760_alameda_nbt_2026_post_itc_2026.csv"
    )
    with pytest.raises(ValueError, match="resolution"):
        sweep_csv_path("alameda", resolution="hourly-ish")

    nem2_path = sweep_csv_path(
        "alameda",
        export_compensation_regime=(
            ExportCompensationRegime.NEM2_AT_2026_RETAIL_RATES
        ),
    )
    assert nem2_path.name == (
        "sweep_288_alameda_nem2_at_2026_retail_rates_post_itc_2026.csv"
    )


def test_market_observation_path_is_separate_from_sensitivity_sweeps():
    assert market_observation_csv_path("alameda").name == (
        "market_8760_alameda_nbt_2026_post_itc_2026.csv"
    )
    assert market_observation_csv_path(
        "alameda",
        export_compensation_regime=(
            ExportCompensationRegime.NEM2_AT_2026_RETAIL_RATES
        ),
    ).name == (
        "market_8760_alameda_nem2_at_2026_retail_rates_post_itc_2026.csv"
    )


def test_select_market_observation_requires_one_exact_finite_solved_row():
    frame = pd.DataFrame(
        [
            [500.0, 3.0, 10.0, 2_000.0, 0.8, 40.0, 2, 2],
            [1460.64, 2.0, 0.0, 2_500.0, 0.5, 40.0, 0, 1],
        ],
        columns=SWEEP_COLUMNS,
    )

    row = select_market_observation(frame, 1460.64)
    assert row["pv_kw"] == 2.0
    assert row["batt_kwh"] == 0.0

    with pytest.raises(ValueError, match="found 0"):
        select_market_observation(frame, 1_000.0)
    with pytest.raises(ValueError, match="found 2"):
        select_market_observation(pd.concat([frame, frame.iloc[[1]]]), 1460.64)
    malformed = frame.copy()
    malformed.loc[1, "batt_kwh"] = float("nan")
    with pytest.raises(ValueError, match="missing values"):
        select_market_observation(malformed, 1460.64)


def test_market_collector_runs_only_exact_price_at_full_resolution(tmp_path):
    solved = pd.DataFrame(
        [[1460.64, 2.0, 0.0, 2_500.0, 0.5, 40.0, 0, 1]],
        columns=SWEEP_COLUMNS,
    )
    prices = SimpleNamespace(
        regime="post_itc_2026",
        batt_net_per_kwh=1460.64,
    )

    with (
        patch("figure_builder.datasets.live_prices", return_value=prices),
        patch(
            "figure_builder.datasets.market_observation_csv_path",
            return_value=tmp_path / "market.csv",
        ),
        patch(
            "figure_builder.datasets.collect_battery_capex_sweep",
            return_value=solved,
        ) as collect,
    ):
        result = collect_market_price_observation("alameda", verbose=False)

    assert list(result.columns) == MARKET_OBSERVATION_COLUMNS
    assert result.loc[0, "scenario"] == "full_electric_ev_coopt"
    assert result.loc[0, "policy_regime"] == "post_itc_2026"
    assert result.loc[0, "interval_count"] == 8760
    collect.assert_called_once_with(
        "alameda",
        regime=None,
        export_compensation_regime=ExportCompensationRegime.NBT_2026,
        scenario="full_electric_ev_coopt",
        points=[1460.64],
        max_battery_kwh=40.0,
        fine=True,
        cache=False,
        force=True,
        verbose=False,
    )


def test_committed_current_law_market_observations_are_complete_and_plausible():
    """Publication guardrail: all four exact solved points exist and retain the
    headline no-material-storage result without pinning float serialization."""

    price = live_prices().batt_net_per_kwh
    for slug, _, _ in CLAIM1_COUNTIES:
        path = market_observation_csv_path(slug, live_prices().regime)
        frame = pd.read_csv(path)
        row = select_market_observation(frame, price)

        assert list(frame.columns) == MARKET_OBSERVATION_COLUMNS
        assert len(frame) == 1
        assert frame.loc[0, "scenario"] == "full_electric_ev_coopt"
        assert frame.loc[0, "policy_regime"] == "post_itc_2026"
        assert frame.loc[0, "interval_count"] == 8760
        assert 1.0 < row["pv_kw"] < 3.0
        assert 0.0 <= row["batt_kwh"] <= 0.1
        assert 1_000.0 < row["total_cost"] < 5_000.0
        assert 1 <= row["solver_rounds"] <= 10


def test_claims_eac_collector_requires_complete_paired_county_coverage(tmp_path):
    source = tmp_path / "step18.csv"
    _eac_source_fixture().to_csv(source, index=False)

    eac = collect_claims_eac_results(
        source,
        expected_counties={"alpha", "beta"},
        require_manifest=False,
    )
    summary = summarize_claims_eac(eac).set_index("county_slug")

    assert len(eac) == 6
    assert summary.loc["alpha", "gas_to_coopt_savings"] == pytest.approx(2_000.0)
    assert summary.loc["alpha", "gas_to_coopt_pct"] == pytest.approx(100 / 7)
    assert summary.loc["alpha", "fixed_to_coopt_savings"] == pytest.approx(1_500.0)
    assert summary.loc["beta", "gas_to_coopt_savings"] == pytest.approx(-500.0)
    assert summary.loc["beta", "fixed_to_coopt_savings"] == pytest.approx(500.0)


@pytest.mark.parametrize("defect,message", [
    ("missing", "coverage mismatch"),
    ("duplicate", "duplicate keys"),
    ("nan", "missing/non-numeric costs"),
    ("infinite", "non-finite costs"),
    ("negative", "negative costs"),
])
def test_claims_eac_collector_rejects_incomplete_or_malformed_sources(
    tmp_path,
    defect,
    message,
):
    source = tmp_path / "step18.csv"
    frame = _eac_source_fixture()
    if defect == "missing":
        frame = frame.iloc[1:].copy()
    elif defect == "duplicate":
        frame = pd.concat([frame, frame.iloc[[0]]], ignore_index=True)
    elif defect == "nan":
        frame.loc[0, "annual_bill_electric"] = float("nan")
    elif defect == "infinite":
        frame.loc[0, "annual_bill_electric"] = float("inf")
    else:
        frame.loc[0, "annual_bill_electric"] = -1.0
    frame.to_csv(source, index=False)

    with pytest.raises(ValueError, match=message):
        collect_claims_eac_results(
            source,
            expected_counties={"alpha", "beta"},
            require_manifest=False,
        )


def test_claims_source_builder_uses_exact_scenario_runs_and_writes_receipt(
    tmp_path,
):
    counties = {"alpha", "beta"}
    model_sha = "abc1234"
    timestamps = {
        "baseline_ice_car": "20260817_17",
        "full_electric_ev": "20260817_17",
        "full_electric_ev_coopt": "20260817_18",
    }
    completion_dir = tmp_path / "completion"
    for scenario in CLAIMS_EAC_SCENARIOS:
        scenario_dir = completion_dir / scenario
        scenario_dir.mkdir(parents=True)
        for county in counties:
            (scenario_dir / f"{county}_diagnostics_g{model_sha}.html").write_text(
                "complete",
                encoding="utf-8",
            )
    fixture = _eac_source_fixture()

    def collect(_base, _housing, scenarios, _counties, **kwargs):
        assert len(scenarios) == 1
        scenario = scenarios[0]
        assert kwargs["timestamp"] == timestamps[scenario]
        assert kwargs["electricity_variant"] == "nem3"
        return fixture[fixture["scenario"] == scenario].copy()

    source = tmp_path / "claims.csv"
    with patch(
        "helpers.plot_scenario_comparison_helper.collect_eac_components_by_county",
        side_effect=collect,
    ):
        result = build_claims_eac_source(
            model_run_sha=model_sha,
            run_timestamps=timestamps,
            source=source,
            completion_dir=completion_dir,
            expected_counties=counties,
        )

    assert result == source
    assert len(pd.read_csv(source)) == 6
    manifest = load_claims_eac_manifest(source)
    assert manifest["model_git_sha"] == model_sha
    assert manifest["scenario_run_timestamps"] == timestamps
    assert manifest["completion_marker_count"] == 6
    assert manifest["source_csv"]["row_count"] == 6
    assert manifest["source_csv"]["path"] == str(source.resolve())


def test_claims_source_manifest_uses_repo_relative_path_for_public_source():
    source = REPO / "analysis_results" / "claims.csv"

    assert _manifest_display_path(source) == "analysis_results/claims.csv"


def test_claims_source_builder_rejects_incomplete_model_run(tmp_path):
    with pytest.raises(FileNotFoundError, match="completion markers missing"):
        build_claims_eac_source(
            model_run_sha="abc1234",
            run_timestamps={
                "baseline_ice_car": "20260817_17",
                "full_electric_ev": "20260817_17",
                "full_electric_ev_coopt": "20260817_18",
            },
            source=tmp_path / "claims.csv",
            completion_dir=tmp_path / "completion",
            expected_counties={"alpha"},
        )


def test_claims_source_manifest_detects_csv_replacement(tmp_path):
    source = tmp_path / "claims.csv"
    _eac_source_fixture().to_csv(source, index=False)
    manifest_path = claims_eac_manifest_path(source)
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "model_git_sha": "abc1234",
                "scenario_run_timestamps": {
                    "baseline_ice_car": "20260817_17",
                    "full_electric_ev": "20260817_17",
                    "full_electric_ev_coopt": "20260817_18",
                },
                "scenario_cases": CLAIMS_EAC_SCENARIOS,
                "source_csv": {"sha256": "not-the-real-fingerprint"},
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="fingerprint"):
        load_claims_eac_manifest(source)


@pytest.mark.parametrize(
    "run_timestamps,message",
    [
        (
            {
                "baseline_ice_car": "20260817_17",
                "full_electric_ev": "20260817_17",
            },
            "identify exactly",
        ),
        (
            {
                "baseline_ice_car": "20260817_17",
                "full_electric_ev": "latest",
                "full_electric_ev_coopt": "20260817_18",
            },
            "YYYYMMDD_HH",
        ),
    ],
)
def test_claims_source_builder_rejects_ambiguous_run_identity(
    tmp_path,
    run_timestamps,
    message,
):
    with pytest.raises(ValueError, match=message):
        build_claims_eac_source(
            model_run_sha="abc1234",
            run_timestamps=run_timestamps,
            source=tmp_path / "claims.csv",
            completion_dir=tmp_path / "completion",
            expected_counties={"alpha"},
        )


@pytest.mark.parametrize(
    "fine,expected_intervals,expected_cycle_monthly",
    [(False, 288, True), (True, 8760, False)],
)
def test_sweep_collector_wires_declared_temporal_resolution(
    fine, expected_intervals, expected_cycle_monthly
):
    dispatch = DispatchInputs(
        slug="alameda",
        util="PG&E",
        load=np.array([1.0] * 8760),
        pv_gen_per_kw=np.array([0.5] * 8760),
        p_imp=np.array([0.30] * 8760),
        p_exp=np.array([0.05] * 8760),
        export_compensation_regime=ExportCompensationRegime.NBT_2026,
        nem2_terms=None,
    )
    result = SimpleNamespace(
        pv_kw=2.0,
        batt_kwh=5.0,
        total_cost=2_000.0,
        meter_binary_count=0,
        solver_rounds=1,
    )

    with (
        patch("figure_builder.datasets.county_dispatch_inputs", return_value=dispatch),
        patch("pipeline.steps.step9b_cooptimize_core._solve_lp", return_value=result) as solve,
    ):
        frame = collect_battery_capex_sweep(
            "alameda",
            points=[500],
            cache=False,
            verbose=False,
            fine=fine,
        )

    solved_inputs = solve.call_args.args[0]
    assert solved_inputs.max_pv_to_annual_load_ratio == pytest.approx(1.5)
    assert len(solved_inputs.load_kwh) == expected_intervals
    assert solve.call_args.kwargs["cycle_monthly"] is expected_cycle_monthly
    if fine:
        assert solve.call_args.kwargs["weights"] is None
    else:
        assert len(solve.call_args.kwargs["weights"]) == 288
    assert frame.loc[0, "max_battery_kwh"] == 40.0
