"""Unit tests for live pricing — the single source of truth for figure captions.

Locks the regime -> dollar mapping so a figure can never silently drift from the
model's prices again (the bug that started the Claim-1 rework).
"""
import pytest

from figure_builder.pricing import LivePrices, live_prices


def test_default_regime_is_current_law_no_itc():
    p = live_prices()
    assert p.regime == "post_itc_2026"
    # current law: no federal ITC, so net == gross
    assert p.pv_net_per_kw == pytest.approx(3300.0)
    assert p.batt_net_per_kwh == pytest.approx(1460.64, abs=0.01)


def test_itc_2025_regime_applies_30pct_credit():
    from appliances.incentive_policy import PolicyRegime

    p = live_prices(PolicyRegime.ITC_2025)
    assert p.regime == "itc_2025"
    # 30% ITC off the gross prices above
    assert p.pv_net_per_kw == pytest.approx(2310.0)
    assert p.batt_net_per_kwh == pytest.approx(1022.45, abs=0.01)


def test_itc_makes_storage_cheaper_than_current_law():
    from appliances.incentive_policy import PolicyRegime

    assert live_prices(PolicyRegime.ITC_2025).batt_net_per_kwh < live_prices().batt_net_per_kwh


def test_pv_lcoe_matches_hand_computation():
    from evaluations.eac import crf

    p = LivePrices(regime="x", pv_net_per_kw=3300.0, batt_net_per_kwh=1460.64)
    yield_per_kw = 1447.0
    expected = 3300.0 * crf(0.07, 25) / yield_per_kw
    assert p.pv_lcoe(yield_per_kw) == pytest.approx(expected)
