"""Ballpark sanity checks for load profile outputs and the methods manifest.

Two concerns are tested here:

1. Methods manifest integrity: docs/methods.yaml must load cleanly and all
   code references it declares (file:symbol pairs) must point to real files
   and symbols in the repo.

2. Load profile plausibility for Alameda County: the combined_profiles CSVs
   produced by the pipeline must satisfy energy-conservation invariants:
   - Baseline electricity is ~5,558 kWh/yr (within 20% of RECS/EIA benchmarks)
   - Electrified scenarios have strictly higher electricity loads than baseline
   - Reduced-gas scenarios have strictly lower gas loads than baseline
   - All profiles are exactly 8,760 rows with non-negative, non-null values

These tests use Alameda County as the single representative county because it
is the primary validation county throughout the paper. If a scenario's CSVs
are missing (e.g., a partial run), the test skips rather than fails.
"""
import json
import os
import sys

import pandas as pd
import pytest

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from helpers.main_helpers import slugify_county_name
from scenarios import SCENARIOS

def _repo_root() -> str:
    return REPO_ROOT


def _load_manifest() -> dict:
    path = os.path.join(_repo_root(), "docs", "methods.yaml")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def test_methods_manifest_loads() -> None:
    """docs/methods.yaml loads as a non-empty dict."""
    manifest = _load_manifest()
    assert isinstance(manifest, dict)
    assert manifest, "methods manifest is empty"


def test_methods_manifest_code_refs_exist() -> None:
    """every file:symbol code reference in docs/methods.yaml points to a real file and symbol."""
    manifest = _load_manifest()
    root = _repo_root()
    for key, entry in manifest.items():
        for ref in entry.get("code", []):
            path = ref.split(":", 1)[0]
            abs_path = os.path.join(root, path)
            assert os.path.exists(abs_path), f"{key}: missing file {path}"
            if ":" in ref:
                symbol = ref.split(":", 1)[1]
                with open(abs_path, "r", encoding="utf-8") as f:
                    content = f.read()
                assert symbol in content, f"{key}: symbol {symbol} not found in {path}"


# Tests

# 1) Energy load ballpark sanity checks

# a) Alameda baseline scenario should have 5,558 kWh/year of electricity consumption
# b) In all other scenarios, electricity load consumption should be > baseline electricity load
# c) In all other scenarios, gas load consumption should be < baseline gas consumption
# d) Combined profiles should have 8760 rows with non-negative, non-null electricity and gas columns

BASE_INPUT_DIR = os.path.join(REPO_ROOT, "data", "loadprofiles")
HOUSING_TYPE = "single-family-detached"
COUNTY = "Alameda County"
COUNTY_SLUG = slugify_county_name(COUNTY)
COL_ELEC = "electricity.real_and_simulated.for_typical_county_home.kwh"
COL_GAS = "gas.hourly_total.for_typical_county_home.therms"


def _combined_profile_path(scenario: str) -> str:
    return os.path.join(
        BASE_INPUT_DIR,
        scenario,
        HOUSING_TYPE,
        COUNTY_SLUG,
        f"combined_profiles_{scenario}_{COUNTY_SLUG}.csv",
    )


def _load_combined_df(scenario: str) -> pd.DataFrame | None:
    path = _combined_profile_path(scenario)
    if not os.path.exists(path):
        return None
    return pd.read_csv(path)


def _annual_sum(df: pd.DataFrame, column: str) -> float:
    series = pd.to_numeric(df[column], errors="coerce").fillna(0.0)
    return float(series.sum())


def test_alameda_baseline_electricity_ballpark() -> None:
    """Alameda baseline annual electricity consumption is ~5,558 kWh (within 20% of EIA/RECS benchmark)."""
    df = _load_combined_df("baseline")
    if df is None:
        pytest.skip("Baseline combined profiles not found for Alameda County.")
    assert COL_ELEC in df.columns, f"Missing {COL_ELEC} in baseline combined profiles"
    annual_kwh = _annual_sum(df, COL_ELEC)
    assert annual_kwh == pytest.approx(5558.0, rel=0.20)


def test_electricity_increases_for_electrified_scenarios() -> None:
    """every scenario with more electric appliances than baseline has a strictly higher annual electricity load."""
    base_df = _load_combined_df("baseline")
    if base_df is None:
        pytest.skip("Baseline combined profiles not found for Alameda County.")
    if COL_ELEC not in base_df.columns:
        pytest.skip(f"Baseline combined profiles missing {COL_ELEC}")
    baseline_kwh = _annual_sum(base_df, COL_ELEC)

    baseline_electric = SCENARIOS["baseline"]["electric"]
    scenarios = [s for s, v in SCENARIOS.items() if v["electric"] > baseline_electric]
    checked = 0
    for scen in scenarios:
        df = _load_combined_df(scen)
        if df is None:
            continue
        if COL_ELEC not in df.columns:
            raise AssertionError(f"Missing {COL_ELEC} in combined profiles for {scen}")
        kwh = _annual_sum(df, COL_ELEC)
        assert kwh > baseline_kwh, f"{scen} electricity load did not exceed baseline"
        checked += 1
    if checked == 0:
        pytest.skip("No electrified scenario combined profiles available for Alameda County.")


def test_gas_decreases_for_reduced_gas_scenarios() -> None:
    """every scenario with fewer gas appliances than baseline has a strictly lower annual gas consumption."""
    base_df = _load_combined_df("baseline")
    if base_df is None:
        pytest.skip("Baseline combined profiles not found for Alameda County.")
    if COL_GAS not in base_df.columns:
        pytest.skip(f"Baseline combined profiles missing {COL_GAS}")
    baseline_therms = _annual_sum(base_df, COL_GAS)

    baseline_gas = SCENARIOS["baseline"]["gas"]
    scenarios = [s for s, v in SCENARIOS.items() if v["gas"] < baseline_gas]
    checked = 0
    for scen in scenarios:
        df = _load_combined_df(scen)
        if df is None:
            continue
        if COL_GAS not in df.columns:
            raise AssertionError(f"Missing {COL_GAS} in combined profiles for {scen}")
        therms = _annual_sum(df, COL_GAS)
        assert therms < baseline_therms, f"{scen} gas load did not decrease vs baseline"
        checked += 1
    if checked == 0:
        pytest.skip("No reduced-gas scenario combined profiles available for Alameda County.")


def test_combined_profiles_shape_and_non_negative() -> None:
    """combined load profiles for every available scenario have exactly 8,760 rows with non-negative, non-null electricity and gas values."""
    scenarios = list(SCENARIOS.keys())
    checked = 0
    for scen in scenarios:
        df = _load_combined_df(scen)
        if df is None:
            continue
        checked += 1
        assert len(df) == 8760, f"{scen} combined profile row count is {len(df)}"
        for col in (COL_ELEC, COL_GAS):
            assert col in df.columns, f"Missing {col} in combined profiles for {scen}"
            series = pd.to_numeric(df[col], errors="coerce")
            assert series.notna().all(), f"{scen} {col} has NaNs"
            assert (series >= 0).all(), f"{scen} {col} has negative values"
    if checked == 0:
        pytest.skip("No combined profile CSVs found under data/loadprofiles.")
