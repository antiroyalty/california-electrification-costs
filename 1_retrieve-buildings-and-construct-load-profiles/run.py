from __future__ import annotations

import os
import sys
from typing import Iterable, List


# Ensure module folder and repo root are importable
MODDIR = os.path.dirname(os.path.abspath(__file__))
if MODDIR not in sys.path:
    sys.path.insert(0, MODDIR)
ROOT = os.path.dirname(os.path.dirname(MODDIR))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from scenarios import SCENARIOS  # noqa: E402

import step1_identify_suitable_buildings as IdentifySuitableBuildings  # noqa: E402
import step2_pull_buildings as PullBuildings  # noqa: E402
import step3_build_electricity_load_profiles as BuildElectricityLoadProfiles  # noqa: E402
import step4_build_gas_load_profiles as BuildGasLoadProfiles  # noqa: E402
import step5_convert_gas_appliances_to_electrical_appliances as ConvertGasToElectric  # noqa: E402
import step6_build_electric_vehicle_load_profiles as BuildElectricVehicleLoadProfiles  # noqa: E402
import step7_combine_real_and_simulated_electricity_loads as CombineRealAndSimulatedProfiles  # noqa: E402


def run(
    scenario: str,
    housing_type: str,
    counties: Iterable[str],
    *,
    input_dir: str = "data",
    output_dir: str = "data/loadprofiles",
) -> None:
    """Run module 1: retrieve buildings and construct load profiles (Steps 1–7)."""
    c_list: List[str] = list(counties)

    # 1) Identify suitable buildings
    IdentifySuitableBuildings.process(
        scenario,
        housing_type,
        output_base_dir=input_dir,
        target_counties=c_list,
        force_recompute=False,
    )

    # 2) Pull buildings metadata/inputs
    PullBuildings.process(
        scenario,
        housing_type,
        c_list,
        output_base_dir=input_dir,
        download_new_files=False,
    )

    # 3) Electricity load profiles
    BuildElectricityLoadProfiles.process(
        scenario,
        SCENARIOS[scenario],
        housing_type,
        c_list,
        input_dir,
        output_dir,
        force_recompute=False,
    )

    # 4) Gas load profiles
    BuildGasLoadProfiles.process(
        input_dir,
        output_dir,
        scenario,
        SCENARIOS,
        housing_type,
        c_list,
        force_recompute=False,
    )

    # 5) Convert gas appliances to electrical equivalents
    ConvertGasToElectric.process(
        output_dir,
        output_dir,
        c_list,
        scenario,
        [housing_type],
        force_recompute=False,
    )

    # 6) EV load profiles
    BuildElectricVehicleLoadProfiles.process(
        input_dir,
        output_dir,
        scenario,
        SCENARIOS[scenario],
        [housing_type],
        c_list,
        force_recompute=False,
    )

    # 7) Combine real and simulated electricity loads
    CombineRealAndSimulatedProfiles.process(
        output_dir,
        output_dir,
        scenario,
        [housing_type],
        c_list,
        force_recompute=False,
    )


if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser(description="Module 1: load profiles")
    p.add_argument("scenario")
    p.add_argument("--housing-type", default="single-family-detached")
    p.add_argument("--counties", nargs="*", default=["Alameda County"])
    p.add_argument("--input-dir", default="data")
    p.add_argument("--output-dir", default="data/loadprofiles")
    args = p.parse_args()

    run(args.scenario, args.housing_type, args.counties, input_dir=args.input_dir, output_dir=args.output_dir)
