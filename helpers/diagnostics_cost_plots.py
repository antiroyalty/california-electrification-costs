from __future__ import annotations

import base64
import io
import os
from typing import Optional

import pandas as pd

from evaluations.eac import crf
from evaluations.incentives import apply_pv_storage_incentives
from helpers.diagnostics_data import (
    compute_npv_details,
    read_coopt_capacities,
    read_total_annual_cost,
)


def _fig_to_b64(fig) -> str:
    import matplotlib.pyplot as plt

    try:
        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=150, bbox_inches="tight")
        return base64.b64encode(buf.getvalue()).decode("utf-8")
    finally:
        plt.close(fig)


def _pv_storage_net_breakdown(
    base_input_dir: str,
    scenario: str,
    housing_type: str,
    county_slug: str,
    *,
    incentive: str = "full_incentives",
) -> Optional[dict]:
    cap_dir = os.path.join(base_input_dir, "capital_costs")
    fname = f"capital_costs_summary_with_pv_{scenario}_{housing_type.replace('-', '_')}.csv"
    path = os.path.join(cap_dir, fname)
    if not os.path.exists(path):
        return None
    try:
        df = pd.read_csv(path)
        row = df[df["county_slug"].str.lower() == county_slug]
        if row.empty:
            return None
        pv_capex = float(row.iloc[0].get("pv_capex", 0.0))
        st_capex = float(row.iloc[0].get("storage_capex", 0.0))
        pv_inc = float(row.iloc[0].get("pv_incentives_full", 0.0)) if "pv_incentives_full" in row.columns else 0.0
        st_inc = float(row.iloc[0].get("storage_incentives_full", 0.0)) if "storage_incentives_full" in row.columns else 0.0
        pv_net, st_net = apply_pv_storage_incentives(
            pv_capex, st_capex, pv_incentives_full=pv_inc, storage_incentives_full=st_inc, incentive=incentive
        )
        return {
            "pv_net": float(pv_net),
            "storage_net": float(st_net),
        }
    except Exception:
        return None


def estimate_storage_value_upper_bound(
    base_input_dir: str,
    scenario: str,
    housing_type: str,
    county_slug: str,
    *,
    window_hours: int = 24,
    round_trip_efficiency: float = 0.96,
) -> Optional[float]:
    county_dir = os.path.join(base_input_dir, scenario, housing_type, county_slug)
    dispatch_path = os.path.join(county_dir, f"solar_storage_dispatch_profiles_{county_slug}.csv")
    price_path = os.path.join(county_dir, f"coopt_price_series_{county_slug}.csv")
    if not (os.path.exists(dispatch_path) and os.path.exists(price_path)):
        return None

    df = pd.read_csv(dispatch_path)
    prices = pd.read_csv(price_path)
    if "import_price_usd_per_kwh" not in prices.columns or "export_price_usd_per_kwh" not in prices.columns:
        return None
    if "PV to Grid (kWh)" in df.columns:
        exports = pd.to_numeric(df["PV to Grid (kWh)"], errors="coerce").fillna(0.0).tolist()
    elif "System to Grid" in df.columns:
        exports = pd.to_numeric(df["System to Grid"], errors="coerce").fillna(0.0).tolist()
    else:
        return None

    import_prices = pd.to_numeric(prices["import_price_usd_per_kwh"], errors="coerce").fillna(0.0).tolist()
    export_prices = pd.to_numeric(prices["export_price_usd_per_kwh"], errors="coerce").fillna(0.0).tolist()
    n = min(len(exports), len(import_prices), len(export_prices))
    if n == 0:
        return None

    total_value = 0.0
    for i in range(n):
        export_kwh = float(exports[i])
        if export_kwh <= 0:
            continue
        future = import_prices[i + 1 : i + 1 + window_hours]
        if not future:
            continue
        max_future = max(future)
        delta = max_future - float(export_prices[i])
        if delta > 0:
            total_value += export_kwh * delta * round_trip_efficiency
    return total_value


def create_cost_waterfall_chart(
    base_input_dir: str,
    scenario: str,
    housing_type: str,
    county_slug: str,
    *,
    discount_rate: float = 0.07,
    pv_life_yrs: int = 25,
    storage_life_yrs: int = 15,
    incentive: str = "full_incentives",
) -> Optional[str]:
    scenario_cost = read_total_annual_cost(
        base_input_dir, scenario, housing_type, county_slug, with_solar=False
    )
    scenario_solar_cost = read_total_annual_cost(
        base_input_dir, scenario, housing_type, county_slug, with_solar=True
    )
    net = _pv_storage_net_breakdown(
        base_input_dir, scenario, housing_type, county_slug, incentive=incentive
    )
    if scenario_cost is None or scenario_solar_cost is None or net is None:
        return None

    pv_net = net.get("pv_net", 0.0)
    storage_net = net.get("storage_net", 0.0)
    annualized_capex = pv_net * crf(discount_rate, pv_life_yrs) + storage_net * crf(discount_rate, storage_life_yrs)
    total_with = scenario_solar_cost + annualized_capex

    try:
        import matplotlib.pyplot as plt

        labels = [
            "Annual Bill\n(No Solar)",
            "Annual Bill\n(With Solar)",
            "Annualized PV+Storage\nCapex",
            "Total Annualized\n(With Solar)",
        ]
        values = [scenario_cost, scenario_solar_cost, annualized_capex, total_with]
        colors = ["#666666", "#1f77b4", "#ff7f0e", "#2ca02c"]

        fig, ax = plt.subplots(figsize=(9, 4.8), tight_layout=True)
        ax.bar(range(len(values)), values, color=colors)
        ax.set_xticks(range(len(values)))
        ax.set_xticklabels(labels)
        ax.set_ylabel("Annual Cost ($)")
        ax.set_title("Annual Cost Waterfall (Solar + Storage)")
        return _fig_to_b64(fig)
    except Exception:
        return None


def create_cashflow_chart(
    base_input_dir: str,
    scenario: str,
    housing_type: str,
    county_slug: str,
    *,
    horizon_years: int = 25,
    discount_rate: float = 0.07,
    incentive: str = "full_incentives",
) -> Optional[str]:
    details = compute_npv_details(
        base_input_dir,
        scenario,
        housing_type,
        county_slug,
        horizon_years=horizon_years,
        discount_rate=discount_rate,
        incentive=incentive,
    )
    if not details:
        return None
    solar = details.get("solar_storage", {})
    net_capex = solar.get("net_capex")
    annual_savings = solar.get("annual_savings")
    if net_capex is None or annual_savings is None:
        return None

    years = list(range(0, int(horizon_years) + 1))
    cum = []
    running = -float(net_capex)
    cum.append(running)
    for _t in range(1, len(years)):
        running += float(annual_savings)
        cum.append(running)

    try:
        import matplotlib.pyplot as plt

        fig, ax = plt.subplots(figsize=(9, 4.8), tight_layout=True)
        ax.plot(years, cum, color="#1f77b4", linewidth=2)
        ax.axhline(0, color="#999", linewidth=1, linestyle="--")
        ax.set_xlabel("Year")
        ax.set_ylabel("Cumulative Cashflow ($)")
        ax.set_title("Cumulative Cashflow — Solar + Storage")
        return _fig_to_b64(fig)
    except Exception:
        return None


def create_storage_value_vs_cost_chart(
    base_input_dir: str,
    scenario: str,
    housing_type: str,
    county_slug: str,
    *,
    discount_rate: float = 0.07,
    storage_life_yrs: int = 15,
    batt_capex_per_kwh: float = 800.0,
    batt_capex_per_kw: float = 0.0,
) -> Optional[str]:
    storage_value = estimate_storage_value_upper_bound(
        base_input_dir, scenario, housing_type, county_slug
    )
    caps = read_coopt_capacities(base_input_dir, scenario, housing_type, county_slug)
    if storage_value is None or not caps:
        return None
    batt_kwh = caps.get("battery_kwh") or 0.0
    batt_kw = caps.get("battery_kw") or 0.0
    annualized_cost = (float(batt_kwh) * batt_capex_per_kwh + float(batt_kw) * batt_capex_per_kw) * crf(
        discount_rate, storage_life_yrs
    )

    try:
        import matplotlib.pyplot as plt

        labels = ["Storage Value\n(Upper Bound)", "Annualized Battery\nCost (Assumed)"]
        values = [float(storage_value), float(annualized_cost)]
        colors = ["#2ca02c", "#d62728"]
        fig, ax = plt.subplots(figsize=(7, 4.5), tight_layout=True)
        ax.bar(labels, values, color=colors)
        ax.set_ylabel("Annual $")
        ax.set_title("Storage Value vs Annualized Cost")
        return _fig_to_b64(fig)
    except Exception:
        return None


def create_price_signal_overlay_chart(
    base_input_dir: str,
    scenario: str,
    housing_type: str,
    county_slug: str,
) -> Optional[str]:
    county_dir = os.path.join(base_input_dir, scenario, housing_type, county_slug)
    price_path = os.path.join(county_dir, f"coopt_price_series_{county_slug}.csv")
    dispatch_path = os.path.join(county_dir, f"solar_storage_dispatch_profiles_{county_slug}.csv")
    if not (os.path.exists(price_path) and os.path.exists(dispatch_path)):
        return None

    prices = pd.read_csv(price_path)
    df = pd.read_csv(dispatch_path)
    if "import_price_usd_per_kwh" not in prices.columns or "export_price_usd_per_kwh" not in prices.columns:
        return None
    if "PV to Grid (kWh)" in df.columns:
        pv_to_grid = pd.to_numeric(df["PV to Grid (kWh)"], errors="coerce").fillna(0.0)
    elif "System to Grid" in df.columns:
        pv_to_grid = pd.to_numeric(df["System to Grid"], errors="coerce").fillna(0.0)
    else:
        return None

    import_prices = pd.to_numeric(prices["import_price_usd_per_kwh"], errors="coerce").fillna(0.0)
    export_prices = pd.to_numeric(prices["export_price_usd_per_kwh"], errors="coerce").fillna(0.0)
    n = min(len(import_prices), len(export_prices), len(pv_to_grid))
    if n == 0:
        return None

    export_mask = pv_to_grid.iloc[:n] > 0
    if not export_mask.any():
        return None

    import_series = import_prices.iloc[:n].reset_index(drop=True)
    export_series = export_prices.iloc[:n].reset_index(drop=True)

    hours = pd.Series(range(n)) % 24
    export_hours = hours[export_mask.values]
    df_exp = pd.DataFrame(
        {
            "hour": export_hours,
            "import_price": import_series[export_mask.values].values,
            "export_price": export_series[export_mask.values].values,
        }
    )
    hourly = df_exp.groupby("hour").mean()
    counts = df_exp.groupby("hour").size()

    try:
        import matplotlib.pyplot as plt

        fig, ax = plt.subplots(figsize=(9, 4.8), tight_layout=True)
        ax.plot(hourly.index, hourly["import_price"], label="Import ($/kWh)", color="#1f77b4")
        ax.plot(hourly.index, hourly["export_price"], label="Export ($/kWh)", color="#ff7f0e")
        ax.set_xlabel("Hour of Day (export hours only)")
        ax.set_ylabel("Avg Price ($/kWh)")
        ax.set_title("Price Signals During PV Export Hours")
        ax.legend(loc="upper left")

        ax2 = ax.twinx()
        ax2.bar(counts.index, counts.values, alpha=0.2, color="#888", label="Export Hours")
        ax2.set_ylabel("Export Hours")
        return _fig_to_b64(fig)
    except Exception:
        return None
