"""
Step 20: Electrification-Only EAC (No Solar + Storage)

Computes Equivalent Annual Cost (EAC) components WITHOUT PV/storage for one
or more scenarios, aggregated across selected counties. Writes a summary CSV
and an optional stacked-bar plot to analysis_results/.

EAC components per scenario:
  - capex_electric (annualized, excludes PV/storage)
  - capex_gas (annualized)
  - vehicle_om (annual O&M adders from the ledger; can be negative)
  - annual_bill_electric (configured retail import plan, row = <scenario>)
  - annual_bill_gas (row = <scenario>)

Notes
  - Uses Step 14 detailed capital ledger: data/loadprofiles/capital_costs/
    capital_costs_<scenario>_<housing>.csv
  - Annual bills use the separate electricity and gas results for the default
    row (no .solarstorage).
  - Results may be negative (e.g., incentives exceeding capex for some items).
"""

from __future__ import annotations

import argparse
import os
from typing import Iterable, List, Optional

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

from helpers.main_helpers import get_scenario_path, git_short_sha
from helpers.plot_scenario_comparison_helper import (
    collect_eac_components,
    collect_eac_components_by_county,
)
from scenarios import SCENARIOS

def collect_eac_no_pv(
    base_input_dir: str,
    housing_type: str,
    scenarios: Iterable[str],
    counties: Iterable[str],
    *,
    incentive: str = "full_incentives",
    discount_rate: float = 0.07,
    agg: str = "mean",
    electricity_plan_preference: Optional[Iterable[str]] = None,
    timestamp: Optional[str] = None,
) -> pd.DataFrame:
    """Aggregate shared EAC components for the retail no-solar counterfactual."""
    return collect_eac_components(
        base_input_dir, housing_type, scenarios, counties,
        incentive=incentive, discount_rate=discount_rate, agg=agg,
        electricity_plan_preference=electricity_plan_preference,
        electricity_variant="retail", with_solar=False, timestamp=timestamp,
    ).drop(columns=["capex_pv", "capex_storage"])


def collect_eac_no_pv_by_county(
    base_input_dir: str,
    housing_type: str,
    scenarios: Iterable[str],
    counties: Iterable[str],
    *,
    incentive: str = "full_incentives",
    discount_rate: float = 0.07,
    electricity_plan_preference: Optional[Iterable[str]] = None,
    timestamp: Optional[str] = None,
) -> pd.DataFrame:
    """Return shared county EAC components with explicit zero PV/storage costs.

    Require a complete capital ledger even when its costs are zero. This keeps
    appliance and vehicle accounting identical to the with-solar reports.
    """
    return collect_eac_components_by_county(
        base_input_dir, housing_type, scenarios, counties,
        incentive=incentive, discount_rate=discount_rate,
        electricity_plan_preference=electricity_plan_preference,
        electricity_variant="retail", with_solar=False, timestamp=timestamp,
    ).drop(columns=["capex_pv", "capex_storage"])


def plot_eac_no_pv_stacked_bar(df: pd.DataFrame, scenario_order: Optional[List[str]] = None, title: str = "EAC (No Solar + Storage) by Scenario") -> plt.Figure:
    if df.empty:
        fig, ax = plt.subplots(figsize=(8, 4))
        ax.set_title("No data to plot")
        return fig
    if scenario_order is None:
        scenario_order = list(df['scenario'])

    comps = [
        ('capex_electric', '#31a354', 'Electrification capex (annualized)'),
        ('capex_gas', '#756bb1', 'Gas capex (annualized)'),
        ('vehicle_om', '#d62728', 'Vehicle O&M'),
        ('annual_bill_electric', '#1f77b4', 'Annual electricity bill'),
        ('annual_bill_gas', '#17becf', 'Annual gas bill'),
    ]

    x = np.arange(len(scenario_order))
    fig, ax = plt.subplots(figsize=(max(10, len(scenario_order) * 1.3), 5.0))
    bottoms = np.zeros_like(x, dtype=float)
    for key, color, label in comps:
        vals = []
        for scen in scenario_order:
            row = df[df['scenario'] == scen]
            vals.append(float(row[key].values[0]) if not row.empty and key in row.columns else 0.0)
        ax.bar(x, vals, bottom=bottoms, color=color, label=label)
        bottoms = bottoms + np.array(vals)

    # Annotate totals; match Step 18 style when non-negative, otherwise handle negatives gracefully
    try:
        totals = np.asarray(bottoms, dtype=float)
        if totals.size > 0 and np.isfinite(totals).any():
            tmin = float(np.nanmin(totals))
            tmax = float(np.nanmax(totals))
            if tmin >= 0:  # mimic step18 style
                if tmax > 0:
                    ax.set_ylim(0.0, tmax * 1.08)
                yoff = max(1.0, 0.02 * tmax) if tmax > 0 else 1.0
                for xi, tot in zip(x, totals):
                    tval = float(tot) if np.isfinite(tot) else 0.0
                    if tval > 0:
                        ax.text(float(xi), tval + yoff, f"{tval:.0f}", ha='center', va='bottom', fontsize=9, color='black')
            else:
                pad = 0.08 * max(abs(tmax), abs(tmin), 1.0)
                ax.set_ylim(tmin - pad, tmax + pad)
                for xi, tot in zip(x, totals):
                    tval = float(tot) if np.isfinite(tot) else 0.0
                    ax.text(float(xi), tval, f"{tval:.0f}", ha='center', va='bottom' if tval >= 0 else 'top', fontsize=9, color='black')
    except Exception:
        pass

    ax.set_xticks(x)
    ax.set_xticklabels(scenario_order, rotation=20, ha='right')
    ax.set_ylabel('$ per year')
    ax.set_title(title)
    # Put legend outside to avoid overlap with bars
    ax.grid(True, axis='y', linestyle=':', alpha=0.4)
    ax.legend(loc='center left', bbox_to_anchor=(1.02, 0.5), frameon=False, fontsize=9)
    # Reserve right margin for the outside legend
    fig.tight_layout(rect=[0.04, 0.0, 0.78, 1.0])
    return fig


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


def main() -> None:
    p = argparse.ArgumentParser(description="EAC (no solar+storage) per scenario")
    p.add_argument("--base-input-dir", default="data/loadprofiles")
    p.add_argument("--output-dir", default="analysis_results")
    p.add_argument("--housing-type", default="single-family-detached")
    p.add_argument("--scenarios", nargs="*", help="Scenarios to include (default: keys from scenarios.py)")
    p.add_argument("--counties", nargs="*", help="Counties (names or slugs). Use --all-counties for discovery.")
    p.add_argument("--all-counties", action="store_true")
    p.add_argument("--agg", choices=["mean","median"], default="mean")
    p.add_argument("--incentive", default="full_incentives", choices=["full_incentives","half_incentives","no_incentives"])
    p.add_argument("--discount-rate", type=float, default=0.07)
    p.add_argument(
        "--electricity-plans",
        nargs="+",
        required=True,
        help="Ordered retail electricity-plan tokens, one per utility as needed",
    )
    args = p.parse_args()

    base = args.base_input_dir
    out_dir = args.output_dir
    housing = args.housing_type
    scenarios = list(dict.fromkeys(args.scenarios)) if args.scenarios else list(SCENARIOS.keys())
    counties = _discover_counties(base, housing, scenarios) if args.all_counties else (args.counties or ["Alameda County"])
    os.makedirs(out_dir, exist_ok=True)

    df = collect_eac_no_pv(
        base,
        housing,
        scenarios,
        counties,
        incentive=args.incentive,
        discount_rate=args.discount_rate,
        agg=args.agg,
        electricity_plan_preference=args.electricity_plans,
    )
    sha = git_short_sha()
    csv_path = os.path.join(out_dir, f"step20_eac_no_pv_summary_g{sha}.csv")
    if not df.empty:
        df.to_csv(csv_path, index=False)
    # Build a descriptive title that mentions selected counties when specified
    if args.all_counties:
        county_label = "All Counties"
    else:
        county_label = counties[0] if len(counties) == 1 else ", ".join(counties)
    plot_title = f"All-in Annualized Cost (No Solar + Storage) — {county_label}"
    fig = plot_eac_no_pv_stacked_bar(df, scenario_order=scenarios, title=plot_title)
    png_path = os.path.join(out_dir, f"step20_eac_no_pv_stacked_bar_g{sha}.png")
    fig.savefig(png_path, dpi=150, bbox_inches="tight")
    print("EAC (no PV) complete.")
    print(f"  Scenarios: {scenarios}")
    print(f"  Counties:  {counties[:6]}{' …' if len(counties) > 6 else ''}")
    print(f"  Outputs in: {os.path.abspath(out_dir)}")
    print(f"  Plot: {os.path.abspath(png_path)}")


if __name__ == "__main__":
    main()


def process(
    base_input_dir: str,
    output_dir: str,
    housing_type: str,
    scenarios: List[str],
    counties: List[str],
    *,
    incentive: str = "full_incentives",
    discount_rate: float = 0.07,
    agg: str = "mean",
    plan_preference: Optional[Iterable[str]] = None,
):
    os.makedirs(output_dir, exist_ok=True)
    sha = git_short_sha()
    df = collect_eac_no_pv(
        base_input_dir,
        housing_type,
        scenarios,
        counties,
        incentive=incentive,
        discount_rate=discount_rate,
        agg=agg,
        electricity_plan_preference=plan_preference,
    )
    if not df.empty:
        df.to_csv(os.path.join(output_dir, f"step20_eac_no_pv_summary_g{sha}.csv"), index=False)
    fig = plot_eac_no_pv_stacked_bar(df, scenario_order=scenarios, title=f"All-in Annualized Cost (No Solar + Storage)")
    fig.savefig(os.path.join(output_dir, f"step20_eac_no_pv_stacked_bar_g{sha}.png"), dpi=150, bbox_inches="tight")
    return df
