"""Guard for the claim-figure PV price.

The 2026-07-27 investigation found an old claim figure had been drawn at an
unlabeled $4,000/kW PV price (the top of a sensitivity sweep) instead of the
model's sourced net price. No model-default test caught it, because $4,000 was a
figure parameter, not a model value. These tests bind the figure data path to
the model's tested price by default, so the class of bug can't recur silently.
"""
import pandas as pd
import pytest
from types import SimpleNamespace
from unittest.mock import patch

from figure_builder import market_observation_csv_path, sweep_csv_path
from figure_builder.datasets import (
    MARKET_OBSERVATION_COLUMNS,
    SWEEP_COLUMNS,
    canonical_battery_capex_points,
    collect_battery_capex_sweep,
    collect_market_price_observation,
    normalize_battery_capex_points,
    resolve_pv_capex,
    select_market_observation,
    sweep_cache_is_compatible,
)
from figure_builder.pricing import live_prices
from figure_builder.dispatch import CLAIM1_COUNTIES


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
    assert sweep_csv_path("alameda").name == "sweep_288_alameda_post_itc_2026.csv"
    assert sweep_csv_path("alameda", resolution="8760").name == (
        "sweep_8760_alameda_post_itc_2026.csv"
    )
    with pytest.raises(ValueError, match="resolution"):
        sweep_csv_path("alameda", resolution="hourly-ish")


def test_market_observation_path_is_separate_from_sensitivity_sweeps():
    assert market_observation_csv_path("alameda").name == (
        "market_8760_alameda_post_itc_2026.csv"
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


@pytest.mark.parametrize(
    "fine,expected_intervals,expected_cycle_monthly",
    [(False, 288, True), (True, 8760, False)],
)
def test_sweep_collector_wires_declared_temporal_resolution(
    fine, expected_intervals, expected_cycle_monthly
):
    dispatch = SimpleNamespace(
        load=[1.0] * 8760,
        pv_gen_per_kw=[0.5] * 8760,
        p_imp=[0.30] * 8760,
        p_exp=[0.05] * 8760,
        annual_load=8760.0,
        yield_per_kw=4380.0,
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
    assert len(solved_inputs.load_kwh) == expected_intervals
    assert solve.call_args.kwargs["cycle_monthly"] is expected_cycle_monthly
    if fine:
        assert solve.call_args.kwargs["weights"] is None
    else:
        assert len(solve.call_args.kwargs["weights"]) == 288
    assert frame.loc[0, "max_battery_kwh"] == 40.0
