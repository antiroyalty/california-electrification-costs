from __future__ import annotations

import base64
import io
import os
from typing import List, Optional

import pandas as pd

# Matplotlib is an optional dependency; import lazily in functions that need it
import matplotlib.pyplot as plt


def load_appliance_breakdown_data(
    base_input_dir: str,
    scenario: str,
    housing_type: str,
    county_slug: str,
) -> dict:
    """
    Load appliance breakdown data by end-use category.

    Notes
    - Uses baseline electricity appliance breakdown (available only in baseline).
    - For non-baseline scenarios, adds simulated electrified end-uses (heat pump, induction, water heating).
    - Excludes gas appliances from the pie chart breakdown.
    """
    appliance_data: dict[str, float] = {}

    electricity_categories = {
        "Cooling": ["ceiling_fan"],
        "Appliances": ["clothes_dryer", "dishwasher", "freezer", "refrigerator"],
        "Lighting": ["lighting_garage", "lighting_interior"],
        "Plug Loads": ["plug_loads"],
        "Pool/Spa": ["permanent_spa_heat", "permanent_spa_pump", "pool_heater", "pool_pump"],
        "Other Electric": ["mech_vent"],
    }

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
    if not scenario.startswith("baseline"):
        scen_dir = os.path.join(base_input_dir, scenario, housing_type, county_slug)
        simulated_file = os.path.join(scen_dir, f"electricity_loads_simulated_{county_slug}.csv")
        if not os.path.exists(simulated_file):
            scen_dir = os.path.join(base_input_dir, "baseline", housing_type, county_slug)
            simulated_file = os.path.join(scen_dir, f"electricity_loads_simulated_{county_slug}.csv")
        if os.path.exists(simulated_file):
            try:
                df = pd.read_csv(simulated_file, parse_dates=["timestamp"]).set_index("timestamp")
                df = df.resample("H").sum()
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


def _slice_week(df: pd.DataFrame, period: str) -> pd.DataFrame:
    periods = {
        "january": ("2018-01-01", "2018-01-08"),
        "july": ("2018-07-01", "2018-07-08"),
    }
    key = period.lower()
    start, end = periods.get(key, periods["january"])  # default jan
    return df.loc[start:end]


def load_battery_soc_data(
    base_input_dir: str,
    scenario: str,
    housing_type: str,
    county_slug: str,
) -> Optional[pd.DataFrame]:
    county_dir = os.path.join(base_input_dir, scenario, housing_type, county_slug)
    sam_file = os.path.join(county_dir, f"solar_storage_dispatch_profiles_{county_slug}.csv")
    if not os.path.exists(sam_file):
        print(f"Warning: Solar+storage load profiles file not found: {sam_file}")
        return None
    try:
        df = pd.read_csv(sam_file, parse_dates=[0], index_col=0)
        if "Battery SOC" not in df.columns:
            print(f"Warning: Battery SOC column not found in {sam_file}")
            print(f"Available columns: {list(df.columns)}")
            return None
        return df[["Battery SOC"]]
    except Exception as e:
        print(f"Warning: Error reading solar+storage load profiles for {county_slug}: {e}")
        return None


def create_battery_soc_chart(
    base_input_dir: str,
    scenario: str,
    housing_type: str,
) -> str:
    """
    Create a simple 2-panel Battery SOC chart (Jan/Jul) for a representative county.

    Returns base64-encoded PNG. If no suitable data is found, returns a small HTML
    note to embed in place of the image.
    """
    try:
        import matplotlib.dates as mdates

        # Find a county directory that has a SAM file with 'Battery SOC'
        base_dir = os.path.join(base_input_dir, scenario, housing_type)
        if not os.path.isdir(base_dir):
            return "<div class='muted'>No battery SOC data directory</div>"

        def find_sam_path(cslug: str) -> Optional[str]:
            p1 = os.path.join(base_dir, cslug, f"solar_storage_dispatch_profiles_{cslug}.csv")
            p2 = os.path.join(base_dir, cslug, f"solar_storage_dispatch_profiles_{scenario}_{cslug}.csv")
            if os.path.exists(p1):
                return p1
            if os.path.exists(p2):
                return p2
            return None

        chosen_slug: Optional[str] = None
        chosen_path: Optional[str] = None
        for entry in sorted(os.listdir(base_dir)):
            county_dir = os.path.join(base_dir, entry)
            if not os.path.isdir(county_dir):
                continue
            sam_path = find_sam_path(entry)
            if not sam_path:
                continue
            try:
                df = pd.read_csv(sam_path, parse_dates=[0], index_col=0)
                if "Battery SOC" in df.columns:
                    chosen_slug = entry
                    chosen_path = sam_path
                    break
            except Exception:
                continue

        if not chosen_slug or not chosen_path:
            return "<div class='muted'>No battery SOC found for any county</div>"

        # Prepare weekly slices (Jan and Jul)
        df = pd.read_csv(chosen_path, parse_dates=[0], index_col=0)
        if "Battery SOC" not in df.columns:
            return "<div class='muted'>Battery SOC column missing</div>"
        soc = df[["Battery SOC"]].copy()
        jan = _slice_week(soc, "january")
        jul = _slice_week(soc, "july")

        fig, axes = plt.subplots(1, 2, figsize=(16, 5), sharey=True)
        axes = axes if isinstance(axes, (list, tuple)) else [axes]
        def plot(ax, series: pd.DataFrame, title: str):
            if series is None or series.empty:
                ax.text(0.5, 0.5, f"No data for {title}", ha="center", va="center")
                ax.axis("off")
                return
            ax.plot(series.index, series["Battery SOC"], color="#2E86AB")
            ax.set_title(title, fontsize=12, fontweight="bold")
            ax.set_ylabel("Battery SOC")
            ax.grid(True, alpha=0.3)
            ax.xaxis.set_major_locator(mdates.DayLocator())
            ax.xaxis.set_major_formatter(mdates.DateFormatter("%m/%d"))
            ax.xaxis.set_minor_locator(mdates.HourLocator(interval=6))
            plt.setp(ax.xaxis.get_majorticklabels(), rotation=45, ha="right")

        plot(axes[0], jan, "January — First Week")
        plot(axes[1], jul, "July — First Week")
        fig.suptitle(
            f"Battery SOC — {scenario.replace('_', ' ').title()} — {chosen_slug.replace('-', ' ').title()} County",
            fontsize=14,
            fontweight="bold",
        )
        plt.tight_layout()
        buf = io.BytesIO()
        plt.savefig(buf, format="png", dpi=150, bbox_inches="tight")
        buf.seek(0)
        out = base64.b64encode(buf.getvalue()).decode()
        plt.close()
        return out
    except Exception as e:
        print(f"Warning: Could not create battery SOC chart: {e}")
        return "<div class='muted'>Battery SOC chart unavailable</div>"


def load_sam_weekly_data(
    base_input_dir: str,
    scenario: str,
    housing_type: str,
    county_slug: str,
    metric_columns: Optional[List[str]] = None,
) -> Optional[pd.DataFrame]:
    """Load SAM CSV and return requested metric columns for weekly charting."""
    county_dir = os.path.join(base_input_dir, scenario, housing_type, county_slug)
    sam_file = os.path.join(county_dir, f"solar_storage_dispatch_profiles_{county_slug}.csv")
    if not os.path.exists(sam_file):
        alt = os.path.join(county_dir, f"solar_storage_dispatch_profiles_{scenario}_{county_slug}.csv")
        sam_file = alt if os.path.exists(alt) else sam_file
    if not os.path.exists(sam_file):
        print(f"Warning: Solar+storage load profiles file not found: {sam_file}")
        return None
    try:
        df = pd.read_csv(sam_file, parse_dates=[0], index_col=0)
        cols = metric_columns or ["Load Profile", "System to Load", "Battery to Load", "Grid to Load", "System to Battery"]
        missing = [c for c in cols if c not in df.columns]
        if missing:
            print(f"Warning: Missing columns in {sam_file}: {missing}")
            print(f"Available columns: {list(df.columns)}")
            return None
        return df[cols]
    except Exception as e:
        print(f"Warning: Error reading solar+storage load profiles for {county_slug}: {e}")
        return None


def create_sam_weekly_chart(
    base_input_dir: str,
    scenario: str,
    housing_type: str,
    county_slug: str,
) -> str:
    """
    Create a compact weekly chart for Jan and Jul with key SAM metrics.
    Returns base64 PNG or small HTML message on failure.
    """
    try:
        import matplotlib.dates as mdates

        metrics = ["Load Profile", "System to Load", "Battery to Load", "Grid to Load", "System to Battery"]
        df = load_sam_weekly_data(base_input_dir, scenario, housing_type, county_slug, metrics)
        if df is None:
            return "<div class='muted'>No SAM metrics available</div>"

        fig, axes = plt.subplots(2, 1, figsize=(16, 10), sharex=False)
        periods = {
            "January (Winter)": ("2018-01-01", "2018-01-08"),
            "July (Summer)": ("2018-07-01", "2018-07-08"),
        }
        colors = {
            "Load Profile": "#2E86AB",
            "System to Load": "#F39C12",
            "Battery to Load": "#27AE60",
            "Grid to Load": "#8E44AD",
            "System to Battery": "#E74C3C",
        }

        for ax, (title, (start, end)) in zip(axes, periods.items()):
            week = df.loc[start:end].copy()
            if week.empty:
                ax.text(0.5, 0.5, f"No data for {title}", ha="center", va="center")
                ax.axis("off")
                continue
            for col in metrics:
                ax.plot(week.index, week[col], label=col, color=colors.get(col, None), linewidth=1.3)
            ax.set_title(title, fontsize=13, fontweight="bold")
            ax.grid(True, alpha=0.3)
            ax.legend(loc="upper right", fontsize=9, ncol=2)
            ax.xaxis.set_major_locator(mdates.DayLocator())
            ax.xaxis.set_major_formatter(mdates.DateFormatter("%m/%d"))
            ax.xaxis.set_minor_locator(mdates.HourLocator(interval=6))
            plt.setp(ax.xaxis.get_majorticklabels(), rotation=45, ha="right")

        fig.suptitle(
            f"SAM Metrics — {scenario.replace('_', ' ').title()} — {county_slug.replace('-', ' ').title()} County",
            fontsize=15,
            fontweight="bold",
        )
        plt.tight_layout()
        buf = io.BytesIO()
        plt.savefig(buf, format="png", dpi=150, bbox_inches="tight")
        buf.seek(0)
        out = base64.b64encode(buf.getvalue()).decode()
        plt.close()
        return out
    except Exception as e:
        print(f"Warning: Could not create SAM weekly chart: {e}")
        return "<div class='muted'>SAM weekly chart unavailable</div>"

