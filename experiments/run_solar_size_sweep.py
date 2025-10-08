from __future__ import annotations

import argparse
import os
from typing import List

from experiments.solar_size_sweep import run, SweepOptions
from main_helpers import norcal_counties, socal_counties, central_counties


def parse_args():
    p = argparse.ArgumentParser(description="Run experimental PV-size sweeps (non-intrusive)")
    p.add_argument("--base-input-dir", default="data/loadprofiles")
    p.add_argument("--experiments-root", default="data/experiments/solar_size_sweep")
    p.add_argument("--scenario", default="baseline")
    p.add_argument("--housing-type", default="single-family-detached")
    p.add_argument("--counties", nargs="*")
    p.add_argument("--all-counties", action="store_true")
    p.add_argument("--fractions", default="0.1,0.2,0.3,0.4,0.5,0.6,0.7,0.8,0.9,1.0")
    p.add_argument("--enable-pv-surplus", action="store_true", help="Enable PV→Battery surplus charging")
    p.add_argument("--disable-grid-charging", action="store_true", help="Disable scheduled grid charging")
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
    fracs = [float(s) for s in args.fractions.split(',') if s.strip()]
    opts = SweepOptions(
        enable_pv_surplus_to_battery=args.enable_pv_surplus,
        grid_charging_enabled=(not args.disable_grid_charging),
        compute_bills=args.compute_bills,
    )
    os.makedirs(exp_root, exist_ok=True)
    results = run(
        base_input,
        scenario,
        housing,
        counties=counties,
        fractions=fracs,
        options=opts,
        experiments_root=exp_root,
    )
    print(f"PV-size sweep complete for {len(results)} counties. Output: {os.path.abspath(exp_root)}")


if __name__ == "__main__":
    main()

