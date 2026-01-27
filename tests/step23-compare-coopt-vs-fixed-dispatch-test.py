import glob
import os
import sys

import pandas as pd
import pytest

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from helpers.main_helpers import slugify_county_name
from pipeline.steps.step23_compare_coopt_vs_fixed_dispatch import _read_assets_for_county


BASE_INPUT_DIR = os.path.join(REPO_ROOT, "data", "loadprofiles")


def _find_coopt_capacity_csvs() -> list[str]:
    pattern = os.path.join(BASE_INPUT_DIR, "*", "*", "CAPITAL_COSTS", "electrified_assets.csv")
    candidates = sorted(glob.glob(pattern))
    return [p for p in candidates if "_coopt" in os.path.normpath(p)]


def _scenario_and_housing_from_path(path: str) -> tuple[str, str]:
    parts = os.path.normpath(path).split(os.sep)
    # .../data/loadprofiles/<scenario>/<housing_type>/CAPITAL_COSTS/electrified_assets.csv
    return parts[-4], parts[-3]


def _first_row_county_slug(df: pd.DataFrame) -> str:
    if "County" in df.columns:
        val = df.iloc[0]["County"]
    else:
        val = df.iloc[0][df.columns[0]]
    return slugify_county_name(str(val))


def test_step23_reads_coopt_cost_fields() -> None:
    files = _find_coopt_capacity_csvs()
    if not files:
        pytest.skip("No co-optimization capacity CSVs found under data/loadprofiles.")
    path = files[0]
    df = pd.read_csv(path)
    if df.empty:
        pytest.skip(f"Co-optimization capacity CSV is empty: {path}")

    scenario, housing_type = _scenario_and_housing_from_path(path)
    county_slug = _first_row_county_slug(df)

    required_cols = [
        "Battery Power Capacity (kW)",
        "Coopt Total Cost",
        "Coopt Capex Annual",
        "Coopt Import Cost",
        "Coopt Export Credit",
        "Coopt Degradation Cost",
    ]
    missing = [c for c in required_cols if c not in df.columns]
    if missing:
        raise AssertionError(f"{os.path.basename(path)} missing columns: {missing}")

    size = _read_assets_for_county(BASE_INPUT_DIR, scenario, housing_type, county_slug)
    assert size.batt_kw is not None, "Expected battery power capacity from coopt assets"
    assert size.coopt_total_cost is not None, "Expected coopt total cost from assets"
    assert size.coopt_capex_annual is not None, "Expected coopt capex annual from assets"
    assert size.coopt_import_cost is not None, "Expected coopt import cost from assets"
    assert size.coopt_export_credit is not None, "Expected coopt export credit from assets"
    assert size.coopt_degradation_cost is not None, "Expected coopt degradation cost from assets"
