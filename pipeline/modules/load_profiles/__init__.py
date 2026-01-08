from __future__ import annotations

from typing import List

from ...config import Config
from helpers.main_helpers import log_step
from scenarios import SCENARIOS

import step1_identify_suitable_buildings as IdentifySuitableBuildings
import step2_pull_buildings as PullBuildings
import step3_build_electricity_load_profiles as BuildElectricityLoadProfiles
import step4_build_gas_load_profiles as BuildGasLoadProfiles
import step5_convert_gas_appliances_to_electrical_appliances as ConvertGasToElectric
import step6_build_electric_vehicle_load_profiles as BuildElectricVehicleLoadProfiles
import step7_combine_real_and_simulated_electricity_loads as CombineRealAndSimulatedProfiles


def run(cfg: Config) -> None:
    """Run Module 1: retrieve buildings and construct load profiles (Steps 1–7)."""
    c_list: List[str] = list(cfg.counties)
    input_dir = "data"  # consistent with previous scripts
    output_dir = cfg.base_input_dir

    # 1) Identify suitable buildings
    log_step(1)
    IdentifySuitableBuildings.process(
        cfg.scenario,
        cfg.housing_type,
        output_base_dir=input_dir,
        target_counties=c_list,
        force_recompute=False,
    )

    # 2) Pull buildings metadata/inputs
    log_step(2)
    PullBuildings.process(
        cfg.scenario,
        cfg.housing_type,
        c_list,
        output_base_dir=input_dir,
        download_new_files=False,
    )

    # 3) Electricity load profiles
    log_step(3)
    BuildElectricityLoadProfiles.process(
        cfg.scenario,
        SCENARIOS[cfg.scenario],
        cfg.housing_type,
        c_list,
        input_dir,
        output_dir,
        force_recompute=False,
    )

    # 4) Gas load profiles
    log_step(4)
    BuildGasLoadProfiles.process(
        input_dir,
        output_dir,
        cfg.scenario,
        SCENARIOS,
        cfg.housing_type,
        c_list,
        force_recompute=False,
    )

    # 5) Convert gas appliances to electrical equivalents
    log_step(5)
    ConvertGasToElectric.process(
        output_dir,
        output_dir,
        c_list,
        cfg.scenario,
        [cfg.housing_type],
        force_recompute=False,
    )

    # 6) EV load profiles
    log_step(6)
    BuildElectricVehicleLoadProfiles.process(
        input_dir,
        output_dir,
        cfg.scenario,
        SCENARIOS[cfg.scenario],
        [cfg.housing_type],
        c_list,
        force_recompute=False,
    )

    # 7) Combine real and simulated electricity loads
    log_step(7)
    CombineRealAndSimulatedProfiles.process(
        output_dir,
        output_dir,
        cfg.scenario,
        [cfg.housing_type],
        c_list,
        force_recompute=False,
    )


__all__ = ["run"]
