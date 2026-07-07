git"""Regression tests for Config parameters actually reaching the steps that use them.

Found tonight: `Config.discount_rate` had a correct default and was correctly
used *inside* step9b's LP and step18's EAC collection — but the module-level
orchestration (`mod_solar_storage.run`, `mod_visualization.run`) never passed
`cfg.discount_rate` to them at all, so the config value was silently ignored
by the real pipeline. Same story for NBC: `calculate_nem3_annual_costs`
accepted an `options` override, but nothing above it exposed a way to set it.

These tests exercise the wiring at the module-call boundary, not the math
inside the steps (that's covered by lp_cooptimize_test.py and friends). A
passing test here means "the parameter you set on Config is the parameter
the step receives," which is a different and easier-to-silently-break claim
than "the formula is correct."
"""
import inspect
import os
import sys
from unittest.mock import patch

import pytest

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from pipeline.config import Config


def test_solar_storage_module_passes_discount_rate_to_lp():
    import pipeline.modules.solar_storage as mod

    cfg = Config(
        scenario="baseline_coopt",
        housing_type="single-family-detached",
        counties=["Alameda County"],
        discount_rate=0.1234,
    )

    with patch.object(mod, "WeatherFiles") as mock_weather, patch.object(mod, "Step9bCoopt") as mock_step9b:
        mod.run(cfg)

    assert mock_weather.process.called
    assert mock_step9b.process.called
    _, kwargs = mock_step9b.process.call_args
    assert kwargs.get("discount_rate") == 0.1234, (
        "mod_solar_storage.run() must pass cfg.discount_rate to Step9bCoopt.process — "
        "otherwise the LP always sizes PV/battery at its own hardcoded default "
        "regardless of what Config specifies."
    )


def test_solar_storage_module_sizes_against_net_cost_for_the_configured_incentive_scenario():
    """2026-07-07 refinement: the LP's sizing price must reflect the actual
    incentive scenario Config specifies, not always full_incentives. Uses a
    non-default scenario (no_incentives) specifically so this can't pass by
    coincidentally matching the common-case default."""
    import pipeline.modules.solar_storage as mod
    from appliances.solar_system import SolarSystemAppliance
    from appliances.battery_storage import BatteryStorageAppliance
    from appliances.electric_base import IncentiveScenario

    cfg = Config(
        scenario="baseline_coopt",
        housing_type="single-family-detached",
        counties=["Alameda County"],
        incentive="no_incentives",
    )

    with patch.object(mod, "WeatherFiles"), patch.object(mod, "Step9bCoopt") as mock_step9b:
        mod.run(cfg)

    _, kwargs = mock_step9b.process.call_args
    expected_pv = SolarSystemAppliance.per_kw_cost_net(IncentiveScenario.NO_INCENTIVES)
    expected_batt = BatteryStorageAppliance.per_kwh_cost_net(IncentiveScenario.NO_INCENTIVES)
    assert kwargs.get("pv_capex_per_kw") == pytest.approx(expected_pv), (
        "mod_solar_storage.run() must size PV against cfg.incentive's net cost, "
        "not a fixed full_incentives assumption."
    )
    assert kwargs.get("batt_capex_per_kwh") == pytest.approx(expected_batt)
    # no_incentives means net == gross (nothing subtracted)
    assert expected_pv == pytest.approx(SolarSystemAppliance.per_kw_cost())
    assert expected_batt == pytest.approx(BatteryStorageAppliance.per_kwh_cost())


def test_rates_capital_module_passes_nbc_override_to_step12():
    import pipeline.modules.rates_capital as mod

    cfg = Config(
        scenario="baseline",
        housing_type="single-family-detached",
        counties=["Alameda County"],
        nbc_dollars_per_kwh_override=0.0321,
    )

    with patch.object(mod, "GetLoadsForRates") as m10, \
         patch.object(mod, "EvaluateGasRates") as m11, \
         patch.object(mod, "EvaluateElectricityRates") as m12, \
         patch.object(mod, "CombineTotalAnnualCosts") as m13, \
         patch.object(mod, "BuildCapitalCostsLifetimesIncentives") as m14:
        mod.run(cfg)

    assert m12.process.called
    _, kwargs = m12.process.call_args
    assert kwargs.get("nbc_dollars_per_kwh_override") == 0.0321, (
        "mod_rates_capital.run() must pass cfg.nbc_dollars_per_kwh_override to "
        "step12 — otherwise NBC sensitivity silently has no effect on billing."
    )


def test_visualization_module_passes_discount_rate_to_step18():
    """Source-level check: mocking the full mod_visualization.run() call chain
    (steps 15-22, several with try/except branches) is disproportionate to
    what this regression guards against. Instead assert the actual call site
    includes discount_rate=cfg.discount_rate, which is what broke silently.
    """
    import pipeline.modules.visualization as mod

    source = inspect.getsource(mod.run)
    step18_call_start = source.index("Step18CrossScenarioComparisons.process(")
    step18_call = source[step18_call_start:step18_call_start + 400]
    assert "discount_rate=cfg.discount_rate" in step18_call, (
        "mod_visualization.run() must pass cfg.discount_rate to "
        "Step18CrossScenarioComparisons.process — otherwise the EAC reporting "
        "layer always uses the default rate regardless of Config."
    )


def test_step12_process_forwards_nbc_override_to_nem3_calculation():
    import pipeline.steps.step12_evaluate_electricity_rates as step12

    with patch.object(step12, "process_county_scenario_nem3", wraps=step12.process_county_scenario_nem3) as spy, \
         patch.object(step12, "process_county_scenario_from_series", return_value={}), \
         patch.object(step12, "get_utility_for_county", return_value="PG&E"), \
         patch.object(step12, "utility_to_rate_plans", return_value=["E-TOU-D"]), \
         patch.object(step12, "build_results_df_with_variants", return_value={}), \
         patch.object(step12, "update_df_with_results", side_effect=lambda df, r: df), \
         patch.object(step12, "get_output_file_path", return_value="/dev/null"), \
         patch.object(step12, "update_csv_with_results", side_effect=lambda path, df: df), \
         patch("pandas.DataFrame.to_csv"):
        try:
            step12.process(
                "data/loadprofiles", "data/loadprofiles", "baseline",
                "single-family-detached", ["Alameda County"],
                nbc_dollars_per_kwh_override=0.03,
            )
        except FileNotFoundError:
            pass  # process_county_scenario_nem3 itself will hit real files; we only care it was called correctly

    assert spy.called
    _, kwargs = spy.call_args
    assert kwargs.get("nbc_dollars_per_kwh_override") == 0.03
