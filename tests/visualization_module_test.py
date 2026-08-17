import os
import sys

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from pipeline.modules.visualization import (  # noqa: E402
    _cross_scenario_list,
    _plan_pref_from,
    _vehicle_compare_pair,
)
from pipeline.steps.step18_cross_scenario_comparisons import _default_scenarios  # noqa: E402
from scenarios import SCENARIOS  # noqa: E402


def test_cross_scenario_list_non_coopt() -> None:
    scenarios = _cross_scenario_list("baseline")
    assert scenarios
    assert all(not s.endswith("_coopt") for s in scenarios)
    assert "baseline" in scenarios
    assert "baseline_coopt" not in scenarios


def test_cross_scenario_list_coopt() -> None:
    scenarios = _cross_scenario_list("baseline_coopt")
    assert scenarios
    assert all(s.endswith("_coopt") for s in scenarios)
    assert "baseline_coopt" in scenarios
    assert "baseline" not in scenarios


def test_vehicle_compare_pair_tracks_scenario_family() -> None:
    assert _vehicle_compare_pair("baseline") == ["baseline_ice_car", "baseline_ev_car"]
    assert _vehicle_compare_pair("baseline_coopt") == [
        "baseline_ice_car_coopt",
        "baseline_ev_car_coopt",
    ]


def test_step18_default_scenarios_are_non_coopt() -> None:
    expected = [s for s in SCENARIOS.keys() if not s.endswith("_coopt")]
    assert _default_scenarios() == expected


def test_plan_preferences_preserve_configured_utility_order() -> None:
    rate_plans = {
        "PG&E": {"electricity": "E-TOU-D", "gas": "G-1"},
        "SCE": {"electricity": "TOU-D-4-9PM", "gas": "GR"},
        "duplicate": {"electricity": "E-TOU-D", "gas": "G-1"},
        "SDG&E": {"electricity": "TOU-DR1", "gas": "GR"},
    }

    assert _plan_pref_from(rate_plans) == [
        "E-TOU-D",
        "TOU-D-4-9PM",
        "TOU-DR1",
    ]
