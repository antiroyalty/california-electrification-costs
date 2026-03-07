from __future__ import annotations

import os
from typing import Dict, Iterable, List, Optional

from ...config import Config
from helpers.main_helpers import log_step

from pipeline.steps import step15_payback_periods as PaybackPeriods
from pipeline.steps import step16_display_key_metrics_maps as Step16DisplayMaps
from pipeline.steps import step18_cross_scenario_comparisons as Step18CrossScenarioComparisons
from pipeline.steps import step19_compare_two_scenarios as Step19CompareTwoScenarios
from pipeline.steps import step20_no_solar_storage_electrification as Step20NoSolarStorageElectrification
from pipeline.steps import step21_compare_eac_with_vs_without as Step21CompareEACWithVsWithout
from pipeline.steps import step22_build_county_diagnostics as Step22BuildCountyDiagnostics
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


def _is_coopt_scenario(name: str) -> bool:
    return str(name).endswith("_coopt")


def _cross_scenario_list(current_scenario: str) -> List[str]:
    """Return cross-scenario set aligned to the current scenario family."""
    want_coopt = _is_coopt_scenario(current_scenario)
    return [s for s in SCENARIOS.keys() if _is_coopt_scenario(s) == want_coopt]


def _vehicle_compare_pair(current_scenario: str) -> List[str]:
    if _is_coopt_scenario(current_scenario):
        return ["baseline_ice_car_coopt", "baseline_ev_car_coopt"]
    return ["baseline_ice_car", "baseline_ev_car"]


def run(cfg: Config) -> None:
    """Run Module 4: visualize and compare results (Steps 15, 16, 18–22)."""
    c_list: List[str] = list(cfg.counties)
    os.makedirs(cfg.output_dir, exist_ok=True)

    # Compute plan preference if not provided
    plan_preference = _plan_pref_from(cfg.rate_plans)

    # Print assumptions summary (dispatch + sizing + plan preference)
    try:
        from pipeline.steps import step9_my_own_solar_storage as S9
        pv_size_fraction = getattr(S9, "PV_SIZE_FRACTION", None)
        use_eac_opt = bool(getattr(S9, "USE_EAC_OPTIMAL_SIZING", False))
        batt = getattr(S9, "BATTERY_CAPACITY_KWH", None)
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

    # 16) Key metrics maps (HTML dashboard + appliance breakdown)
    # Skipping map regeneration by default.
    # try:
    #     log_step(16)
    #     Step16DisplayMaps.process(
    #         cfg.base_input_dir,
    #         cfg.base_input_dir,
    #         cfg.scenario,
    #         cfg.housing_type,
    #         c_list,
    #         cfg.rate_plans or {},
    #     )
    # except Exception as e:
    #     # Non-fatal — continue with other visualizations
    #     print(f"[Step16] Warning: map generation failed: {e}")

    # 18) Cross-scenario EAC (stay within current scenario family: coopt vs non-coopt)
    log_step(18)
    Step18CrossScenarioComparisons.process(
        cfg.base_input_dir,
        cfg.output_dir,
        cfg.housing_type,
        _cross_scenario_list(cfg.scenario),
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
        _vehicle_compare_pair(cfg.scenario),
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
        open_browser=True,
    )


__all__ = ["run"]
