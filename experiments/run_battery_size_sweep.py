from __future__ import annotations

import argparse
import os
from typing import List

try:
    from .battery_size_sweep import run, BatterySweepOptions  # type: ignore
except Exception:
    import sys
    sys.path.append(os.path.dirname(os.path.dirname(__file__)))
    from experiments.battery_size_sweep import run, BatterySweepOptions  # type: ignore

from main_helpers import norcal_counties, socal_counties, central_counties
import step9_my_own_solar_storage as diy


def parse_args():
    p = argparse.ArgumentParser(description="Run experimental Battery-size sweeps (non-intrusive)")
    p.add_argument("--base-input-dir", default="data/loadprofiles")
    p.add_argument("--experiments-root", default="data/experiments/battery_size_sweep")
    p.add_argument("--scenario", default="baseline")
    p.add_argument("--housing-type", default="single-family-detached")
    p.add_argument("--counties", nargs="*")
    p.add_argument("--all-counties", action="store_true")
    p.add_argument("--capacities", default="3,5,7.5,10,12.5,15", help="Comma-separated battery sizes in kWh")
    p.add_argument("--enable-pv-surplus", action="store_true", help="Enable PV→Battery surplus charging")
    p.add_argument("--compute-bills", action="store_true", help="Compute total bills via Steps 10/11/13 into experiments tree")
    return p.parse_args()


def main():
    args = parse_args()
    base_input = args.base_input_dir
    exp_root = args.experiments_root
    scenario = args.scenario
    housing = args.housing_type
    if args.all_counties:
        counties = norcal_counties + socal_counties + central_counties
    else:
        counties = args.counties or ["Alameda County"]
    capacities = [float(s) for s in args.capacities.split(',') if s.strip()]
    opts = BatterySweepOptions(
        enable_pv_surplus_to_battery=args.enable_pv_surplus,
        compute_bills=args.compute_bills,
    )
    dispatch_label = "dispatch_dynamic" if getattr(diy, "USE_DYNAMIC_DISPATCH", False) else "dispatch_classic"
    eff_root = os.path.join(exp_root, dispatch_label)
    os.makedirs(eff_root, exist_ok=True)
    results = run(
        base_input,
        scenario,
        housing,
        counties=counties,
        capacities_kwh=capacities,
        options=opts,
        experiments_root=eff_root,
    )
    print(f"Battery-size sweep complete for {len(results)} counties. Output: {os.path.abspath(eff_root)}")


if __name__ == "__main__":
    main()
