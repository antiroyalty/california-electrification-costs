"""
Step 18: Cross-Scenario Comparisons

Command-line tool to aggregate results across scenarios and generate
reusable comparison plots for:
- Payback periods (with solar) across incentive levels
- Annual kWh flows (Load Profile, System→Load, Battery→Load, Grid→Load)
- Annual savings with solar and total annual bill (with solar)

This script uses helpers in plot_scenario_comparison_helper.py and writes
summary CSVs and PNG plots to analysis_results/.

Examples
  python3 step18_cross_scenario_comparisons.py \
      --housing-type single-family-detached \
      --scenarios baseline induction_stove heat_pump water_heating full_electric_ev \
      --all-counties

  python3 step18_cross_scenario_comparisons.py --counties "Alameda County" "Marin County"
"""

from __future__ import annotations

import argparse
import os
import subprocess
from typing import List, Set

import pandas as pd

from helpers.main_helpers import git_short_sha
from helpers.plot_scenario_comparison_helper import (
    collect_payback_with_solar,
    plot_payback_dotline,
    collect_kwh_flows,
    plot_kwh_flows_dotline,
    collect_savings_and_bills,
    plot_savings_and_bills_dotline,
    collect_eac_components,
    plot_eac_stacked_bar,
    collect_pv_sizes,
    plot_pv_size_bar,
)

from helpers.main_helpers import get_scenario_path
from scenarios import SCENARIOS




def _discover_counties(base_input_dir: str, housing_type: str, scenarios: List[str]) -> List[str]:
    """Return a sorted union of county folder names (slugs) found under all scenarios."""
    counties: Set[str] = set()
    for scen in scenarios:
        scen_path = get_scenario_path(base_input_dir, scen, housing_type)
        if not os.path.isdir(scen_path):
            continue
        for name in os.listdir(scen_path):
            path = os.path.join(scen_path, name)
            if os.path.isdir(path) and not name.startswith('.'):
                counties.add(name)
    return sorted(counties)


def main() -> None:
    parser = argparse.ArgumentParser(description="Cross-scenario comparison plots")
    parser.add_argument("--base-input-dir", default="data/loadprofiles", help="Base input directory (default: data/loadprofiles)")
    parser.add_argument("--output-dir", default="analysis_results", help="Output directory for plots/CSVs")
    parser.add_argument("--housing-type", default="single-family-detached", help="Housing type")
    parser.add_argument(
        "--scenarios",
        nargs="*",
        help="Scenarios to include (default: all from scenarios.py)",
    )
    parser.add_argument("--counties", nargs="*", help="Counties (names or slugs). If omitted, use --all-counties or default to Alameda County")
    parser.add_argument("--all-counties", action="store_true", help="Use all available counties under the provided scenarios")
    parser.add_argument("--agg", choices=["mean", "median"], default="mean", help="Aggregation across counties")
    parser.add_argument(
        "--run-timestamp",
        default=None,
        help="Optional YYYYMMDD_HH timestamp to select specific Step 10/11/13 results instead of latest",
    )

    args = parser.parse_args()

    base_input_dir = args.base_input_dir
    output_dir = args.output_dir
    housing_type = args.housing_type
    # Use all scenarios from scenarios.py when none provided
    if args.scenarios:
        scenarios = list(dict.fromkeys(args.scenarios))  # preserve order, dedup
    else:
        scenarios = list(SCENARIOS.keys())

    # Include all scenarios, including baseline_ice_car, so Vehicle O&M (gasoline) can be shown in EAC.
    os.makedirs(output_dir, exist_ok=True)

    if args.all_counties:
        counties = _discover_counties(base_input_dir, housing_type, scenarios)
    elif args.counties:
        counties = args.counties
    else:
        counties = ["Alameda County"]

    sha = git_short_sha()

    # 1) Payback (with solar)
    payback_df = collect_payback_with_solar(base_input_dir, housing_type, scenarios, counties, agg=args.agg)
    payback_csv = os.path.join(output_dir, f"step18_payback_with_solar_summary_g{sha}.csv")
    if not payback_df.empty:
        payback_df.to_csv(payback_csv, index=False)
    fig, _ = plot_payback_dotline(payback_df, scenario_order=scenarios)
    fig.savefig(os.path.join(output_dir, f"step18_payback_with_solar_dotline_g{sha}.png"), dpi=150, bbox_inches="tight")

    # 2) kWh flows
    flows_df = collect_kwh_flows(base_input_dir, housing_type, scenarios, counties, agg=args.agg)
    flows_csv = os.path.join(output_dir, f"step18_kwh_flows_summary_g{sha}.csv")
    if not flows_df.empty:
        flows_df.to_csv(flows_csv, index=False)
    fig = plot_kwh_flows_dotline(flows_df, scenario_order=scenarios)
    fig.savefig(os.path.join(output_dir, f"step18_kwh_flows_dotline_g{sha}.png"), dpi=150, bbox_inches="tight")

    # 3) Savings and total bill (with solar)
    sb_df = collect_savings_and_bills(base_input_dir, housing_type, scenarios, counties, agg=args.agg)
    sb_csv = os.path.join(output_dir, f"step18_savings_bills_summary_g{sha}.csv")
    if not sb_df.empty:
        sb_df.to_csv(sb_csv, index=False)
    fig = plot_savings_and_bills_dotline(sb_df, scenario_order=scenarios)
    fig.savefig(os.path.join(output_dir, f"step18_savings_bills_dotline_g{sha}.png"), dpi=150, bbox_inches="tight")

    # 4) All-in annualized cost (EAC) stacked bar
    eac_df = collect_eac_components(
        base_input_dir,
        housing_type,
        scenarios,
        counties,
        incentive='full_incentives',
        agg=args.agg,
        timestamp=args.run_timestamp,
    )
    eac_csv = os.path.join(output_dir, f"step18_eac_summary_g{sha}.csv")
    if not eac_df.empty:
        eac_df.to_csv(eac_csv, index=False)
    fig = plot_eac_stacked_bar(eac_df, scenario_order=scenarios)
    eac_png = os.path.join(output_dir, f"step18_eac_stacked_bar_g{sha}.png")
    fig.savefig(eac_png, dpi=150, bbox_inches="tight")
    # Print the absolute path for quick access in logs
    try:
        print(f"EAC stacked bar PNG: {os.path.abspath(eac_png)}")
    except Exception:
        pass

    # 5) PV size (kW) by scenario
    pv_df = collect_pv_sizes(base_input_dir, housing_type, scenarios, counties, agg=args.agg)
    pv_csv = os.path.join(output_dir, f"step18_pv_size_summary_g{sha}.csv")
    if not pv_df.empty:
        pv_df.to_csv(pv_csv, index=False)
    fig = plot_pv_size_bar(pv_df, scenario_order=scenarios)
    fig.savefig(os.path.join(output_dir, f"step18_pv_size_bar_g{sha}.png"), dpi=150, bbox_inches="tight")

    # Final console summary
    print("Cross-scenario comparisons complete.")
    print(f"  Scenarios: {scenarios}")
    print(f"  Counties:  {counties[:6]}{' …' if len(counties) > 6 else ''}")
    print(f"  Outputs in: {os.path.abspath(output_dir)}")


if __name__ == "__main__":
    main()


def process(
    base_input_dir: str,
    output_dir: str,
    housing_type: str,
    scenarios: List[str],
    counties: List[str],
    *,
    plan_preference: List[str] | None = None,
    electricity_variant: str = "nem3",
    agg: str = "mean",
    run_timestamp: str | None = None,
):
    os.makedirs(output_dir, exist_ok=True)
    sha = git_short_sha()

    # EAC summary and plot
    eac_df = collect_eac_components(
        base_input_dir,
        housing_type,
        scenarios,
        counties,
        incentive='full_incentives',
        agg=agg,
        timestamp=run_timestamp,
        electricity_plan_preference=plan_preference,
        electricity_variant=electricity_variant,
    )
    if not eac_df.empty:
        # compute total for ranking/plot
        if 'annual_bill_electric' in eac_df.columns and 'annual_bill_gas' in eac_df.columns:
            bill_col = eac_df['annual_bill_electric'].fillna(0) + eac_df['annual_bill_gas'].fillna(0)
        else:
            bill_col = eac_df.get('annual_bill_with_solar', pd.Series([0] * len(eac_df)))
        comp = ['capex_pv', 'capex_storage', 'capex_electric', 'capex_gas', 'vehicle_om']
        eac_df['total_eac'] = eac_df[comp].sum(axis=1) + bill_col
        eac_df.to_csv(os.path.join(output_dir, f"step18_eac_summary_g{sha}.csv"), index=False)
        fig = plot_eac_stacked_bar(eac_df, scenario_order=scenarios)
        fig.savefig(os.path.join(output_dir, f"step18_eac_stacked_bar_g{sha}.png"), dpi=150, bbox_inches='tight')

    # Per-county exports (NEM3 and retail)
    from helpers.plot_scenario_comparison_helper import collect_eac_components_by_county
    by_cty_nem3 = collect_eac_components_by_county(
        base_input_dir,
        housing_type,
        scenarios,
        counties,
        incentive='full_incentives',
        electricity_plan_preference=plan_preference,
        electricity_variant='nem3',
    )
    by_cty_retail = collect_eac_components_by_county(
        base_input_dir,
        housing_type,
        scenarios,
        counties,
        incentive='full_incentives',
        electricity_plan_preference=plan_preference,
        electricity_variant='retail',
    )
    by_cty_nem3.to_csv(os.path.join(output_dir, f"step18_eac_by_county_nem3_g{sha}.csv"), index=False)
    by_cty_retail.to_csv(os.path.join(output_dir, f"step18_eac_by_county_retail_g{sha}.csv"), index=False)

    return eac_df
