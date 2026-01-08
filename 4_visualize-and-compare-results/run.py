from __future__ import annotations

import os
import sys
from typing import Iterable, List, Optional


# Ensure module folder and repo root are importable
MODDIR = os.path.dirname(os.path.abspath(__file__))
if MODDIR not in sys.path:
    sys.path.insert(0, MODDIR)
ROOT = os.path.dirname(os.path.dirname(MODDIR))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from scenarios import SCENARIOS  # noqa: E402

import step15_payback_periods as PaybackPeriods  # noqa: E402
# import step16_display_key_metrics_maps as DisplayMaps  # optional, mirrors cost_service (commented)
import step18_cross_scenario_comparisons as Step18CrossScenarioComparisons  # noqa: E402
import step19_compare_two_scenarios as Step19CompareTwoScenarios  # noqa: E402
import step20_no_solar_storage_electrification as Step20NoSolarStorageElectrification  # noqa: E402
import step21_compare_eac_with_vs_without as Step21CompareEACWithVsWithout  # noqa: E402
import step22_build_county_diagnostics as Step22BuildCountyDiagnostics  # noqa: E402
from helpers.main_helpers import log_step  # noqa: E402


def run(
    scenario: str,
    housing_type: str,
    counties: Iterable[str],
    *,
    base_input_dir: str = "data/loadprofiles",
    output_dir: str = "analysis_results",
    electricity_variant: str = "nem3",
    plan_preference: Optional[Iterable[str]] = None,
    incentive: str = "full_incentives",
    discount_rate: float = 0.07,
    agg: str = "mean",
) -> None:
    """Run module 4: visualize and compare results (Steps 15, 18–22)."""
    c_list: List[str] = list(counties)
    os.makedirs(output_dir, exist_ok=True)
    # 15) Payback periods
    log_step(15)
    PaybackPeriods.process(base_input_dir, scenario, housing_type, c_list)

    # 16) Optional maps (kept commented to match cost_service behavior)
    # DisplayMaps.process(base_input_dir, base_input_dir, scenario, housing_type, c_list, desired_rate_plans)

    # 18) Cross-scenario EAC (use all scenarios)
    log_step(18)
    Step18CrossScenarioComparisons.process(
        base_input_dir,
        output_dir,
        housing_type,
        list(SCENARIOS.keys()),
        c_list,
        plan_preference=list(plan_preference) if plan_preference else None,
        electricity_variant=electricity_variant,
    )

    # 19) EV vs ICE comparison
    log_step(19)
    Step19CompareTwoScenarios.process(
        base_input_dir,
        output_dir,
        housing_type,
        ["baseline_ice_car", "baseline_ev_car"],
        c_list,
        plan_preference=list(plan_preference) if plan_preference else None,
        electricity_variant=electricity_variant,
    )

    # 20) No-solar EAC for the current scenario
    log_step(20)
    Step20NoSolarStorageElectrification.process(
        base_input_dir,
        output_dir,
        housing_type,
        [scenario],
        c_list,
        incentive=incentive,
        discount_rate=discount_rate,
        agg=agg,
    )

    # 21) With vs without PV for the current scenario
    log_step(21)
    Step21CompareEACWithVsWithout.process(
        base_input_dir,
        output_dir,
        housing_type,
        scenario,
        c_list,
        plan_preference=list(plan_preference) if plan_preference else None,
        electricity_variant=electricity_variant,
        incentive=incentive,
        discount_rate=discount_rate,
        agg=agg,
    )

    # 22) Per-county diagnostics
    log_step(22)
    Step22BuildCountyDiagnostics.process(
        base_input_dir,
        output_dir,
        housing_type,
        scenario,
        c_list,
    )


if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser(description="Module 4: visualization & comparison")
    p.add_argument("scenario")
    p.add_argument("--housing-type", default="single-family-detached")
    p.add_argument("--counties", nargs="*", default=["Alameda County"])
    p.add_argument("--base-input-dir", default="data/loadprofiles")
    p.add_argument("--output-dir", default="analysis_results")
    args = p.parse_args()

    run(
        args.scenario,
        args.housing_type,
        args.counties,
        base_input_dir=args.base_input_dir,
        output_dir=args.output_dir,
    )
