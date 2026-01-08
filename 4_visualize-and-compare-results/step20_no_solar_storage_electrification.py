"""
Step 20: Electrification-Only EAC (No Solar + Storage)

Computes Equivalent Annual Cost (EAC) components WITHOUT PV/storage for one
or more scenarios, aggregated across selected counties. Writes a summary CSV
and an optional stacked-bar plot to analysis_results/.

EAC components per scenario:
  - capex_electric (annualized, excludes PV/storage)
  - capex_gas (annualized)
  - vehicle_om (annual O&M adders from the ledger; can be negative)
  - annual_bill_default (from Step 13 totals, row = <scenario>)

Notes
  - Uses Step 14 detailed capital ledger: data/loadprofiles/capital_costs/
    capital_costs_<scenario>_<housing>.csv
  - Annual bill uses Step 13 totals for the default row (no .solarstorage).
  - Results may be negative (e.g., incentives exceeding capex for some items).
"""

from __future__ import annotations

import argparse
import os
import subprocess
from typing import Dict, Iterable, List, Optional

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

from helpers.main_helpers import slugify_county_name, get_scenario_path, git_short_sha
from helpers.capital_cost_map_builder import LIFETIMES
from step15_payback_periods import vehicle_annual_adders_from_ledger
from scenarios import SCENARIOS

try:
    # Helper to find latest totals CSV per county
    from helpers.plot_scenario_comparison_helper import _latest_totals_csv
except Exception:
    _latest_totals_csv = None




def _read_capital_ledger(base_input_dir: str, scenario: str, housing_type: str) -> Optional[pd.DataFrame]:
    cap_dir = os.path.join(base_input_dir, "capital_costs")
    fname = f"capital_costs_{scenario}_{housing_type.replace('-', '_')}.csv"
    path = os.path.join(cap_dir, fname)
    if not os.path.exists(path):
        return None
    try:
        return pd.read_csv(path)
    except Exception:
        return None


def _crf(rate: float, n_years: float) -> float:
    if rate <= 0 or n_years <= 0:
        return 1.0 / max(n_years, 1.0)
    r = float(rate)
    n = float(n_years)
    return (r * (1 + r) ** n) / (((1 + r) ** n) - 1)


def _read_totals_cost_default(base_input_dir: str, scenario: str, housing_type: str, county_slug: str) -> float:
    """Return total annual bill (default row, no solarstorage) for a county.
    Falls back to 0.0 if not available.
    """
    try:
        if _latest_totals_csv is None:
            # Minimal inline finder (mirrors helper behavior)
            results_dir = os.path.join(base_input_dir, scenario, housing_type, county_slug, "results", "totals")
            if not os.path.isdir(results_dir):
                return 0.0
            files = [f for f in os.listdir(results_dir) if f.startswith("RESULTS_total_annual_costs_") and f.endswith(".csv")]
            if not files:
                return 0.0
            # Pick lexicographically last as a crude latest; helper is smarter with timestamp
            files.sort()
            path = os.path.join(results_dir, files[-1])
        else:
            path = _latest_totals_csv(base_input_dir, scenario, housing_type, county_slug)
        if not path or not os.path.exists(path):
            return 0.0
        df = pd.read_csv(path, index_col="scenario")
        if scenario not in df.index:
            # Fallback to the first row's first value
            return float(df.iloc[0].iloc[0])
        return float(df.loc[scenario].iloc[0])
    except Exception:
        return 0.0


def collect_eac_no_pv(
    base_input_dir: str,
    housing_type: str,
    scenarios: Iterable[str],
    counties: Iterable[str],
    *,
    incentive: str = "full_incentives",
    discount_rate: float = 0.07,
    agg: str = "mean",
) -> pd.DataFrame:
    """Collect EAC components WITHOUT PV/storage for each scenario (aggregated over counties).

    Returns a DataFrame with columns:
      scenario, capex_electric, capex_gas, vehicle_om,
      annual_bill_electric, annual_bill_gas
    """
    inc = incentive.lower()
    county_slugs = [slugify_county_name(c) for c in counties]
    out_rows: List[Dict] = []

    for scen in scenarios:
        ledger = _read_capital_ledger(base_input_dir, scen, housing_type)
        per_county: List[Dict] = []

        for slug in county_slugs:
            capex_electric = 0.0
            capex_gas = 0.0
            vehicle_om = 0.0
            # Split default (no PV/storage) bills into electric + gas
            try:
                from helpers.plot_scenario_comparison_helper import _annual_bill_parts as _bill_parts  # reuse helper
                e_bill, g_bill = _bill_parts(base_input_dir, scen, housing_type, slug, with_solar=False)
            except Exception:
                # Fallback to totals if helper import fails
                total_bill = _read_totals_cost_default(base_input_dir, scen, housing_type, slug)
                e_bill, g_bill = total_bill, 0.0

            # Annualize capital ledger rows (exclude PV/storage entirely)
            if ledger is not None and not ledger.empty:
                df = ledger.copy()
                # Focus on this county and incentive scenario
                if 'county_slug' in df.columns:
                    df = df[df['county_slug'].str.lower() == slug]
                if 'incentive_scenario' in df.columns:
                    df['incentive_scenario'] = df['incentive_scenario'].str.lower()
                    df = df[df['incentive_scenario'] == inc]
                # Loop rows
                for _, r in df.iterrows():
                    try:
                        lt = float(r.get('lifetime_years', 15) or 15)
                        c = _crf(discount_rate, lt)
                        cat = r.get('appliance_category')
                        typ = r.get('appliance_type')
                        if cat == 'electric' and typ not in ('solar', 'storage'):
                            net = float(r.get('net_cost', 0.0))
                            capex_electric += net * c
                        if cat == 'gas':
                            base = float(r.get('base_cost', 0.0))
                            capex_gas += base * c
                    except Exception:
                        continue

                # Vehicle O&M adders (ICE/EV), scenario-informed
                try:
                    adders = vehicle_annual_adders_from_ledger(df)
                    if slug in adders.index:
                        ev_val = float(adders.loc[slug, 'ev_operating']) if 'ev_operating' in adders.columns else 0.0
                        ice_val = float(adders.loc[slug, 'ice_operating']) if 'ice_operating' in adders.columns else 0.0
                        scen_l = (scen or '').lower()
                        if ('ev' in scen_l) or (ev_val > 0):
                            vehicle_om += ev_val
                        if ('ice' in scen_l) or (ice_val > 0 and 'ev' not in scen_l):
                            vehicle_om += ice_val
                except Exception:
                    pass

            per_county.append({
                'scenario': scen,
                'county_slug': slug,
                'capex_electric': capex_electric,
                'capex_gas': capex_gas,
                'vehicle_om': vehicle_om,
                'annual_bill_electric': e_bill,
                'annual_bill_gas': g_bill,
            })

        if not per_county:
            continue
        dfc = pd.DataFrame(per_county)
        if agg == 'median':
            agg_df = dfc.groupby('scenario').median(numeric_only=True).reset_index()
        else:
            agg_df = dfc.groupby('scenario').mean(numeric_only=True).reset_index()
        out_rows.append(agg_df.iloc[0].to_dict())

    return pd.DataFrame(out_rows)


def collect_eac_no_pv_by_county(
    base_input_dir: str,
    housing_type: str,
    scenarios: Iterable[str],
    counties: Iterable[str],
    *,
    incentive: str = "full_incentives",
    discount_rate: float = 0.07,
) -> pd.DataFrame:
    """Per-county EAC components WITHOUT PV/storage for each scenario.

    Columns per row: scenario, county_slug, capex_electric, capex_gas, vehicle_om,
                     annual_bill_electric, annual_bill_gas
    """
    inc = (incentive or "").lower()
    county_slugs = [slugify_county_name(c) for c in counties]
    rows: List[Dict] = []
    for scen in scenarios:
        ledger = _read_capital_ledger(base_input_dir, scen, housing_type)
        for slug in county_slugs:
            capex_electric = 0.0
            capex_gas = 0.0
            vehicle_om = 0.0
            e_bill = 0.0
            g_bill = 0.0

            total_bill = _read_totals_cost_default(base_input_dir, scen, housing_type, slug)
            util = get_utility_for_county(slug)
            if util and str(util).upper() in ("PG&E", "PGE"):
                e_bill, g_bill = total_bill, 0.0
            else:
                e_bill, g_bill = total_bill, 0.0

            if ledger is not None and not ledger.empty:
                df = ledger.copy()
                if 'county_slug' in df.columns:
                    df = df[df['county_slug'].str.lower() == slug]
                if 'incentive_scenario' in df.columns:
                    df['incentive_scenario'] = df['incentive_scenario'].str.lower()
                    df = df[df['incentive_scenario'] == inc]
                for _, r in df.iterrows():
                    try:
                        lt = float(r.get('lifetime_years', 15) or 15)
                        c = _crf(discount_rate, lt)
                        cat = r.get('appliance_category')
                        typ = r.get('appliance_type')
                        if cat == 'electric' and typ not in ('solar', 'storage'):
                            capex_electric += float(r.get('net_cost', 0.0)) * c
                        if cat == 'gas':
                            capex_gas += float(r.get('base_cost', 0.0)) * c
                    except Exception:
                        continue
                try:
                    adders = vehicle_annual_adders_from_ledger(df)
                    if slug in adders.index:
                        ev_val = float(adders.loc[slug, 'ev_operating']) if 'ev_operating' in adders.columns else 0.0
                        ice_val = float(adders.loc[slug, 'ice_operating']) if 'ice_operating' in adders.columns else 0.0
                        scen_l = (scen or '').lower()
                        if ('ev' in scen_l) or (ev_val > 0):
                            vehicle_om += ev_val
                        if ('ice' in scen_l) or (ice_val > 0 and 'ev' not in scen_l):
                            vehicle_om += ice_val
                except Exception:
                    pass

            rows.append({
                'scenario': scen,
                'county_slug': slug,
                'capex_electric': capex_electric,
                'capex_gas': capex_gas,
                'vehicle_om': vehicle_om,
                'annual_bill_electric': e_bill,
                'annual_bill_gas': g_bill,
            })
    return pd.DataFrame(rows)


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
    args = p.parse_args()

    base = args.base_input_dir
    out_dir = args.output_dir
    housing = args.housing_type
    scenarios = list(dict.fromkeys(args.scenarios)) if args.scenarios else list(SCENARIOS.keys())
    counties = _discover_counties(base, housing, scenarios) if args.all_counties else (args.counties or ["Alameda County"])
    os.makedirs(out_dir, exist_ok=True)

    df = collect_eac_no_pv(base, housing, scenarios, counties, incentive=args.incentive, discount_rate=args.discount_rate, agg=args.agg)
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
):
    os.makedirs(output_dir, exist_ok=True)
    sha = git_short_sha()
    df = collect_eac_no_pv(base_input_dir, housing_type, scenarios, counties, incentive=incentive, discount_rate=discount_rate, agg=agg)
    if not df.empty:
        df.to_csv(os.path.join(output_dir, f"step20_eac_no_pv_summary_g{sha}.csv"), index=False)
    fig = plot_eac_no_pv_stacked_bar(df, scenario_order=scenarios, title=f"All-in Annualized Cost (No Solar + Storage)")
    fig.savefig(os.path.join(output_dir, f"step20_eac_no_pv_stacked_bar_g{sha}.png"), dpi=150, bbox_inches="tight")
    return df
