from __future__ import annotations

import os
import sys
from typing import Iterable, List


# Ensure repo root is importable
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import step8_get_weather_files as WeatherFiles  # noqa: E402
import step9_my_own_solar_storage as Step9MyOwnSolarStorage  # noqa: E402
import step9b_cooptimize_pv_battery as Step9bCoopt  # noqa: E402


def _is_coopt_scenario(name: str) -> bool:
    return str(name).endswith("_coopt")


def run(
    scenario: str,
    housing_type: str,
    counties: Iterable[str],
    *,
    base_dir: str = "data/loadprofiles",
    weather_year: int = 2018,
) -> None:
    """Run module 2: weather fetch + PV/Storage sizing/dispatch (Steps 8–9)."""
    c_list: List[str] = list(counties)

    # 8) Weather files
    WeatherFiles.process(base_dir, base_dir, scenario, [housing_type], weather_year, c_list)

    # 9) PV/Storage modeling (co‑opt LP variant or default dispatch)
    if _is_coopt_scenario(scenario):
        Step9bCoopt.process(
            base_input_dir=base_dir,
            base_output_dir=base_dir,
            scenario=scenario,
            housing_type=housing_type,
            counties=c_list,
            allow_grid_charging=False,
            allow_batt_export=True,
        )
    else:
        Step9MyOwnSolarStorage.process(
            base_dir,
            base_dir,
            scenario,
            housing_type,
            c_list,
            force_recompute=True,
        )


if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser(description="Module 2: solar + storage")
    p.add_argument("scenario")
    p.add_argument("--housing-type", default="single-family-detached")
    p.add_argument("--counties", nargs="*", default=["Alameda County"])
    p.add_argument("--base-dir", default="data/loadprofiles")
    p.add_argument("--weather-year", type=int, default=2018)
    args = p.parse_args()

    run(args.scenario, args.housing_type, args.counties, base_dir=args.base_dir, weather_year=args.weather_year)

