import glob
import os
import sys

import pandas as pd
import pytest

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from helpers.main_helpers import slugify_county_name
from pipeline.steps.step22_build_county_diagnostics import create_coopt_results_card


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


def test_step22_coopt_card_includes_cost_components() -> None:
    files = _find_coopt_capacity_csvs()
    if not files:
        pytest.skip("No co-optimization capacity CSVs found under data/loadprofiles.")
    path = files[0]
    df = pd.read_csv(path)
    if df.empty:
        pytest.skip(f"Co-optimization capacity CSV is empty: {path}")
    scenario, housing_type = _scenario_and_housing_from_path(path)
    county_slug = _first_row_county_slug(df)

    card_html = create_coopt_results_card(BASE_INPUT_DIR, scenario, housing_type, county_slug)
    if "Co-optimization results not found" in card_html:
        pytest.skip("Co-optimization results not found for selected county.")

    required_snippets = [
        "Battery Power",
        "Total Cost",
        "Storage Value",
        "Capex Annual",
        "Import Cost",
        "Export Credit",
        "Degradation Cost",
    ]
    for snippet in required_snippets:
        assert snippet in card_html, f"Missing '{snippet}' in co-opt results card"
