"""
Step 22: Build County Diagnostics

Creates per-county diagnostic dashboards that assemble:
- Solar + storage deployment graph (from Step 9 outputs)
- Appliance breakdown pie chart (moved from Step 16)
- Weekly SAM charts for January and July (separate panels)
- Cross‑scenario cards from Step 18 (EAC stacked bar, kWh flows, Savings & Bills, Payback, PV size)

Outputs are saved under analysis_results/county_diagnostics/<scenario>/.

Usage (module):
  from step22_build_county_diagnostics import process
  process(
      base_input_dir="data/loadprofiles",
      output_dir="analysis_results",
      housing_type="single-family-detached",
      scenario="baseline",
      counties=["alameda", "los-angeles"],
  )

Also supports CLI invocation similar to other steps.
"""

from __future__ import annotations

import argparse
import base64
import io
import os
from typing import Iterable, List, Optional, Tuple

import pandas as pd

from helpers.main_helpers import (
    get_scenario_path,
    git_short_sha,
    slugify_county_name,
)


# ---------- Appliance breakdown (moved from Step 16) ----------

import matplotlib.pyplot as plt


def load_appliance_breakdown_data(
    base_input_dir: str,
    scenario: str,
    housing_type: str,
    county_slug: str,
) -> dict:
    """
    Load appliance breakdown data by end-use category with proper time series handling.

    IMPORTANT: Only loads ELECTRIFIED end-uses for pie charts:
    - For baseline: Shows only electricity end-uses (lighting, appliances, cooling, etc.) - NO gas appliances
    - For electrified scenarios: Shows electricity end-uses + electrified appliances (Heat Pump, Induction, etc.)

    Returns dictionary with appliance categories and their annual kWh consumption.
    """
    import os

    appliance_data: dict[str, float] = {}

    electricity_categories = {
        "Cooling": ["ceiling_fan"],
        "Appliances": ["clothes_dryer", "dishwasher", "freezer", "refrigerator"],
        "Lighting": ["lighting_garage", "lighting_interior"],
        "Plug Loads": ["plug_loads"],
        "Pool/Spa": ["permanent_spa_heat", "permanent_spa_pump", "pool_heater", "pool_pump"],
        "Other Electric": ["mech_vent"],
    }

    # For electricity loads, ALWAYS use baseline data (individual appliance breakdown only exists in baseline)
    baseline_electricity_dir = os.path.join(base_input_dir, "baseline", housing_type, county_slug)
    electricity_file = os.path.join(baseline_electricity_dir, f"electricity_loads_{county_slug}.csv")

    if os.path.exists(electricity_file):
        try:
            df = pd.read_csv(electricity_file, parse_dates=["timestamp"]).set_index("timestamp")
            for category, appliances in electricity_categories.items():
                series = pd.Series(0.0, index=df.index)
                for appliance in appliances:
                    col = f"out.electricity.{appliance}.energy_consumption"
                    if col in df.columns:
                        series = series.add(df[col], fill_value=0.0)
                if float(series.sum()) > 0:
                    appliance_data[category] = float(series.sum())
        except Exception as e:
            print(f"Warning: Error reading baseline electricity loads for {county_slug}: {e}")
    else:
        print(f"Warning: Baseline electricity loads file not found: {electricity_file}")

    # For pie charts: exclude gas appliances; focus on electrified end-uses
    print(
        f"Note: Excluding gas appliances from pie chart for {scenario} - showing only electrified end-uses"
    )

    # Load simulated electric appliances for electrified scenarios
    if not scenario.startswith("baseline"):
        scen_dir = os.path.join(base_input_dir, scenario, housing_type, county_slug)
        simulated_file = os.path.join(scen_dir, f"electricity_loads_simulated_{county_slug}.csv")
        if not os.path.exists(simulated_file):
            scen_dir = os.path.join(base_input_dir, "baseline", housing_type, county_slug)
            simulated_file = os.path.join(scen_dir, f"electricity_loads_simulated_{county_slug}.csv")
        if os.path.exists(simulated_file):
            try:
                df = pd.read_csv(simulated_file, parse_dates=["timestamp"]).set_index("timestamp")
                df = df.resample("H").sum()  # resample 15‑min to hourly
                sim_map = {
                    "Heat Pump": "simulated.electricity.heat_pump.energy_consumption.electricity.kwh",
                    "Induction Cooking": "simulated.electricity.induction_stove.energy_consumption.electricity.kwh",
                    "Electric Hot Water": "simulated.electricity.hot_water.energy_consumption.electricity.kwh",
                }
                for label, col in sim_map.items():
                    if col in df.columns:
                        val = float(df[col].sum())
                        if val > 0:
                            if (
                                label == "Heat Pump"
                                and scenario
                                in [
                                    "heat_pump",
                                    "heat_pump_and_induction_stove",
                                    "heat_pump_and_induction_stove_and_water_heating",
                                    "full_electric_ev",
                                ]
                            ):
                                appliance_data["Heat Pump"] = val
                            elif (
                                label == "Induction Cooking"
                                and scenario
                                in [
                                    "induction_stove",
                                    "heat_pump_and_induction_stove",
                                    "heat_pump_and_induction_stove_and_water_heating",
                                    "full_electric_ev",
                                ]
                            ):
                                appliance_data["Induction Cooking"] = val
                            elif (
                                label == "Electric Hot Water"
                                and scenario in [
                                    "water_heating",
                                    "heat_pump_and_induction_stove_and_water_heating",
                                    "full_electric_ev",
                                ]
                            ):
                                appliance_data["Electric Hot Water"] = val
            except Exception as e:
                print(f"Warning: Error reading simulated loads for {county_slug}: {e}")

    if not appliance_data:
        print(f"Warning: No appliance data found for {county_slug}. Using placeholder data.")
        appliance_data = {"Data Not Available": 1.0}

    return appliance_data


def create_appliance_breakdown_chart(
    base_input_dir: str,
    scenario: str,
    housing_type: str,
    county_slug: str,
) -> str:
    """
    Create a pie chart showing appliance breakdown by end‑use category.
    Returns base64 encoded PNG image string or HTML table if matplotlib is unavailable.
    """
    import io

    data = load_appliance_breakdown_data(base_input_dir, scenario, housing_type, county_slug)
    try:
        if not data or "Data Not Available" in data:
            fig, ax = plt.subplots(figsize=(8, 6))
            ax.text(
                0.5,
                0.5,
                "No appliance data available",
                ha="center",
                va="center",
                fontsize=14,
            )
            ax.set_xlim(0, 1)
            ax.set_ylim(0, 1)
            ax.axis("off")
        else:
            fig, ax = plt.subplots(figsize=(10, 8))
            categories = list(data.keys())
            values = list(data.values())
            color_map = {
                "Heating": "#FF6B6B",
                "Heat Pump": "#FF8E53",
                "Cooling": "#4ECDC4",
                "Hot Water": "#45B7D1",
                "Electric Hot Water": "#96CEB4",
                "Cooking": "#FFEAA7",
                "Induction Cooking": "#DDA0DD",
                "Appliances": "#FD79A8",
                "Lighting": "#FDCB6E",
                "Plug Loads": "#6C5CE7",
                "Pool/Spa": "#00B894",
                "Other Electric": "#A29BFE",
                "Other Gas": "#E17055",
            }
            colors = [color_map.get(cat, "#BDC3C7") for cat in categories]
            wedges, texts, autotexts = ax.pie(
                values,
                labels=categories,
                colors=colors,
                autopct="%1.1f%%",
                startangle=90,
                textprops={"fontsize": 10},
            )
            for autotext in autotexts:
                autotext.set_color("white")
                autotext.set_fontweight("bold")
            county_name = county_slug.replace("-", " ").title()
            scenario_name = scenario.replace("_", " ").title()
            ax.set_title(
                f"Annual Electricity Consumption by End‑Use\n{county_name} County - {scenario_name} Scenario\n(Electrified End‑Uses Only)",
                fontsize=14,
                fontweight="bold",
                pad=20,
            )
            total_kwh = sum(values)
            ax.text(
                0,
                -1.3,
                f"Total: {total_kwh:,.0f} kWh/year",
                ha="center",
                fontsize=12,
                fontweight="bold",
            )

        buf = io.BytesIO()
        plt.tight_layout()
        plt.savefig(buf, format="png", dpi=150, bbox_inches="tight")
        buf.seek(0)
        image_b64 = base64.b64encode(buf.getvalue()).decode()
        plt.close()
        return image_b64
    except Exception as e:
        print(f"Error creating appliance breakdown chart for {county_slug}: {e}")
        # simple text placeholder as base64 PNG
        fig, ax = plt.subplots(figsize=(6, 4))
        ax.text(0.5, 0.5, "Chart unavailable", ha="center", va="center")
        ax.axis("off")
        buf = io.BytesIO()
        plt.savefig(buf, format="png", dpi=120, bbox_inches="tight")
        buf.seek(0)
        image_b64 = base64.b64encode(buf.getvalue()).decode()
        plt.close()
        return image_b64


# ---------- Solar + storage deployment figure (from Step 9 outputs) ----------


def _find_latest_step9_png(county_dir: str) -> Optional[str]:
    if not os.path.isdir(county_dir):
        return None
    candidates = [
        f
        for f in os.listdir(county_dir)
        if f.startswith("step9_my_own_solar_storage_plots_") and f.endswith(".png")
    ]
    if not candidates:
        return None
    # choose newest by mtime
    candidates.sort(key=lambda n: os.path.getmtime(os.path.join(county_dir, n)), reverse=True)
    return os.path.join(county_dir, candidates[0])


def _read_step9_series(path: str) -> Optional[dict]:
    try:
        # Prefer the enriched CSV written by Step 9
        df = pd.read_csv(path)
        cols = df.columns
        required = [
            "Load Profile",
            "Battery to Load",
            "Grid to Load",
        ]
        if not all(c in cols for c in required):
            return None
        series = {
            "load": df["Load Profile"].astype(float).tolist(),
            "batt_to_load": df.get("Battery to Load", pd.Series([0] * len(df))).astype(float).tolist(),
            "grid_to_load": df.get("Grid to Load", pd.Series([0] * len(df))).astype(float).tolist(),
            # PV AC is optional; if missing, approximate from System to Load + System to Battery
            "pv_ac": df.get("PV AC (kWh)", None),
            "pv_to_batt": df.get("System to Battery", None),
            "grid_to_batt": df.get("Grid to Battery", None),
            "soc": df.get("Battery SOC", None),
        }
        if series["pv_ac"] is None:
            pv_ac = df.get("System to Load", pd.Series([0] * len(df))).astype(float) + df.get(
                "System to Battery", pd.Series([0] * len(df))
            ).astype(float)
            series["pv_ac"] = pv_ac.tolist()
        else:
            series["pv_ac"] = pd.to_numeric(series["pv_ac"], errors="coerce").fillna(0.0).tolist()
        # Normalize optional series to lists
        for key in ("pv_to_batt", "grid_to_batt", "soc"):
            if isinstance(series[key], pd.Series):
                series[key] = pd.to_numeric(series[key], errors="coerce").fillna(0.0).tolist()
            elif series[key] is None:
                series[key] = [0.0] * 8760
        return series
    except Exception as e:
        print(f"Warning: could not read Step 9 CSV for deployment figure: {e}")
        return None


def create_solar_storage_deployment_graph(
    base_input_dir: str,
    scenario: str,
    housing_type: str,
    county_slug: str,
) -> Optional[str]:
    """
    Return a base64 PNG of the solar + storage deployment graph for the county.
    If a Step 9 PNG exists, embed it. Otherwise reconstruct from the Step 9 CSV.
    """
    county_dir = os.path.join(base_input_dir, scenario, housing_type, county_slug)
    png = _find_latest_step9_png(county_dir)
    if png and os.path.exists(png):
        try:
            with open(png, "rb") as f:
                return base64.b64encode(f.read()).decode()
        except Exception as e:
            print(f"Warning: could not embed Step 9 PNG for {county_slug}: {e}")

    # Fallback: load time series and plot using helper
    csv_path = os.path.join(county_dir, f"sam_optimized_load_profiles_{county_slug}.csv")
    if not os.path.exists(csv_path):
        # Older naming variant
        csv_path = os.path.join(county_dir, f"sam_optimized_load_profiles_{scenario}_{county_slug}.csv")
    if not os.path.exists(csv_path):
        print(f"Warning: Step 9 CSV not found for {county_slug}")
        return None

    series = _read_step9_series(csv_path)
    if not series:
        return None

    # Use the dedicated plotting helper from Step 9
    try:
        from helpers.step9_plotting_helper import plot_first_weeks

        fig, _ = plot_first_weeks(
            load_kwh=series["load"],
            pv_ac_kwh=series["pv_ac"],
            batt_to_load_kwh=series["batt_to_load"],
            grid_to_load_kwh=series["grid_to_load"],
            grid_to_batt_kwh=series.get("grid_to_batt"),
            pv_to_batt_kwh=series.get("pv_to_batt"),
            soc_percent=series.get("soc"),
            pv_used_kwh=None,
            summary_stats=None,
            title=f"DIY Dispatch — {scenario} — {county_slug.replace('-', ' ').title()}",
            show=False,
            save_path=None,
        )
        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=140, bbox_inches="tight")
        buf.seek(0)
        img_b64 = base64.b64encode(buf.getvalue()).decode()
        plt.close(fig)
        return img_b64
    except Exception as e:
        print(f"Warning: Could not reconstruct deployment graph for {county_slug}: {e}")
        return None


# ---------- New metric cards ----------

def create_solar_size_card(
    base_input_dir: str,
    scenario: str,
    housing_type: str,
    county_slug: str,
) -> str:
    """Create a simple text card showing solar system size in kW."""
    try:
        county_dir = os.path.join(base_input_dir, scenario, housing_type, county_slug)
        sam_file = os.path.join(county_dir, f"sam_optimized_load_profiles_{county_slug}.csv")
        
        if not os.path.exists(sam_file):
            return "<div class='metric-value'>N/A<br><small>No data available</small></div>"
            
        df = pd.read_csv(sam_file, nrows=1)  # Only need first row
        
        # Look for PV system size column
        size_col = None
        for col in df.columns:
            if 'pv' in col.lower() and any(x in col.lower() for x in ['size', 'capacity', 'system']):
                size_col = col
                break
        
        if size_col and not df[size_col].isna().all():
            size_kw = float(df[size_col].iloc[0])
            return f"<div class='metric-value'>{size_kw:.1f} kW<br><small>System Size</small></div>"
        else:
            return "<div class='metric-value'>N/A<br><small>No PV system</small></div>"
            
    except Exception as e:
        print(f"Warning: Error getting solar size for {county_slug}: {e}")
        return "<div class='metric-value'>N/A<br><small>Error loading data</small></div>"


def create_annual_load_card(
    base_input_dir: str,
    scenario: str,
    housing_type: str,
    county_slug: str,
) -> str:
    """Create a simple text card showing total annual household load in kWh."""
    try:
        county_dir = os.path.join(base_input_dir, scenario, housing_type, county_slug)
        sam_file = os.path.join(county_dir, f"sam_optimized_load_profiles_{county_slug}.csv")
        
        if not os.path.exists(sam_file):
            return "<div class='metric-value'>N/A<br><small>No data available</small></div>"
            
        df = pd.read_csv(sam_file)
        
        # Look for household load column
        load_col = None
        for col in df.columns:
            if any(x in col.lower() for x in ['household_load', 'load', 'demand']):
                load_col = col
                break
                
        if load_col and not df[load_col].isna().all():
            annual_kwh = float(df[load_col].sum())
            return f"<div class='metric-value'>{annual_kwh:,.0f} kWh<br><small>Annual Household Load</small></div>"
        else:
            return "<div class='metric-value'>N/A<br><small>No load data</small></div>"
            
    except Exception as e:
        print(f"Warning: Error getting annual load for {county_slug}: {e}")
        return "<div class='metric-value'>N/A<br><small>Error loading data</small></div>"


def create_grid_supply_card(
    base_input_dir: str,
    scenario: str,
    housing_type: str,
    county_slug: str,
) -> str:
    """Create a simple text card showing annual load supplied by grid in kWh."""
    try:
        county_dir = os.path.join(base_input_dir, scenario, housing_type, county_slug)
        sam_file = os.path.join(county_dir, f"sam_optimized_load_profiles_{county_slug}.csv")
        
        if not os.path.exists(sam_file):
            return "<div class='metric-value'>N/A<br><small>No data available</small></div>"
            
        df = pd.read_csv(sam_file)
        
        # Look for grid supply column
        grid_col = None
        for col in df.columns:
            if 'grid' in col.lower() and any(x in col.lower() for x in ['load', 'supply', 'to_load']):
                grid_col = col
                break
                
        if grid_col and not df[grid_col].isna().all():
            annual_grid_kwh = float(df[grid_col].sum())
            return f"<div class='metric-value'>{annual_grid_kwh:,.0f} kWh<br><small>Grid Supply to Load</small></div>"
        else:
            return "<div class='metric-value'>N/A<br><small>No grid data</small></div>"
            
    except Exception as e:
        print(f"Warning: Error getting grid supply for {county_slug}: {e}")
        return "<div class='metric-value'>N/A<br><small>Error loading data</small></div>"


# ---------- Weekly SAM and Battery SOC charts (moved from Step 16) ----------


def load_sam_weekly_data(
    base_input_dir: str,
    scenario: str,
    housing_type: str,
    county_slug: str,
    metric_columns: list,
) -> Optional[pd.DataFrame]:
    county_dir = os.path.join(base_input_dir, scenario, housing_type, county_slug)
    sam_file = os.path.join(county_dir, f"sam_optimized_load_profiles_{county_slug}.csv")
    if not os.path.exists(sam_file):
        print(f"Warning: SAM load profiles file not found: {sam_file}")
        return None
    try:
        df = pd.read_csv(sam_file, parse_dates=[0], index_col=0)
        missing = [c for c in metric_columns if c not in df.columns]
        if missing:
            print(f"Warning: Missing columns in {sam_file}: {missing}")
            print(f"Available columns: {list(df.columns)}")
            return None
        return df[metric_columns]
    except Exception as e:
        print(f"Warning: Error reading SAM load profiles for {county_slug}: {e}")
        return None


def load_battery_soc_data(
    base_input_dir: str,
    scenario: str,
    housing_type: str,
    county_slug: str,
) -> Optional[pd.DataFrame]:
    county_dir = os.path.join(base_input_dir, scenario, housing_type, county_slug)
    sam_file = os.path.join(county_dir, f"sam_optimized_load_profiles_{county_slug}.csv")
    if not os.path.exists(sam_file):
        print(f"Warning: SAM load profiles file not found: {sam_file}")
        return None
    try:
        df = pd.read_csv(sam_file, parse_dates=[0], index_col=0)
        if "Battery SOC" not in df.columns:
            print(f"Warning: Battery SOC column not found in {sam_file}")
            print(f"Available columns: {list(df.columns)}")
            return None
        return df[["Battery SOC"]]
    except Exception as e:
        print(f"Warning: Error reading SAM load profiles for {county_slug}: {e}")
        return None

def create_sam_weekly_chart(
    base_input_dir: str,
    scenario: str,
    housing_type: str,
    county_slug: str,
) -> str:
    """Weekly charts for SAM metrics (load breakdown and solar power) for Jan/Jul; returns base64 PNG."""
    try:
        import matplotlib.dates as mdates
        sam_metrics = ["Load Profile", "System to Load", "Battery to Load", "Grid to Load"]
        solar_metrics = ["System to Load", "System to Battery"]
        all_metrics = list(dict.fromkeys(sam_metrics + solar_metrics))
        sam_df = load_sam_weekly_data(base_input_dir, scenario, housing_type, county_slug, all_metrics)
        if sam_df is None:
            return ""
        fig, axes = plt.subplots(4, 1, figsize=(16, 20))
        fig.suptitle(
            f"SAM Load Profile and Solar Power Analysis - Weekly Comparison\n{county_slug.replace('-', ' ').title()} County - {scenario.replace('_', ' ').title()} Scenario",
            fontsize=16,
            fontweight="bold",
        )
        periods = {"January (Winter)": ("2018-01-01", "2018-01-08"), "July (Summer)": ("2018-07-01", "2018-07-08")}
        colors = {
            "Load Profile": "#2E86AB",
            "System to Load": "#F24236",
            "Battery to Load": "#F6AE2D",
            "Grid to Load": "#2F9599",
            "Solar + Battery to Load": "#F26419",
            "System to Battery": "#8B5A2B",
        }
        for idx, (pname, (start, end)) in enumerate(periods.items()):
            ax_load = axes[idx]
            ax_sol = axes[idx + 2]
            try:
                week = sam_df.loc[start:end]
                if week.empty:
                    for ax in (ax_load, ax_sol):
                        ax.text(0.5, 0.5, f"No data for {pname}", ha="center", va="center", color="red")
                    continue
                # Shade 4–9pm each day
                for d in range(7):
                    day_start = pd.Timestamp(start) + pd.Timedelta(days=d)
                    pk0 = day_start + pd.Timedelta(hours=16)
                    pk1 = day_start + pd.Timedelta(hours=21)
                    ax_load.axvspan(pk0, pk1, color="#d62728", alpha=0.15, zorder=0, label=("Peak TOU (4-9pm)" if d == 0 and idx == 0 else ""))
                    ax_sol.axvspan(pk0, pk1, color="#d62728", alpha=0.15, zorder=0)
                for m in sam_metrics:
                    ax_load.plot(week.index, week[m], linewidth=2, label=m, color=colors.get(m, "#333"), alpha=0.8)
                for m in ["System to Load", "System to Battery"]:
                    ax_sol.plot(week.index, week[m], linewidth=2, label=m, color=colors.get(m, "#333"), alpha=0.8)
                total_solar = week["System to Load"] + week["System to Battery"]
                ax_sol.plot(week.index, total_solar, linewidth=2, label="Total Solar Generation", color="#FF6B35", alpha=0.8, linestyle="--")
                ax_load.set_ylabel("Power (kW)", fontsize=12)
                ax_load.set_title(f"{pname} - Load Profile Breakdown", fontsize=14, fontweight="bold")
                ax_load.grid(True, alpha=0.3)
                ax_load.legend(loc="upper right", fontsize=10)
                ax_sol.set_ylabel("Solar Power (kW)", fontsize=12)
                ax_sol.set_title(f"{pname} - Solar Power Profile", fontsize=14, fontweight="bold")
                ax_sol.grid(True, alpha=0.3)
                ax_sol.legend(loc="upper right", fontsize=10)
                for ax in (ax_load, ax_sol):
                    ax.xaxis.set_major_locator(mdates.DayLocator())
                    ax.xaxis.set_major_formatter(mdates.DateFormatter("%m/%d"))
                    ax.xaxis.set_minor_locator(mdates.HourLocator(interval=6))
                    plt.setp(ax.xaxis.get_majorticklabels(), rotation=45, ha="right")
                load_max = week["Load Profile"].max()
                solar_avg = week["System to Load"].mean()
                battery_total = week["Battery to Load"].sum()
                ax_load.text(
                    0.02,
                    0.98,
                    f"Week Summary:\nPeak Load: {load_max:.2f} kW\nAvg Solar to Load: {solar_avg:.2f} kW\nBattery Discharge: {battery_total:.1f} kWh",
                    transform=ax_load.transAxes,
                    fontsize=9,
                    va="top",
                    bbox=dict(boxstyle="round", facecolor="white", alpha=0.9),
                )
                solar_to_load_avg = week["System to Load"].mean()
                solar_to_batt_avg = week["System to Battery"].mean()
                total_solar_avg = total_solar.mean()
                solar_peak = total_solar.max()
                ax_sol.text(
                    0.02,
                    0.98,
                    f"Solar Summary:\nPeak Generation: {solar_peak:.2f} kW\nAvg Total Solar: {total_solar_avg:.2f} kW\nAvg to Load: {solar_to_load_avg:.2f} kW\nAvg to Battery: {solar_to_batt_avg:.2f} kW",
                    transform=ax_sol.transAxes,
                    fontsize=9,
                    va="top",
                    bbox=dict(boxstyle="round", facecolor="white", alpha=0.9),
                )
            except Exception as e:
                print(f"Error plotting {pname}: {e}")
                ax_load.text(0.5, 0.5, f"Error loading\n{pname} data", ha="center", va="center", color="red")
                ax_sol.text(0.5, 0.5, f"Error loading\n{pname} data", ha="center", va="center", color="red")
        fig.text(
            0.5,
            0.02,
            "Top: Load breakdown | Bottom: Solar breakdown",
            ha="center",
            fontsize=10,
            style="italic",
        )
        plt.tight_layout()
        plt.subplots_adjust(top=0.92, bottom=0.10)
        buf = io.BytesIO()
        plt.savefig(buf, format="png", dpi=150, bbox_inches="tight")
        buf.seek(0)
        b64 = base64.b64encode(buf.getvalue()).decode()
        plt.close()
        return b64
    except Exception as e:
        print(f"Error creating SAM weekly chart: {e}")
        fig, ax = plt.subplots(figsize=(6, 4))
        ax.text(0.5, 0.5, "SAM chart unavailable", ha="center", va="center")
        ax.axis("off")
        buf = io.BytesIO()
        plt.savefig(buf, format="png", dpi=120, bbox_inches="tight")
        buf.seek(0)
        b64 = base64.b64encode(buf.getvalue()).decode()
        plt.close()
        return b64


def create_sam_weekly_chart_for_period(
    base_input_dir: str,
    scenario: str,
    housing_type: str,
    county_slug: str,
    *,
    period: str = "january",
) -> str:
    """Weekly charts for a single period (Jan or Jul): two stacked subplots (load and solar)."""
    try:
        import matplotlib.dates as mdates
        sam_metrics = ["Load Profile", "System to Load", "Battery to Load", "Grid to Load"]
        solar_metrics = ["System to Load", "System to Battery"]
        all_metrics = list(dict.fromkeys(sam_metrics + solar_metrics))
        sam_df = load_sam_weekly_data(base_input_dir, scenario, housing_type, county_slug, all_metrics)
        if sam_df is None:
            return ""
        periods = {
            "january": ("January (Winter)", ("2018-01-01", "2018-01-08")),
            "july": ("July (Summer)", ("2018-07-01", "2018-07-08")),
        }
        key = period.lower()
        if key not in periods:
            key = "january"
        title_suffix, (start, end) = periods[key]
        fig, (ax_load, ax_sol) = plt.subplots(2, 1, figsize=(16, 10))
        fig.suptitle(
            f"SAM Load & Solar — {title_suffix}\n{county_slug.replace('-', ' ').title()} County — {scenario.replace('_', ' ').title()} Scenario",
            fontsize=16,
            fontweight="bold",
        )
        colors = {
            "Load Profile": "#2E86AB",
            "System to Load": "#F24236",
            "Battery to Load": "#F6AE2D",
            "Grid to Load": "#2F9599",
            "Solar + Battery to Load": "#F26419",
            "System to Battery": "#8B5A2B",
        }
        week = sam_df.loc[start:end]
        if week.empty:
            for ax in (ax_load, ax_sol):
                ax.text(0.5, 0.5, f"No data for {title_suffix}", ha="center", va="center", color="red")
            buf = io.BytesIO()
            plt.tight_layout()
            plt.savefig(buf, format="png", dpi=150, bbox_inches="tight")
            buf.seek(0)
            out = base64.b64encode(buf.getvalue()).decode()
            plt.close()
            return out
        # Shade 4–9pm each day
        for d in range(7):
            day_start = pd.Timestamp(start) + pd.Timedelta(days=d)
            pk0 = day_start + pd.Timedelta(hours=16)
            pk1 = day_start + pd.Timedelta(hours=21)
            ax_load.axvspan(pk0, pk1, color="#d62728", alpha=0.15, zorder=0)
            ax_sol.axvspan(pk0, pk1, color="#d62728", alpha=0.15, zorder=0)
        for m in sam_metrics:
            ax_load.plot(week.index, week[m], linewidth=2, label=m, color=colors.get(m, "#333"), alpha=0.8)
        for m in ["System to Load", "System to Battery"]:
            ax_sol.plot(week.index, week[m], linewidth=2, label=m, color=colors.get(m, "#333"), alpha=0.8)
        total_solar = week["System to Load"] + week["System to Battery"]
        ax_sol.plot(week.index, total_solar, linewidth=2, label="Total Solar Generation", color="#FF6B35", alpha=0.8, linestyle="--")
        ax_load.set_ylabel("Power (kW)", fontsize=12)
        ax_load.set_title(f"{title_suffix} — Load Profile Breakdown", fontsize=14, fontweight="bold")
        ax_load.grid(True, alpha=0.3)
        ax_load.legend(loc="upper right", fontsize=10)
        ax_sol.set_ylabel("Solar Power (kW)", fontsize=12)
        ax_sol.set_title(f"{title_suffix} — Solar Power Profile", fontsize=14, fontweight="bold")
        ax_sol.grid(True, alpha=0.3)
        ax_sol.legend(loc="upper right", fontsize=10)
        for ax in (ax_load, ax_sol):
            ax.xaxis.set_major_locator(mdates.DayLocator())
            ax.xaxis.set_major_formatter(mdates.DateFormatter("%m/%d"))
            ax.xaxis.set_minor_locator(mdates.HourLocator(interval=6))
            plt.setp(ax.xaxis.get_majorticklabels(), rotation=45, ha="right")
        load_max = week["Load Profile"].max()
        solar_avg = week["System to Load"].mean()
        battery_total = week["Battery to Load"].sum()
        ax_load.text(
            0.02,
            0.98,
            f"Week Summary:\nPeak Load: {load_max:.2f} kW\nAvg Solar to Load: {solar_avg:.2f} kW\nBattery Discharge: {battery_total:.1f} kWh",
            transform=ax_load.transAxes,
            fontsize=9,
            va="top",
            bbox=dict(boxstyle="round", facecolor="white", alpha=0.9),
        )
        solar_to_load_avg = week["System to Load"].mean()
        solar_to_batt_avg = week["System to Battery"].mean()
        total_solar_avg = total_solar.mean()
        solar_peak = total_solar.max()
        ax_sol.text(
            0.02,
            0.98,
            f"Solar Summary:\nPeak Generation: {solar_peak:.2f} kW\nAvg Total Solar: {total_solar_avg:.2f} kW\nAvg to Load: {solar_to_load_avg:.2f} kW\nAvg to Battery: {solar_to_batt_avg:.2f} kW",
            transform=ax_sol.transAxes,
            fontsize=9,
            va="top",
            bbox=dict(boxstyle="round", facecolor="white", alpha=0.9),
        )
        plt.tight_layout()
        buf = io.BytesIO()
        plt.savefig(buf, format="png", dpi=150, bbox_inches="tight")
        buf.seek(0)
        out = base64.b64encode(buf.getvalue()).decode()
        plt.close()
        return out
    except Exception as e:
        print(f"Error creating SAM weekly single-period chart: {e}")
        fig, ax = plt.subplots(figsize=(6, 4))
        ax.text(0.5, 0.5, "SAM chart unavailable", ha="center", va="center")
        ax.axis("off")
        buf = io.BytesIO()
        plt.savefig(buf, format="png", dpi=120, bbox_inches="tight")
        buf.seek(0)
        out = base64.b64encode(buf.getvalue()).decode()
        plt.close()
        return out


# ---------- Dashboard assembly ----------


def _dashboard_html(
    scenario: str,
    housing_type: str,
    county_slug: str,
    deployment_b64: Optional[str],
    appliance_b64: Optional[str],
    weekly_jan_b64: Optional[str],
    weekly_jul_b64: Optional[str],
    step18_images: Optional[dict] = None,
    solar_size_html: Optional[str] = None,
    annual_load_html: Optional[str] = None,
    grid_supply_html: Optional[str] = None,
) -> str:
    scen_title = scenario.replace("_", " ").title()
    county_title = county_slug.replace("-", " ").title()
    parts: List[str] = []
    parts.append(
        f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset=\"utf-8\" />
            <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
            <title>County Diagnostics — {county_title} — {scen_title}</title>
            <style>
                body {{ font-family: Arial, sans-serif; margin: 0; padding: 20px; background: #f7f7f7; }}
                .header {{ background: white; padding: 16px; border-radius: 8px; box-shadow: 0 1px 3px rgba(0,0,0,.08); margin-bottom: 18px; }}
                .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(480px, 1fr)); gap: 16px; }}
                .card {{ background: white; border-radius: 8px; box-shadow: 0 1px 3px rgba(0,0,0,.08); padding: 12px; }}
                .metric-card {{ background: white; border-radius: 8px; box-shadow: 0 1px 3px rgba(0,0,0,.08); padding: 20px; text-align: center; }}
                h1 {{ margin: 0 0 6px; }}
                h2 {{ margin: 6px 0 12px; font-size: 18px; }}
                .imgwrap img {{ width: 100%; height: auto; border-radius: 6px; }}
                .muted {{ color: #666; font-size: 12px; }}
                .metric-value {{ font-size: 24px; font-weight: bold; color: #2c5aa0; line-height: 1.2; }}
                .metric-value small {{ font-size: 12px; color: #666; font-weight: normal; display: block; margin-top: 4px; }}
            </style>
        </head>
        <body>
            <div class="header">
                <h1>County Diagnostics</h1>
                <div class="muted">{county_title} — {scen_title} — {housing_type}</div>
            </div>
            <div class="grid">
        """
    )

    # Card 1: Appliance breakdown (now first)
    parts.append("<div class=\"card\">")
    parts.append("<h2>Appliance Breakdown (Electric End‑Uses)</h2>")
    if appliance_b64:
        parts.append(
            f"<div class=\"imgwrap\"><img src=\"data:image/png;base64,{appliance_b64}\" alt=\"appliance breakdown\"></div>"
        )
    else:
        parts.append("<div class=\"muted\">No appliance chart available</div>")
    parts.append("</div>")

    # Card 2: Solar system size
    parts.append("<div class=\"metric-card\">")
    parts.append("<h2>Solar System Size</h2>")
    if solar_size_html:
        parts.append(solar_size_html)
    else:
        parts.append("<div class=\"metric-value\">N/A<br><small>No data available</small></div>")
    parts.append("</div>")

    # Card 3: Annual household load
    parts.append("<div class=\"metric-card\">")
    parts.append("<h2>Annual Household Load</h2>")
    if annual_load_html:
        parts.append(annual_load_html)
    else:
        parts.append("<div class=\"metric-value\">N/A<br><small>No data available</small></div>")
    parts.append("</div>")

    # Card 4: Grid supply load
    parts.append("<div class=\"metric-card\">")
    parts.append("<h2>Grid Supply to Load</h2>")
    if grid_supply_html:
        parts.append(grid_supply_html)
    else:
        parts.append("<div class=\"metric-value\">N/A<br><small>No data available</small></div>")
    parts.append("</div>")

    # Card 5: Deployment figure
    parts.append("<div class=\"card\">")
    parts.append("<h2>Solar + Storage Deployment</h2>")
    if deployment_b64:
        parts.append(
            f"<div class=\"imgwrap\"><img src=\"data:image/png;base64,{deployment_b64}\" alt=\"deployment\"></div>"
        )
    else:
        parts.append("<div class=\"muted\">No deployment figure available</div>")
    parts.append("</div>")

    # Card 6: Weekly SAM chart — January
    parts.append("<div class=\"card\">")
    parts.append("<h2>Load & Solar — January (First Week)</h2>")
    if weekly_jan_b64:
        parts.append(
            f"<div class=\"imgwrap\"><img src=\"data:image/png;base64,{weekly_jan_b64}\" alt=\"sam weekly january\"></div>"
        )
    else:
        parts.append("<div class=\"muted\">No January weekly figure available</div>")
    parts.append("</div>")

    # Card 7: Weekly SAM chart — July
    parts.append("<div class=\"card\">")
    parts.append("<h2>Load & Solar — July (First Week)</h2>")
    if weekly_jul_b64:
        parts.append(
            f"<div class=\"imgwrap\"><img src=\"data:image/png;base64,{weekly_jul_b64}\" alt=\"sam weekly july\"></div>"
        )
    else:
        parts.append("<div class=\"muted\">No July weekly figure available</div>")
    parts.append("</div>")

    # Step 18 cross-scenario comparison cards
    if step18_images:
        for title, b64 in step18_images.items():
            parts.append("<div class=\"card\">")
            parts.append(f"<h2>{title}</h2>")
            if b64:
                parts.append(
                    f"<div class=\"imgwrap\"><img src=\"data:image/png;base64,{b64}\" alt=\"{title}\"></div>"
                )
            else:
                parts.append("<div class=\"muted\">Not available</div>")
            parts.append("</div>")

    parts.append("</div></body></html>")
    return "\n".join(parts)


def _write_dashboard(path: str, html: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)


def process(
    base_input_dir: str,
    output_dir: str,
    housing_type: str,
    scenario: str,
    counties: List[str],
) -> List[str]:
    """
    Build county dashboards. Returns list of written HTML file paths.
    """
    written: List[str] = []
    sha = git_short_sha()
    # Normalize input counties to slugs
    county_slugs = [slugify_county_name(c) for c in counties]
    for county_slug in county_slugs:
        try:
            dep_b64 = create_solar_storage_deployment_graph(
                base_input_dir, scenario, housing_type, county_slug
            )
            app_b64 = create_appliance_breakdown_chart(
                base_input_dir, scenario, housing_type, county_slug
            )
            # Weekly SAM, split per period
            weekly_jan_b64 = create_sam_weekly_chart_for_period(
                base_input_dir, scenario, housing_type, county_slug, period="january"
            )
            weekly_jul_b64 = create_sam_weekly_chart_for_period(
                base_input_dir, scenario, housing_type, county_slug, period="july"
            )
            # New metric cards
            solar_size_html = create_solar_size_card(
                base_input_dir, scenario, housing_type, county_slug
            )
            annual_load_html = create_annual_load_card(
                base_input_dir, scenario, housing_type, county_slug
            )
            grid_supply_html = create_grid_supply_card(
                base_input_dir, scenario, housing_type, county_slug
            )
            # Collect Step 18 cross-scenario plots
            step18 = _gather_step18_images(output_dir, sha)
            html = _dashboard_html(
                scenario=scenario,
                housing_type=housing_type,
                county_slug=county_slug,
                deployment_b64=dep_b64,
                appliance_b64=app_b64,
                weekly_jan_b64=weekly_jan_b64,
                weekly_jul_b64=weekly_jul_b64,
                step18_images=step18,
                solar_size_html=solar_size_html,
                annual_load_html=annual_load_html,
                grid_supply_html=grid_supply_html,
            )
            out_path = os.path.join(
                output_dir,
                "county_diagnostics",
                scenario,
                f"{county_slug}_diagnostics_g{sha}.html",
            )
            _write_dashboard(out_path, html)
            written.append(out_path)
            try:
                print(f"County diagnostics written: {os.path.abspath(out_path)}")
            except Exception:
                pass
        except Exception as e:
            print(f"Error building diagnostics for {county_slug}: {e}")
    return written


def main() -> None:
    parser = argparse.ArgumentParser(description="Build county diagnostics dashboards")
    parser.add_argument("--base-input-dir", default="data/loadprofiles")
    parser.add_argument("--output-dir", default="analysis_results")
    parser.add_argument("--housing-type", default="single-family-detached")
    parser.add_argument("--scenario", required=True)
    parser.add_argument("--counties", nargs="*", help="County slugs (e.g., alameda san-diego)")
    args = parser.parse_args()

    if not args.counties:
        # Fallback to a single representative county if none specified
        args.counties = ["alameda"]

    process(
        base_input_dir=args.base_input_dir,
        output_dir=args.output_dir,
        housing_type=args.housing_type,
        scenario=args.scenario,
        counties=args.counties,
    )


# ---------- Step 18 assets embedding ----------

def _embed_png_as_b64(path: str) -> Optional[str]:
    try:
        if not os.path.exists(path):
            return None
        with open(path, "rb") as f:
            return base64.b64encode(f.read()).decode()
    except Exception:
        return None


def _gather_step18_images(output_dir: str, sha: str) -> dict:
    """Return a dict of Step 18 chart title -> base64 image where available."""
    files = {
        "EAC by Scenario (Stacked)": os.path.join(output_dir, f"step18_eac_stacked_bar_g{sha}.png"),
        "kWh Flows by Scenario": os.path.join(output_dir, f"step18_kwh_flows_dotline_g{sha}.png"),
        "Savings & Bills (with Solar)": os.path.join(output_dir, f"step18_savings_bills_dotline_g{sha}.png"),
        "Payback Periods (with Solar)": os.path.join(output_dir, f"step18_payback_with_solar_dotline_g{sha}.png"),
        "PV Size by Scenario": os.path.join(output_dir, f"step18_pv_size_bar_g{sha}.png"),
        "With vs Without Solar+Storage": os.path.join(output_dir, f"step21_eac_with_vs_without_g{sha}.png"),
    }
    out = {}
    for title, path in files.items():
        out[title] = _embed_png_as_b64(path)
    # prune empty
    return {k: v for k, v in out.items() if v}


if __name__ == "__main__":
    main()
