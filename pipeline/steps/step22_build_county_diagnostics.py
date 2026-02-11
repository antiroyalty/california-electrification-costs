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
import json
import os
import re
import glob
from typing import Iterable, List, Optional, Tuple, Dict
from datetime import datetime

import pandas as pd

from helpers.main_helpers import (
    git_short_sha,
    slugify_county_name,
)
from helpers.diagnostics_data import (
    compute_assets_info,
    compute_cost_breakdowns,
    compute_energy_flow_metrics,
    compute_energy_flow_metrics_without,
    compute_key_metrics,
    compute_npv_details,
    lookup_pv_size_kw,
    read_coopt_capacities,
)
from helpers.diagnostics_cost_plots import (
    create_cost_waterfall_chart,
    create_price_signal_overlay_chart,
    estimate_storage_value_upper_bound,
)
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


def _is_coopt_scenario(scenario: str) -> bool:
    return str(scenario).endswith("_coopt")


def create_coopt_results_card(
    base_input_dir: str,
    scenario: str,
    housing_type: str,
    county_slug: str,
) -> str:
    """Create a card summarizing Step 9b co-optimization results for the county.

    Shows PV size (kW), Battery size (kWh), and dispatch flags.
    If scenario is not a *_coopt variant or data is missing, returns an N/A card.
    """
    if not _is_coopt_scenario(scenario):
        return "<div class='muted'>N/A — Not a co-optimization scenario</div>"
    results = read_coopt_capacities(base_input_dir, scenario, housing_type, county_slug)
    if not results:
        return "<div class='muted'>N/A — Co-optimization results not found</div>"
    def fmt_bool(x):
        return "Yes" if x is True else ("No" if x is False else "—")
    def fmt_usd(x):
        return f"${x:,.0f}" if isinstance(x, (int, float)) else "—"
    pv = results.get("solar_kw")
    bat = results.get("battery_kwh")
    bat_kw = results.get("battery_kw")
    grid_ch = results.get("allow_grid_charging")
    batt_exp = results.get("allow_batt_export")
    total_cost = results.get("coopt_total_cost")
    capex_annual = results.get("coopt_capex_annual")
    import_cost = results.get("coopt_import_cost")
    export_credit = results.get("coopt_export_credit")
    degrade_cost = results.get("coopt_degradation_cost")
    pv_str = f"{pv:.2f} kW" if isinstance(pv, (int, float)) else "—"
    bat_str = f"{bat:.2f} kWh" if isinstance(bat, (int, float)) else "—"
    bat_kw_str = f"{bat_kw:.2f} kW" if isinstance(bat_kw, (int, float)) else "—"
    total_cost_str = fmt_usd(total_cost)
    capex_str = fmt_usd(capex_annual)
    import_str = fmt_usd(import_cost)
    export_str = fmt_usd(export_credit)
    degrade_str = fmt_usd(degrade_cost)

    storage_value_str = "—"
    storage_value = None
    try:
        storage_value = estimate_storage_value_upper_bound(base_input_dir, scenario, housing_type, county_slug)
    except Exception:
        storage_value = None
    if isinstance(storage_value, (int, float)):
        storage_value_str = fmt_usd(storage_value)
    return (
        "<div class='metrics-grid metrics-grid-compact'>"
        f"<div class='metric-block'><div class='muted'>PV Size (co‑opt)</div><div class='metric-value'>{pv_str}</div></div>"
        f"<div class='metric-block'><div class='muted'>Battery Size (co‑opt)</div><div class='metric-value'>{bat_str}</div></div>"
        f"<div class='metric-block'><div class='muted'>Battery Power (co‑opt)</div><div class='metric-value'>{bat_kw_str}</div></div>"
        "<div class='metric-block' "
        "title='LP objective (annual): capex_annual + import_cost - export_credit + degradation_cost. "
        "This is not the full household bill.'>"
        f"<div class='muted'>Co‑opt Total Cost</div><div class='metric-value'>{total_cost_str}</div></div>"
        "<div class='metric-block' "
        "title='Upper bound estimate of annual value from shifting PV exports to higher-priced hours (24h look-ahead, PV-only, 96% RTE). "
        "Requires coopt_price_series_<county>.csv from --debug-prices.'>"
        f"<div class='muted'>Storage Value (24h upper bound)</div><div class='metric-value'>{storage_value_str}</div></div>"
        f"<div class='metric-block'><div class='muted'>Capex Annual</div><div class='metric-value'>{capex_str}</div></div>"
        f"<div class='metric-block'><div class='muted'>Import Cost</div><div class='metric-value'>{import_str}</div></div>"
        f"<div class='metric-block'><div class='muted'>Export Credit</div><div class='metric-value'>{export_str}</div></div>"
        f"<div class='metric-block'><div class='muted'>Degradation Cost</div><div class='metric-value'>{degrade_str}</div></div>"
        f"<div class='metric-block'><div class='muted'>Battery Exports</div><div class='metric-value'>{fmt_bool(batt_exp)}<small>allow_batt_export</small></div></div>"
        f"<div class='metric-block'><div class='muted'>Grid Charging</div><div class='metric-value'>{fmt_bool(grid_ch)}<small>allow_grid_charging</small></div></div>"
        "</div>"
    )


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


def _find_coopt_batt_capex_sweep_png(county_dir: str, county_slug: str) -> Optional[str]:
    path = os.path.join(county_dir, f"coopt_batt_capex_sweep_{county_slug}.png")
    return path if os.path.exists(path) else None


def _find_coopt_batt_cost_heatmap_png(county_dir: str, county_slug: str) -> Optional[str]:
    path = os.path.join(county_dir, f"coopt_batt_cost_heatmap_{county_slug}.png")
    return path if os.path.exists(path) else None


def _find_coopt_pv_batt_cost_heatmap_png(county_dir: str, county_slug: str) -> Optional[str]:
    path = os.path.join(county_dir, f"coopt_pv_batt_cost_heatmap_{county_slug}.png")
    return path if os.path.exists(path) else None


def _find_coopt_batt_size_vs_capex_by_pv_png(county_dir: str, county_slug: str) -> Optional[str]:
    path = os.path.join(county_dir, f"coopt_batt_size_vs_capex_by_pv_{county_slug}.png")
    return path if os.path.exists(path) else None


def _find_coopt_objective_vs_capex_by_pv_png(county_dir: str, county_slug: str) -> Optional[str]:
    path = os.path.join(county_dir, f"coopt_objective_vs_capex_by_pv_{county_slug}.png")
    return path if os.path.exists(path) else None


def _find_coopt_pv_size_vs_capex_by_pv_png(county_dir: str, county_slug: str) -> Optional[str]:
    path = os.path.join(county_dir, f"coopt_pv_size_vs_capex_by_pv_{county_slug}.png")
    return path if os.path.exists(path) else None


def _find_coopt_batt_adoption_curve_png(county_dir: str, county_slug: str) -> Optional[str]:
    path = os.path.join(county_dir, f"coopt_batt_adoption_curve_{county_slug}.png")
    return path if os.path.exists(path) else None


def create_coopt_batt_capex_sweep_chart(
    base_input_dir: str,
    scenario: str,
    housing_type: str,
    county_slug: str,
) -> Optional[str]:
    county_dir = os.path.join(base_input_dir, scenario, housing_type, county_slug)
    png = _find_coopt_batt_capex_sweep_png(county_dir, county_slug)
    if not png:
        return None
    try:
        with open(png, "rb") as f:
            return base64.b64encode(f.read()).decode("utf-8")
    except Exception:
        return None


def create_coopt_batt_cost_heatmap_chart(
    base_input_dir: str,
    scenario: str,
    housing_type: str,
    county_slug: str,
) -> Optional[str]:
    county_dir = os.path.join(base_input_dir, scenario, housing_type, county_slug)
    png = _find_coopt_batt_cost_heatmap_png(county_dir, county_slug)
    if not png:
        return None
    try:
        with open(png, "rb") as f:
            return base64.b64encode(f.read()).decode("utf-8")
    except Exception:
        return None


def create_coopt_pv_batt_cost_heatmap_chart(
    base_input_dir: str,
    scenario: str,
    housing_type: str,
    county_slug: str,
) -> Optional[str]:
    county_dir = os.path.join(base_input_dir, scenario, housing_type, county_slug)
    png = _find_coopt_pv_batt_cost_heatmap_png(county_dir, county_slug)
    if not png:
        return None
    try:
        with open(png, "rb") as f:
            return base64.b64encode(f.read()).decode("utf-8")
    except Exception:
        return None


def create_coopt_batt_size_vs_capex_by_pv_chart(
    base_input_dir: str,
    scenario: str,
    housing_type: str,
    county_slug: str,
) -> Optional[str]:
    county_dir = os.path.join(base_input_dir, scenario, housing_type, county_slug)
    png = _find_coopt_batt_size_vs_capex_by_pv_png(county_dir, county_slug)
    if not png:
        return None
    try:
        with open(png, "rb") as f:
            return base64.b64encode(f.read()).decode("utf-8")
    except Exception:
        return None


def create_coopt_objective_vs_capex_by_pv_chart(
    base_input_dir: str,
    scenario: str,
    housing_type: str,
    county_slug: str,
) -> Optional[str]:
    county_dir = os.path.join(base_input_dir, scenario, housing_type, county_slug)
    png = _find_coopt_objective_vs_capex_by_pv_png(county_dir, county_slug)
    if not png:
        return None
    try:
        with open(png, "rb") as f:
            return base64.b64encode(f.read()).decode("utf-8")
    except Exception:
        return None


def create_coopt_pv_size_vs_capex_by_pv_chart(
    base_input_dir: str,
    scenario: str,
    housing_type: str,
    county_slug: str,
) -> Optional[str]:
    county_dir = os.path.join(base_input_dir, scenario, housing_type, county_slug)
    png = _find_coopt_pv_size_vs_capex_by_pv_png(county_dir, county_slug)
    if not png:
        return None
    try:
        with open(png, "rb") as f:
            return base64.b64encode(f.read()).decode("utf-8")
    except Exception:
        return None


def create_coopt_batt_adoption_curve_chart(
    base_input_dir: str,
    scenario: str,
    housing_type: str,
    county_slug: str,
) -> Optional[str]:
    county_dir = os.path.join(base_input_dir, scenario, housing_type, county_slug)
    png = _find_coopt_batt_adoption_curve_png(county_dir, county_slug)
    if not png:
        return None
    try:
        with open(png, "rb") as f:
            return base64.b64encode(f.read()).decode("utf-8")
    except Exception:
        return None


def _parse_pv_capex_from_filename(path: str) -> Optional[float]:
    name = os.path.basename(path)
    m = re.search(r"_pv([0-9]+(?:p[0-9]+)?)\.png$", name)
    if not m:
        return None
    token = m.group(1).replace("p", ".")
    try:
        return float(token)
    except Exception:
        return None


def _collect_pv_capex_sweep_images(
    county_dir: str,
    county_slug: str,
    prefix: str,
) -> Dict[float, str]:
    pattern = os.path.join(county_dir, f"{prefix}_{county_slug}_pv*.png")
    out: Dict[float, str] = {}
    for path in glob.glob(pattern):
        capex = _parse_pv_capex_from_filename(path)
        if capex is None:
            continue
        b64 = _embed_png_as_b64(path)
        if b64:
            out[capex] = b64
    return out


def create_coopt_pv_capex_sweep_gallery(
    base_input_dir: str,
    scenario: str,
    housing_type: str,
    county_slug: str,
) -> List[dict]:
    county_dir = os.path.join(base_input_dir, scenario, housing_type, county_slug)
    sweep_batt_cost = _collect_pv_capex_sweep_images(county_dir, county_slug, "coopt_batt_cost_heatmap")
    sweep_pv_batt = _collect_pv_capex_sweep_images(county_dir, county_slug, "coopt_pv_batt_cost_heatmap")

    caps = sorted({*sweep_batt_cost.keys(), *sweep_pv_batt.keys()})
    gallery = []
    for cap in caps:
        images = {}
        if cap in sweep_batt_cost:
            images["Battery Cost Heatmap"] = sweep_batt_cost[cap]
        if cap in sweep_pv_batt:
            images["PV × Battery Heatmap"] = sweep_pv_batt[cap]
        if images:
            gallery.append({"capex": cap, "images": images})
    return gallery


def _load_best_of_pv_capex_sweep(
    base_input_dir: str,
    scenario: str,
    housing_type: str,
    county_slug: str,
) -> List[dict]:
    county_dir = os.path.join(base_input_dir, scenario, housing_type, county_slug)
    pattern = os.path.join(county_dir, f"coopt_batt_capex_sweep_{county_slug}_pv*.csv")
    rows = []
    for path in glob.glob(pattern):
        capex = _parse_pv_capex_from_filename(path)
        if capex is None:
            continue
        try:
            df = pd.read_csv(path)
        except Exception:
            continue
        required = {"battery_capex_kwh", "pv_kw", "batt_kwh", "total_cost"}
        if not required.issubset(set(df.columns)) or df.empty:
            continue
        best = df.loc[pd.to_numeric(df["total_cost"], errors="coerce").idxmin()]
        rows.append(
            {
                "pv_capex": float(capex),
                "battery_capex_kwh": float(best["battery_capex_kwh"]),
                "pv_kw": float(best["pv_kw"]),
                "batt_kwh": float(best["batt_kwh"]),
                "total_cost": float(best["total_cost"]),
            }
        )
    return sorted(rows, key=lambda r: r["pv_capex"])
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




def create_npv_card(npv_details: Optional[dict]) -> str:
    if not npv_details:
        return "<div class='muted'>No NPV data available</div>"

    def fmt_money(val: Optional[float]) -> str:
        try:
            if val is None:
                return "N/A"
            return f"${float(val):,.0f}"
        except Exception:
            return "N/A"

    def fmt_rate(val: Optional[float]) -> str:
        try:
            if val is None:
                return "N/A"
            return f"{float(val):.2%}"
        except Exception:
            return "N/A"

    h = npv_details.get("horizon_years")
    r = npv_details.get("discount_rate")
    s = npv_details.get("solar_storage", {})
    a = npv_details.get("all_electrification", {})

    parts = []
    parts.append("<div class='method-section'>")
    parts.append("<div class='method-label'>Formula</div>")
    parts.append("<div class='mono'>NPV = -capex + sum_{t=1..N} savings_t / (1 + r)^t</div>")
    parts.append("</div>")
    parts.append("<table class='kmtbl'>")
    parts.append("<thead><tr><th>Case</th><th>NPV</th><th>Net Capex</th><th>Annual Savings</th></tr></thead>")
    parts.append("<tbody>")
    parts.append(
        "<tr>"
        "<td>Solar + Storage Only</td>"
        f"<td class='money'>{fmt_money(s.get('npv'))}</td>"
        f"<td class='money'>{fmt_money(s.get('net_capex'))}</td>"
        f"<td class='money'>{fmt_money(s.get('annual_savings'))}</td>"
        "</tr>"
    )
    parts.append(
        "<tr>"
        "<td>All Electrification</td>"
        f"<td class='money'>{fmt_money(a.get('npv'))}</td>"
        f"<td class='money'>{fmt_money(a.get('net_capex'))}</td>"
        f"<td class='money'>{fmt_money(a.get('annual_savings'))}</td>"
        "</tr>"
    )
    parts.append("</tbody></table>")
    parts.append(
        f"<div class='muted'>Horizon: {h} years; Discount rate: {fmt_rate(r)}. "
        "Savings definitions: "
        f"Solar+Storage uses {s.get('savings_definition')}; "
        f"All Electrification uses {a.get('savings_definition')}.</div>"
    )
    return "".join(parts)


def _load_methods_manifest() -> Optional[dict]:
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    path = os.path.join(root, "docs", "methods.yaml")
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"Warning: could not load methods manifest: {e}")
        return None


def _render_methods_manifest(methods: Optional[dict]) -> str:
    if not methods:
        return "<div class='muted'>Methods manifest not available</div>"

    def render_table(section: str, data: dict) -> str:
        if not data:
            return ""
        rows = []
        for k, v in data.items():
            rows.append(f"<tr><td class='method-key'>{k}</td><td>{v}</td></tr>")
        return (
            f"<div class='method-section'><div class='method-label'>{section}</div>"
            "<table class='method-table'>"
            "<tbody>"
            + "".join(rows)
            + "</tbody></table></div>"
        )

    parts: List[str] = []
    for key, entry in methods.items():
        title = entry.get("title") or key
        formula = entry.get("formula")
        assumptions = entry.get("assumptions") or {}
        constants = entry.get("constants") or {}
        data_sources = entry.get("data_sources") or {}
        code_refs = entry.get("code") or []
        notes = entry.get("notes")
        parts.append(f"<details class='method'><summary>{title} ({key})</summary>")
        parts.append("<div class='method-body'>")
        if formula:
            parts.append(
                "<div class='method-section'>"
                "<div class='method-label'>Formula</div>"
                f"<div class='mono'>{formula}</div>"
                "</div>"
            )
        parts.append(render_table("Assumptions", assumptions))
        parts.append(render_table("Constants", constants))
        parts.append(render_table("Data Sources", data_sources))
        if code_refs:
            parts.append("<div class='method-section'><div class='method-label'>Code</div>")
            parts.append("<ul class='code-list'>")
            for ref in code_refs:
                parts.append(f"<li><span class='mono'>{ref}</span></li>")
            parts.append("</ul></div>")
        if notes:
            parts.append(
                "<div class='method-section'>"
                "<div class='method-label'>Notes</div>"
                f"<div>{notes}</div>"
                "</div>"
            )
        parts.append("</div></details>")
    return "".join(parts)


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
    csv_path = os.path.join(county_dir, f"solar_storage_dispatch_profiles_{county_slug}.csv")
    if not os.path.exists(csv_path):
        # Older naming variant
        csv_path = os.path.join(county_dir, f"solar_storage_dispatch_profiles_{scenario}_{county_slug}.csv")
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
        size_kw = lookup_pv_size_kw(base_input_dir, scenario, housing_type, county_slug)
        if size_kw is None:
            return "<div class='metric-value'>N/A<br><small>No PV system</small></div>"
        return f"<div class='metric-value'>{float(size_kw):.1f} kW<br><small>System Size</small></div>"
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
        sam_file = os.path.join(county_dir, f"solar_storage_dispatch_profiles_{county_slug}.csv")
        
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
        sam_file = os.path.join(county_dir, f"solar_storage_dispatch_profiles_{county_slug}.csv")
        
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
        s9_exp = os.path.join(s9_dir, f"solar_storage_dispatch_profiles_with_exports_{county_slug}.csv")
        if os.path.exists(s9_exp):
            try:
                df = pd.read_csv(s9_exp)
                if "Exports to Grid (kWh)" in df.columns:
                    exp = pd.to_numeric(df["Exports to Grid (kWh)"], errors="coerce").fillna(0.0)
                    ts = pd.date_range(start="2018-01-01", periods=len(exp), freq="H")
                    return pd.DataFrame({"exports": exp.values}, index=ts)
            except Exception:
                pass
        s9_base = os.path.join(s9_dir, f"solar_storage_dispatch_profiles_{county_slug}.csv")
        if not os.path.exists(s9_base):
            alt = os.path.join(s9_dir, f"solar_storage_dispatch_profiles_{scenario}_{county_slug}.csv")
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
    coopt_card_html: Optional[str] = None,
    coopt_capex_sweep_b64: Optional[str] = None,
    coopt_cost_heatmap_b64: Optional[str] = None,
    coopt_pv_batt_heatmap_b64: Optional[str] = None,
    coopt_batt_size_vs_capex_by_pv_b64: Optional[str] = None,
    coopt_objective_vs_capex_by_pv_b64: Optional[str] = None,
    coopt_pv_size_vs_capex_by_pv_b64: Optional[str] = None,
    coopt_batt_adoption_curve_b64: Optional[str] = None,
    coopt_pv_capex_gallery: Optional[List[dict]] = None,
    coopt_best_of_summary: Optional[List[dict]] = None,
    cost_waterfall_b64: Optional[str] = None,
    price_signal_b64: Optional[str] = None,
    methods_manifest: Optional[dict] = None,
    npv_details: Optional[dict] = None,
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
                .section {{ background: #fff7e6; border-radius: 8px; box-shadow: 0 1px 3px rgba(0,0,0,.08); padding: 12px; grid-column: 1 / -1; }}
                .section summary {{ cursor: pointer; font-size: 18px; font-weight: 600; color: #b00020; }}
                .section-grid {{ display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 16px; margin-top: 12px; }}
                @media (max-width: 1100px) {{
                    .section-grid {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
                }}
                @media (max-width: 720px) {{
                    .section-grid {{ grid-template-columns: repeat(1, minmax(0, 1fr)); }}
                }}
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
                .metrics-grid-compact {{
                    grid-template-columns: repeat(2, minmax(0, 1fr));
                }}
                .metrics-grid-compact .metric-block {{
                    padding: 12px;
                }}
                .metrics-grid-compact .metric-value {{
                    font-size: 20px;
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
                /* Right-align numeric value cells for better readability */
                .kmtbl td.val {{ text-align: right; }}
                .kmtbl td.money {{ text-align: right; }}
                .val {{ font-weight: 700; color: #2c5aa0; }}
                .formula {{ color: #888; font-size: 11px; margin-top: 2px; }}
                .money {{ color: #1a5; font-weight: 700; }}
                /* Highlight for minimum cost cell in plan table */
                .highlight-min {{ background: #eaffea; }}
                /* Methods manifest */
                .method {{ margin-bottom: 8px; }}
                .method summary {{ cursor: pointer; font-weight: 600; color: #2c3e50; }}
                .method-body {{ margin-top: 6px; }}
                .method-section {{ margin: 6px 0 10px; }}
                .method-label {{ font-size: 12px; font-weight: 600; color: #555; margin-bottom: 4px; }}
                .method-table {{ width: 100%; border-collapse: collapse; font-size: 12px; }}
                .method-table td {{ border-bottom: 1px solid #eee; padding: 4px 6px; vertical-align: top; }}
                .method-key {{ width: 30%; color: #444; }}
                .mono {{ font-family: "Courier New", monospace; font-size: 12px; background: #f5f5f5; padding: 4px 6px; border-radius: 4px; display: inline-block; }}
                .code-list {{ margin: 4px 0 8px 18px; }}
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

    # Energy flows section
    parts.append('<details class="section">')
    parts.append("<summary>Energy Flows</summary>")
    parts.append('<div class="section-grid">')

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

    parts.append("</div>")
    parts.append("</details>")

    # Annual Costs + NPV section
    parts.append('<details class="section">')
    parts.append("<summary>Annual Costs & NPV</summary>")
    parts.append('<div class="section-grid">')

    # Card: NPV
    parts.append("<div class=\"card\">")
    parts.append("<h2>NPV (25-year horizon)</h2>")
    parts.append(create_npv_card(npv_details))
    parts.append("</div>")

    # Card: Cost Waterfall
    parts.append('<div class="card">')
    parts.append("<h2>Annual Cost Waterfall — Solar + Storage</h2>")
    if cost_waterfall_b64:
        parts.append(
            f"<div class=\"imgwrap\"><a href=\"data:image/png;base64,{cost_waterfall_b64}\" target=\"_blank\" rel=\"noopener noreferrer\"><img src=\"data:image/png;base64,{cost_waterfall_b64}\" alt=\"annual cost waterfall\"/></a></div>"
        )
    else:
        parts.append("<div class=\"muted\">No waterfall available (missing annual cost or capex inputs).</div>")
    parts.append("</div>")

    # Card: Annual Costs by Rate Plan (Electricity + Gas)
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

    parts.append("</div>")
    parts.append("</details>")

    # Co-Optimization section
    parts.append('<details class="section">')
    parts.append("<summary>Co-Optimization</summary>")
    parts.append('<div class="section-grid">')

    # Card 2e: Co-Optimization Results (Step 9b)
    parts.append('<div class="card">')
    parts.append("<h2>Co‑Optimization Results (Step 9b)</h2>")
    if coopt_card_html:
        parts.append(coopt_card_html)
    else:
        parts.append('<div class="muted">N/A</div>')
    parts.append("</div>")

    # Card 2f: Co-Optimization Battery Capex Sweep
    parts.append('<div class="card">')
    parts.append("<h2>Battery Capex Sweep — Co‑opt (Step 9b)</h2>")
    if coopt_capex_sweep_b64:
        parts.append(
            f"<div class=\"imgwrap\"><a href=\"data:image/png;base64,{coopt_capex_sweep_b64}\" target=\"_blank\" rel=\"noopener noreferrer\"><img src=\"data:image/png;base64,{coopt_capex_sweep_b64}\" alt=\"coopt battery capex sweep\"/></a></div>"
        )
    else:
        parts.append("<div class=\"muted\">No sweep plot available (run Step 9b with --batt-capex-sweep).</div>")
    parts.append("</div>")

    # Card 2g: Co-Optimization Cost Heatmap (Capex x Battery Size)
    parts.append('<div class="card">')
    parts.append("<h2>Cost Heatmap — Battery Size × Capex (Co‑opt)</h2>")
    if coopt_cost_heatmap_b64:
        parts.append(
            f"<div class=\"imgwrap\"><a href=\"data:image/png;base64,{coopt_cost_heatmap_b64}\" target=\"_blank\" rel=\"noopener noreferrer\"><img src=\"data:image/png;base64,{coopt_cost_heatmap_b64}\" alt=\"coopt cost heatmap\"/></a></div>"
        )
    else:
        parts.append("<div class=\"muted\">No heatmap available (run Step 9b with --batt-capex-sweep and --batt-size-sweep).</div>")
    parts.append("</div>")

    # Card 2g.1: Co-Optimization PV × Battery Cost Heatmap
    parts.append('<div class="card">')
    parts.append("<h2>Cost Heatmap — PV Size × Battery Size (Co‑opt)</h2>")
    if coopt_pv_batt_heatmap_b64:
        parts.append(
            f"<div class=\"imgwrap\"><a href=\"data:image/png;base64,{coopt_pv_batt_heatmap_b64}\" target=\"_blank\" rel=\"noopener noreferrer\"><img src=\"data:image/png;base64,{coopt_pv_batt_heatmap_b64}\" alt=\"coopt pv vs battery heatmap\"/></a></div>"
        )
    else:
        parts.append("<div class=\"muted\">No PV×battery heatmap available (run Step 9b with --pv-size-sweep and --batt-size-sweep).</div>")
    parts.append("</div>")

    # Card 2g.1b: Battery Size vs Battery Capex (PV Capex sweep)
    parts.append('<div class="card">')
    parts.append("<h2>Battery Size vs Battery Capex — PV Capex Sweep</h2>")
    if coopt_batt_size_vs_capex_by_pv_b64:
        parts.append(
            f"<div class=\"imgwrap\"><a href=\"data:image/png;base64,{coopt_batt_size_vs_capex_by_pv_b64}\" target=\"_blank\" rel=\"noopener noreferrer\"><img src=\"data:image/png;base64,{coopt_batt_size_vs_capex_by_pv_b64}\" alt=\"battery size vs capex by pv\"/></a></div>"
        )
    else:
        parts.append("<div class=\"muted\">No PV capex sweep battery-size plot available (run Step 9b with --pv-capex-sweep and --batt-capex-sweep).</div>")
    parts.append("</div>")

    # Card 2g.1b.0: Battery Adoption Curve (NEM 3.0)
    parts.append('<div class="card">')
    parts.append("<h2>Battery Adoption Curve Under NEM 3.0</h2>")
    if coopt_batt_adoption_curve_b64:
        parts.append(
            f"<div class=\"imgwrap\"><a href=\"data:image/png;base64,{coopt_batt_adoption_curve_b64}\" target=\"_blank\" rel=\"noopener noreferrer\"><img src=\"data:image/png;base64,{coopt_batt_adoption_curve_b64}\" alt=\"battery adoption curve\"/></a></div>"
        )
    else:
        parts.append("<div class=\"muted\">No adoption curve available (run Step 9b with --batt-capex-sweep).</div>")
    parts.append("</div>")

    # Card 2g.1b.1: PV Size vs Battery Capex (PV Capex sweep)
    parts.append('<div class="card">')
    parts.append("<h2>PV Size vs Battery Capex — PV Capex Sweep</h2>")
    if coopt_pv_size_vs_capex_by_pv_b64:
        parts.append(
            f"<div class=\"imgwrap\"><a href=\"data:image/png;base64,{coopt_pv_size_vs_capex_by_pv_b64}\" target=\"_blank\" rel=\"noopener noreferrer\"><img src=\"data:image/png;base64,{coopt_pv_size_vs_capex_by_pv_b64}\" alt=\"pv size vs capex by pv\"/></a></div>"
        )
    else:
        parts.append("<div class=\"muted\">No PV capex sweep PV-size plot available (run Step 9b with --pv-capex-sweep and --batt-capex-sweep).</div>")
    parts.append("</div>")

    # Card 2g.1c: Co-Opt Objective vs Battery Capex (PV Capex sweep)
    parts.append('<div class="card">')
    parts.append("<h2>Co‑Opt Objective vs Battery Capex — PV Capex Sweep</h2>")
    if coopt_objective_vs_capex_by_pv_b64:
        parts.append(
            f"<div class=\"imgwrap\"><a href=\"data:image/png;base64,{coopt_objective_vs_capex_by_pv_b64}\" target=\"_blank\" rel=\"noopener noreferrer\"><img src=\"data:image/png;base64,{coopt_objective_vs_capex_by_pv_b64}\" alt=\"objective vs capex by pv\"/></a></div>"
        )
    else:
        parts.append("<div class=\"muted\">No PV capex sweep objective plot available (run Step 9b with --pv-capex-sweep and --batt-capex-sweep).</div>")
    parts.append("</div>")

    # Card 2g.1e: Best-of Summary (PV Capex sweep)
    parts.append('<div class="card">')
    parts.append("<h2>Best‑of Summary — PV Capex Sweep</h2>")
    if coopt_best_of_summary:
        parts.append("<table class=\"kmtbl\"><thead><tr>"
                     "<th>PV Capex ($/kW)</th><th>Best Batt Capex ($/kWh)</th>"
                     "<th>PV Size (kW)</th><th>Battery Size (kWh)</th><th>Min Annual Cost</th>"
                     "</tr></thead><tbody>")
        for row in coopt_best_of_summary:
            parts.append(
                "<tr>"
                f"<td>{row['pv_capex']:.0f}</td>"
                f"<td>{row['battery_capex_kwh']:.0f}</td>"
                f"<td>{row['pv_kw']:.2f}</td>"
                f"<td>{row['batt_kwh']:.2f}</td>"
                f"<td class=\"money\">${row['total_cost']:,.0f}</td>"
                "</tr>"
            )
        parts.append("</tbody></table>")
    else:
        parts.append("<div class=\"muted\">No best‑of summary available (run Step 9b with --pv-capex-sweep and --batt-capex-sweep).</div>")
    parts.append("</div>")

    # Card 2g.2: PV × Battery Heatmaps (PV capex sweep)
    parts.append('<div class="card">')
    parts.append("<h2>PV × Battery Heatmaps — PV Capex Sweep</h2>")
    if coopt_pv_capex_gallery:
        any_pv_batt = False
        for entry in coopt_pv_capex_gallery:
            cap = entry.get("capex")
            b64 = (entry.get("images") or {}).get("PV × Battery Heatmap")
            if not b64:
                continue
            any_pv_batt = True
            parts.append(f"<div class=\"muted\" style=\"font-weight:600; margin-top:8px;\">PV Capex: ${cap:,.0f}/kW</div>")
            parts.append(
                f"<div class=\"imgwrap\"><a href=\"data:image/png;base64,{b64}\" target=\"_blank\" rel=\"noopener noreferrer\"><img src=\"data:image/png;base64,{b64}\" alt=\"PV × Battery Heatmap\"/></a></div>"
            )
        if not any_pv_batt:
            parts.append("<div class=\"muted\">No PV × battery heatmaps available (run Step 9b with --pv-capex-sweep and --pv-size-sweep).</div>")
    else:
        parts.append("<div class=\"muted\">No PV capex sweep plots available (run Step 9b with --pv-capex-sweep).</div>")
    parts.append("</div>")

    # Card 2g.3: Battery Cost Heatmaps (PV capex sweep)
    parts.append('<div class="card">')
    parts.append("<h2>Battery Cost Heatmaps — PV Capex Sweep</h2>")
    if coopt_pv_capex_gallery:
        any_batt_cost = False
        for entry in coopt_pv_capex_gallery:
            cap = entry.get("capex")
            b64 = (entry.get("images") or {}).get("Battery Cost Heatmap")
            if not b64:
                continue
            any_batt_cost = True
            parts.append(f"<div class=\"muted\" style=\"font-weight:600; margin-top:8px;\">PV Capex: ${cap:,.0f}/kW</div>")
            parts.append(
                f"<div class=\"imgwrap\"><a href=\"data:image/png;base64,{b64}\" target=\"_blank\" rel=\"noopener noreferrer\"><img src=\"data:image/png;base64,{b64}\" alt=\"Battery Cost Heatmap\"/></a></div>"
            )
        if not any_batt_cost:
            parts.append("<div class=\"muted\">No battery cost heatmaps available (run Step 9b with --pv-capex-sweep and --batt-size-sweep).</div>")
    else:
        parts.append("<div class=\"muted\">No PV capex sweep plots available (run Step 9b with --pv-capex-sweep).</div>")
    parts.append("</div>")

    parts.append("</div>")
    parts.append("</details>")

    # Weekly flows section
    parts.append('<details class="section">')
    parts.append("<summary>Weekly Flows: Load + Solar + Battery</summary>")
    parts.append('<div class="section-grid">')

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

    parts.append("</div>")
    parts.append("</details>")

    # Exports to Grid section
    parts.append('<details class="section">')
    parts.append("<summary>Exports to Grid</summary>")
    parts.append('<div class="section-grid">')

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

    # Card: Price Signal Overlay
    parts.append('<div class="card">')
    parts.append("<h2>Price Signal Overlay (PV Export Hours)</h2>")
    if price_signal_b64:
        parts.append(
            f"<div class=\"imgwrap\"><a href=\"data:image/png;base64,{price_signal_b64}\" target=\"_blank\" rel=\"noopener noreferrer\"><img src=\"data:image/png;base64,{price_signal_b64}\" alt=\"price signal overlay\"/></a></div>"
        )
    else:
        parts.append("<div class=\"muted\">No price signal plot available (run Step 9b with --debug-prices).</div>")
    parts.append("</div>")

    parts.append("</div>")
    parts.append("</details>")

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

    # Methods (last card)
    parts.append("<div class=\"card\">")
    parts.append("<h2>Methods</h2>")
    parts.append(_render_methods_manifest(methods_manifest))
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
    *,
    open_browser: bool = False,
) -> List[str]:
    """
    Build county dashboards. Returns list of written HTML file paths.
    """
    written: List[str] = []
    sha = git_short_sha()
    methods_manifest = _load_methods_manifest()
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
            coopt_capex_sweep_b64 = create_coopt_batt_capex_sweep_chart(
                base_input_dir, scenario, housing_type, county_slug
            )
            coopt_cost_heatmap_b64 = create_coopt_batt_cost_heatmap_chart(
                base_input_dir, scenario, housing_type, county_slug
            )
            coopt_pv_batt_heatmap_b64 = create_coopt_pv_batt_cost_heatmap_chart(
                base_input_dir, scenario, housing_type, county_slug
            )
            coopt_batt_size_vs_capex_by_pv_b64 = create_coopt_batt_size_vs_capex_by_pv_chart(
                base_input_dir, scenario, housing_type, county_slug
            )
            coopt_objective_vs_capex_by_pv_b64 = create_coopt_objective_vs_capex_by_pv_chart(
                base_input_dir, scenario, housing_type, county_slug
            )
            coopt_pv_size_vs_capex_by_pv_b64 = create_coopt_pv_size_vs_capex_by_pv_chart(
                base_input_dir, scenario, housing_type, county_slug
            )
            coopt_batt_adoption_curve_b64 = create_coopt_batt_adoption_curve_chart(
                base_input_dir, scenario, housing_type, county_slug
            )
            coopt_pv_capex_gallery = create_coopt_pv_capex_sweep_gallery(
                base_input_dir, scenario, housing_type, county_slug
            )
            coopt_best_of_summary = _load_best_of_pv_capex_sweep(
                base_input_dir, scenario, housing_type, county_slug
            )
            cost_waterfall_b64 = create_cost_waterfall_chart(
                base_input_dir, scenario, housing_type, county_slug
            )
            price_signal_b64 = create_price_signal_overlay_chart(
                base_input_dir, scenario, housing_type, county_slug
            )
            npv_details = compute_npv_details(
                base_input_dir,
                scenario,
                housing_type,
                county_slug,
                horizon_years=25,
                discount_rate=0.07,
                incentive="full_incentives",
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
                coopt_card_html=create_coopt_results_card(base_input_dir, scenario, housing_type, county_slug),
                coopt_capex_sweep_b64=coopt_capex_sweep_b64,
                coopt_cost_heatmap_b64=coopt_cost_heatmap_b64,
                coopt_pv_batt_heatmap_b64=coopt_pv_batt_heatmap_b64,
                coopt_batt_size_vs_capex_by_pv_b64=coopt_batt_size_vs_capex_by_pv_b64,
                coopt_objective_vs_capex_by_pv_b64=coopt_objective_vs_capex_by_pv_b64,
                coopt_pv_size_vs_capex_by_pv_b64=coopt_pv_size_vs_capex_by_pv_b64,
                coopt_batt_adoption_curve_b64=coopt_batt_adoption_curve_b64,
                coopt_pv_capex_gallery=coopt_pv_capex_gallery,
                coopt_best_of_summary=coopt_best_of_summary,
                cost_waterfall_b64=cost_waterfall_b64,
                price_signal_b64=price_signal_b64,
                methods_manifest=methods_manifest,
                npv_details=npv_details,
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
    # Optionally open the first generated dashboard in the default browser
    if open_browser and written:
        try:
            import webbrowser
            from pathlib import Path

            first = Path(written[0]).resolve().as_uri()
            print(f"Opening county diagnostics dashboard: {first}")
            webbrowser.open_new_tab(first)
        except Exception as e:
            print(f"Warning: Could not open dashboard automatically: {e}")
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
        open_browser=not args.no_open,
    )
    # process already handles opening when requested


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
    # prune empty and omit LCOE visuals to avoid confusion in diagnostics dashboard
    out = {k: v for k, v in out.items() if v}
    return {k: v for k, v in out.items() if "lcoe" not in k.lower()}


if __name__ == "__main__":
    main()
# ---------- NEM3 exports plot (new card) ----------
