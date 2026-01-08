from __future__ import annotations

import os
import runpy
from typing import Dict, Iterable, List, Optional

from ...config import Config
from helpers.main_helpers import log_step

import step15_payback_periods as PaybackPeriods
import step18_cross_scenario_comparisons as Step18CrossScenarioComparisons
import step19_compare_two_scenarios as Step19CompareTwoScenarios
import step20_no_solar_storage_electrification as Step20NoSolarStorageElectrification
import step21_compare_eac_with_vs_without as Step21CompareEACWithVsWithout
import step22_build_county_diagnostics as Step22BuildCountyDiagnostics
from scenarios import SCENARIOS


def _plan_pref_from(rate_plans: Optional[Dict[str, Dict[str, str]]]) -> Optional[List[str]]:
    if not rate_plans:
        return None
    try:
        return list({
            v.get('electricity') for v in rate_plans.values()
            if isinstance(v, dict) and v.get('electricity')
        })
    except Exception:
        return None


def run(cfg: Config) -> None:
    """Run Module 4: visualize and compare results (Steps 15, 18–22)."""
    c_list: List[str] = list(cfg.counties)
    os.makedirs(cfg.output_dir, exist_ok=True)

    # Compute plan preference if not provided
    plan_preference = _plan_pref_from(cfg.rate_plans)

    # Print assumptions summary (dispatch + sizing + plan preference)
    try:
        step9_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
                                  "2_compute-and-cooptimize-solar-storage",
                                  "step9_my_own_solar_storage.py")
        ns = runpy.run_path(step9_path, run_name="__not_main__")
        pv_size_fraction = ns.get("PV_SIZE_FRACTION")
        use_eac_opt = bool(ns.get("USE_EAC_OPTIMAL_SIZING", False))
        batt = ns.get("BATTERY_CAPACITY_KWH")
        mode = "dynamic PV-only"
        sizing = (
            "EAC-optimal per county"
            if use_eac_opt
            else (
                f"fraction of annual-match (PV_SIZE_FRACTION={pv_size_fraction})"
                if pv_size_fraction is not None
                else "default sizing"
            )
        )
        plans = list(plan_preference) if plan_preference else []
        plan_str = f"; Electricity plan preference: {', '.join(plans)}" if plans else ""
        batt_str = f", default battery ≈{batt} kWh" if batt else ""
        print("\nAssumptions — " + f"Dispatch: {mode}; Sizing: {sizing}{batt_str}{plan_str}; Billing variant: NEM3 for with-solar")
    except Exception:
        pass

    # 15) Payback periods
    log_step(15)
    PaybackPeriods.process(cfg.base_input_dir, cfg.scenario, cfg.housing_type, c_list)

    # 18) Cross-scenario EAC (use all scenarios)
    log_step(18)
    Step18CrossScenarioComparisons.process(
        cfg.base_input_dir,
        cfg.output_dir,
        cfg.housing_type,
        list(SCENARIOS.keys()),
        c_list,
        plan_preference=plan_preference,
        electricity_variant=cfg.electricity_variant,
    )

    # 19) EV vs ICE comparison
    log_step(19)
    Step19CompareTwoScenarios.process(
        cfg.base_input_dir,
        cfg.output_dir,
        cfg.housing_type,
        ["baseline_ice_car", "baseline_ev_car"],
        c_list,
        plan_preference=plan_preference,
        electricity_variant=cfg.electricity_variant,
    )

    # 20) No-solar EAC for the current scenario
    log_step(20)
    Step20NoSolarStorageElectrification.process(
        cfg.base_input_dir,
        cfg.output_dir,
        cfg.housing_type,
        [cfg.scenario],
        c_list,
        incentive=cfg.incentive,
        discount_rate=cfg.discount_rate,
        agg=cfg.agg,
    )

    # 21) With vs without PV for the current scenario
    log_step(21)
    Step21CompareEACWithVsWithout.process(
        cfg.base_input_dir,
        cfg.output_dir,
        cfg.housing_type,
        cfg.scenario,
        c_list,
        plan_preference=plan_preference,
        electricity_variant=cfg.electricity_variant,
        incentive=cfg.incentive,
        discount_rate=cfg.discount_rate,
        agg=cfg.agg,
    )

    # 22) Per-county diagnostics
    log_step(22)
    Step22BuildCountyDiagnostics.process(
        cfg.base_input_dir,
        cfg.output_dir,
        cfg.housing_type,
        cfg.scenario,
        c_list,
    )


__all__ = ["run"]
