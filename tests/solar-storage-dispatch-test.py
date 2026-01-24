import glob
import os

import pandas as pd
import pytest

BASE_INPUT_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "loadprofiles")
ENERGY_TOL = 1e-3  # kWh tolerance for per-timestep comparisons
SOC_TOL = 1e-6


def _find_dispatch_csvs() -> list[str]:
    pattern = os.path.join(BASE_INPUT_DIR, "*", "*", "*", "solar_storage_dispatch_profiles_*.csv")
    return sorted(glob.glob(pattern))


def _load_dispatch_df(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    required = ["Load Profile", "System to Load", "Battery to Load", "Grid to Load", "System to Battery"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise AssertionError(f"{os.path.basename(path)} missing required columns: {missing}")
    return df


def _numeric_series(df: pd.DataFrame, column: str, path: str) -> pd.Series:
    if column not in df.columns:
        raise AssertionError(f"{os.path.basename(path)} missing required column: {column}")
    series = pd.to_numeric(df[column], errors="raise")
    if series.isna().any():
        raise AssertionError(f"{os.path.basename(path)} column {column} contains NaN values")
    return series


@pytest.fixture(scope="module")
def dispatch_files() -> list[str]:
    files = _find_dispatch_csvs()
    if not files:
        pytest.skip("No dispatch CSVs found under data/loadprofiles.")
    return files[:5]


# Relational laws for solar + storage dispatch

def test_pv_and_battery_flows_do_not_exceed_load(dispatch_files: list[str]) -> None:
    for path in dispatch_files:
        df = _load_dispatch_df(path)
        load = _numeric_series(df, "Load Profile", path)
        pv_to_load = _numeric_series(df, "System to Load", path)
        batt_to_load = _numeric_series(df, "Battery to Load", path)
        grid_to_load = _numeric_series(df, "Grid to Load", path)
        assert (pv_to_load <= load + ENERGY_TOL).all(), f"PV->Load exceeds Load in {path}"
        assert (batt_to_load <= load + ENERGY_TOL).all(), f"Battery->Load exceeds Load in {path}"
        assert (grid_to_load <= load + ENERGY_TOL).all(), f"Grid->Load exceeds Load in {path}"


def test_pv_to_battery_and_grid_do_not_exceed_pv(dispatch_files: list[str]) -> None:
    for path in dispatch_files:
        df = _load_dispatch_df(path)
        pv_to_batt = _numeric_series(df, "System to Battery", path)
        pv_to_load = _numeric_series(df, "System to Load", path)

        pv_gen = None
        if "PV AC (kWh)" in df.columns:
            pv_gen = _numeric_series(df, "PV AC (kWh)", path)
        elif "PV to Grid (kWh)" in df.columns:
            pv_to_grid = _numeric_series(df, "PV to Grid (kWh)", path)
            pv_gen = pv_to_load + pv_to_batt + pv_to_grid
        elif "System to Grid" in df.columns:
            pv_to_grid = _numeric_series(df, "System to Grid", path)
            pv_gen = pv_to_load + pv_to_batt + pv_to_grid

        if pv_gen is None:
            pytest.skip(f"No PV generation column found in {path}")

        assert (pv_to_batt <= pv_gen + ENERGY_TOL).all(), f"PV->Battery exceeds PV in {path}"

        if "PV to Grid (kWh)" in df.columns:
            pv_to_grid = _numeric_series(df, "PV to Grid (kWh)", path)
            assert (pv_to_grid <= pv_gen + ENERGY_TOL).all(), f"PV->Grid exceeds PV in {path}"
        elif "System to Grid" in df.columns:
            pv_to_grid = _numeric_series(df, "System to Grid", path)
            assert (pv_to_grid <= pv_gen + ENERGY_TOL).all(), f"PV->Grid exceeds PV in {path}"


def test_grid_equals_load_when_no_solar_or_battery(dispatch_files: list[str]) -> None:
    checked = 0
    for path in dispatch_files:
        df = _load_dispatch_df(path)
        pv_to_load = _numeric_series(df, "System to Load", path)
        pv_to_batt = _numeric_series(df, "System to Battery", path)
        batt_to_load = _numeric_series(df, "Battery to Load", path)
        pv_to_grid = None
        if "PV to Grid (kWh)" in df.columns:
            pv_to_grid = _numeric_series(df, "PV to Grid (kWh)", path)
        elif "System to Grid" in df.columns:
            pv_to_grid = _numeric_series(df, "System to Grid", path)

        pv_flow_max = (pv_to_load + pv_to_batt + (pv_to_grid if pv_to_grid is not None else 0.0)).max()
        batt_flow_max = batt_to_load.max()
        if pv_flow_max <= ENERGY_TOL and batt_flow_max <= ENERGY_TOL:
            load = _numeric_series(df, "Load Profile", path)
            grid_to_load = _numeric_series(df, "Grid to Load", path)
            diff = (grid_to_load - load).abs()
            assert (diff <= ENERGY_TOL).all(), f"Grid->Load not equal to Load in {path}"
            checked += 1
    if checked == 0:
        pytest.skip("No no-solar/battery dispatch files found to verify grid equals load.")


def test_load_balance_per_timestep(dispatch_files: list[str]) -> None:
    for path in dispatch_files:
        df = _load_dispatch_df(path)
        load = _numeric_series(df, "Load Profile", path)
        pv_to_load = _numeric_series(df, "System to Load", path)
        batt_to_load = _numeric_series(df, "Battery to Load", path)
        grid_to_load = _numeric_series(df, "Grid to Load", path)
        total = pv_to_load + batt_to_load + grid_to_load
        diff = (total - load).abs()
        assert (diff <= ENERGY_TOL).all(), f"Load balance violated in {path}"


def test_pv_allocation_balance_per_timestep(dispatch_files: list[str]) -> None:
    for path in dispatch_files:
        df = _load_dispatch_df(path)
        pv_to_load = _numeric_series(df, "System to Load", path)
        pv_to_batt = _numeric_series(df, "System to Battery", path)
        pv_to_grid = None
        if "PV to Grid (kWh)" in df.columns:
            pv_to_grid = _numeric_series(df, "PV to Grid (kWh)", path)
        elif "System to Grid" in df.columns:
            pv_to_grid = _numeric_series(df, "System to Grid", path)

        if "PV AC (kWh)" in df.columns:
            pv_gen = _numeric_series(df, "PV AC (kWh)", path)
        elif pv_to_grid is not None:
            pv_gen = pv_to_load + pv_to_batt + pv_to_grid
        else:
            pytest.skip(f"No PV generation or grid export columns found in {path}")

        allocation = pv_to_load + pv_to_batt + (pv_to_grid if pv_to_grid is not None else 0.0)
        assert (allocation <= pv_gen + ENERGY_TOL).all(), f"PV allocation exceeds PV generation in {path}"


def test_battery_soc_bounds(dispatch_files: list[str]) -> None:
    for path in dispatch_files:
        df = pd.read_csv(path)
        if "Battery SOC" not in df.columns:
            continue
        soc = pd.to_numeric(df["Battery SOC"], errors="raise")
        if soc.isna().any():
            raise AssertionError(f"{os.path.basename(path)} column Battery SOC contains NaN values")
        max_soc = float(soc.max())
        if max_soc > 1.5:
            assert soc.min() >= -SOC_TOL, f"Battery SOC below 0% in {path}"
            assert soc.max() <= 100.0 + SOC_TOL, f"Battery SOC above 100% in {path}"
        else:
            assert soc.min() >= -SOC_TOL, f"Battery SOC below 0 in {path}"
            assert soc.max() <= 1.0 + SOC_TOL, f"Battery SOC above 1 in {path}"
