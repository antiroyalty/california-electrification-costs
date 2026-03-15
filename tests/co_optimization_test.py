import glob
import os

import pandas as pd
import pytest

BASE_INPUT_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "loadprofiles")

REQUIRED_COLUMNS = [
    "Solar Capacity (kW)",
    "Battery Capacity (kWh)",
    "Battery Power Capacity (kW)",
    "Coopt Total Cost",
    "Coopt Capex Annual",
    "Coopt Import Cost",
    "Coopt Export Credit",
    "Coopt Degradation Cost",
    "Allow Grid Charging",
    "Allow Battery Export",
]


def _find_coopt_capacity_csvs() -> list[str]:
    pattern = os.path.join(BASE_INPUT_DIR, "*", "*", "CAPITAL_COSTS", "electrified_assets.csv")
    candidates = sorted(glob.glob(pattern))
    coopt = []
    for path in candidates:
        parts = os.path.normpath(path).split(os.sep)
        if any(p.endswith("_coopt") for p in parts):
            coopt.append(path)
    return coopt


def _load_capacity_df(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    if df.empty:
        raise AssertionError(f"{os.path.basename(path)} is empty")
    return df


def _numeric_series(df: pd.DataFrame, column: str, path: str) -> pd.Series:
    if column not in df.columns:
        raise AssertionError(f"{os.path.basename(path)} missing required column: {column}")
    series = pd.to_numeric(df[column], errors="raise")
    if series.isna().any():
        raise AssertionError(f"{os.path.basename(path)} column {column} contains NaN values")
    return series


@pytest.fixture(scope="module")
def coopt_capacity_files() -> list[str]:
    files = _find_coopt_capacity_csvs()
    if not files:
        pytest.skip("No co-optimization capacity CSVs found under data/loadprofiles.")
    return files


def test_coopt_capacity_columns_present(coopt_capacity_files: list[str]) -> None:
    for path in coopt_capacity_files:
        df = _load_capacity_df(path)
        missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
        if missing:
            raise AssertionError(f"{os.path.basename(path)} missing columns: {missing}")


def test_coopt_cost_components_reconcile(coopt_capacity_files: list[str]) -> None:
    tol = 1e-2
    for path in coopt_capacity_files:
        df = _load_capacity_df(path)
        total = _numeric_series(df, "Coopt Total Cost", path)
        capex = _numeric_series(df, "Coopt Capex Annual", path)
        imports = _numeric_series(df, "Coopt Import Cost", path)
        exports = _numeric_series(df, "Coopt Export Credit", path)
        degrade = _numeric_series(df, "Coopt Degradation Cost", path)
        recomposed = capex + imports - exports + degrade
        diff = (total - recomposed).abs()
        assert (diff <= tol).all(), f"Coopt cost components do not reconcile in {path}"


def test_coopt_power_capacity_non_negative(coopt_capacity_files: list[str]) -> None:
    for path in coopt_capacity_files:
        df = _load_capacity_df(path)
        batt_kw = _numeric_series(df, "Battery Power Capacity (kW)", path)
        assert (batt_kw >= 0.0).all(), f"Negative battery power capacity in {path}"
