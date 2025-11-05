"""
Step 19: Compare All-in Annualized Cost (EAC) for two scenarios

This script produces a focused comparison of two scenarios' all-in annualized cost
(stacked bar by component), aggregated across selected counties.

Defaults compare baseline_ice_car vs baseline_ev for single-family-detached.

Outputs:
- CSV summary of EAC components per scenario (+ a differences row)
- Stacked bar PNG showing component breakdown side-by-side

Usage examples:
  python3 step19_compare_two_scenarios.py \
      --scenarios baseline_ice_car baseline_ev \
      --housing-type single-family-detached \
      --all-counties

  python3 step19_compare_two_scenarios.py --counties "Alameda County" "San Diego County"
"""

from __future__ import annotations

import argparse
import os
import subprocess
from typing import List

import pandas as pd

from helpers.plot_scenario_comparison_helper import (
    collect_eac_components,
    plot_eac_stacked_bar,
)
from scenarios import SCENARIOS
from helpers.main_helpers import get_scenario_path


def _git_short_sha() -> str:
    try:
        sha = subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], stderr=subprocess.DEVNULL).decode().strip()
        return sha or "nogit"
    except Exception:
        return "nogit"


def _discover_counties(base_input_dir: str, housing_type: str, scenarios: List[str]) -> List[str]:
    counties: set[str] = set()
    for scen in scenarios:
        scen_path = get_scenario_path(base_input_dir, scen, housing_type)
        if not os.path.isdir(scen_path):
            continue
        for name in os.listdir(scen_path):
            path = os.path.join(scen_path, name)
            if os.path.isdir(path) and not name.startswith('.'):
                counties.add(name)
    return sorted(counties)


def _differences_row(df: pd.DataFrame, scenario_a: str, scenario_b: str) -> pd.DataFrame:
    """Return a one-row DataFrame with component differences (B - A) and totals."""
    a = df[df["scenario"] == scenario_a]
    b = df[df["scenario"] == scenario_b]
    if a.empty or b.empty:
        return pd.DataFrame()
    comps = [
        "capex_pv", "capex_storage", "capex_electric", "capex_gas",
        "annual_bill_with_solar", "vehicle_om",
    ]
    diff = {"scenario": f"{scenario_b} - {scenario_a}"}
    for c in comps:
        diff[c] = float(b[c].values[0]) - float(a[c].values[0])
    diff["total_eac"] = sum(diff[c] for c in comps)
    return pd.DataFrame([diff])


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare all-in annualized cost for two scenarios")
    parser.add_argument("--base-input-dir", default="data/loadprofiles", help="Base input directory")
    parser.add_argument("--output-dir", default="analysis_results", help="Directory for outputs")
    parser.add_argument("--housing-type", default="single-family-detached", help="Housing type")
    parser.add_argument(
        "--scenarios",
        nargs=2,
        default=["baseline_ice_car", "baseline_ev_car"],
        help="Exactly two scenarios to compare (default: baseline_ice_car vs baseline_ev_car)",
    )
    parser.add_argument("--counties", nargs="*", help="Counties (names or slugs). If omitted, use --all-counties or default Alameda County")
    parser.add_argument("--all-counties", action="store_true", help="Use all available counties under the scenarios")
    parser.add_argument("--agg", choices=["mean", "median"], default="mean", help="Aggregation across counties")

    args = parser.parse_args()

    base_input_dir = args.base_input_dir
    output_dir = args.output_dir
    housing_type = args.housing_type
    scenarios = list(dict.fromkeys(args.scenarios))  # keep order, dedup if needed

    # Validate scenarios exist in SCENARIOS
    for s in scenarios:
        if s not in SCENARIOS:
            raise SystemExit(f"Unknown scenario '{s}'. Available: {', '.join(SCENARIOS.keys())}")

    os.makedirs(output_dir, exist_ok=True)

    if args.all_counties:
        counties = _discover_counties(base_input_dir, housing_type, scenarios)
    elif args.counties:
        counties = args.counties
    else:
        counties = ["Alameda County"]

    # Collect EAC components
    eac_df = collect_eac_components(base_input_dir, housing_type, scenarios, counties, incentive='full_incentives', agg=args.agg)
    # Compute totals for convenience
    if not eac_df.empty:
        eac_df["total_eac"] = (
            eac_df["capex_pv"] + eac_df["capex_storage"] + eac_df["capex_electric"] +
            eac_df["capex_gas"] + eac_df["annual_bill_with_solar"] + eac_df["vehicle_om"]
        )

    # Save summary CSV with a differences row
    sha = _git_short_sha()
    csv_path = os.path.join(output_dir, f"step19_eac_compare_{scenarios[0]}_vs_{scenarios[1]}_g{sha}.csv")
    if not eac_df.empty:
        diff_df = _differences_row(eac_df, scenarios[0], scenarios[1])
        out_df = pd.concat([eac_df, diff_df], ignore_index=True)
        out_df.to_csv(csv_path, index=False)

    # Plot stacked bars for the two scenarios
    fig = plot_eac_stacked_bar(eac_df, scenario_order=scenarios, title=f"All-in Annualized Cost — {scenarios[0]} vs {scenarios[1]}")
    png_path = os.path.join(output_dir, f"step19_eac_stacked_bar_{scenarios[0]}_vs_{scenarios[1]}_g{sha}.png")
    fig.savefig(png_path, dpi=150, bbox_inches="tight")

    print("Step 19 comparison complete.")
    print(f"  Scenarios: {scenarios}")
    print(f"  Counties:  {counties}")
    print(f"  Saved CSV: {os.path.abspath(csv_path)}")
    print(f"  Saved PNG: {os.path.abspath(png_path)}")


if __name__ == "__main__":
    main()

