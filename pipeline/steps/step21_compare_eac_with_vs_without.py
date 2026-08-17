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
from typing import List, Optional

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

from scenarios import SCENARIOS
from helpers.main_helpers import slugify_county_name, get_scenario_path, git_short_sha

from helpers.plot_scenario_comparison_helper import (
    collect_eac_components,
    collect_eac_components_by_county,
)
from .step20_no_solar_storage_electrification import (
    collect_eac_no_pv,
    collect_eac_no_pv_by_county,
)




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
    # ensure consistent bill split columns
    if 'annual_bill_electric' not in a.columns and 'annual_bill_with_solar' in a.columns:
        a['annual_bill_electric'] = a['annual_bill_with_solar']
        a['annual_bill_gas'] = 0.0
    a['variant'] = 'with_pv'

    b = df_no.copy()
    # ensure PV components present (zeros) for no-PV and align bill columns
    if 'annual_bill_electric' not in b.columns and 'annual_bill_default' in b.columns:
        b['annual_bill_electric'] = b['annual_bill_default']
        b['annual_bill_gas'] = 0.0
    for c in ['capex_pv', 'capex_storage']:
        if c not in b.columns:
            b[c] = 0.0
    b['variant'] = 'no_pv'

    keep_cols = ['scenario', 'variant', 'capex_pv', 'capex_storage', 'capex_electric', 'capex_gas', 'vehicle_om', 'annual_bill_electric', 'annual_bill_gas']
    return pd.concat([a[keep_cols], b[keep_cols]], ignore_index=True)


def _build_county_comparison(
    with_by_county: pd.DataFrame,
    no_by_county: pd.DataFrame,
) -> pd.DataFrame:
    """Reconcile per-county EAC inputs and calculate with-minus-without deltas."""
    keys = ["scenario", "county_slug"]
    if with_by_county.empty or no_by_county.empty:
        raise ValueError("Step 21 requires non-empty with-PV and no-PV county data")
    for label, frame in (
        ("with-PV", with_by_county),
        ("no-PV", no_by_county),
    ):
        missing = [column for column in keys if column not in frame.columns]
        if missing:
            raise KeyError(f"{label} county data missing key columns: {missing}")
        duplicates = frame.duplicated(keys, keep=False)
        if duplicates.any():
            duplicate_keys = frame.loc[duplicates, keys].to_dict("records")
            raise ValueError(
                f"{label} county data has duplicate scenario/county rows: "
                f"{duplicate_keys}"
            )

    with_components = [
        "capex_pv",
        "capex_storage",
        "capex_electric",
        "capex_gas",
        "vehicle_om",
        "annual_bill_electric",
        "annual_bill_gas",
    ]
    no_components = [
        "capex_electric",
        "capex_gas",
        "vehicle_om",
        "annual_bill_electric",
        "annual_bill_gas",
    ]
    for label, frame, columns in (
        ("with-PV", with_by_county, with_components),
        ("no-PV", no_by_county, no_components),
    ):
        missing = [column for column in columns if column not in frame.columns]
        if missing:
            raise KeyError(f"{label} county data missing EAC columns: {missing}")
        if frame[columns].isna().any().any():
            raise ValueError(f"{label} county data contains missing EAC values")

    with_totals = with_by_county.copy()
    with_totals["total_eac"] = with_totals[with_components].sum(axis=1)
    no_totals = no_by_county.copy()
    no_totals["total_eac_no_pv"] = no_totals[no_components].sum(axis=1)

    reconciled = with_totals.merge(
        no_totals[keys + ["total_eac_no_pv"]],
        on=keys,
        how="outer",
        validate="one_to_one",
        indicator=True,
    )
    unmatched = reconciled[reconciled["_merge"] != "both"]
    if not unmatched.empty:
        missing_keys = unmatched[keys + ["_merge"]].to_dict("records")
        raise ValueError(
            "With-PV and no-PV county results do not cover the same rows: "
            f"{missing_keys}"
        )
    reconciled = reconciled.drop(columns="_merge")

    if (reconciled["total_eac_no_pv"] == 0).any():
        zero_keys = reconciled.loc[
            reconciled["total_eac_no_pv"] == 0, keys
        ].to_dict("records")
        raise ValueError(f"Cannot calculate percent delta for zero no-PV EAC: {zero_keys}")

    reconciled["delta_with_minus_without"] = (
        reconciled["total_eac"] - reconciled["total_eac_no_pv"]
    )
    reconciled["delta_pct"] = (
        reconciled["delta_with_minus_without"]
        / reconciled["total_eac_no_pv"]
        * 100.0
    )
    if not np.isfinite(reconciled["delta_pct"]).all():
        raise ValueError("Step 21 county percent deltas contain non-finite values")
    return reconciled


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
        ('annual_bill_electric', '#1f77b4', 'Annual electricity bill'),
        ('annual_bill_gas', '#17becf', 'Annual gas bill'),
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
    # Legend inside, top-left to reduce eye travel and avoid outside spacing
    ax.legend(loc='upper left', frameon=False, fontsize=9)
    ax.grid(True, axis='y', linestyle=':', alpha=0.4)
    fig.tight_layout()
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
    p.add_argument(
        "--electricity-plans",
        nargs="+",
        required=True,
        help="Ordered retail electricity-plan tokens, one per utility as needed",
    )
    p.add_argument(
        "--electricity-variant",
        choices=["nem3", "retail"],
        default="nem3",
    )
    args = p.parse_args()

    base = args.base_input_dir
    out_dir = args.output_dir
    housing = args.housing_type
    scenarios = list(dict.fromkeys(args.scenarios)) if args.scenarios else list(SCENARIOS.keys())
    counties = _discover_counties(base, housing, scenarios) if args.all_counties else (args.counties or ["Alameda County"])
    os.makedirs(out_dir, exist_ok=True)

    # Collect
    df_with = collect_eac_components(
        base,
        housing,
        scenarios,
        counties,
        incentive=args.incentive,
        discount_rate=args.discount_rate,
        agg=args.agg,
        electricity_plan_preference=args.electricity_plans,
        electricity_variant=args.electricity_variant,
    )
    df_no = collect_eac_no_pv(
        base,
        housing,
        scenarios,
        counties,
        incentive=args.incentive,
        discount_rate=args.discount_rate,
        agg=args.agg,
        electricity_plan_preference=args.electricity_plans,
    )
    merged = _prepare_combined_df(df_with, df_no)

    # Save merged CSV
    sha = git_short_sha()
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


def process(
    base_input_dir: str,
    output_dir: str,
    housing_type: str,
    scenario: str,
    counties: List[str],
    *,
    plan_preference: List[str] | None = None,
    electricity_variant: str = "nem3",
    incentive: str = "full_incentives",
    discount_rate: float = 0.07,
    agg: str = "mean",
):
    os.makedirs(output_dir, exist_ok=True)
    sha = git_short_sha()

    df_with = collect_eac_components(
        base_input_dir,
        housing_type,
        [scenario],
        counties,
        incentive=incentive,
        discount_rate=discount_rate,
        agg=agg,
        electricity_plan_preference=plan_preference,
        electricity_variant=electricity_variant,
    )
    df_no = collect_eac_no_pv(
        base_input_dir,
        housing_type,
        [scenario],
        counties,
        incentive=incentive,
        discount_rate=discount_rate,
        agg=agg,
        electricity_plan_preference=plan_preference,
    )
    merged = _prepare_combined_df(df_with, df_no)
    merged.to_csv(os.path.join(output_dir, f"step21_eac_with_vs_without_g{sha}.csv"), index=False)
    fig = plot_grouped_eac(merged, scenario_order=[scenario], county_label="All Counties")
    fig.savefig(os.path.join(output_dir, f"step21_eac_with_vs_without_g{sha}.png"), dpi=150, bbox_inches='tight')

    # Per-county delta export is a required research output. Any missing,
    # duplicate, or non-reconciling rows now stop the reporting run.
    with_by_cty = collect_eac_components_by_county(
        base_input_dir,
        housing_type,
        [scenario],
        counties,
        incentive=incentive,
        discount_rate=discount_rate,
        electricity_plan_preference=plan_preference,
        electricity_variant=electricity_variant,
    )
    no_by_cty = collect_eac_no_pv_by_county(
        base_input_dir,
        housing_type,
        [scenario],
        counties,
        incentive=incentive,
        discount_rate=discount_rate,
        electricity_plan_preference=plan_preference,
    )
    merged_cty = _build_county_comparison(with_by_cty, no_by_cty)
    merged_cty.to_csv(
        os.path.join(
            output_dir,
            f"step21_with_vs_without_by_county_g{sha}.csv",
        ),
        index=False,
    )

    return merged
