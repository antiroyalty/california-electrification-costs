"""
Step 22: Build County Diagnostics

Creates per-county diagnostic dashboards that assemble:
- Solar + storage deployment graph (from Step 9 outputs)
- Appliance breakdown pie chart (moved from Step 16)
 - Weekly charts for January and July (separate panels)
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
from datetime import datetime

import pandas as pd

from helpers.main_helpers import (
    get_scenario_path,
    git_short_sha,
    slugify_county_name,
)
from helpers.maps_helpers import get_latest_csv_file
from helpers.diagnostics_helpers import (
    load_appliance_breakdown_data,
    create_appliance_breakdown_chart,
    load_battery_soc_data,
    create_battery_soc_chart,
    load_sam_weekly_data,
    create_sam_weekly_chart,
    _slice_week,
)


import matplotlib.pyplot as plt


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

def _infer_pv_size_kw_from_csv(csv_path: str) -> Optional[float]:
    """Try to infer PV system size (kW) from the solar+storage CSV header.

    Returns None if a size column cannot be found.
    """
    try:
        if not os.path.exists(csv_path):
            return None
        df_head = pd.read_csv(csv_path, nrows=1)
        candidates = [
            "pv system size",
            "pv size",
            "pv capacity",
            "system size",
            "pv_kw",
            "pv kw",
            "pv (kw)",
            "system capacity",
        ]
        chosen = None
        for col in df_head.columns:
            low = str(col).lower()
            if any(c in low for c in candidates):
                chosen = col
                break
        if chosen is None:
            return None
        val = df_head.iloc[0][chosen]
        try:
            size_kw = float(val)
            if size_kw >= 0:
                return size_kw
        except Exception:
            return None
    except Exception:
        return None


def _lookup_pv_size_kw(
    base_input_dir: str, scenario: str, housing_type: str, county_slug: str
) -> Optional[float]:
    """Find PV size (kW) for a county from Step 9 capacity summary, falling back to CSV header.

    1) Look for `{base_input_dir}/{scenario}/{housing_type}/CAPITAL_COSTS/electrified_assets.csv`
       and read the row for `county_slug` (index or County col), using "Solar Capacity (kW)".
    2) Fallback: `_infer_pv_size_kw_from_csv` on the per-county solar+storage CSV.
    """
    try:
        cap_csv = os.path.join(
            base_input_dir, scenario, housing_type, "CAPITAL_COSTS", "electrified_assets.csv"
        )
        if os.path.exists(cap_csv):
            try:
                df = pd.read_csv(cap_csv)
                # Normalize county id
                # accept either index name 'County' or a column
                county_col = None
                for c in df.columns:
                    if str(c).strip().lower() in ("county", "county_slug"):
                        county_col = c
                        break
                if county_col is not None:
                    df_idx = df.set_index(county_col)
                else:
                    # maybe CSV saved with County as index; try to read the first column as index name
                    # if not, create a slug from any existing column
                    df_idx = df
                # Normalize index to slugs for matching
                def to_slug(x):
                    try:
                        return slugify_county_name(str(x))
                    except Exception:
                        return str(x)
                df_idx = df_idx.copy()
                df_idx["__slug__"] = [to_slug(x) for x in (df_idx.index if county_col is None else df_idx.index)]
                if "__slug__" not in df_idx.columns:
                    df_idx["__slug__"] = [to_slug(x) for x in df_idx.index]
                # Try to locate the row
                row = df_idx[df_idx["__slug__"] == county_slug]
                if row.empty and county_col is not None:
                    # try without slug normalization
                    row = df[df[county_col] == county_slug]
                if not row.empty:
                    # Find the solar capacity column
                    cap_col = None
                    for c in row.columns:
                        low = str(c).lower()
                        if "solar capacity" in low and "kw" in low:
                            cap_col = c
                            break
                        if low in ("solar capacity (kwh)"):
                            # unlikely, but skip energy unit
                            continue
                    if cap_col is not None:
                        val = float(row.iloc[0][cap_col])
                        return val
            except Exception:
                pass
        # Fallback to inspecting per-county solar+storage CSV header
        county_dir = os.path.join(base_input_dir, scenario, housing_type, county_slug)
        sam_file = os.path.join(county_dir, f"sam_optimized_load_profiles_{county_slug}.csv")
        if not os.path.exists(sam_file):
            alt = os.path.join(county_dir, f"sam_optimized_load_profiles_{scenario}_{county_slug}.csv")
            sam_file = alt if os.path.exists(alt) else sam_file
        return _infer_pv_size_kw_from_csv(sam_file)
    except Exception:
        return None


def compute_key_metrics(
    base_input_dir: str,
    scenario: str,
    housing_type: str,
    county_slug: str,
) -> Optional[dict]:
    """Compute key metrics with and without solar+storage from Step 9 output.

    Returns a dict with keys "with" and "without", each containing:
      - solar_kw
      - annual_load_kwh
      - grid_to_load_kwh

    If data is missing, returns None.
    """
    county_dir = os.path.join(base_input_dir, scenario, housing_type, county_slug)
    sam_file = os.path.join(county_dir, f"sam_optimized_load_profiles_{county_slug}.csv")
    if not os.path.exists(sam_file):
        # Older naming variant
        alt = os.path.join(county_dir, f"sam_optimized_load_profiles_{scenario}_{county_slug}.csv")
        sam_file = alt if os.path.exists(alt) else sam_file
    if not os.path.exists(sam_file):
        return None
    try:
        df = pd.read_csv(sam_file)
        # Required columns for robust computation
        load_col = None
        grid_to_load_col = None
        for col in df.columns:
            low = str(col).lower()
            if load_col is None and "load profile" in low:
                load_col = col
            if grid_to_load_col is None and ("grid to load" in low or ("grid" in low and "load" in low)):
                grid_to_load_col = col
        if load_col is None:
            # fallback: first numeric-looking column
            for col in df.columns:
                if pd.api.types.is_numeric_dtype(df[col]):
                    load_col = col
                    break
        # Annual load
        annual_load_kwh = float(pd.to_numeric(df[load_col], errors="coerce").fillna(0.0).sum()) if load_col else None
        # Grid to load (with solar)
        grid_with_kwh = (
            float(pd.to_numeric(df[grid_to_load_col], errors="coerce").fillna(0.0).sum())
            if grid_to_load_col
            else None
        )
        # PV and Battery sizes: read from the same source as the capacities card (electrified_assets.csv)
        assets = compute_assets_info(base_input_dir, scenario, housing_type, county_slug) or {}
        pv_size_kw = assets.get("Solar Capacity (kW)")
        batt_kwh = assets.get("Battery Capacity (kWh)")
        # Without solar+storage: PV size = 0; grid supplies all load
        without = {
            "solar_kw": 0.0 if annual_load_kwh is not None else None,
            "battery_kwh": 0.0 if annual_load_kwh is not None else None,
            "annual_load_kwh": annual_load_kwh,
            "grid_to_load_kwh": annual_load_kwh,
        }
        with_vals = {
            "solar_kw": pv_size_kw,
            "battery_kwh": batt_kwh,
            "annual_load_kwh": annual_load_kwh,
            "grid_to_load_kwh": grid_with_kwh,
        }
        return {"with": with_vals, "without": without}
    except Exception:
        return None


def _lookup_battery_capacity_kwh(
    base_input_dir: str, scenario: str, housing_type: str, county_slug: str
) -> Optional[float]:
    """Look up battery capacity (kWh) from the Step 9 capacity summary file.

    Falls back to None if not found.
    """
    try:
        cap_csv = os.path.join(
            base_input_dir, scenario, housing_type, "CAPITAL_COSTS", "electrified_assets.csv"
        )
        if not os.path.exists(cap_csv):
            return None
        df = pd.read_csv(cap_csv)
        county_col = None
        for c in df.columns:
            if str(c).strip().lower() in ("county", "county_slug"):
                county_col = c
                break
        if county_col is not None:
            df_idx = df.set_index(county_col)
        else:
            df_idx = df
        # Normalize to slug
        def to_slug(x):
            try:
                return slugify_county_name(str(x))
            except Exception:
                return str(x)
        df_idx = df_idx.copy()
        df_idx["__slug__"] = [to_slug(ix) for ix in (df_idx.index)]
        row = df_idx[df_idx["__slug__"] == county_slug]
        if row.empty:
            return None
        cap_col = None
        for c in row.columns:
            low = str(c).lower()
            if "battery capacity" in low and "kwh" in low:
                cap_col = c
                break
        if cap_col is None:
            return None
        return float(row.iloc[0][cap_col])
    except Exception:
        return None


def compute_energy_flow_metrics(
    base_input_dir: str,
    scenario: str,
    housing_type: str,
    county_slug: str,
) -> Optional[dict]:
    """Compute detailed energy flow metrics from Step 9 solar+storage CSV.

    Returns dict with keys:
      - battery_capacity_kwh
      - pv_to_load_kwh
      - batt_to_load_kwh
      - grid_to_load_kwh
      - pv_to_batt_kwh
      - grid_to_batt_kwh
      - pv_exports_kwh
      - pv_exports_formula
      - total_grid_purchases_kwh
      - self_sufficiency_pct
      - peak_net_load_kw
    """
    county_dir = os.path.join(base_input_dir, scenario, housing_type, county_slug)
    sam_file = os.path.join(county_dir, f"sam_optimized_load_profiles_{county_slug}.csv")
    if not os.path.exists(sam_file):
        alt = os.path.join(county_dir, f"sam_optimized_load_profiles_{scenario}_{county_slug}.csv")
        sam_file = alt if os.path.exists(alt) else sam_file
    if not os.path.exists(sam_file):
        return None

    try:
        df = pd.read_csv(sam_file)
        def num(col: str) -> pd.Series:
            if col not in df.columns:
                return pd.Series([0.0] * len(df))
            return pd.to_numeric(df[col], errors="coerce").fillna(0.0)

        load = num("Load Profile")
        pv_to_load = num("System to Load")
        batt_to_load = num("Battery to Load")
        grid_to_load = num("Grid to Load")
        pv_to_batt = num("System to Battery")
        grid_to_batt = num("Grid to Battery")
        # Optional columns that enable PV exports calc
        system_to_grid = df["System to Grid"] if "System to Grid" in df.columns else None
        pv_to_grid = df["PV to Grid (kWh)"] if "PV to Grid (kWh)" in df.columns else None
        pv_ac = df["PV AC (kWh)"] if "PV AC (kWh)" in df.columns else None

        total_load_kwh = float(load.sum()) if len(load) else None
        pv_to_load_kwh = float(pv_to_load.sum())
        batt_to_load_kwh = float(batt_to_load.sum())
        grid_to_load_kwh = float(grid_to_load.sum())
        pv_to_batt_kwh = float(pv_to_batt.sum())
        grid_to_batt_kwh = float(grid_to_batt.sum())
        total_grid_purchases_kwh = grid_to_load_kwh + grid_to_batt_kwh

        # PV exports: prefer explicit PV to Grid, then System to Grid, then PV AC minus uses
        pv_exports_kwh = None
        pv_exports_formula = None
        try:
            if pv_to_grid is not None:
                pv_exports_kwh = float(pd.to_numeric(pv_to_grid, errors="coerce").fillna(0.0).sum())
                pv_exports_formula = "sum('PV to Grid (kWh)')"
            elif system_to_grid is not None:
                pv_exports_kwh = float(pd.to_numeric(system_to_grid, errors="coerce").fillna(0.0).sum())
                pv_exports_formula = "sum('System to Grid')"
            elif pv_ac is not None:
                pv_exports_kwh = float(
                    pd.to_numeric(pv_ac, errors="coerce").fillna(0.0).sum()
                    - pv_to_load_kwh
                    - pv_to_batt_kwh
                )
                if pv_exports_kwh < 0 and abs(pv_exports_kwh) < 1e-6:
                    pv_exports_kwh = 0.0
                pv_exports_formula = "sum('PV AC (kWh)') − sum('System to Load') − sum('System to Battery')"
        except Exception:
            pv_exports_kwh = None
            pv_exports_formula = None

        if total_load_kwh and total_load_kwh > 0:
            self_sufficiency_pct = 100.0 * (1.0 - (grid_to_load_kwh / total_load_kwh))
        else:
            self_sufficiency_pct = None

        net = load - pv_to_load - batt_to_load
        peak_net_load_kw = float(net.max()) if len(net) else None

        battery_capacity_kwh = _lookup_battery_capacity_kwh(
            base_input_dir, scenario, housing_type, county_slug
        )

        return {
            "battery_capacity_kwh": battery_capacity_kwh,
            "pv_to_load_kwh": pv_to_load_kwh,
            "batt_to_load_kwh": batt_to_load_kwh,
            "grid_to_load_kwh": grid_to_load_kwh,
            "pv_to_batt_kwh": pv_to_batt_kwh,
            "grid_to_batt_kwh": grid_to_batt_kwh,
            "pv_exports_kwh": pv_exports_kwh,
            "pv_exports_formula": pv_exports_formula,
            "total_grid_purchases_kwh": total_grid_purchases_kwh,
            "self_sufficiency_pct": self_sufficiency_pct,
            "peak_net_load_kw": peak_net_load_kw,
        }
    except Exception:
        return None


# ---------- Annual cost breakdown helpers (electricity vs gas) ----------

def _latest_results_csv_path(
    base_input_dir: str,
    scenario: str,
    housing_type: str,
    county_slug: str,
    *,
    kind: str,  # 'electricity' or 'gas'
) -> Optional[str]:
    try:
        base = get_scenario_path(base_input_dir, scenario, housing_type)
        res_dir = os.path.join(base, county_slug, "results", kind)
        if not os.path.isdir(res_dir):
            return None
        prefix = f"RESULTS_{kind}_annual_costs_{county_slug}_"
        return get_latest_csv_file(res_dir, prefix)
    except Exception:
        return None


def compute_energy_flow_metrics_without(
    base_input_dir: str,
    scenario: str,
    housing_type: str,
    county_slug: str,
) -> Optional[dict]:
    """Compute no-PV/battery flows using Step 7 combined profiles (default scenario loads).

    Returns the same keys used by the 'with' flows metrics for easy rendering, with PV/battery flows set to zero.
    """
    county_dir = os.path.join(base_input_dir, scenario, housing_type, county_slug)
    combined = os.path.join(county_dir, f"combined_profiles_{scenario}_{county_slug}.csv")
    if not os.path.exists(combined):
        return None
    try:
        df = pd.read_csv(combined)
        col = "electricity.real_and_simulated.for_typical_county_home.kwh"
        if col not in df.columns:
            return None
        load = pd.to_numeric(df[col], errors="coerce").fillna(0.0)
        total_load_kwh = float(load.sum())
        peak_net_load_kw = float(load.max())
        return {
            "battery_capacity_kwh": 0.0,
            "pv_to_load_kwh": 0.0,
            "batt_to_load_kwh": 0.0,
            "grid_to_load_kwh": total_load_kwh,
            "pv_to_batt_kwh": 0.0,
            "grid_to_batt_kwh": 0.0,
            "pv_exports_kwh": 0.0,
            "pv_exports_formula": "N/A (no PV)",
            "total_grid_purchases_kwh": total_load_kwh,
            "self_sufficiency_pct": 0.0,
            "peak_net_load_kw": peak_net_load_kw,
        }
    except Exception:
        return None


def _parse_electricity_results(path: str, scenario: str) -> tuple[dict, dict]:
    """Return two dicts keyed by plan token -> dollars for (retail, nem3) for scenario.solarstorage row.

    If the NEM3 column is missing for a plan, the nem3 dict omits that key.
    """
    retail: dict[str, float] = {}
    nem3: dict[str, float] = {}
    if not path or not os.path.exists(path):
        return retail, nem3
    try:
        df = pd.read_csv(path, index_col="scenario")
        row_name = f"{scenario}.solarstorage" if f"{scenario}.solarstorage" in df.index else scenario
        row = df.loc[row_name] if row_name in df.index else df.iloc[0]
        for c in row.index:
            s = str(c)
            if not s.startswith("electricity."):
                continue
            val = pd.to_numeric(row[c], errors="coerce")
            if pd.isna(val):
                continue
            # token: electricity.<utility>.<plan>[ _NEM3]
            is_nem3 = s.endswith("_NEM3")
            plan_token = s.split(".")[-1].replace("_NEM3", "")
            if is_nem3:
                nem3[plan_token] = float(val)
            else:
                retail[plan_token] = float(val)
        return retail, nem3
    except Exception:
        return retail, nem3


def _parse_gas_results(path: str, scenario: str) -> dict:
    """Return dict plan -> dollars for scenario.solarstorage row."""
    out: dict[str, float] = {}
    if not path or not os.path.exists(path):
        return out
    try:
        df = pd.read_csv(path, index_col="scenario")
        row_name = f"{scenario}.solarstorage" if f"{scenario}.solarstorage" in df.index else scenario
        row = df.loc[row_name] if row_name in df.index else df.iloc[0]
        for c in row.index:
            s = str(c)
            if not s.startswith("gas."):
                continue
            val = pd.to_numeric(row[c], errors="coerce")
            if pd.isna(val):
                continue
            plan_token = s.split(".")[-1]
            out[plan_token] = float(val)
        return out
    except Exception:
        return out


def compute_cost_breakdowns(
    base_input_dir: str,
    scenario: str,
    housing_type: str,
    county_slug: str,
) -> dict:
    """Return structured totals and per-plan electricity/gas annual costs.

    Structure:
      {
        'electricity': { 'retail': {plan: $, ...}, 'nem3': {plan: $, ...} },
        'gas': { plan: $ },
        'totals': {
            'electricity_best_retail': (plan, $),
            'electricity_best_nem3': (plan, $),
            'gas_best': (plan, $),
        }
      }
    """
    e_path = _latest_results_csv_path(base_input_dir, scenario, housing_type, county_slug, kind="electricity")
    g_path = _latest_results_csv_path(base_input_dir, scenario, housing_type, county_slug, kind="gas")
    retail, nem3 = _parse_electricity_results(e_path, scenario)
    gas = _parse_gas_results(g_path, scenario)

    def best(d: dict) -> tuple[str, float] | tuple[None, None]:
        if not d:
            return (None, None)
        k = min(d, key=lambda k: d[k])
        return (k, float(d[k]))

    eb_retail = best(retail)
    eb_nem3 = best(nem3)
    gb = best(gas)

    return {
        "electricity": {"retail": retail, "nem3": nem3},
        "gas": gas,
        "totals": {
            "electricity_best_retail": eb_retail,
            "electricity_best_nem3": eb_nem3,
            "gas_best": gb,
        },
    }


def compute_assets_info(
    base_input_dir: str,
    scenario: str,
    housing_type: str,
    county_slug: str,
) -> Optional[dict]:
    """Read PV and battery capacities for a county from electrified_assets.csv.

    Returns a dict like {"Solar Capacity (kW)": float|None, "Battery Capacity (kWh)": float|None}
    or None if the file is absent.
    """
    cap_csv = os.path.join(
        base_input_dir, scenario, housing_type, "CAPITAL_COSTS", "electrified_assets.csv"
    )
    if not os.path.exists(cap_csv):
        return None
    try:
        df = pd.read_csv(cap_csv)
        county_col = None
        for c in df.columns:
            if str(c).strip().lower() in ("county", "county_slug"):
                county_col = c
                break
        if county_col is not None:
            df_idx = df.set_index(county_col)
        else:
            df_idx = df
        # Normalize index to slug
        def to_slug(x):
            try:
                return slugify_county_name(str(x))
            except Exception:
                return str(x)
        df_idx = df_idx.copy()
        # Try index slug match
        if df_idx.index.name is None or any(isinstance(i, (int, float)) for i in df_idx.index):
            # ensure we have a slug column to match against
            df_idx["__slug__"] = [to_slug(x) for x in range(len(df_idx))]
        # Better: try to find a slug either in index or in County column
        # Iterate rows to find matching slug
        match_row = None
        for _, r in df.iterrows():
            nm = r.get("County") or r.get(county_col) or ""
            if slugify_county_name(str(nm)) == county_slug:
                match_row = r
                break
        if match_row is None and not df.empty:
            # last resort: first row
            match_row = df.iloc[0]
        out = {
            "Solar Capacity (kW)": None,
            "Battery Capacity (kWh)": None,
        }
        if match_row is not None:
            for key in out.keys():
                if key in match_row.index:
                    val = match_row[key]
                    if pd.isna(val):
                        out[key] = None
                    else:
                        # Preserve raw as text exactly as in CSV
                        out[key] = str(val)
        # Add source path and last modified timestamp
        try:
            mtime = os.path.getmtime(cap_csv)
            out["CSV Path"] = cap_csv
            out["Last Modified"] = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            out["CSV Path"] = cap_csv
            out["Last Modified"] = None
        return out
    except Exception:
        return None

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


# ---------- End‑use breakdown weekly charts (Jan & Jul; real vs simulated) ----------

def _load_real_enduse_timeseries(
    base_input_dir: str,
    housing_type: str,
    county_slug: str,
) -> Optional[pd.DataFrame]:
    """Load 'real' electricity end‑use timeseries from baseline electricity_loads CSV.

    Returns a DataFrame indexed by timestamp with columns for each end‑use category.
    """
    baseline_dir = os.path.join(base_input_dir, "baseline", housing_type, county_slug)
    path = os.path.join(baseline_dir, f"electricity_loads_{county_slug}.csv")
    if not os.path.exists(path):
        return None
    try:
        df = pd.read_csv(path, parse_dates=["timestamp"]).set_index("timestamp").sort_index()
        categories = {
            "Cooling": ["ceiling_fan"],
            "Appliances": ["clothes_dryer", "dishwasher", "freezer", "refrigerator"],
            "Lighting": ["lighting_garage", "lighting_interior"],
            "Plug Loads": ["plug_loads"],
            "Pool/Spa": ["permanent_spa_heat", "permanent_spa_pump", "pool_heater", "pool_pump"],
            "Other Electric": ["mech_vent"],
        }
        out = pd.DataFrame(index=df.index)
        for cat, apps in categories.items():
            series = pd.Series(0.0, index=df.index)
            for a in apps:
                col = f"out.electricity.{a}.energy_consumption"
                if col in df.columns:
                    series = series.add(pd.to_numeric(df[col], errors="coerce").fillna(0.0), fill_value=0.0)
            if float(series.sum()) > 0:
                out[cat] = series
        return out if not out.empty else None
    except Exception:
        return None


def _load_sim_enduse_timeseries(
    base_input_dir: str,
    scenario: str,
    housing_type: str,
    county_slug: str,
) -> Optional[pd.DataFrame]:
    """Load simulated electrified appliance timeseries (heat pump, induction, hot water)."""
    def find_path(scen: str) -> Optional[str]:
        d = os.path.join(base_input_dir, scen, housing_type, county_slug)
        p = os.path.join(d, f"electricity_loads_simulated_{county_slug}.csv")
        return p if os.path.exists(p) else None
    path = find_path(scenario) or find_path("baseline")
    if not path:
        return None
    try:
        df = pd.read_csv(path, parse_dates=["timestamp"]).set_index("timestamp").sort_index()
        sim_map = {
            "Heat Pump": "simulated.electricity.heat_pump.energy_consumption.electricity.kwh",
            "Induction Cooking": "simulated.electricity.induction_stove.energy_consumption.electricity.kwh",
            "Electric Hot Water": "simulated.electricity.hot_water.energy_consumption.electricity.kwh",
        }
        out = pd.DataFrame(index=df.index)
        for label, col in sim_map.items():
            if col in df.columns:
                out[label] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)
        return out if not out.empty else None
    except Exception:
        return None



def create_enduse_breakdown_weekly(
    base_input_dir: str,
    scenario: str,
    housing_type: str,
    county_slug: str,
) -> Optional[str]:
    """Create a 2x2 stacked area chart: Jan and Jul, Real and Simulated end‑uses.

    Returns base64 PNG.
    """
    real = _load_real_enduse_timeseries(base_input_dir, housing_type, county_slug)
    sim = _load_sim_enduse_timeseries(base_input_dir, scenario, housing_type, county_slug)
    if real is None and sim is None:
        return None
    try:
        import matplotlib.dates as mdates
        fig, axes = plt.subplots(1, 2, figsize=(18, 6), sharex=False)
        color_map = {
            "Cooling": "#4ECDC4",
            "Appliances": "#FD79A8",
            "Lighting": "#FDCB6E",
            "Plug Loads": "#6C5CE7",
            "Pool/Spa": "#00B894",
            "Other Electric": "#A29BFE",
            "Heat Pump": "#FF8E53",
            "Induction Cooking": "#DDA0DD",
            "Electric Hot Water": "#96CEB4",
        }
        def plot_both_enduse(ax, real_week: Optional[pd.DataFrame], sim_week: Optional[pd.DataFrame], title: str, y_max: Optional[float] = None):
            # Build combined categories (distinct) with labels indicating Real/Sim
            series_list = []
            labels = []
            colors = []
            # Use union of indices for full x axis
            if real_week is not None and not real_week.empty:
                x_index = real_week.index
            elif sim_week is not None and not sim_week.empty:
                x_index = sim_week.index
            else:
                ax.text(0.5, 0.5, f"No data for {title}", ha="center", va="center", color="red")
                ax.axis("off")
                return
            # Real categories
            if real_week is not None and not real_week.empty:
                for c in real_week.columns:
                    if real_week[c].sum() > 0:
                        labels.append(f"{c} (Real)")
                        colors.append(color_map.get(c, None))
                        series_list.append(real_week[c].reindex(x_index).astype(float).values)
            # Simulated categories
            if sim_week is not None and not sim_week.empty:
                sim_colors = {
                    "Heat Pump": "#FF8E53",
                    "Induction Cooking": "#DDA0DD",
                    "Electric Hot Water": "#96CEB4",
                }
                for c in sim_week.columns:
                    if sim_week[c].sum() > 0:
                        labels.append(f"{c} (Sim)")
                        colors.append(sim_colors.get(c, "#999999"))
                        series_list.append(sim_week[c].reindex(x_index).astype(float).values)
            if not series_list:
                ax.text(0.5, 0.5, f"No data for {title}", ha="center", va="center", color="red")
                ax.axis("off")
                return
            ax.stackplot(x_index, *series_list, labels=labels, colors=colors, alpha=0.85)
            ax.set_title(title, fontsize=13, fontweight="bold")
            ax.set_ylabel("kWh per interval")
            ax.grid(True, alpha=0.3)
            if y_max is not None and y_max > 0:
                ax.set_ylim(0, y_max * 1.05)
            ax.xaxis.set_major_locator(mdates.DayLocator())
            ax.xaxis.set_major_formatter(mdates.DateFormatter("%m/%d"))
            ax.xaxis.set_minor_locator(mdates.HourLocator(interval=6))
            ax.legend(loc="upper right", fontsize=9, ncol=2)

        # Jan / Jul weekly slices
        real_jan = _slice_week(real, "january") if real is not None else None
        sim_jan = _slice_week(sim, "january") if sim is not None else None
        def stack_max(df: Optional[pd.DataFrame]) -> float:
            if df is None or df.empty:
                return 0.0
            try:
                return float(df.sum(axis=1).max())
            except Exception:
                return 0.0
        real_jul = _slice_week(real, "july") if real is not None else None
        sim_jul = _slice_week(sim, "july") if sim is not None else None
        # Global y-axis across both months, combined totals (real + sim)
        def combined_max(r: Optional[pd.DataFrame], s: Optional[pd.DataFrame]) -> float:
            if (r is None or r.empty) and (s is None or s.empty):
                return 0.0
            try:
                idx = None
                if r is not None and not r.empty:
                    idx = r.index
                if idx is None and s is not None and not s.empty:
                    idx = s.index
                rsum = r.reindex(idx).sum(axis=1) if r is not None and not r.empty else pd.Series(0.0, index=idx)
                ssum = s.reindex(idx).sum(axis=1) if s is not None and not s.empty else pd.Series(0.0, index=idx)
                return float((rsum + ssum).max())
            except Exception:
                return 0.0
        y_max_global = max(combined_max(real_jan, sim_jan), combined_max(real_jul, sim_jul))
        plot_both_enduse(axes[0], real_jan, sim_jan, "January — Real + Simulated End‑Uses", y_max=y_max_global)
        plot_both_enduse(axes[1], real_jul, sim_jul, "July — Real + Simulated End‑Uses", y_max=y_max_global)
        plt.tight_layout()
        buf = io.BytesIO()
        plt.savefig(buf, format="png", dpi=150, bbox_inches="tight")
        buf.seek(0)
        b64 = base64.b64encode(buf.getvalue()).decode()
        plt.close()
        return b64
    except Exception as e:
        print(f"Error creating end‑use weekly charts: {e}")
        return None


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


# ---------- Weekly charts (load and solar) and Battery SOC ----------
    

def create_weekly_chart(
    base_input_dir: str,
    scenario: str,
    housing_type: str,
    county_slug: str,
) -> str:
    """Weekly charts for load breakdown and solar power for Jan/Jul; returns base64 PNG."""
    try:
        import matplotlib.dates as mdates
        sam_metrics = ["Load Profile", "System to Load", "Battery to Load", "Grid to Load"]
        solar_metrics = ["System to Load", "System to Battery"]
        all_metrics = list(dict.fromkeys(sam_metrics + solar_metrics))
        weekly_df = load_sam_weekly_data(base_input_dir, scenario, housing_type, county_slug, all_metrics)
        if weekly_df is None:
            return ""
        fig, axes = plt.subplots(4, 1, figsize=(16, 20))
        fig.suptitle(
            f"Load Profile and Solar Power — Weekly Comparison\n{county_slug.replace('-', ' ').title()} County — {scenario.replace('_', ' ').title()} Scenario",
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
                week = weekly_df.loc[start:end]
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
        print(f"Error creating weekly chart: {e}")
        fig, ax = plt.subplots(figsize=(6, 4))
        ax.text(0.5, 0.5, "Weekly chart unavailable", ha="center", va="center")
        ax.axis("off")
        buf = io.BytesIO()
        plt.savefig(buf, format="png", dpi=120, bbox_inches="tight")
        buf.seek(0)
        b64 = base64.b64encode(buf.getvalue()).decode()
        plt.close()
        return b64


def create_weekly_chart_for_period(
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
        weekly_df = load_sam_weekly_data(base_input_dir, scenario, housing_type, county_slug, all_metrics)
        if weekly_df is None:
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
            f"Load & Solar — {title_suffix}\n{county_slug.replace('-', ' ').title()} County — {scenario.replace('_', ' ').title()} Scenario",
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
        week = weekly_df.loc[start:end]
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
        print(f"Error creating weekly single-period chart: {e}")
        fig, ax = plt.subplots(figsize=(6, 4))
        ax.text(0.5, 0.5, "Weekly chart unavailable", ha="center", va="center")
        ax.axis("off")
        buf = io.BytesIO()
        plt.savefig(buf, format="png", dpi=120, bbox_inches="tight")
        buf.seek(0)
        out = base64.b64encode(buf.getvalue()).decode()
        plt.close()
        return out


# ---------- NEM3 exports plots (annual + weekly) ----------

def _load_exports_timeseries(
    base_input_dir: str,
    scenario: str,
    housing_type: str,
    county_slug: str,
) -> Optional[pd.DataFrame]:
    """Load hourly exports to grid for NEM3 plotting.

    Preference order:
    1) Step 10 Aggregator: nem3.exports.kwh with timestamp
    2) Step 9 exports CSV: Exports to Grid (kWh)
    3) Step 9 base CSV: PV to Grid (kWh)
    """
    try:
        agg_path = os.path.join(
            base_input_dir, scenario, housing_type, county_slug, f"loadprofiles_for_rates_{county_slug}.csv"
        )
        if os.path.exists(agg_path):
            try:
                df = pd.read_csv(agg_path)
                ts = pd.to_datetime(df["timestamp"]) if "timestamp" in df.columns else None
                if "nem3.exports.kwh" in df.columns:
                    exp = pd.to_numeric(df["nem3.exports.kwh"], errors="coerce").fillna(0.0)
                    if ts is None:
                        ts = pd.date_range(start="2018-01-01", periods=len(exp), freq="H")
                    return pd.DataFrame({"exports": exp.values}, index=ts)
            except Exception:
                pass
        s9_dir = os.path.join(base_input_dir, scenario, housing_type, county_slug)
        s9_exp = os.path.join(s9_dir, f"sam_optimized_load_profiles_with_exports_{county_slug}.csv")
        if os.path.exists(s9_exp):
            try:
                df = pd.read_csv(s9_exp)
                if "Exports to Grid (kWh)" in df.columns:
                    exp = pd.to_numeric(df["Exports to Grid (kWh)"], errors="coerce").fillna(0.0)
                    ts = pd.date_range(start="2018-01-01", periods=len(exp), freq="H")
                    return pd.DataFrame({"exports": exp.values}, index=ts)
            except Exception:
                pass
        s9_base = os.path.join(s9_dir, f"sam_optimized_load_profiles_{county_slug}.csv")
        if not os.path.exists(s9_base):
            alt = os.path.join(s9_dir, f"sam_optimized_load_profiles_{scenario}_{county_slug}.csv")
            s9_base = alt if os.path.exists(alt) else s9_base
        if os.path.exists(s9_base):
            try:
                df = pd.read_csv(s9_base)
                if "PV to Grid (kWh)" in df.columns:
                    exp = pd.to_numeric(df["PV to Grid (kWh)"], errors="coerce").fillna(0.0)
                    ts = pd.date_range(start="2018-01-01", periods=len(exp), freq="H")
                    return pd.DataFrame({"exports": exp.values}, index=ts)
            except Exception:
                pass
        return None
    except Exception:
        return None


def create_nem3_exports_plot(
    base_input_dir: str,
    scenario: str,
    housing_type: str,
    county_slug: str,
) -> Optional[str]:
    df = _load_exports_timeseries(base_input_dir, scenario, housing_type, county_slug)
    if df is None or df.empty:
        return None
    try:
        s = pd.to_numeric(df["exports"], errors="coerce").fillna(0.0)
        daily = s.resample("D").sum()
        monthly = s.resample("M").sum()
        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(16, 9))
        fig.suptitle(
            f"Exports to Grid (NEM3) — {county_slug.replace('-', ' ').title()} County — {scenario.replace('_', ' ').title()}",
            fontsize=16,
            fontweight="bold",
        )
        ax1.plot(daily.index, daily.values, color="#1f77b4", linewidth=1.5)
        ax1.set_ylabel("kWh/day")
        ax1.set_title("Daily Exported Energy")
        ax1.grid(True, alpha=0.3)
        ax2.bar(monthly.index.strftime("%b"), monthly.values, color="#ff7f0e")
        ax2.set_ylabel("kWh/month")
        ax2.set_title("Monthly Exported Energy (Sum)")
        ax2.grid(True, axis="y", alpha=0.3)
        plt.tight_layout()
        buf = io.BytesIO()
        plt.savefig(buf, format="png", dpi=150, bbox_inches="tight")
        buf.seek(0)
        b64 = base64.b64encode(buf.getvalue()).decode()
        plt.close()
        return b64
    except Exception as e:
        print(f"Error creating NEM3 exports plot for {county_slug}: {e}")
        return None


def create_nem3_exports_weekly_chart_for_period(
    base_input_dir: str,
    scenario: str,
    housing_type: str,
    county_slug: str,
    *,
    period: str = "january",
) -> Optional[str]:
    df = _load_exports_timeseries(base_input_dir, scenario, housing_type, county_slug)
    if df is None or df.empty:
        return None
    try:
        import matplotlib.dates as mdates
        window = ("2018-01-01", "2018-01-08") if (period or "january").lower() == "january" else ("2018-07-01", "2018-07-08")
        title_suffix = "January (Winter)" if (period or "january").lower() == "january" else "July (Summer)"
        s = pd.to_numeric(df["exports"], errors="coerce").fillna(0.0)
        if not isinstance(s.index, pd.DatetimeIndex):
            s.index = pd.date_range(start="2018-01-01", periods=len(s), freq="H")
        week = s.loc[window[0]:window[1]]
        fig, ax = plt.subplots(1, 1, figsize=(16, 4))
        ax.plot(week.index, week.values, color="#1f77b4", linewidth=1.8, label="Exports")
        ax.set_ylabel("kWh (hourly)")
        ax.set_title(
            f"Exports to Grid — {title_suffix}\n{county_slug.replace('-', ' ').title()} County — {scenario.replace('_', ' ').title()}",
            fontsize=14,
            fontweight="bold",
        )
        ax.grid(True, alpha=0.3)
        ax.legend(loc="upper right", fontsize=10)
        ax.xaxis.set_major_locator(mdates.DayLocator())
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%m/%d"))
        ax.xaxis.set_minor_locator(mdates.HourLocator(interval=6))
        plt.setp(ax.xaxis.get_majorticklabels(), rotation=45, ha="right")
        plt.tight_layout()
        buf = io.BytesIO()
        plt.savefig(buf, format="png", dpi=150, bbox_inches="tight")
        buf.seek(0)
        b64 = base64.b64encode(buf.getvalue()).decode()
        plt.close()
        return b64
    except Exception as e:
        print(f"Error creating weekly NEM3 exports plot for {county_slug}: {e}")
        return None
# ---------- Dashboard assembly ----------


def _dashboard_html(
    scenario: str,
    housing_type: str,
    county_slug: str,
    deployment_b64: Optional[str],
    appliance_b64: Optional[str],
    weekly_jan_b64: Optional[str],
    weekly_jul_b64: Optional[str],
    enduse_weekly_b64: Optional[str],
    nem3_exports_b64: Optional[str] = None,
    nem3_exports_week_jan_b64: Optional[str] = None,
    nem3_exports_week_jul_b64: Optional[str] = None,
    step18_images: Optional[dict] = None,
    solar_size_html: Optional[str] = None,
    annual_load_html: Optional[str] = None,
    grid_supply_html: Optional[str] = None,
    key_metrics: Optional[dict] = None,
    flows_without: Optional[dict] = None,
    flows_with: Optional[dict] = None,
    cost_breakdowns: Optional[dict] = None,
    assets_info: Optional[dict] = None,
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
                .imgwrap img {{ width: 100%; height: auto; border-radius: 6px; cursor: zoom-in; }}
                .muted {{ color: #666; font-size: 12px; }}
                .metric-value {{ font-size: 24px; font-weight: bold; color: #2c5aa0; line-height: 1.2; }}
                .metric-value small {{ font-size: 12px; color: #666; font-weight: normal; display: block; margin-top: 4px; }}
                /* New: lay out multiple metrics in a single panel */
                .metrics-grid {{
                    display: grid;
                    grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
                    gap: 12px;
                    align-items: stretch;
                }}
                .metric-block {{
                    background: #fbfbfb;
                    border: 1px solid #eee;
                    border-radius: 8px;
                    padding: 16px;
                    text-align: center;
                }}
                /* With-vs-Without table */
                .kmtbl {{ width: 100%; border-collapse: collapse; }}
                .kmtbl th, .kmtbl td {{ padding: 10px 12px; border-bottom: 1px solid #eee; }}
                .kmtbl th {{ text-align: center; font-weight: 600; color: #2c3e50; }}
                .kmtbl td {{ text-align: center; }}
                .kmtbl td:first-child {{ text-align: left; color: #666; width: 40%; }}
                .val {{ font-weight: 700; color: #2c5aa0; }}
                .formula {{ color: #888; font-size: 11px; margin-top: 2px; }}
                .money {{ color: #1a5; font-weight: 700; }}
                /* Highlight for minimum cost cell in plan table */
                .highlight-min {{ background: #eaffea; }}
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
            f"<div class=\"imgwrap\"><a href=\"data:image/png;base64,{appliance_b64}\" target=\"_blank\" rel=\"noopener noreferrer\"><img src=\"data:image/png;base64,{appliance_b64}\" alt=\"appliance breakdown\"/></a></div>"
        )
    else:
        parts.append("<div class=\"muted\">No appliance chart available</div>")
    parts.append("</div>")

    

    # Card 2: Key metrics — With vs Without Solar+Storage
    parts.append("<div class=\"card\">")
    parts.append("<h2>Key Metrics — With vs Without Solar+Storage</h2>")
    if key_metrics:
        w = key_metrics.get("with", {})
        wo = key_metrics.get("without", {})
        def fmt(val, unit=""):
            try:
                if val is None:
                    return "N/A"
                if unit == "kWh":
                    return f"{float(val):,.0f}"
                if unit == "kW":
                    return f"{float(val):,.1f}"
                return str(val)
            except Exception:
                return "N/A"
        parts.append("<table class=\"kmtbl\">")
        parts.append("<thead><tr><th>Metric</th><th>With Solar+Storage</th><th>Without Solar+Storage</th></tr></thead>")
        parts.append("<tbody>")
        # Solar size with formula (raw values from electrified_assets.csv)
        if assets_info:
            with_solar_kw = assets_info.get('Solar Capacity (kW)')
        else:
            with_solar_kw = w.get('solar_kw')
        parts.append(
            f"<tr><td>Solar System Size<div class=\"formula\">from Step 9 capacity: 'Solar Capacity (kW)'</div></td><td class=\"val\">{with_solar_kw if with_solar_kw is not None else 'N/A'} kW</td><td class=\"val\">0 kW</td></tr>"
        )
        # Battery capacity (raw values from electrified_assets.csv)
        if assets_info:
            print("A")
            with_batt_kwh = assets_info.get('Battery Capacity (kWh)')
        else:
            print("B")
            with_batt_kwh = w.get('battery_kwh')
        parts.append(
            f"<tr><td>Battery Capacity<div class=\"formula\">from Step 9 capacity: 'Battery Capacity (kWh)'</div></td><td class=\"val\">{with_batt_kwh if with_batt_kwh is not None else 'N/A'} kWh</td><td class=\"val\">0 kWh</td></tr>"
        )
        parts.append(
            f"<tr><td>Annual Household Load</td><td class=\"val\">{fmt(w.get('annual_load_kwh'), 'kWh')} kWh</td><td class=\"val\">{fmt(wo.get('annual_load_kwh'), 'kWh')} kWh</td></tr>"
        )
        parts.append(
            f"<tr><td>Grid Supply to Load</td><td class=\"val\">{fmt(w.get('grid_to_load_kwh'), 'kWh')} kWh</td><td class=\"val\">{fmt(wo.get('grid_to_load_kwh'), 'kWh')} kWh</td></tr>"
        )
        parts.append("</tbody></table>")
        parts.append("<div class=\"muted\" style=\"margin-top:6px;\">Note: 'Without' assumes no PV or battery; grid serves entire load.</div>")
    else:
        # Fallback to prior single-metric layout if key metrics unavailable
        parts.append("<div class=\"metrics-grid\">")
        # Solar system size
        parts.append("<div class=\"metric-block\">")
        parts.append("<div class=\"muted\">Solar System Size</div>")
        parts.append(solar_size_html or "<div class=\"metric-value\">N/A<br><small>No data</small></div>")
        parts.append("</div>")
        # Annual household load
        parts.append("<div class=\"metric-block\">")
        parts.append("<div class=\"muted\">Annual Household Load</div>")
        parts.append(annual_load_html or "<div class=\"metric-value\">N/A<br><small>No data</small></div>")
        parts.append("</div>")
        # Grid supply to load
        parts.append("<div class=\"metric-block\">")
        parts.append("<div class=\"muted\">Grid Supply to Load</div>")
        parts.append(grid_supply_html or "<div class=\"metric-value\">N/A<br><small>No data</small></div>")
        parts.append("</div>")
        parts.append("</div>")
    parts.append("</div>")

    # Card 3: Energy Flows — With vs Without Solar+Storage
    parts.append("<div class=\"card\">")
    parts.append("<h2>Energy Flows — With vs Without Solar+Storage</h2>")
    if flows_with or flows_without:
        fw = flows_with or {}
        fwo = flows_without or {}
        def fmt(val, unit=""):
            try:
                if val is None:
                    return "N/A"
                if unit == "kWh":
                    return f"{float(val):,.0f}"
                if unit == "kW":
                    return f"{float(val):,.1f}"
                if unit == "%":
                    return f"{float(val):.1f}%"
                return str(val)
            except Exception:
                return "N/A"
        parts.append("<table class=\"kmtbl\"><thead><tr><th>Metric</th><th>With Solar+Storage</th><th>Without Solar+Storage</th></tr></thead><tbody>")
        rows = [
            ("PV → Load", fw.get('pv_to_load_kwh'), fwo.get('pv_to_load_kwh'), "sum('System to Load')"),
            ("Battery → Load", fw.get('batt_to_load_kwh'), fwo.get('batt_to_load_kwh'), "sum('Battery to Load')"),
            ("Grid → Load", fw.get('grid_to_load_kwh'), fwo.get('grid_to_load_kwh'), "sum('Grid to Load')"),
            ("PV → Battery", fw.get('pv_to_batt_kwh'), fwo.get('pv_to_batt_kwh'), "sum('System to Battery')"),
            ("Grid → Battery", fw.get('grid_to_batt_kwh'), fwo.get('grid_to_batt_kwh'), "sum('Grid to Battery')"),
            (
                "PV → Grid (Exports)",
                fw.get('pv_exports_kwh'),
                fwo.get('pv_exports_kwh'),
                fw.get('pv_exports_formula') or "sum('System to Grid') or sum('PV AC (kWh)') − sum('System to Load') − sum('System to Battery')",
            ),
            ("Total Grid Purchases", fw.get('total_grid_purchases_kwh'), fwo.get('total_grid_purchases_kwh'), "sum('Grid to Load') + sum('Grid to Battery')"),
            ("Self‑sufficiency", fw.get('self_sufficiency_pct'), fwo.get('self_sufficiency_pct'), "1 − sum('Grid to Load') / sum('Load Profile')"),
            ("Peak Net Load", fw.get('peak_net_load_kw'), fwo.get('peak_net_load_kw'), "max('Load Profile' − 'System to Load' − 'Battery to Load')"),
        ]
        for label, wval, oval, formula in rows:
            unit = '%' if 'Self' in label else ('kW' if 'Peak' in label else 'kWh')
            html_row = (
                f'<tr><td>{label}<div class="formula">{formula}</div></td>'
                f'<td class="val">{fmt(wval, unit)}{(" "+unit) if unit!="%" else ""}</td>'
                f'<td class="val">{fmt(oval, unit)}{(" "+unit) if unit!="%" else ""}</td></tr>'
            )
            parts.append(html_row)
        parts.append("</tbody></table>")
    else:
        parts.append("<div class=\"muted\">No energy flow data available</div>")
    parts.append("</div>")

    # Card 5: Annual Costs by Rate Plan (Electricity + Gas)
    parts.append("<div class=\"card\">")
    parts.append("<h2>Annual Costs by Rate Plan</h2>")
    if cost_breakdowns and cost_breakdowns.get("electricity"):
        e = cost_breakdowns["electricity"]
        retail = e.get("retail", {})
        nem3 = e.get("nem3", {})
        all_plans = sorted(set(list(retail.keys()) + list(nem3.keys())))
        def fmt_money(x):
            try:
                return f"${float(x):,.0f}"
            except Exception:
                return "N/A"
        # Determine which electricity column to highlight: prefer NEM3; fallback to Retail if NEM3 empty
        min_nem3_plan = None
        min_retail_plan = None
        if nem3:
            try:
                min_nem3_plan = min(nem3, key=lambda k: nem3[k])
            except Exception:
                min_nem3_plan = None
        if retail:
            try:
                min_retail_plan = min(retail, key=lambda k: retail[k])
            except Exception:
                min_retail_plan = None
        parts.append(
            "<table class=\"kmtbl\"><thead><tr>"
            "<th>Plan</th>"
            "<th>Retail (imports only)</th>"
            "<th>NEM3 (imports on plan + ACC credits)</th>"
            "</tr></thead><tbody>"
        )
        for p in all_plans:
            r = retail.get(p)
            n = nem3.get(p)
            retail_classes = ["money"]
            nem3_classes = ["money"]
            # Highlight logic: prefer highlighting NEM3 minimum; if NEM3 absent, highlight Retail minimum
            if min_nem3_plan and p == min_nem3_plan:
                nem3_classes.append("highlight-min")
            elif not min_nem3_plan and min_retail_plan and p == min_retail_plan:
                retail_classes.append("highlight-min")
            parts.append(
                f"<tr><td>{p}</td>"
                f"<td class=\"{' '.join(retail_classes)}\">{fmt_money(r) if r is not None else '—'}</td>"
                f"<td class=\"{' '.join(nem3_classes)}\">{fmt_money(n) if n is not None else '—'}</td></tr>"
            )
        parts.append("</tbody></table>")
        parts.append("<div class=\"muted\" style=\"margin-top:6px;\">NEM3 applies export credits at ACC; retail shows import-only bill.</div>")
    else:
        parts.append("<div class=\"muted\">No electricity plan data available</div>")
    # Gas section — its own table with G-1 entry
    gas = (cost_breakdowns or {}).get("gas", {})
    # Try to locate a key that corresponds to 'G-1' robustly
    g1_key = None
    for k in gas.keys():
        try:
            if str(k).lower().replace("_", "-") == "g-1":
                g1_key = k
                break
        except Exception:
            continue
    parts.append("<div class=\"muted\" style=\"margin-top:12px; font-weight:600;\">Gas</div>")
    parts.append("<table class=\"kmtbl\"><thead><tr><th>Plan</th><th>Annual Cost</th></tr></thead><tbody>")
    def fmt_money_local(x):
        try:
            return f"${float(x):,.0f}"
        except Exception:
            return "N/A"
    if gas:
        val = gas.get(g1_key) if g1_key is not None else None
        parts.append(
            f"<tr><td>G-1</td><td class=\"money\">{fmt_money_local(val) if val is not None else '—'}</td></tr>"
        )
    else:
        parts.append("<tr><td colspan=2 class=\"muted\">No gas plan data available</td></tr>")
    parts.append("</tbody></table>")
    parts.append("</div>")

    # Card 7: Deployment figure
    parts.append("<div class=\"card\">")
    parts.append("<h2>Solar + Storage Deployment</h2>")
    if deployment_b64:
        parts.append(
            f"<div class=\"imgwrap\"><a href=\"data:image/png;base64,{deployment_b64}\" target=\"_blank\" rel=\"noopener noreferrer\"><img src=\"data:image/png;base64,{deployment_b64}\" alt=\"deployment\"/></a></div>"
        )
    else:
        parts.append("<div class=\"muted\">No deployment figure available</div>")
    parts.append("</div>")

    # Card 8: Weekly chart — January
    parts.append("<div class=\"card\">")
    parts.append("<h2>Load & Solar — January (First Week)</h2>")
    if weekly_jan_b64:
        parts.append(
            f"<div class=\"imgwrap\"><a href=\"data:image/png;base64,{weekly_jan_b64}\" target=\"_blank\" rel=\"noopener noreferrer\"><img src=\"data:image/png;base64,{weekly_jan_b64}\" alt=\"weekly january\"/></a></div>"
        )
    else:
        parts.append("<div class=\"muted\">No January weekly figure available</div>")
    parts.append("</div>")

    # Card 9: Weekly chart — July
    parts.append("<div class=\"card\">")
    parts.append("<h2>Load & Solar — July (First Week)</h2>")
    if weekly_jul_b64:
        parts.append(
            f"<div class=\"imgwrap\"><a href=\"data:image/png;base64,{weekly_jul_b64}\" target=\"_blank\" rel=\"noopener noreferrer\"><img src=\"data:image/png;base64,{weekly_jul_b64}\" alt=\"weekly july\"/></a></div>"
        )
    else:
        parts.append("<div class=\"muted\">No July weekly figure available</div>")
    parts.append("</div>")

    # Card 10: Electric Load by End‑Use — Real + Simulated (Jan/Jul)
    parts.append("<div class=\"card\">")
    parts.append("<h2>Electric Load by End‑Use — Real + Simulated (First Week Jan & Jul)</h2>")
    if enduse_weekly_b64:
        parts.append(
            f"<div class=\"imgwrap\"><a href=\"data:image/png;base64,{enduse_weekly_b64}\" target=\"_blank\" rel=\"noopener noreferrer\"><img src=\"data:image/png;base64,{enduse_weekly_b64}\" alt=\"enduse weekly jan+jul\"/></a></div>"
        )
        parts.append("<div class=\"muted\">Granularity: 15‑minute if available, else hourly.</div>")
    else:
        parts.append("<div class=\"muted\">No end‑use breakdown data available</div>")
    parts.append("</div>")

    # Card 11: Exports to Grid (NEM3)
    parts.append("<div class=\"card\">")
    parts.append("<h2>Exports to Grid (NEM3)</h2>")
    if nem3_exports_b64:
        parts.append(
            f"<div class=\"imgwrap\"><a href=\"data:image/png;base64,{nem3_exports_b64}\" target=\"_blank\" rel=\"noopener noreferrer\"><img src=\"data:image/png;base64,{nem3_exports_b64}\" alt=\"NEM3 exports\"/></a></div>"
        )
        parts.append("<div class=\"muted\">Top: daily exports; Bottom: monthly totals.</div>")
    else:
        parts.append("<div class=\"muted\">No exports data available</div>")
    parts.append("</div>")

    # Card 12: Exports — January (First Week)
    parts.append("<div class=\"card\">")
    parts.append("<h2>Exports to Grid — January (First Week)</h2>")
    if nem3_exports_week_jan_b64:
        parts.append(
            f"<div class=\"imgwrap\"><a href=\"data:image/png;base64,{nem3_exports_week_jan_b64}\" target=\"_blank\" rel=\"noopener noreferrer\"><img src=\"data:image/png;base64,{nem3_exports_week_jan_b64}\" alt=\"NEM3 exports January\"/></a></div>"
        )
    else:
        parts.append("<div class=\"muted\">No January exports data available</div>")
    parts.append("</div>")

    # Card 13: Exports — July (First Week)
    parts.append("<div class=\"card\">")
    parts.append("<h2>Exports to Grid — July (First Week)</h2>")
    if nem3_exports_week_jul_b64:
        parts.append(
            f"<div class=\"imgwrap\"><a href=\"data:image/png;base64,{nem3_exports_week_jul_b64}\" target=\"_blank\" rel=\"noopener noreferrer\"><img src=\"data:image/png;base64,{nem3_exports_week_jul_b64}\" alt=\"NEM3 exports July\"/></a></div>"
        )
    else:
        parts.append("<div class=\"muted\">No July exports data available</div>")
    parts.append("</div>")

    # Step 18 cross-scenario comparison cards
    if step18_images:
        for title, b64 in step18_images.items():
            parts.append("<div class=\"card\">")
            parts.append(f"<h2>{title}</h2>")
            if b64:
                parts.append(
                    f"<div class=\"imgwrap\"><a href=\"data:image/png;base64,{b64}\" target=\"_blank\" rel=\"noopener noreferrer\"><img src=\"data:image/png;base64,{b64}\" alt=\"{title}\"/></a></div>"
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
            # Weekly charts, split per period
            weekly_jan_b64 = create_weekly_chart_for_period(
                base_input_dir, scenario, housing_type, county_slug, period="january"
            )
            weekly_jul_b64 = create_weekly_chart_for_period(
                base_input_dir, scenario, housing_type, county_slug, period="july"
            )
            # End‑use breakdown charts (real vs simulated, Jan & Jul)
            enduse_weekly_b64 = create_enduse_breakdown_weekly(
                base_input_dir, scenario, housing_type, county_slug
            )
            # NEM3 exports plot
            nem3_exports_b64 = create_nem3_exports_plot(
                base_input_dir, scenario, housing_type, county_slug
            )
            # NEM3 exports weekly charts
            nem3_exports_week_jan_b64 = create_nem3_exports_weekly_chart_for_period(
                base_input_dir, scenario, housing_type, county_slug, period="january"
            )
            nem3_exports_week_jul_b64 = create_nem3_exports_weekly_chart_for_period(
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
            # With vs Without key metrics
            key_metrics = compute_key_metrics(
                base_input_dir, scenario, housing_type, county_slug
            )
            # Detailed energy flows (before/with)
            flows_with = compute_energy_flow_metrics(
                base_input_dir, scenario, housing_type, county_slug
            )
            flows_without = compute_energy_flow_metrics_without(
                base_input_dir, scenario, housing_type, county_slug
            )
            # Annual cost breakdowns (electricity vs gas, and plans)
            cost_breakdowns = compute_cost_breakdowns(
                base_input_dir, scenario, housing_type, county_slug
            )
            # PV & Storage capacities from electrified_assets.csv
            assets_info = compute_assets_info(
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
                enduse_weekly_b64=enduse_weekly_b64,
                nem3_exports_b64=nem3_exports_b64,
                nem3_exports_week_jan_b64=nem3_exports_week_jan_b64,
                nem3_exports_week_jul_b64=nem3_exports_week_jul_b64,
                step18_images=step18,
                solar_size_html=solar_size_html,
                annual_load_html=annual_load_html,
                grid_supply_html=grid_supply_html,
                key_metrics=key_metrics,
                flows_without=flows_without,
                flows_with=flows_with,
                cost_breakdowns=cost_breakdowns,
                assets_info=assets_info,
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
    parser.add_argument(
        "--no-open",
        action="store_true",
        help="Do not automatically open the generated dashboard in a browser",
    )
    args = parser.parse_args()

    if not args.counties:
        # Fallback to a single representative county if none specified
        args.counties = ["alameda"]

    written = process(
        base_input_dir=args.base_input_dir,
        output_dir=args.output_dir,
        housing_type=args.housing_type,
        scenario=args.scenario,
        counties=args.counties,
    )
    # Auto-open the first generated dashboard unless disabled
    try:
        if not args.no_open and written:
            import webbrowser
            from pathlib import Path

            first = Path(written[0]).resolve().as_uri()
            print(f"Opening dashboard in browser: {first}")
            webbrowser.open_new_tab(first)
    except Exception as e:
        print(f"Warning: Could not open dashboard automatically: {e}")


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
        "Annualized Cost — No Solar+Storage": os.path.join(output_dir, f"step20_eac_no_pv_stacked_bar_g{sha}.png"),
    }
    out = {}
    for title, path in files.items():
        out[title] = _embed_png_as_b64(path)
    # prune empty
    return {k: v for k, v in out.items() if v}


if __name__ == "__main__":
    main()
# ---------- NEM3 exports plot (new card) ----------
