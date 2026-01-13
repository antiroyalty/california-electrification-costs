"""
Reusable helpers to compare scenarios across payback, kWh flows, savings, and bills.

This module mirrors data-access patterns established in step15/step16:
- Payback CSVs:   data/results/{housing_type}/payback_periods_{scenario}.csv
- Totals results: data/loadprofiles/{scenario}/{housing_type}/{county_slug}/results/totals/
- SAM hourly CSV: data/loadprofiles/{scenario}/{housing_type}/{county_slug}/sam_optimized_load_profiles_*.csv

Main capabilities
- Collect and aggregate payback periods (with-solar only) over counties/scenarios
- Collect and aggregate kWh flows (Load Profile, System→Load, Battery→Load, Grid→Load)
- Collect and aggregate annual savings (with solar) and total annual bill
- Plot scenario-comparison dot+line charts for each set of metrics

Usage (example)
    from plot_scenario_comparison_helper import (
        collect_payback_with_solar, plot_payback_dotline,
        collect_kwh_flows, plot_kwh_flows_dotline,
        collect_savings_and_bills, plot_savings_and_bills_dotline,
    )

    base = "data/loadprofiles"
    housing = "single-family-detached"
    scenarios = [
        "baseline",
        "induction_stove",
        "heat_pump",
        "water_heating",
        "full_electric_ev",
    ]
    counties = ["Alameda County"]

    payback_df = collect_payback_with_solar(base, housing, scenarios, counties)
    fig, ax = plot_payback_dotline(payback_df, scenario_order=scenarios)
    fig.savefig("analysis_results/payback_dotline.png", dpi=150)

    flows_df = collect_kwh_flows(base, housing, scenarios, counties)
    fig = plot_kwh_flows_dotline(flows_df, scenario_order=scenarios)
    fig.savefig("analysis_results/flows_dotline.png", dpi=150)

    sb_df = collect_savings_and_bills(base, housing, scenarios, counties)
    fig = plot_savings_and_bills_dotline(sb_df, scenario_order=scenarios)
    fig.savefig("analysis_results/savings_bills_dotline.png", dpi=150)
"""

from __future__ import annotations

import os
from typing import Dict, Iterable, List, Optional, Tuple

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

from helpers.main_helpers import slugify_county_name, get_scenario_path
from helpers.maps_helpers import get_latest_csv_file
from helpers.utility_helpers import get_utility_for_county
from helpers.capital_cost_map_builder import LIFETIMES
from evaluations.vehicles import vehicle_annual_adders_from_ledger


# ---------- Internal data access helpers ----------

def _latest_totals_csv(base_input_dir: str, scenario: str, housing_type: str, county_slug: str) -> Optional[str]:
    results_dir = os.path.join(base_input_dir, scenario, housing_type, county_slug, "results", "totals")
    if not os.path.exists(results_dir):
        return None
    try:
        # Prefix expects filenames like: RESULTS_total_annual_costs_{county_slug}_YYYYMMDD_HH.csv
        return get_latest_csv_file(results_dir, f"RESULTS_total_annual_costs_{county_slug}")
    except Exception:
        return None


def _read_totals_cost(base_input_dir: str, scenario: str, housing_type: str, county_slug: str, row_name: str) -> float:
    path = _latest_totals_csv(base_input_dir, scenario, housing_type, county_slug)
    if not path or not os.path.exists(path):
        return 0.0
    try:
        df = pd.read_csv(path, index_col="scenario")
        if row_name not in df.index:
            # Fallback to the first row/column if the expected row is missing
            row = df.iloc[0]
        else:
            row = df.loc[row_name]
        # Use the first numeric column as the total annual cost
        if hasattr(row, "iloc"):
            return float(row.iloc[0])
        return float(row)
    except Exception:
        return 0.0


# ---------- Helpers to read latest electricity/gas annual costs ----------
def _find_csv_with_timestamp(directory: str, prefix: str, ts: str) -> Optional[str]:
    """Return a CSV path in directory matching prefix and exact timestamp 'YYYYMMDD_HH'."""
    try:
        for f in os.listdir(directory):
            if f.startswith(prefix) and f.endswith(".csv") and f.endswith(f"_{ts}.csv"):
                return os.path.join(directory, f)
    except Exception:
        pass
    return None


def _latest_electricity_csv(base_input_dir: str, scenario: str, housing_type: str, county_slug: str, timestamp: Optional[str] = None) -> Optional[str]:
    directory = os.path.join(base_input_dir, scenario, housing_type, county_slug, "results", "electricity")
    if not os.path.isdir(directory):
        return None
    try:
        prefix = f"RESULTS_electricity_annual_costs_{county_slug}_"
        if timestamp:
            p = _find_csv_with_timestamp(directory, prefix, timestamp)
            if p:
                return p
        return get_latest_csv_file(directory, prefix)
    except Exception:
        return None


def _latest_gas_csv(base_input_dir: str, scenario: str, housing_type: str, county_slug: str, timestamp: Optional[str] = None) -> Optional[str]:
    directory = os.path.join(base_input_dir, scenario, housing_type, county_slug, "results", "gas")
    if not os.path.isdir(directory):
        return None
    try:
        prefix = f"RESULTS_gas_annual_costs_{county_slug}_"
        if timestamp:
            p = _find_csv_with_timestamp(directory, prefix, timestamp)
            if p:
                return p
        return get_latest_csv_file(directory, prefix)
    except Exception:
        return None


def _read_first_numeric_for_row(path: Optional[str], row_name: str) -> float:
    if not path or not os.path.exists(path):
        return 0.0
    try:
        df = pd.read_csv(path, index_col="scenario")
        if row_name not in df.index:
            row = df.iloc[0]
        else:
            row = df.loc[row_name]
        # first numeric cell of the row
        return float(pd.to_numeric(row, errors="coerce").dropna().iloc[0])
    except Exception:
        return 0.0


def _read_row_value_for_plan(
    path: Optional[str],
    row_name: str,
    *,
    plan_preference: Optional[Iterable[str]] = None,
    variant: Optional[str] = None,
) -> float:
    """Return a row value for a specific electricity plan/variant; fallback to first numeric.

    - plan_preference: ordered sequence of substrings to match within the plan token.
    - variant: 'nem3' selects columns ending with '_NEM3'; 'retail' selects columns without that suffix.
    """
    if not path or not os.path.exists(path):
        return 0.0
    try:
        df = pd.read_csv(path, index_col="scenario")
        row = df.iloc[0] if row_name not in df.index else df.loc[row_name]
        # Electricity-only columns
        cols = [c for c in row.index if str(c).startswith("electricity.")]
        if not cols:
            return _read_first_numeric_for_row(path, row_name)
        # Filter by variant
        if variant:
            v = str(variant).lower()
            if v == "nem3":
                cols = [c for c in cols if str(c).endswith("_NEM3")]
            elif v == "retail":
                cols = [c for c in cols if not str(c).endswith("_NEM3")]
        # Filter by plan preference
        if plan_preference:
            prefs = list(plan_preference)
            for pref in prefs:
                sub = [c for c in cols if str(pref).lower() in str(c).lower()]
                if sub:
                    val = pd.to_numeric(row[sub[0]], errors="coerce")
                    if pd.notna(val):
                        return float(val)
        # Fallback: first numeric among considered columns
        for c in cols:
            val = pd.to_numeric(row[c], errors="coerce")
            if pd.notna(val):
                return float(val)
        # Last resort: first numeric anywhere in row
        ser = pd.to_numeric(row, errors="coerce").dropna()
        return float(ser.iloc[0]) if not ser.empty else 0.0
    except Exception:
        return 0.0


def _annual_bill_parts(
    base_input_dir: str,
    scenario: str,
    housing_type: str,
    county_slug: str,
    with_solar: bool,
    timestamp: Optional[str] = None,
    *,
    electricity_plan_preference: Optional[Iterable[str]] = None,
    electricity_variant: Optional[str] = None,
) -> tuple[float, float]:
    row = f"{scenario}.solarstorage" if with_solar else scenario
    e_path = _latest_electricity_csv(base_input_dir, scenario, housing_type, county_slug, timestamp=timestamp)
    g_path = _latest_gas_csv(base_input_dir, scenario, housing_type, county_slug, timestamp=timestamp)
    e_val = _read_row_value_for_plan(
        e_path,
        row,
        plan_preference=electricity_plan_preference,
        variant=electricity_variant,
    )
    g_val = _read_first_numeric_for_row(g_path, row)
    return e_val, g_val


def _sam_csv_path(base_input_dir: str, scenario: str, housing_type: str, county_slug: str) -> Optional[str]:
    county_dir = os.path.join(base_input_dir, scenario, housing_type, county_slug)
    a = os.path.join(county_dir, f"sam_optimized_load_profiles_{county_slug}.csv")
    b = os.path.join(county_dir, f"sam_optimized_load_profiles_{scenario}_{county_slug}.csv")
    if os.path.exists(a):
        return a
    if os.path.exists(b):
        return b
    return None


def _sam_metric_sum(base_input_dir: str, scenario: str, housing_type: str, county_slug: str, column: str) -> float:
    path = _sam_csv_path(base_input_dir, scenario, housing_type, county_slug)
    if not path:
        return 0.0
    try:
        df = pd.read_csv(path)
        if column not in df.columns:
            return 0.0
        return float(pd.to_numeric(df[column], errors="coerce").fillna(0).sum())
    except Exception:
        return 0.0


# ---------- Payback (with-solar) collection and plotting ----------

def collect_payback_with_solar(
    base_input_dir: str,
    housing_type: str,
    scenarios: Iterable[str],
    counties: Iterable[str],
    incentive_levels: Tuple[str, ...] = ("no_incentives", "half_incentives", "full_incentives"),
    agg: str = "mean",
) -> pd.DataFrame:
    """Collect payback periods (with-solar only) across scenarios and counties.

    Reads data/results/{housing_type}/payback_periods_{scenario}.csv and filters to rows
    where 'savings_type' == 'with_solar'. Aggregates by scenario and incentive_scenario.

    Returns a long DataFrame with columns: scenario, incentive_scenario, value (years).
    """
    rows: List[Dict] = []
    payback_dir = os.path.join("data", "results", housing_type)
    counties_set = {slugify_county_name(c) for c in counties}
    for scen in scenarios:
        path = os.path.join(payback_dir, f"payback_periods_{scen}.csv")
        if not os.path.exists(path):
            continue
        try:
            df = pd.read_csv(path)
        except Exception:
            continue
        # Filter to with-solar only, and restrict to provided counties if present
        df = df[df.get("savings_type", "with_solar").str.lower() == "with_solar"]
        if "county_slug" in df.columns and counties_set:
            df = df[df["county_slug"].isin(counties_set)]
        # Keep only needed columns
        if "payback_period_years" not in df.columns or "incentive_scenario" not in df.columns:
            continue
        df = df[["incentive_scenario", "payback_period_years"]].copy()
        # Aggregate per scenario (across counties)
        if agg == "median":
            agg_df = df.groupby("incentive_scenario", as_index=False)["payback_period_years"].median()
        else:
            agg_df = df.groupby("incentive_scenario", as_index=False)["payback_period_years"].mean()
        for _, r in agg_df.iterrows():
            if r["incentive_scenario"] not in incentive_levels:
                continue
            rows.append({
                "scenario": scen,
                "incentive_scenario": r["incentive_scenario"],
                "value": float(r["payback_period_years"]),
            })

    out = pd.DataFrame(rows)
    return out


def plot_payback_dotline(
    df: pd.DataFrame,
    scenario_order: Optional[List[str]] = None,
    incentive_order: Tuple[str, ...] = ("no_incentives", "half_incentives", "full_incentives"),
    colors: Optional[Dict[str, str]] = None,
    title: str = "Payback Periods (with solar+storage)",
) -> Tuple[plt.Figure, plt.Axes]:
    """Plot dot+line chart of payback periods by scenario across incentive levels.

    - x: scenarios (ordered)
    - y: payback years
    - three dots per scenario (no/half/full), connected with a thin line
    """
    if df.empty:
        fig, ax = plt.subplots(figsize=(8, 4))
        ax.set_title("No data to plot")
        return fig, ax

    if scenario_order is None:
        scenario_order = sorted(df["scenario"].unique())
    if colors is None:
        colors = {
            "no_incentives": "#d62728",
            "half_incentives": "#ff7f0e",
            "full_incentives": "#2ca02c",
        }

    x = np.arange(len(scenario_order), dtype=float)
    offsets = {incentive_order[i]: o for i, o in enumerate(np.linspace(-0.2, 0.2, len(incentive_order)))}

    fig, ax = plt.subplots(figsize=(max(8, len(scenario_order) * 1.4), 4.5))
    for scen in scenario_order:
        sub = df[df["scenario"] == scen]
        # draw line connecting incentive dots in the specified order
        xs, ys = [], []
        for inc in incentive_order:
            row = sub[sub["incentive_scenario"] == inc]
            if row.empty:
                continue
            xi = float(x[list(scenario_order).index(scen)] + offsets[inc])
            yi = float(row["value"].values[0])
            xs.append(xi)
            ys.append(yi)
            ax.scatter([xi], [yi], color=colors.get(inc, "gray"), s=40, zorder=3, label=inc if scen == scenario_order[0] else None)
        if len(xs) >= 2:
            ax.plot(xs, ys, color="#888", linewidth=1.0, zorder=2)

    ax.set_xticks(x)
    ax.set_xticklabels(scenario_order, rotation=20, ha="right")
    ax.set_ylabel("Payback (years)")
    ax.set_title(title)
    # one legend entry per incentive level
    handles, labels = ax.get_legend_handles_labels()
    by_label = dict(zip(labels, handles))
    if by_label:
        ax.legend(by_label.values(), [l.replace("_", " ").title() for l in by_label.keys()], frameon=False, loc="best")
    ax.grid(True, axis="y", linestyle=":", alpha=0.4)
    fig.tight_layout()
    return fig, ax


# ---------- kWh flows collection and plotting ----------

KWH_METRICS = [
    ("Load Profile", "Load Profile"),
    ("System to Load", "System to Load"),
    ("Battery to Load", "Battery to Load"),
    ("Grid to Load", "Grid to Load"),
    ("System to Battery", "System to Battery"),  # PV→Battery
]


def collect_kwh_flows(
    base_input_dir: str,
    housing_type: str,
    scenarios: Iterable[str],
    counties: Iterable[str],
    agg: str = "mean",
) -> pd.DataFrame:
    """Collect annual kWh totals for key flow metrics across scenarios.

    Returns a long DataFrame with columns: scenario, metric, value.
    Aggregates over counties via mean (default) or median.
    """
    rows: List[Dict] = []
    for scen in scenarios:
        for county in counties:
            slug = slugify_county_name(county)
            vals = {}
            for metric_label, col in KWH_METRICS:
                vals[metric_label] = _sam_metric_sum(base_input_dir, scen, housing_type, slug, col)
            rows.append({"scenario": scen, "county_slug": slug, **vals})

    if not rows:
        return pd.DataFrame(columns=["scenario", "metric", "value"])
    df = pd.DataFrame(rows)

    if agg == "median":
        agg_df = df.groupby("scenario").median(numeric_only=True).reset_index()
    else:
        agg_df = df.groupby("scenario").mean(numeric_only=True).reset_index()

    long_rows: List[Dict] = []
    for _, r in agg_df.iterrows():
        for metric_label, _ in KWH_METRICS:
            long_rows.append({
                "scenario": r["scenario"],
                "metric": metric_label,
                "value": float(r[metric_label]),
            })
    return pd.DataFrame(long_rows)


def plot_kwh_flows_dotline(
    df: pd.DataFrame,
    scenario_order: Optional[List[str]] = None,
    metrics: Optional[List[str]] = None,
    title: str = "Annual kWh Flows by Scenario",
) -> plt.Figure:
    """Plot dot+line charts for kWh flows with one subplot per metric."""
    if df.empty:
        fig, ax = plt.subplots(figsize=(8, 4))
        ax.set_title("No data to plot")
        return fig

    if scenario_order is None:
        scenario_order = sorted(df["scenario"].unique())
    if metrics is None:
        metrics = [m for m, _ in KWH_METRICS]

    ncols = min(2, len(metrics))
    nrows = int(np.ceil(len(metrics) / ncols))
    fig, axes = plt.subplots(nrows, ncols, figsize=(max(8, len(scenario_order) * 1.5), 3.2 * nrows), squeeze=False)

    for idx, metric in enumerate(metrics):
        ax = axes[idx // ncols][idx % ncols]
        sub = df[df["metric"] == metric]
        x = np.arange(len(scenario_order), dtype=float)
        # Use a single dot per scenario; connect with a line across scenarios
        ys, xs = [], []
        for scen in scenario_order:
            row = sub[sub["scenario"] == scen]
            if row.empty:
                continue
            xs.append(float(x[list(scenario_order).index(scen)]))
            ys.append(float(row["value"].values[0]))
        if xs and ys:
            ax.plot(xs, ys, color="#1f77b4", linewidth=1.0, marker="o")
        ax.set_title(metric)
        ax.set_xticks(x)
        ax.set_xticklabels(scenario_order, rotation=20, ha="right")
        ax.grid(True, axis="y", linestyle=":", alpha=0.4)
        ax.set_ylabel("kWh")

    fig.suptitle(title)
    fig.tight_layout(rect=[0, 0, 1, 0.96])
    return fig


# ---------- Savings and total bill collection + plotting ----------

def _annual_savings_with_solar(base_input_dir: str, scenario: str, housing_type: str, county_slug: str) -> float:
    # baseline total cost (no electrification)
    baseline = _read_totals_cost(base_input_dir, "baseline", housing_type, county_slug, "baseline")
    # scenario + solar total cost
    scen_solar = _read_totals_cost(base_input_dir, scenario, housing_type, county_slug, f"{scenario}.solarstorage")
    if baseline <= 0 or scen_solar <= 0:
        return 0.0
    return float(baseline - scen_solar)


def _total_annual_bill_with_solar(base_input_dir: str, scenario: str, housing_type: str, county_slug: str) -> float:
    return _read_totals_cost(base_input_dir, scenario, housing_type, county_slug, f"{scenario}.solarstorage")


def collect_savings_and_bills(
    base_input_dir: str,
    housing_type: str,
    scenarios: Iterable[str],
    counties: Iterable[str],
    agg: str = "mean",
) -> pd.DataFrame:
    """Collect annual savings (with solar) and total bill (with solar) across scenarios.

    Returns wide DataFrame with columns: scenario, annual_savings_with_solar, total_annual_bill_with_solar.
    """
    rows: List[Dict] = []
    for scen in scenarios:
        vals = []
        bills = []
        for county in counties:
            slug = slugify_county_name(county)
            vals.append(_annual_savings_with_solar(base_input_dir, scen, housing_type, slug))
            bills.append(_total_annual_bill_with_solar(base_input_dir, scen, housing_type, slug))
        if not vals:
            continue
        if agg == "median":
            savings_val = float(np.median(vals))
            bills_val = float(np.median(bills))
        else:
            savings_val = float(np.mean(vals))
            bills_val = float(np.mean(bills))
        rows.append({
            "scenario": scen,
            "annual_savings_with_solar": savings_val,
            "total_annual_bill_with_solar": bills_val,
        })
    return pd.DataFrame(rows)


def plot_savings_and_bills_dotline(
    df: pd.DataFrame,
    scenario_order: Optional[List[str]] = None,
    title_savings: str = "Annual Savings (with solar + storage)",
    title_bill: str = "Total Annual Energy Bill (with solar + storage)",
) -> plt.Figure:
    """Plot dot+line charts (two subplots): savings and total annual bill by scenario."""
    if df.empty:
        fig, ax = plt.subplots(figsize=(8, 4))
        ax.set_title("No data to plot")
        return fig

    if scenario_order is None:
        scenario_order = sorted(df["scenario"].unique())
    x = np.arange(len(scenario_order), dtype=float)

    # Two subplots side by side (savings left, bill right)
    # Make each subplot a bit wider for readability
    width = max(12, min(20, len(scenario_order) * 1.6))
    fig, axes = plt.subplots(1, 2, figsize=(width, 5.2))

    # Savings
    ax = axes[0]
    xs, ys = [], []
    for scen in scenario_order:
        row = df[df["scenario"] == scen]
        if row.empty:
            continue
        xs.append(float(x[list(scenario_order).index(scen)]))
        ys.append(float(row["annual_savings_with_solar"].values[0]))
    if xs and ys:
        ax.plot(xs, ys, color="#2ca02c", marker="o")
    ax.set_title(title_savings)
    ax.set_xticks(x)
    ax.set_xticklabels(scenario_order, rotation=15, ha="right")
    ax.set_ylabel("$ per year")
    ax.grid(True, axis="y", linestyle=":", alpha=0.4)

    # Total bill
    ax = axes[1]
    xs, ys = [], []
    for scen in scenario_order:
        row = df[df["scenario"] == scen]
        if row.empty:
            continue
        xs.append(float(x[list(scenario_order).index(scen)]))
        ys.append(float(row["total_annual_bill_with_solar"].values[0]))
    if xs and ys:
        ax.plot(xs, ys, color="#1f77b4", marker="o")
    ax.set_title(title_bill)
    ax.set_xticks(x)
    ax.set_xticklabels(scenario_order, rotation=15, ha="right")
    ax.set_ylabel("$ per year")
    ax.grid(True, axis="y", linestyle=":", alpha=0.4)

    fig.tight_layout()
    return fig


# ---------- Recommendations ----------

def recommended_additional_plots() -> List[str]:
    return [
        "Scenario vs. Effective Electricity Price: scatter of price vs. payback (with solar)",
        "PV capacity factor vs. payback: county scatter with best-fit line per scenario",
        "Stacked bars per scenario: annual energy components (PV→Load, Battery→Load, Grid→Load)",
        "Peak-period load share vs. annual savings: reveal tariff/time-of-use sensitivity",
        "County distribution (violin/box) of payback per scenario under full incentives",
        "Sensitivity lines: vary solar size ±20% and show impact on payback per scenario",
    ]


# ---------- Equivalent Annual Cost (EAC) collection and plotting ----------

def _crf(rate: float, n_years: float) -> float:
    """Capital Recovery Factor."""
    if rate <= 0 or n_years <= 0:
        return 1.0 / max(n_years, 1.0)
    r = rate
    n = float(n_years)
    return (r * (1 + r) ** n) / (((1 + r) ** n) - 1)


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


def _read_capital_summary_with_pv(base_input_dir: str, scenario: str, housing_type: str) -> Optional[pd.DataFrame]:
    cap_dir = os.path.join(base_input_dir, "capital_costs")
    fname = f"capital_costs_summary_with_pv_{scenario}_{housing_type.replace('-', '_')}.csv"
    path = os.path.join(cap_dir, fname)
    if not os.path.exists(path):
        return None
    try:
        return pd.read_csv(path)
    except Exception:
        return None


# ---------- PV size collection + plotting ----------

def collect_pv_sizes(
    base_input_dir: str,
    housing_type: str,
    scenarios: Iterable[str],
    counties: Iterable[str],
    agg: str = "mean",
) -> pd.DataFrame:
    """Collect PV system size (kW) by scenario, aggregated across counties.

    Returns DataFrame with columns: scenario, pv_kw.
    """
    county_slugs = [slugify_county_name(c) for c in counties]
    rows: List[Dict] = []
    for scen in scenarios:
        pvsum = _read_capital_summary_with_pv(base_input_dir, scen, housing_type)
        if pvsum is None or pvsum.empty or 'solar_kw' not in pvsum.columns:
            rows.append({"scenario": scen, "pv_kw": 0.0})
            continue
        sub = pvsum[pvsum['county_slug'].str.lower().isin([s.lower() for s in county_slugs])]
        if sub.empty:
            rows.append({"scenario": scen, "pv_kw": 0.0})
            continue
        vals = pd.to_numeric(sub['solar_kw'], errors='coerce').fillna(0.0)
        pv_val = float(vals.median()) if agg == 'median' else float(vals.mean())
        rows.append({"scenario": scen, "pv_kw": pv_val})
    return pd.DataFrame(rows)


def plot_pv_size_bar(
    df: pd.DataFrame,
    scenario_order: Optional[List[str]] = None,
    title: str = "PV Size (kW) by Scenario",
) -> plt.Figure:
    """Simple bar chart of PV system size by scenario."""
    if df.empty:
        fig, ax = plt.subplots(figsize=(8, 4))
        ax.set_title("No PV size data to plot")
        return fig

    if scenario_order is None:
        scenario_order = list(df['scenario'])

    x = np.arange(len(scenario_order))
    vals = []
    for scen in scenario_order:
        row = df[df['scenario'] == scen]
        vals.append(float(row['pv_kw'].values[0]) if not row.empty else 0.0)

    fig, ax = plt.subplots(figsize=(max(8, len(scenario_order) * 1.0), 4.5))
    bars = ax.bar(x, vals, color="#ffbb78")
    ax.set_xticks(x)
    ax.set_xticklabels(scenario_order, rotation=20, ha='right')
    ax.set_ylabel('PV size (kW)')
    ax.set_title(title)
    ax.grid(True, axis='y', linestyle=':', alpha=0.4)
    # Annotate values above each bar
    if vals:
        ymax = max(vals) if len(vals) > 0 else 0.0
        offset = 0.02 * ymax if ymax > 0 else 0.1
        for xi, v in zip(x, vals):
            ax.text(xi, v + offset, f"{v:.2f}", ha='center', va='bottom', fontsize=9)
    fig.tight_layout()
    return fig


def collect_eac_components(
    base_input_dir: str,
    housing_type: str,
    scenarios: Iterable[str],
    counties: Iterable[str],
    incentive: str = "full_incentives",
    discount_rate: float = 0.07,
    agg: str = "mean",
    timestamp: Optional[str] = None,
    electricity_plan_preference: Optional[Iterable[str]] = None,
    electricity_variant: Optional[str] = "nem3",
) -> pd.DataFrame:
    """Collect Equivalent Annual Cost components.

    Components per scenario (aggregated across counties):
      - capex_pv (annualized)
      - capex_storage (annualized)
      - capex_electric (annualized, excluding PV/storage)
      - capex_gas (annualized)
      - annual_bill_with_solar (defaults to NEM 3.0 if available)
      - vehicle_om (ICE for baseline_ice_car; EV for full_electric_ev; else 0)

    Parameters
    - electricity_plan_preference: optional ordered list of plan tokens to match
      (e.g., ["E-TOU-D", "TOU-D-4-9PM", "TOU-DR1"]).
    - electricity_variant: billing variant for with-solar electricity bills.
      Defaults to "nem3". Use "retail" to ignore export credits and use import-only.
    """
    inc = incentive.lower()
    county_slugs = [slugify_county_name(c) for c in counties]
    rows = []
    for scen in scenarios:
        ledger = _read_capital_ledger(base_input_dir, scen, housing_type)
        pvsum = _read_capital_summary_with_pv(base_input_dir, scen, housing_type)

        per_county = []
        for slug in county_slugs:
            capex_pv = 0.0
            capex_storage = 0.0
            capex_electric = 0.0
            capex_gas = 0.0
            vehicle_om = 0.0
            # Bills split into electricity + gas under with-solar variant
            e_bill, g_bill = _annual_bill_parts(
                base_input_dir,
                scen,
                housing_type,
                slug,
                with_solar=True,
                timestamp=timestamp,
                electricity_plan_preference=electricity_plan_preference,
                electricity_variant=electricity_variant,
            )

            # From capital ledger (annualize per appliance)
            if ledger is not None and not ledger.empty:
                df = ledger.copy()
                df = df[df['county_slug'].str.lower() == slug]
                df['incentive_scenario'] = df['incentive_scenario'].str.lower()
                df = df[df['incentive_scenario'] == inc]
                # Electric capex (non-PV/storage)
                if not df.empty:
                    # Some rows may miss lifetime_years; default to 15
                    life = pd.to_numeric(df.get('lifetime_years', pd.Series([15] * len(df))), errors='coerce').fillna(15)
                    crf = _crf(discount_rate, 1)  # placeholder, recompute per row below
                    # Annualize per-row
                    capex_electric += float((
                        ((df['appliance_category'] == 'electric') & (~df['appliance_type'].isin(['solar', 'storage'])))
                        .astype(float)
                        * 0  # placeholder
                    ).sum())
                    # Loop rows for clarity
                    for _, r in df.iterrows():
                        try:
                            lt = float(r.get('lifetime_years', 15) or 15)
                            c = _crf(discount_rate, lt)
                            if r.get('appliance_category') == 'electric' and r.get('appliance_type') not in ('solar', 'storage'):
                                capex_electric += float(r.get('net_cost', 0.0)) * c
                            if r.get('appliance_category') == 'gas':
                                capex_gas += float(r.get('base_cost', 0.0)) * c
                        except Exception:
                            continue

                # Vehicle O&M adders
                try:
                    adders = vehicle_annual_adders_from_ledger(df)
                    if slug in adders.index:
                        ev_val = float(adders.loc[slug, 'ev_operating']) if 'ev_operating' in adders.columns else 0.0
                        ice_val = float(adders.loc[slug, 'ice_operating']) if 'ice_operating' in adders.columns else 0.0
                        # Prefer scenario-driven inclusion, fall back to positive values
                        scen_l = (scen or '').lower()
                        if ('ev' in scen_l) or (ev_val > 0):
                            vehicle_om += ev_val
                        if ('ice' in scen_l) or (ice_val > 0 and 'ev' not in scen_l):
                            vehicle_om += ice_val
                except Exception:
                    pass

            # PV + Storage capex (annualized) from summary_with_pv
            if pvsum is not None and not pvsum.empty:
                row = pvsum[pvsum['county_slug'].str.lower() == slug]
                if not row.empty:
                    pv_capex = float(row.iloc[0].get('pv_capex', 0.0))
                    st_capex = float(row.iloc[0].get('storage_capex', 0.0))
                    pv_inc_full = float(row.iloc[0].get('pv_incentives_full', 0.0)) if 'pv_incentives_full' in row.columns else 0.0
                    st_inc_full = float(row.iloc[0].get('storage_incentives_full', 0.0)) if 'storage_incentives_full' in row.columns else 0.0
                    if inc == 'full_incentives':
                        pv_net = pv_capex - pv_inc_full
                        st_net = st_capex - st_inc_full
                    elif inc == 'half_incentives':
                        pv_net = pv_capex - (pv_inc_full * 0.5)
                        st_net = st_capex - (st_inc_full * 0.5)
                    else:  # no_incentives
                        pv_net = pv_capex
                        st_net = st_capex
                    capex_pv += pv_net * _crf(discount_rate, LIFETIMES.get('solar', 25))
                    capex_storage += st_net * _crf(discount_rate, LIFETIMES.get('storage', 15))

            per_county.append({
                'scenario': scen,
                'county_slug': slug,
                'capex_pv': capex_pv,
                'capex_storage': capex_storage,
                'capex_electric': capex_electric,
                'capex_gas': capex_gas,
                'annual_bill_electric': e_bill,
                'annual_bill_gas': g_bill,
                'vehicle_om': vehicle_om,
            })

        if not per_county:
            continue
        per_df = pd.DataFrame(per_county)
        if agg == 'median':
            agg_df = per_df.groupby('scenario').median(numeric_only=True).reset_index()
        else:
            agg_df = per_df.groupby('scenario').mean(numeric_only=True).reset_index()
        rows.append(agg_df.iloc[0].to_dict())

    return pd.DataFrame(rows)


def collect_eac_components_by_county(
    base_input_dir: str,
    housing_type: str,
    scenarios: Iterable[str],
    counties: Iterable[str],
    incentive: str = "full_incentives",
    discount_rate: float = 0.07,
    timestamp: Optional[str] = None,
    electricity_plan_preference: Optional[Iterable[str]] = None,
    electricity_variant: Optional[str] = "nem3",
) -> pd.DataFrame:
    """Return per-county Equivalent Annual Cost components for each scenario.

    Columns:
      scenario, county_slug, capex_pv, capex_storage, capex_electric, capex_gas,
      annual_bill_electric, annual_bill_gas, vehicle_om

    Notes
      - Uses the same accounting as collect_eac_components but does not aggregate.
      - electricity_variant defaults to 'nem3' for with-solar electricity bills.
    """
    inc = (incentive or "").lower()
    county_slugs = [slugify_county_name(c) for c in counties]
    out_rows: List[Dict] = []
    for scen in scenarios:
        ledger = _read_capital_ledger(base_input_dir, scen, housing_type)
        pvsum = _read_capital_summary_with_pv(base_input_dir, scen, housing_type)
        for slug in county_slugs:
            capex_pv = 0.0
            capex_storage = 0.0
            capex_electric = 0.0
            capex_gas = 0.0
            vehicle_om = 0.0
            e_bill, g_bill = _annual_bill_parts(
                base_input_dir,
                scen,
                housing_type,
                slug,
                with_solar=True,
                timestamp=timestamp,
                electricity_plan_preference=electricity_plan_preference,
                electricity_variant=electricity_variant,
            )

            if ledger is not None and not ledger.empty:
                df = ledger.copy()
                if 'county_slug' in df.columns:
                    df = df[df['county_slug'].str.lower() == slug]
                if 'incentive_scenario' in df.columns:
                    df['incentive_scenario'] = df['incentive_scenario'].str.lower()
                    df = df[df['incentive_scenario'] == inc]
                if not df.empty:
                    for _, r in df.iterrows():
                        try:
                            lt = float(r.get('lifetime_years', 15) or 15)
                            c = _crf(discount_rate, lt)
                            if r.get('appliance_category') == 'electric' and r.get('appliance_type') not in ('solar', 'storage'):
                                capex_electric += float(r.get('net_cost', 0.0)) * c
                            if r.get('appliance_category') == 'gas':
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

            if pvsum is not None and not pvsum.empty:
                row = pvsum[pvsum['county_slug'].str.lower() == slug]
                if not row.empty:
                    pv_capex = float(row.iloc[0].get('pv_capex', 0.0))
                    st_capex = float(row.iloc[0].get('storage_capex', 0.0))
                    pv_inc_full = float(row.iloc[0].get('pv_incentives_full', 0.0)) if 'pv_incentives_full' in row.columns else 0.0
                    st_inc_full = float(row.iloc[0].get('storage_incentives_full', 0.0)) if 'storage_incentives_full' in row.columns else 0.0
                    if inc == 'full_incentives':
                        pv_net = pv_capex - pv_inc_full
                        st_net = st_capex - st_inc_full
                    elif inc == 'half_incentives':
                        pv_net = pv_capex - (pv_inc_full * 0.5)
                        st_net = st_capex - (st_inc_full * 0.5)
                    else:
                        pv_net = pv_capex
                        st_net = st_capex
                    capex_pv += pv_net * _crf(discount_rate, LIFETIMES.get('solar', 25))
                    capex_storage += st_net * _crf(discount_rate, LIFETIMES.get('storage', 15))

            out_rows.append({
                'scenario': scen,
                'county_slug': slug,
                'capex_pv': capex_pv,
                'capex_storage': capex_storage,
                'capex_electric': capex_electric,
                'capex_gas': capex_gas,
                'annual_bill_electric': e_bill,
                'annual_bill_gas': g_bill,
                'vehicle_om': vehicle_om,
            })

    return pd.DataFrame(out_rows)


def plot_eac_stacked_bar(
    df: pd.DataFrame,
    scenario_order: Optional[List[str]] = None,
    title: str = "All-in Annualized Cost (EAC) by Scenario",
) -> plt.Figure:
    if df.empty:
        fig, ax = plt.subplots(figsize=(8, 4))
        ax.set_title("No data to plot")
        return fig

    if scenario_order is None:
        scenario_order = list(df['scenario'])

    components = [
        ('capex_pv', '#fdae6b', 'PV capex (annualized)'),
        ('capex_storage', '#9ecae1', 'Storage capex (annualized)'),
        ('capex_electric', '#31a354', 'Electrification capex (annualized)'),
        ('capex_gas', '#756bb1', 'Gas capex (annualized)'),
        ('annual_bill_with_solar', '#1f77b4', 'Annual energy bill (with solar+storage)'),
        ('vehicle_om', '#d62728', 'Vehicle O&M'),
    ]

    x = np.arange(len(scenario_order))
    fig, ax = plt.subplots(figsize=(max(10, len(scenario_order) * 1.3), 5.0))
    bottoms = np.zeros_like(x, dtype=float)
    # Choose bill components: split into electric + gas if present, else fall back to single total
    has_split_bill = ('annual_bill_electric' in df.columns) and ('annual_bill_gas' in df.columns)
    if has_split_bill:
        comps = [
            ('capex_pv', '#fdae6b', 'PV capex (annualized)'),
            ('capex_storage', '#9ecae1', 'Storage capex (annualized)'),
            ('capex_electric', '#31a354', 'Electrification capex (annualized)'),
            ('capex_gas', '#756bb1', 'Gas capex (annualized)'),
            ('vehicle_om', '#d62728', 'Vehicle O&M'),
            ('annual_bill_electric', '#1f77b4', 'Annual electricity bill'),
            ('annual_bill_gas', '#17becf', 'Annual gas bill'),
        ]
    else:
        comps = components
    for key, color, label in comps:
        vals = []
        for scen in scenario_order:
            row = df[df['scenario'] == scen]
            vals.append(float(row[key].values[0]) if not row.empty and key in row.columns else 0.0)
        ax.bar(x, vals, bottom=bottoms, color=color, label=label)
        bottoms = bottoms + np.array(vals)
    # Annotate total EAC above each stacked bar
    try:
        totals = np.asarray(bottoms, dtype=float)
        if totals.size > 0 and np.isfinite(totals).any():
            ymax = float(np.nanmax(totals))
            if ymax > 0:
                ax.set_ylim(0.0, ymax * 1.08)
            yoff = max(1.0, 0.02 * ymax) if ymax > 0 else 1.0
            for xi, tot in zip(x, totals):
                tval = float(tot) if np.isfinite(tot) else 0.0
                if tval > 0:
                    ax.text(float(xi), tval + yoff, f"{tval:.0f}", ha='center', va='bottom', fontsize=9, color='black')
    except Exception:
        pass
    ax.set_xticks(x)
    ax.set_xticklabels(scenario_order, rotation=20, ha='right')
    ax.set_ylabel('$ per year')
    ax.set_title(title)
    ax.legend(frameon=False, loc='best')
    ax.grid(True, axis='y', linestyle=':', alpha=0.4)
    fig.tight_layout()
    return fig
