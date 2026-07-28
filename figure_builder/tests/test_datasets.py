"""Guard for the claim-figure PV price.

The 2026-07-27 investigation found an old claim figure had been drawn at an
unlabeled $4,000/kW PV price (the top of a sensitivity sweep) instead of the
model's sourced net price. No model-default test caught it, because $4,000 was a
figure parameter, not a model value. These tests bind the figure data path to
the model's tested price by default, so the class of bug can't recur silently.
"""
import pytest

from figure_builder.datasets import resolve_pv_capex
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
