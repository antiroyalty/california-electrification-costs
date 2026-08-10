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

from figure_builder import sweep_csv_path
from figure_builder.datasets import (
    SWEEP_COLUMNS,
    collect_battery_capex_sweep,
    resolve_pv_capex,
    sweep_cache_is_compatible,
)
from figure_builder.pricing import live_prices


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


def test_sweep_cache_requires_current_schema_and_requested_battery_bound():
    current = pd.DataFrame(
        [[500.0, 3.0, 10.0, 2_000.0, 0.8, 40.0, 2, 2]],
        columns=SWEEP_COLUMNS,
    )
    old_unbounded = current.drop(
        columns=["max_battery_kwh", "meter_binary_count", "solver_rounds"]
    )

    assert sweep_cache_is_compatible(current, 40.0)
    assert not sweep_cache_is_compatible(current, 55.0)
    assert not sweep_cache_is_compatible(old_unbounded, 40.0)


def test_sweep_cache_path_separates_coarse_and_full_resolution():
    assert sweep_csv_path("alameda").name == "sweep_288_alameda_post_itc_2026.csv"
    assert sweep_csv_path("alameda", resolution="8760").name == (
        "sweep_8760_alameda_post_itc_2026.csv"
    )
    with pytest.raises(ValueError, match="resolution"):
        sweep_csv_path("alameda", resolution="hourly-ish")


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
