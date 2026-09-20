from __future__ import annotations

import os
from typing import List

from ...config import Config
from helpers.main_helpers import log_step, slugify_county_name

from pipeline.steps import step8_get_weather_files as WeatherFiles
from pipeline.steps import step9_my_own_solar_storage as Step9MyOwnSolarStorage
from pipeline.steps import step9b_cooptimize_pv_battery as Step9bCoopt
from appliances.solar_system import SolarSystemAppliance
from appliances.battery_storage import BatteryStorageAppliance
from appliances.electric_base import IncentiveScenario


def _is_coopt_scenario(name: str) -> bool:
    return str(name).endswith("_coopt")


def run(cfg: Config) -> None:
    """Run Module 2: compute and co‑optimize solar and storage (Steps 8–9)."""
    if cfg.coopt_federal_credit_policy is not None and not _is_coopt_scenario(cfg.scenario):
        raise ValueError("Federal purchase-credit sizing requires a _coopt scenario")
    base_dir = cfg.base_input_dir
    c_list: List[str] = list(cfg.counties)

    # Reuse baseline weather for co-opt scenarios (copy if needed)
    if _is_coopt_scenario(cfg.scenario):
        for c in c_list:
            slug = slugify_county_name(c)
            base_raw = os.path.join(base_dir, "baseline", cfg.housing_type, slug, f"weather_TMY_{slug}.csv")
            coopt_raw = os.path.join(base_dir, cfg.scenario, cfg.housing_type, slug, f"weather_TMY_{slug}.csv")
            if not os.path.exists(coopt_raw) and os.path.exists(base_raw):
                os.makedirs(os.path.dirname(coopt_raw), exist_ok=True)
                try:
                    import shutil
                    shutil.copy2(base_raw, coopt_raw)
                    print(f"[coopt] Copied weather for {slug}: {coopt_raw}")
                except Exception as e:
                    print(f"[coopt] Warning: could not copy weather for {slug}: {e}")

    # 8) Weather files
    log_step(8)
    WeatherFiles.process(base_dir, base_dir, cfg.scenario, [cfg.housing_type], 2018, c_list)

    # 9) PV/Storage modeling
    log_step(9)
    if _is_coopt_scenario(cfg.scenario):
        # The LP's sizing decision should reflect what the modeled
        # decision-maker actually pays under the incentive scenario being
        # run — not a fixed default that only matches full_incentives.
        # See step9b_cooptimize_pv_battery.py for the full note
        # (2026-07-07 refinement).
        incentive_scenario = IncentiveScenario(cfg.incentive)
        if cfg.coopt_federal_credit_policy is None:
            pv_unit_cost = SolarSystemAppliance.per_kw_cost_net(incentive_scenario)
            battery_unit_cost = BatteryStorageAppliance.per_kwh_cost_net(incentive_scenario)
        else:
            # The solver deducts the initial credit once; net prices would count it twice.
            pv_unit_cost = SolarSystemAppliance.per_kw_cost()
            battery_unit_cost = BatteryStorageAppliance.per_kwh_cost()
        Step9bCoopt.process(
            base_input_dir=base_dir,
            base_output_dir=base_dir,
            scenario=cfg.scenario,
            housing_type=cfg.housing_type,
            counties=c_list,
            allow_grid_charging=False,
            allow_batt_export=True,
            discount_rate=cfg.discount_rate,
            pv_capex_per_kw=pv_unit_cost,
            batt_capex_per_kwh=battery_unit_cost,
            max_battery_kwh=cfg.max_battery_kwh,
            solver_options=cfg.coopt_solver,
            federal_credit_policy=cfg.coopt_federal_credit_policy,
            nbt_scenario=cfg.nbt_scenario(),
            nbc_dollars_per_kwh_override=cfg.nbc_dollars_per_kwh_override,
        )
    else:
        Step9MyOwnSolarStorage.process(
            base_dir,
            base_dir,
            cfg.scenario,
            cfg.housing_type,
            c_list,
            force_recompute=True,
        )


__all__ = ["run"]
