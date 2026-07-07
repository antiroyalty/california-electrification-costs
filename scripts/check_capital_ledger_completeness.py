"""Post-run completeness check for a scenario's capital-cost ledger, or for a
sensitivity sweep output from pipeline.sensitivity_runner.

Run this after (re-)computing a scenario across counties, before trusting any
report built on top of it. Catches exactly the failure mode a broad
`except Exception: continue` in step14/eac.py can hide: a county silently
present with zero-valued or missing capex fields instead of an error.

Usage
  python3 scripts/check_capital_ledger_completeness.py <scenario> [--housing-type single-family-detached]
  python3 scripts/check_capital_ledger_completeness.py --sensitivity analysis_results/sensitivity_discount_rate.csv

Checks (per scenario, or per (parameter, value) group for sensitivity output)
  1. Every county in the pipeline's county list appears.
  2. No missing (NaN) values in required numeric columns.
  3. No county has every capex/net_cost (or total_eac) value equal to 0.0 (a
     silent computation failure typically produces exact zeros, not small
     numbers).
"""
from __future__ import annotations

import argparse
import os
import sys

import pandas as pd

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from helpers.main_helpers import (
    slugify_county_name,
    norcal_counties,
    central_counties,
    socal_counties,
)

REQUIRED_NUMERIC_COLS = ["net_cost", "base_cost", "lifetime_years"]
ZERO_CHECK_COLS = ["net_cost", "base_cost"]


def all_expected_county_slugs() -> set[str]:
    all_counties = norcal_counties + central_counties + socal_counties
    return {slugify_county_name(c) for c in all_counties}


def _check_county_coverage(df: pd.DataFrame, zero_cols: list[str], label: str) -> int:
    """Shared coverage/NaN/all-zero checks for one (df slice, label) pair."""
    problems = 0
    expected = all_expected_county_slugs()
    present = set(df["county_slug"].unique()) if "county_slug" in df.columns else set()
    missing_counties = sorted(expected - present)
    unexpected_counties = sorted(present - expected)

    print(f"{label}")
    print(f"  Expected counties: {len(expected)}")
    print(f"  Present counties:  {len(present)}")

    if missing_counties:
        problems += 1
        print(f"  MISSING ({len(missing_counties)}): {missing_counties}")
    if unexpected_counties:
        problems += 1
        print(f"  UNEXPECTED (not in pipeline county list): {unexpected_counties}")

    for col in zero_cols:
        if col not in df.columns:
            continue
        n_nan = df[col].isna().sum()
        if n_nan:
            problems += 1
            print(f"  NaN in '{col}': {n_nan} rows")

    present_zero_cols = [c for c in zero_cols if c in df.columns]
    if present_zero_cols and "county_slug" in df.columns:
        by_county = df.groupby("county_slug")[present_zero_cols].sum()
        all_zero = by_county[(by_county == 0.0).all(axis=1)]
        if not all_zero.empty:
            problems += 1
            print(
                f"  ALL-ZERO across {present_zero_cols} for {len(all_zero)} counties "
                f"(likely silent computation failure): {sorted(all_zero.index)}"
            )

    if problems == 0:
        print("  OK — no issues found.")
    return problems


def check_ledger(path: str) -> int:
    """Print a report for a capital_costs ledger; return the problem count."""
    if not os.path.exists(path):
        print(f"MISSING FILE: {path}")
        return 1
    df = pd.read_csv(path)
    return _check_county_coverage(df, REQUIRED_NUMERIC_COLS, f"Ledger: {path}")


def check_sensitivity_output(path: str) -> int:
    """Print a report for a pipeline.sensitivity_runner output; return the
    problem count, checked separately for each (parameter, value) sweep point.

    A sensitivity file spans multiple runs of the pipeline (one per swept
    value) — checking the file as a whole would hide a single bad value's
    missing counties inside an otherwise-complete-looking total.
    """
    if not os.path.exists(path):
        print(f"MISSING FILE: {path}")
        return 1
    df = pd.read_csv(path)
    problems = 0
    if not {"parameter", "value"}.issubset(df.columns):
        print(f"MALFORMED: {path} is missing 'parameter'/'value' columns — not a sensitivity output?")
        return 1
    for (parameter, value), group in df.groupby(["parameter", "value"]):
        label = f"Sensitivity: {path}  [{parameter}={value}]"
        problems += _check_county_coverage(group, ["total_eac"], label)
    return problems


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scenario", nargs="?", help="Scenario name, e.g. full_electric_ev_coopt")
    parser.add_argument("--housing-type", default="single-family-detached")
    parser.add_argument("--base-input-dir", default="data/loadprofiles")
    parser.add_argument("--sensitivity", metavar="PATH", help="Check a sensitivity_runner output CSV instead of a ledger")
    args = parser.parse_args()

    if args.sensitivity:
        problems = check_sensitivity_output(args.sensitivity)
    else:
        if not args.scenario:
            parser.error("scenario is required unless --sensitivity is given")
        fname = f"capital_costs_{args.scenario}_{args.housing_type.replace('-', '_')}.csv"
        path = os.path.join(args.base_input_dir, "capital_costs", fname)
        problems = check_ledger(path)

    sys.exit(1 if problems else 0)


if __name__ == "__main__":
    main()
