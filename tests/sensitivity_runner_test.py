"""Orchestration tests for pipeline.sensitivity_runner.run_sensitivity.

Mocks the actual pipeline modules and data access so these run fast and
don't require real county data or an LP solve — they verify *which
functions get called with what arguments*, not the underlying math (that's
covered by lp_cooptimize_test.py and evaluations_methods_test.py).
"""
import os
import sys
from unittest.mock import patch

import pandas as pd
import pytest

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

import pipeline.sensitivity_runner as runner


def _fake_by_county_df(counties, scenarios):
    rows = []
    for c in counties:
        for s in scenarios:
            rows.append({
                "scenario": s,
                "county_slug": c,
                "capex_pv": 100.0,
                "capex_storage": 50.0,
                "capex_electric": 200.0,
                "capex_gas": 0.0,
                "annual_bill_electric": 500.0,
                "annual_bill_gas": 0.0,
                "vehicle_om": 0.0,
            })
    return pd.DataFrame(rows)


def test_discount_rate_sweep_calls_lp_resolve_for_each_value():
    with patch.object(runner, "mod_solar_storage") as mock_solar, \
         patch.object(runner, "mod_rates_capital") as mock_rates, \
         patch.object(runner, "collect_eac_components_by_county") as mock_collect, \
         patch.object(runner, "merge_and_write_csv") as mock_write:
        mock_collect.side_effect = lambda *a, **k: _fake_by_county_df(["alameda"], ["baseline_coopt"])

        runner.run_sensitivity(
            "discount_rate",
            [0.03, 0.07, 0.10],
            scenario="baseline_coopt",
            sibling_scenarios=["baseline_coopt"],
            counties=["Alameda County"],
        )

    assert mock_solar.run.call_count == 3, "discount_rate requires an LP resolve for every swept value"
    assert mock_rates.run.call_count == 3
    rates_seen = [call.args[0].discount_rate for call in mock_solar.run.call_args_list]
    assert rates_seen == [0.03, 0.07, 0.10]


def test_nbc_sweep_never_calls_lp_resolve():
    with patch.object(runner, "mod_solar_storage") as mock_solar, \
         patch.object(runner, "mod_rates_capital") as mock_rates, \
         patch.object(runner, "collect_eac_components_by_county") as mock_collect, \
         patch.object(runner, "merge_and_write_csv"):
        mock_collect.side_effect = lambda *a, **k: _fake_by_county_df(["alameda"], ["baseline"])

        runner.run_sensitivity(
            "nbc_dollars_per_kwh",
            [0.0, 0.02, 0.03],
            scenario="baseline",
            sibling_scenarios=["baseline"],
            counties=["Alameda County"],
        )

    assert mock_solar.run.call_count == 0, (
        "NBC sensitivity must not re-solve the LP (see SENSITIVITY_PARAMETERS docstring) — "
        "if this now fails, the methodology decision changed and this test should be updated deliberately"
    )
    assert mock_rates.run.call_count == 3
    nbc_seen = [call.args[0].nbc_dollars_per_kwh_override for call in mock_rates.run.call_args_list]
    assert nbc_seen == [0.0, 0.02, 0.03]


def test_output_is_tagged_and_written_with_composite_key():
    with patch.object(runner, "mod_solar_storage"), \
         patch.object(runner, "mod_rates_capital"), \
         patch.object(runner, "collect_eac_components_by_county") as mock_collect, \
         patch.object(runner, "merge_and_write_csv") as mock_write:
        mock_collect.side_effect = lambda *a, **k: _fake_by_county_df(["alameda", "fresno"], ["baseline_coopt"])

        result = runner.run_sensitivity(
            "discount_rate",
            [0.05],
            scenario="baseline_coopt",
            sibling_scenarios=["baseline_coopt"],
            counties=["Alameda County", "Fresno County"],
        )

    assert set(result["parameter"]) == {"discount_rate"}
    assert set(result["value"]) == {0.05}
    assert "total_eac" in result.columns
    assert (result["total_eac"] > 0).all()

    assert mock_write.called
    _, kwargs = mock_write.call_args
    assert kwargs.get("key_col") == ["parameter", "value", "scenario", "county_slug"]


def test_unknown_parameter_raises_clear_error():
    with pytest.raises(ValueError, match="Unknown sensitivity parameter"):
        runner.run_sensitivity(
            "not_a_real_parameter",
            [1, 2],
            scenario="baseline",
            sibling_scenarios=["baseline"],
            counties=["Alameda County"],
        )
