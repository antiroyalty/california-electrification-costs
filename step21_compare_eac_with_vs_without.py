"""
Step 21: Compare EAC With vs Without Solar + Storage

Generates a grouped stacked-bar chart per scenario with two bars:
  - No PV/Storage (electrification-only): capex_electric, capex_gas, vehicle_om, annual_bill
  - With PV/Storage: capex_pv, capex_storage, capex_electric, capex_gas, vehicle_om, annual_bill

Inputs
  - Capital ledger and summaries written by Step 14
  - Totals (annual bills) written by Steps 10–13

Outputs
  - CSV (merged summary): analysis_results/step21_eac_with_vs_without_g<sha>.csv
  - Plot (PNG):          analysis_results/step21_eac_with_vs_without_g<sha>.png
"""

from __future__ import annotations

import argparse
import os
import subprocess
from typing import List, Optional

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

from scenarios import SCENARIOS
from main_helpers import slugify_county_name, get_scenario_path

from plot_scenario_comparison_helper import collect_eac_components
from step20_no_solar_storage_electrification import collect_eac_no_pv


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
            p = os.path.join(scen_path, name)
            if os.path.isdir(p) and not name.startswith('.'):
                counties.add(name)
    return sorted(counties)


def _prepare_combined_df(df_with: pd.DataFrame, df_no: pd.DataFrame) -> pd.DataFrame:
    """Return tidy frame with variant column and harmonized bill column name."""
    a = df_with.copy()
    if 'annual_bill_with_solar' in a.columns:
        a = a.rename(columns={'annual_bill_with_solar': 'annual_bill'})
    a['variant'] = 'with_pv'

    b = df_no.copy()
    if 'annual_bill_default' in b.columns:
        b = b.rename(columns={'annual_bill_default': 'annual_bill'})
    # ensure PV components present (zeros) for no-PV
    for c in ['capex_pv', 'capex_storage']:
        if c not in b.columns:
            b[c] = 0.0
    b['variant'] = 'no_pv'

    keep_cols = ['scenario', 'variant', 'capex_pv', 'capex_storage', 'capex_electric', 'capex_gas', 'vehicle_om', 'annual_bill']
    return pd.concat([a[keep_cols], b[keep_cols]], ignore_index=True)


def plot_grouped_eac(df: pd.DataFrame, scenario_order: Optional[List[str]] = None, county_label: str = "All Counties") -> plt.Figure:
    if df.empty:
        fig, ax = plt.subplots(figsize=(8, 4))
        ax.set_title("No data to plot")
        return fig

    if scenario_order is None:
        scenario_order = sorted(df['scenario'].unique())

    # Colors consistent with Step 18
    comps = [
        ('capex_pv', '#fdae6b', 'PV capex (annualized)'),
        ('capex_storage', '#9ecae1', 'Storage capex (annualized)'),
        ('capex_electric', '#31a354', 'Electrification capex (annualized)'),
        ('capex_gas', '#756bb1', 'Gas capex (annualized)'),
        ('vehicle_om', '#d62728', 'Vehicle O&M'),
        ('annual_bill', '#1f77b4', 'Annual energy bill'),
    ]

    x = np.arange(len(scenario_order), dtype=float)
    # Bar geometry: add a small gap between the two bars per scenario
    width = 0.32
    gap = 0.06
    offsets = {
        'no_pv':  -(width/2 + gap/2),
        'with_pv': +(width/2 + gap/2),
    }

    fig, ax = plt.subplots(figsize=(max(12, len(scenario_order) * 1.6), 5.4))

    totals_by_variant = {'no_pv': np.zeros_like(x, dtype=float), 'with_pv': np.zeros_like(x, dtype=float)}
    for variant in ['no_pv', 'with_pv']:
        bottoms = np.zeros_like(x, dtype=float)
        sub = df[df['variant'] == variant]
        for key, color, label in comps:
            vals = []
            for scen in scenario_order:
                row = sub[sub['scenario'] == scen]
                vals.append(float(row[key].values[0]) if not row.empty and key in row.columns else 0.0)
            vals = np.array(vals, dtype=float)
            ax.bar(x + offsets[variant], vals, width=width, bottom=bottoms, color=color, label=label if variant == 'with_pv' else None)
            bottoms = bottoms + vals
        totals_by_variant[variant] = bottoms

    # Totals annotation (use style similar to Step 18 when non-negative)
    try:
        t_all = np.concatenate(list(totals_by_variant.values()))
        tmin, tmax = float(np.nanmin(t_all)), float(np.nanmax(t_all))
        if tmin >= 0 and tmax > 0:
            ax.set_ylim(0.0, tmax * 1.10)
            yoff = max(1.0, 0.02 * tmax)
            for variant in ['no_pv', 'with_pv']:
                for xi, tot in zip(x, totals_by_variant[variant]):
                    if tot > 0:
                        ax.text(float(xi + offsets[variant]), float(tot + yoff), f"{tot:.0f}", ha='center', va='bottom', fontsize=8)
        else:
            pad = 0.10 * max(abs(tmax), abs(tmin), 1.0)
            ax.set_ylim(tmin - pad, tmax + pad)
            for variant in ['no_pv', 'with_pv']:
                for xi, tot in zip(x, totals_by_variant[variant]):
                    ax.text(float(xi + offsets[variant]), float(tot), f"{tot:.0f}", ha='center', va='bottom' if tot >= 0 else 'top', fontsize=8)
    except Exception:
        pass

    ax.set_xticks(x)
    ax.set_xticklabels(scenario_order, rotation=20, ha='right')
    ax.set_ylabel('$ per year')
    ax.set_title(f"All-in Annualized Cost — No PV vs With PV — {county_label}")
    # legend outside (one set for components)
    ax.legend(loc='center left', bbox_to_anchor=(1.02, 0.5), frameon=False, fontsize=9)
    ax.grid(True, axis='y', linestyle=':', alpha=0.4)
    fig.tight_layout(rect=[0.04, 0.0, 0.78, 1.0])
    return fig


def main() -> None:
    p = argparse.ArgumentParser(description="Compare EAC with vs without solar+storage (grouped stacked bars)")
    p.add_argument("--base-input-dir", default="data/loadprofiles")
    p.add_argument("--output-dir", default="analysis_results")
    p.add_argument("--housing-type", default="single-family-detached")
    p.add_argument("--scenarios", nargs="*", help="Scenarios to include (default: keys from scenarios.py)")
    p.add_argument("--counties", nargs="*", help="Counties (names or slugs). Use --all-counties for discovery.")
    p.add_argument("--all-counties", action="store_true")
    p.add_argument("--agg", choices=["mean","median"], default="mean")
    p.add_argument("--incentive", default="full_incentives", choices=["full_incentives","half_incentives","no_incentives"])
    p.add_argument("--discount-rate", type=float, default=0.07)
    args = p.parse_args()

    base = args.base_input_dir
    out_dir = args.output_dir
    housing = args.housing_type
    scenarios = list(dict.fromkeys(args.scenarios)) if args.scenarios else list(SCENARIOS.keys())
    counties = _discover_counties(base, housing, scenarios) if args.all_counties else (args.counties or ["Alameda County"])
    os.makedirs(out_dir, exist_ok=True)

    # Collect
    df_with = collect_eac_components(base, housing, scenarios, counties, incentive=args.incentive)
    df_no = collect_eac_no_pv(base, housing, scenarios, counties, incentive=args.incentive, discount_rate=args.discount_rate, agg=args.agg)
    merged = _prepare_combined_df(df_with, df_no)

    # Save merged CSV
    sha = _git_short_sha()
    csv_path = os.path.join(out_dir, f"step21_eac_with_vs_without_g{sha}.csv")
    merged.to_csv(csv_path, index=False)

    # Title county label
    county_label = "All Counties" if args.all_counties else (counties[0] if len(counties)==1 else ", ".join(counties))

    fig = plot_grouped_eac(merged, scenario_order=scenarios, county_label=county_label)
    out_png = os.path.join(out_dir, f"step21_eac_with_vs_without_g{sha}.png")
    fig.savefig(out_png, dpi=150, bbox_inches='tight')
    print("EAC with-vs-without comparison complete.")
    print(f"  Scenarios: {scenarios}")
    print(f"  Counties:  {counties[:6]}{' …' if len(counties) > 6 else ''}")
    print(f"  Outputs in: {os.path.abspath(out_dir)}")
    print(f"  Plot: {os.path.abspath(out_png)}")


if __name__ == "__main__":
    main()
