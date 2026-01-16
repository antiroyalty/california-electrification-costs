import os
from typing import Optional

import pandas as pd

from evaluations.incentives import apply_pv_storage_incentives
from evaluations.npv import compute_npv_details_from_inputs
from helpers.maps_helpers import get_latest_csv_file


def read_total_annual_cost(
    base_input_dir: str,
    scenario: str,
    housing_type: str,
    county_slug: str,
    *,
    with_solar: bool = False,
) -> Optional[float]:
    if with_solar:
        results_dir = os.path.join(base_input_dir, scenario, housing_type, county_slug, "results", "solarstorage")
        row_name = f"{scenario}.solarstorage"
    else:
        results_dir = os.path.join(base_input_dir, scenario, housing_type, county_slug, "results", "totals")
        row_name = scenario
    if not os.path.isdir(results_dir):
        return None
    try:
        path = get_latest_csv_file(results_dir, f"RESULTS_total_annual_costs_{county_slug}_")
        df = pd.read_csv(path, index_col="scenario")
        if row_name not in df.index:
            return None
        row = df.loc[row_name]
        vals = pd.to_numeric(row, errors="coerce").dropna()
        if vals.empty:
            return None
        return float(vals.iloc[0])
    except Exception:
        return None


def pv_storage_net_capex(
    base_input_dir: str,
    scenario: str,
    housing_type: str,
    county_slug: str,
    *,
    incentive: str = "full_incentives",
) -> Optional[float]:
    cap_dir = os.path.join(base_input_dir, "capital_costs")
    fname = f"capital_costs_summary_with_pv_{scenario}_{housing_type.replace('-', '_')}.csv"
    path = os.path.join(cap_dir, fname)
    if not os.path.exists(path):
        return None
    try:
        df = pd.read_csv(path)
        if df.empty or "county_slug" not in df.columns:
            return None
        row = df[df["county_slug"].str.lower() == county_slug]
        if row.empty:
            return None
        pv_capex = float(row.iloc[0].get("pv_capex", 0.0))
        st_capex = float(row.iloc[0].get("storage_capex", 0.0))
        pv_inc_full = float(row.iloc[0].get("pv_incentives_full", 0.0))
        st_inc_full = float(row.iloc[0].get("storage_incentives_full", 0.0))
        pv_net, st_net = apply_pv_storage_incentives(
            pv_capex,
            st_capex,
            pv_incentives_full=pv_inc_full,
            storage_incentives_full=st_inc_full,
            incentive=incentive,
        )
        return float(pv_net + st_net)
    except Exception:
        return None


def electrification_net_capex(
    base_input_dir: str,
    scenario: str,
    housing_type: str,
    county_slug: str,
    *,
    incentive: str = "full_incentives",
) -> Optional[float]:
    cap_dir = os.path.join(base_input_dir, "capital_costs")
    fname = f"capital_costs_{scenario}_{housing_type.replace('-', '_')}.csv"
    path = os.path.join(cap_dir, fname)
    if not os.path.exists(path):
        return None
    try:
        df = pd.read_csv(path)
        if df.empty:
            return None
        if "county_slug" not in df.columns or "net_cost" not in df.columns:
            return None
        sub = df[df["county_slug"].str.lower() == county_slug]
        if "incentive_scenario" in sub.columns:
            sub["incentive_scenario"] = sub["incentive_scenario"].str.lower()
            sub = sub[sub["incentive_scenario"] == (incentive or "").lower()]
        if sub.empty:
            return None
        if "appliance_category" in sub.columns:
            sub = sub[sub["appliance_category"] == "electric"]
        if "appliance_type" in sub.columns:
            sub = sub[~sub["appliance_type"].isin(["solar", "storage"])]
        if sub.empty:
            return None
        vals = pd.to_numeric(sub["net_cost"], errors="coerce").dropna()
        if vals.empty:
            return None
        return float(vals.sum())
    except Exception:
        return None


def compute_npv_details(
    base_input_dir: str,
    scenario: str,
    housing_type: str,
    county_slug: str,
    *,
    horizon_years: int = 25,
    discount_rate: float = 0.07,
    incentive: str = "full_incentives",
) -> Optional[dict]:
    baseline_cost = read_total_annual_cost(
        base_input_dir, "baseline", housing_type, county_slug, with_solar=False
    )
    scenario_cost = read_total_annual_cost(
        base_input_dir, scenario, housing_type, county_slug, with_solar=False
    )
    scenario_solar_cost = read_total_annual_cost(
        base_input_dir, scenario, housing_type, county_slug, with_solar=True
    )
    if baseline_cost is None or scenario_cost is None or scenario_solar_cost is None:
        return None

    pv_storage_net = pv_storage_net_capex(
        base_input_dir, scenario, housing_type, county_slug, incentive=incentive
    )
    electrification_net = electrification_net_capex(
        base_input_dir, scenario, housing_type, county_slug, incentive=incentive
    )
    if pv_storage_net is None:
        return None

    try:
        return compute_npv_details_from_inputs(
            baseline_cost=baseline_cost,
            scenario_cost=scenario_cost,
            scenario_solar_cost=scenario_solar_cost,
            pv_storage_net_capex=pv_storage_net,
            electrification_net_capex=electrification_net,
            horizon_years=horizon_years,
            discount_rate=discount_rate,
        )
    except Exception:
        return None
