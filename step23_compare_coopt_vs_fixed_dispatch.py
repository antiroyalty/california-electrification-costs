"""
Step 23 — Compare Co‑Optimization (baseline_coopt) vs Fixed Dispatch (baseline)

Outputs per county a compact dashboard and a CSV of key metrics, plus an
aggregated CSV across counties. It focuses on:

- System sizes: PV (kW), Battery (kWh), and co-optimization flags
- Energy flows: annual PV AC, grid imports, exports, self-consumption
- Bills: electricity (Retail or NEM3 variant), gas, and total
- Optional EAC (Equivalent Annual Cost) comparison if inputs available
- Monthly imports/exports bars and a simple weekly overlay for January

The step expects prior steps to have produced:
- Step 9 (baseline) and Step 9b (baseline_coopt) SAM CSVs per county
- Step 10 aggregated loads for rates (imports/exports series)
- Step 11/12 annual bills (RESULTS_* CSVs)
"""

from __future__ import annotations

import argparse
import base64
import io
import os
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Tuple

import matplotlib.pyplot as plt
import pandas as pd

from helpers.main_helpers import (
    get_scenario_path,
    git_short_sha,
    slugify_county_name,
)
from helpers.maps_helpers import get_latest_csv_file
from helpers.utility_helpers import get_utility_for_county

from helpers.plot_scenario_comparison_helper import (
    collect_eac_components_by_county,
)


BASELINE_SCENARIO = "baseline"
COOPT_SCENARIO = "baseline_coopt"


# ---------------- I/O helpers ----------------

def _latest_results_csv(directory: str, prefix: str) -> Optional[str]:
    if not os.path.isdir(directory):
        return None
    try:
        return get_latest_csv_file(directory, prefix)
    except Exception:
        return None


def _electrified_assets_csv(base_input_dir: str, scenario: str, housing_type: str) -> Optional[str]:
    path = os.path.join(
        base_input_dir, scenario, housing_type, "CAPITAL_COSTS", "electrified_assets.csv"
    )
    return path if os.path.exists(path) else None


def _sam_csv_path(base_input_dir: str, scenario: str, housing_type: str, county_slug: str) -> Optional[str]:
    folder = os.path.join(base_input_dir, scenario, housing_type, county_slug)
    c1 = os.path.join(folder, f"sam_optimized_load_profiles_{county_slug}.csv")
    if os.path.exists(c1):
        return c1
    c2 = os.path.join(folder, f"sam_optimized_load_profiles_{scenario}_{county_slug}.csv")
    if os.path.exists(c2):
        return c2
    return None


def _aggregator_csv_path(base_input_dir: str, scenario: str, housing_type: str, county_slug: str) -> Optional[str]:
    folder = os.path.join(base_input_dir, scenario, housing_type, county_slug)
    f = os.path.join(folder, f"loadprofiles_for_rates_{county_slug}.csv")
    return f if os.path.exists(f) else None


# ---------------- Data classes ----------------

@dataclass
class SizeInfo:
    pv_kw: Optional[float]
    batt_kwh: Optional[float]
    allow_grid_charging: Optional[bool]
    allow_batt_export: Optional[bool]


@dataclass
class FlowInfo:
    pv_ac_kwh: float
    grid_to_load_kwh: float
    exports_kwh: float
    self_consumption_ratio: Optional[float]


@dataclass
class CostInfo:
    electricity: Optional[float]
    electricity_plan: Optional[str]
    gas: Optional[float]
    total_bill: Optional[float]


# ---------------- Loaders ----------------

def _read_assets_for_county(
    base_input_dir: str, scenario: str, housing_type: str, county_slug: str
) -> SizeInfo:
    path = _electrified_assets_csv(base_input_dir, scenario, housing_type)
    pv = batt = None
    allow_gc = allow_be = None
    if path and os.path.exists(path):
        try:
            df = pd.read_csv(path)
            # try to find matching row by County or slug
            row = None
            if "County" in df.columns:
                for _, r in df.iterrows():
                    if slugify_county_name(str(r["County"])) == county_slug:
                        row = r
                        break
            if row is None:
                # fallback: first col might be county identifier
                first_col = df.columns[0]
                for _, r in df.iterrows():
                    if slugify_county_name(str(r[first_col])) == county_slug:
                        row = r
                        break
            if row is not None:
                pv = pd.to_numeric(row.get("Solar Capacity (kW)"), errors="coerce")
                batt = pd.to_numeric(row.get("Battery Capacity (kWh)"), errors="coerce")
                # flags available for coopt (Step 9b); may be absent for baseline
                agc = row.get("Allow Grid Charging")
                abe = row.get("Allow Battery Export")
                allow_gc = None if pd.isna(agc) else bool(agc)
                allow_be = None if pd.isna(abe) else bool(abe)
            else:
                print(f"[step23] Size info not found for {county_slug} in {path}")
        except Exception:
            pass
    return SizeInfo(
        pv_kw=float(pv) if pv is not None and not pd.isna(pv) else None,
        batt_kwh=float(batt) if batt is not None and not pd.isna(batt) else None,
        allow_grid_charging=allow_gc,
        allow_batt_export=allow_be,
    )


def _sam_metric_sums(path: Optional[str]) -> Dict[str, float]:
    out = {
        "PV AC (kWh)": 0.0,
        "Grid to Load": 0.0,
        "PV to Grid (kWh)": 0.0,
        "Battery to Grid (kWh)": 0.0,
        "System to Battery": 0.0,
        "System to Load": 0.0,
    }
    if not path or not os.path.exists(path):
        return out
    try:
        df = pd.read_csv(path)
        for col in out.keys():
            if col in df.columns:
                out[col] = float(pd.to_numeric(df[col], errors="coerce").fillna(0.0).sum())
    except Exception:
        pass
    return out


def _flow_info_from_sources(
    base_input_dir: str,
    scenario: str,
    housing_type: str,
    county_slug: str,
) -> FlowInfo:
    # Prefer Step 10 aggregator for imports/exports, backed by Step 9 sums
    sam_path = _sam_csv_path(base_input_dir, scenario, housing_type, county_slug)
    agg_path = _aggregator_csv_path(base_input_dir, scenario, housing_type, county_slug)
    sums = _sam_metric_sums(sam_path)

    pv_ac = sums.get("PV AC (kWh)", 0.0)
    grid_to_load = sums.get("Grid to Load", 0.0)

    exports = 0.0
    if agg_path and os.path.exists(agg_path):
        try:
            df = pd.read_csv(agg_path)
            # Prefer NEM3 exports for with‑solar row
            if "nem3.exports.kwh" in df.columns:
                exports = float(pd.to_numeric(df["nem3.exports.kwh"], errors="coerce").fillna(0.0).sum())
            elif "retail.exports.kwh" in df.columns:
                exports = float(pd.to_numeric(df["retail.exports.kwh"], errors="coerce").fillna(0.0).sum())
        except Exception:
            exports = 0.0
    else:
        # Fallback to Step 9 sums (PV + Battery exports if available)
        exports = float(sums.get("PV to Grid (kWh)", 0.0) + sums.get("Battery to Grid (kWh)", 0.0))

    sc_ratio = None
    try:
        pv_used = float(sums.get("System to Load", 0.0) + sums.get("System to Battery", 0.0))
        sc_ratio = (pv_used / pv_ac) if pv_ac > 0 else None
    except Exception:
        sc_ratio = None

    return FlowInfo(
        pv_ac_kwh=float(pv_ac),
        grid_to_load_kwh=float(grid_to_load),
        exports_kwh=float(exports),
        self_consumption_ratio=sc_ratio,
    )


def _latest_electricity_results(
    base_input_dir: str, scenario: str, housing_type: str, county_slug: str
) -> Optional[pd.DataFrame]:
    directory = os.path.join(base_input_dir, scenario, housing_type, county_slug, "results", "electricity")
    prefix = f"RESULTS_electricity_annual_costs_{county_slug}_"
    path = _latest_results_csv(directory, prefix)
    if not path:
        return None
    try:
        return pd.read_csv(path, index_col="scenario")
    except Exception:
        return None


def _latest_gas_results(
    base_input_dir: str, scenario: str, housing_type: str, county_slug: str
) -> Optional[pd.DataFrame]:
    directory = os.path.join(base_input_dir, scenario, housing_type, county_slug, "results", "gas")
    prefix = f"RESULTS_gas_annual_costs_{county_slug}_"
    path = _latest_results_csv(directory, prefix)
    if not path:
        return None
    try:
        return pd.read_csv(path, index_col="scenario")
    except Exception:
        return None


def _pick_electric_cost(
    df: pd.DataFrame, scenario: str, variant: str = "nem3"
) -> Tuple[Optional[float], Optional[str]]:
    """Return (cost, plan_col) for scenario.solarstorage row.

    - variant='nem3' selects columns ending with '_NEM3'
    - variant='retail' selects 'electricity.<utility>.<plan>' (no _NEM3)
    """
    try:
        row_name = f"{scenario}.solarstorage"
        if row_name not in df.index:
            # fall back to any solarstorage row
            row = None
            for idx in df.index:
                if str(idx).endswith(".solarstorage"):
                    row_name = idx
                    break
        row = df.loc[row_name]
        if variant == "nem3":
            cols = [c for c in df.columns if c.endswith("_NEM3")]
        else:
            cols = [c for c in df.columns if c.startswith("electricity.") and not c.endswith("_NEM3")]
        best_col = None
        best_val = None
        for c in cols:
            try:
                v = float(row[c])
            except Exception:
                continue
            if best_val is None or v < best_val:
                best_val = v
                best_col = c
        return best_val, best_col
    except Exception:
        return None, None


def _pick_gas_cost(df: pd.DataFrame, scenario: str) -> Optional[float]:
    try:
        row_name = f"{scenario}.solarstorage"
        if row_name not in df.index:
            for idx in df.index:
                if str(idx).endswith(".solarstorage"):
                    row_name = idx
                    break
        row = df.loc[row_name]
        cols = [c for c in df.columns if c.startswith("gas.")]
        best_val = None
        for c in cols:
            try:
                v = float(row[c])
            except Exception:
                continue
            if best_val is None or v < best_val:
                best_val = v
        return best_val
    except Exception:
        return None


def _cost_info(
    base_input_dir: str,
    scenario: str,
    housing_type: str,
    county_slug: str,
    variant: str = "nem3",
) -> CostInfo:
    edf = _latest_electricity_results(base_input_dir, scenario, housing_type, county_slug)
    gdf = _latest_gas_results(base_input_dir, scenario, housing_type, county_slug)
    e_cost = e_plan = None
    g_cost = None
    if edf is not None and not edf.empty:
        e_cost, e_plan = _pick_electric_cost(edf, scenario, variant=variant)
    if gdf is not None and not gdf.empty:
        g_cost = _pick_gas_cost(gdf, scenario)
    total = None
    try:
        total = (e_cost or 0.0) + (g_cost or 0.0)
    except Exception:
        total = None
    return CostInfo(electricity=e_cost, electricity_plan=e_plan, gas=g_cost, total_bill=total)


# ---------------- Charts ----------------

def _save_fig_as_b64(fig: plt.Figure) -> str:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight")
    buf.seek(0)
    b64 = base64.b64encode(buf.getvalue()).decode()
    plt.close(fig)
    return b64


def monthly_imports_exports_chart(
    base_input_dir: str, housing_type: str, county_slug: str
) -> Optional[str]:
    """Build a two‑panel monthly chart comparing baseline vs coopt imports/exports (NEM3)."""
    try:
        def load_monthly(scen: str) -> Tuple[pd.Series, pd.Series]:
            path = _aggregator_csv_path(base_input_dir, scen, housing_type, county_slug)
            if not path or not os.path.exists(path):
                return pd.Series(dtype=float), pd.Series(dtype=float)
            df = pd.read_csv(path)
            ts = pd.to_datetime(df["timestamp"]) if "timestamp" in df.columns else pd.date_range("2018-01-01", periods=len(df), freq="H")
            imp = pd.to_numeric(df.get("nem3.imports.kwh", df.get("retail.imports.kwh", pd.Series([0]*len(ts)))), errors="coerce").fillna(0.0)
            exp = pd.to_numeric(df.get("nem3.exports.kwh", df.get("retail.exports.kwh", pd.Series([0]*len(ts)))), errors="coerce").fillna(0.0)
            mo = ts.month
            mimp = pd.Series(imp).groupby(mo).sum()
            mexp = pd.Series(exp).groupby(mo).sum()
            return mimp, mexp

        imp_b, exp_b = load_monthly(BASELINE_SCENARIO)
        imp_c, exp_c = load_monthly(COOPT_SCENARIO)
        months = range(1, 13)
        fig, axes = plt.subplots(1, 2, figsize=(12, 4))
        # Imports
        axes[0].bar([m - 0.2 for m in months], [float(imp_b.get(m, 0.0)) for m in months], width=0.4, label="Baseline")
        axes[0].bar([m + 0.2 for m in months], [float(imp_c.get(m, 0.0)) for m in months], width=0.4, label="Co‑opt")
        axes[0].set_title("Monthly Grid Imports (kWh)")
        axes[0].set_xticks(list(months))
        axes[0].legend(frameon=False)
        axes[0].grid(True, axis="y", linestyle=":", alpha=0.4)
        # Exports
        axes[1].bar([m - 0.2 for m in months], [float(exp_b.get(m, 0.0)) for m in months], width=0.4, label="Baseline")
        axes[1].bar([m + 0.2 for m in months], [float(exp_c.get(m, 0.0)) for m in months], width=0.4, label="Co‑opt")
        axes[1].set_title("Monthly Exports to Grid (kWh)")
        axes[1].set_xticks(list(months))
        axes[1].legend(frameon=False)
        axes[1].grid(True, axis="y", linestyle=":", alpha=0.4)
        fig.suptitle("Baseline vs Co‑Optimized — Monthly Imports/Exports")
        fig.tight_layout(rect=[0, 0, 1, 0.95])
        return _save_fig_as_b64(fig)
    except Exception:
        return None


def weekly_overlay_chart(
    base_input_dir: str, housing_type: str, county_slug: str, column: str = "Grid to Load"
) -> Optional[str]:
    """Overlay first 7×24 hours for a Step 9 column across baseline and co‑opt."""
    try:
        def first_week(path: Optional[str]) -> List[float]:
            if not path or not os.path.exists(path):
                return [0.0] * 168
            df = pd.read_csv(path)
            series = pd.to_numeric(df.get(column, pd.Series([0.0] * len(df))), errors="coerce").fillna(0.0)
            return series.iloc[:168].tolist() if len(series) >= 168 else series.tolist() + [0.0] * (168 - len(series))

        b_path = _sam_csv_path(base_input_dir, BASELINE_SCENARIO, housing_type, county_slug)
        c_path = _sam_csv_path(base_input_dir, COOPT_SCENARIO, housing_type, county_slug)
        y1 = first_week(b_path)
        y2 = first_week(c_path)
        x = list(range(168))
        fig, ax = plt.subplots(figsize=(12, 3.8))
        ax.plot(x, y1, label="Baseline", linewidth=1.2)
        ax.plot(x, y2, label="Co‑opt", linewidth=1.2)
        ax.set_title(f"First Week Overlay — {column}")
        ax.set_xlabel("Hour")
        ax.set_ylabel("kWh")
        ax.legend(frameon=False)
        ax.grid(True, axis="y", linestyle=":", alpha=0.4)
        fig.tight_layout()
        return _save_fig_as_b64(fig)
    except Exception:
        return None


# ---------------- HTML ----------------

def _html_dashboard(
    county_slug: str,
    housing_type: str,
    size_baseline: SizeInfo,
    size_coopt: SizeInfo,
    flows_baseline: FlowInfo,
    flows_coopt: FlowInfo,
    costs_baseline: CostInfo,
    costs_coopt: CostInfo,
    monthly_b64: Optional[str],
    weekly_b64: Optional[str],
    eac_baseline: Optional[float],
    eac_coopt: Optional[float],
) -> str:
    def fmt(x, unit=""):
        try:
            if x is None:
                return "N/A"
            if unit == "kW":
                return f"{float(x):.2f} kW"
            if unit == "kWh":
                return f"{float(x):,.0f} kWh"
            if unit == "$":
                return f"${float(x):,.0f}"
            if unit == "%":
                return f"{float(x)*100:.1f}%"
            return str(x)
        except Exception:
            return "N/A"

    def pct_delta(a: Optional[float], b: Optional[float]) -> str:
        try:
            if a is None or b is None or a == 0:
                return "—"
            return f"{(b - a) / a * 100:.1f}%"
        except Exception:
            return "—"

    pv_delta = pct_delta(size_baseline.pv_kw, size_coopt.pv_kw)
    batt_delta = pct_delta(size_baseline.batt_kwh, size_coopt.batt_kwh)
    imports_delta = pct_delta(flows_baseline.grid_to_load_kwh, flows_coopt.grid_to_load_kwh)
    exports_delta = pct_delta(flows_baseline.exports_kwh, flows_coopt.exports_kwh)
    bill_delta = pct_delta(costs_baseline.total_bill, costs_coopt.total_bill)
    eac_delta = pct_delta(eac_baseline, eac_coopt) if (eac_baseline is not None and eac_coopt is not None) else "—"

    title = county_slug.replace("-", " ").title()
    parts = []
    parts.append(
        f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset=\"utf-8\" />
            <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
            <title>Co‑opt vs Fixed — {title} — {housing_type}</title>
            <style>
                body {{ font-family: Arial, sans-serif; margin: 0; padding: 18px; background: #f7f7f7; }}
                .header {{ background: white; padding: 14px; border-radius: 8px; box-shadow: 0 1px 3px rgba(0,0,0,.08); margin-bottom: 16px; }}
                .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(480px, 1fr)); gap: 16px; }}
                .card {{ background: white; border-radius: 8px; box-shadow: 0 1px 3px rgba(0,0,0,.08); padding: 12px; }}
                .metric {{ display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 8px; }}
                .mrow {{ display: contents; }}
                .mhead {{ font-weight: 600; color: #2c3e50; }}
                .mhead div {{ text-align: center; }}
                .metric > div:first-child {{ text-align: left; }}
                /* Center numeric values so they sit visually under the column headers */
                .metric .val {{ font-weight: 700; color: #2c5aa0; text-align: center; }}
                .muted {{ color: #666; font-size: 12px; }}
            </style>
        </head>
        <body>
            <div class="header">
                <h2>Co‑Optimization vs Fixed Dispatch — {title}</h2>
                <div class="muted">Housing type: {housing_type}</div>
            </div>
            <div class="grid">
        """
    )

    # Helper to render a compact comparison table
    def table(rows: List[Tuple[str, str, str, str]]) -> str:
        t = []
        t.append("<table style='width:100%; border-collapse:collapse;'>")
        t.append("<thead><tr><th style='text-align:left;'>Metric</th><th>Baseline</th><th>Co‑opt</th><th>Δ</th></tr></thead>")
        t.append("<tbody>")
        for label, vb, vc, vd in rows:
            t.append(
                "<tr>"
                f"<td style='text-align:left; color:#666;'>{label}</td>"
                f"<td style='text-align:center; font-weight:700; color:#2c5aa0;'>{vb}</td>"
                f"<td style='text-align:center; font-weight:700; color:#2c5aa0;'>{vc}</td>"
                f"<td style='text-align:center; color:#666;'>{vd or ''}</td>"
                "</tr>"
            )
        t.append("</tbody></table>")
        return "".join(t)

    # Sizes (as a table)
    parts.append('<div class="card">')
    parts.append("<h3>System Sizes</h3>")
    size_rows = [
        ("PV Size", fmt(size_baseline.pv_kw, 'kW'), fmt(size_coopt.pv_kw, 'kW'), pv_delta),
        ("Battery Size", fmt(size_baseline.batt_kwh, 'kWh'), fmt(size_coopt.batt_kwh, 'kWh'), batt_delta),
        (
            "Flags",
            "n/a",
            f"grid_charging={size_coopt.allow_grid_charging} batt_export={size_coopt.allow_batt_export}",
            "",
        ),
    ]
    parts.append(table(size_rows))
    parts.append("</div>")

    # Flows (as a table)
    parts.append('<div class="card">')
    parts.append("<h3>Energy Flows (Annual)</h3>")
    flow_rows = [
        ("PV AC", fmt(flows_baseline.pv_ac_kwh, 'kWh'), fmt(flows_coopt.pv_ac_kwh, 'kWh'), ""),
        ("Grid Imports", fmt(flows_baseline.grid_to_load_kwh, 'kWh'), fmt(flows_coopt.grid_to_load_kwh, 'kWh'), imports_delta),
        ("Exports", fmt(flows_baseline.exports_kwh, 'kWh'), fmt(flows_coopt.exports_kwh, 'kWh'), exports_delta),
        ("Self‑Consumption", fmt(flows_baseline.self_consumption_ratio, '%'), fmt(flows_coopt.self_consumption_ratio, '%'), ""),
    ]
    parts.append(table(flow_rows))
    parts.append("</div>")

    # Bills (as a table)
    parts.append('<div class="card">')
    parts.append("<h3>Annual Bills</h3>")
    bill_rows = [
        ("Electricity", fmt(costs_baseline.electricity, '$'), fmt(costs_coopt.electricity, '$'), ""),
        ("Gas", fmt(costs_baseline.gas, '$'), fmt(costs_coopt.gas, '$'), ""),
        ("Total Annual Bill", fmt(costs_baseline.total_bill, '$'), fmt(costs_coopt.total_bill, '$'), bill_delta),
    ]
    parts.append(table(bill_rows))
    parts.append("</div>")

    # EAC (as a table)
    parts.append('<div class="card">')
    parts.append("<h3>Equivalent Annual Cost (EAC)</h3>")
    eac_rows = [
        ("Total EAC", fmt(eac_baseline, '$'), fmt(eac_coopt, '$'), eac_delta),
    ]
    parts.append(table(eac_rows))
    parts.append("</div>")

    # Charts
    if monthly_b64:
        parts.append('<div class="card">')
        parts.append("<h3>Monthly Imports / Exports</h3>")
        parts.append(f"<img src='data:image/png;base64,{monthly_b64}' alt='monthly' style='width:100%;height:auto;border-radius:6px;' />")
        parts.append("</div>")
    if weekly_b64:
        parts.append('<div class="card">')
        parts.append("<h3>Weekly Overlay — January (Grid to Load)</h3>")
        parts.append(f"<img src='data:image/png;base64,{weekly_b64}' alt='weekly' style='width:100%;height:auto;border-radius:6px;' />")
        parts.append("</div>")

    parts.append("</div></body></html>")
    return "\n".join(parts)


# ---------------- Main process ----------------

def _total_eac_for_county(
    base_input_dir: str,
    housing_type: str,
    county_slug: str,
    variant: str = "nem3",
) -> Tuple[Optional[float], Optional[float]]:
    try:
        df = collect_eac_components_by_county(
            base_input_dir,
            housing_type,
            [BASELINE_SCENARIO, COOPT_SCENARIO],
            [county_slug],
            electricity_variant=variant,
        )
        if df is None or df.empty:
            return None, None
        out = {}
        for _, r in df.iterrows():
            total = float(
                r.get("capex_pv", 0.0)
                + r.get("capex_storage", 0.0)
                + r.get("capex_electric", 0.0)
                + r.get("capex_gas", 0.0)
                + r.get("vehicle_om", 0.0)
                + r.get("annual_bill_electric", 0.0)
                + r.get("annual_bill_gas", 0.0)
            )
            out[str(r.get("scenario"))] = total
        return out.get(BASELINE_SCENARIO), out.get(COOPT_SCENARIO)
    except Exception:
        return None, None


def _write(path: str, text: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def process(
    base_input_dir: str,
    output_dir: str,
    housing_type: str,
    counties: Iterable[str],
    *,
    electricity_variant: str = "nem3",
) -> List[str]:
    """Compare baseline vs baseline_coopt and write dashboards + CSVs. Returns written HTML paths."""
    written: List[str] = []
    sha = git_short_sha()
    county_slugs = [slugify_county_name(c) for c in counties]

    rows_summary: List[Dict] = []

    for county_slug in county_slugs:
        try:
            # Sizes
            size_b = _read_assets_for_county(base_input_dir, BASELINE_SCENARIO, housing_type, county_slug)
            size_c = _read_assets_for_county(base_input_dir, COOPT_SCENARIO, housing_type, county_slug)

            # Flows
            flow_b = _flow_info_from_sources(base_input_dir, BASELINE_SCENARIO, housing_type, county_slug)
            flow_c = _flow_info_from_sources(base_input_dir, COOPT_SCENARIO, housing_type, county_slug)

            # Costs
            cost_b = _cost_info(base_input_dir, BASELINE_SCENARIO, housing_type, county_slug, variant=electricity_variant)
            cost_c = _cost_info(base_input_dir, COOPT_SCENARIO, housing_type, county_slug, variant=electricity_variant)

            # EAC totals (optional)
            eac_b, eac_c = _total_eac_for_county(base_input_dir, housing_type, county_slug, variant=electricity_variant)

            # Charts
            monthly_b64 = monthly_imports_exports_chart(base_input_dir, housing_type, county_slug)
            weekly_b64 = weekly_overlay_chart(base_input_dir, housing_type, county_slug, column="Grid to Load")

            # HTML
            html = _html_dashboard(
                county_slug,
                housing_type,
                size_b,
                size_c,
                flow_b,
                flow_c,
                cost_b,
                cost_c,
                monthly_b64,
                weekly_b64,
                eac_b,
                eac_c,
            )
            out_html = os.path.join(
                output_dir,
                "compare_coopt_vs_fixed",
                housing_type,
                f"{county_slug}_compare_g{sha}.html",
            )
            _write(out_html, html)
            written.append(out_html)

            # Per‑county CSV of metrics
            def safe(x):
                return None if x is None or (isinstance(x, float) and pd.isna(x)) else x

            per_row = {
                "county_slug": county_slug,
                # Sizes
                "pv_kw_baseline": safe(size_b.pv_kw),
                "pv_kw_coopt": safe(size_c.pv_kw),
                "batt_kwh_baseline": safe(size_b.batt_kwh),
                "batt_kwh_coopt": safe(size_c.batt_kwh),
                # Flows
                "imports_kwh_baseline": flow_b.grid_to_load_kwh,
                "imports_kwh_coopt": flow_c.grid_to_load_kwh,
                "exports_kwh_baseline": flow_b.exports_kwh,
                "exports_kwh_coopt": flow_c.exports_kwh,
                "sc_ratio_baseline": safe(flow_b.self_consumption_ratio),
                "sc_ratio_coopt": safe(flow_c.self_consumption_ratio),
                # Costs
                "electricity_bill_baseline": safe(cost_b.electricity),
                "electricity_bill_coopt": safe(cost_c.electricity),
                "gas_bill_baseline": safe(cost_b.gas),
                "gas_bill_coopt": safe(cost_c.gas),
                "total_bill_baseline": safe(cost_b.total_bill),
                "total_bill_coopt": safe(cost_c.total_bill),
                # EAC
                "total_eac_baseline": safe(eac_b),
                "total_eac_coopt": safe(eac_c),
            }
            per_csv = os.path.join(
                output_dir,
                "compare_coopt_vs_fixed",
                housing_type,
                f"{county_slug}_metrics_g{sha}.csv",
            )
            pd.DataFrame([per_row]).to_csv(per_csv, index=False)
            rows_summary.append(per_row)
        except Exception as e:
            print(f"[step23] Error comparing {county_slug}: {e}")

    # Aggregated CSV across counties
    if rows_summary:
        summary_csv = os.path.join(
            output_dir,
            "compare_coopt_vs_fixed",
            housing_type,
            f"summary_{housing_type}_g{sha}.csv",
        )
        pd.DataFrame(rows_summary).to_csv(summary_csv, index=False)
    return written


def _discover_union_counties(base_input_dir: str, housing_type: str) -> List[str]:
    out: List[str] = []
    for scen in (BASELINE_SCENARIO, COOPT_SCENARIO):
        path = get_scenario_path(base_input_dir, scen, housing_type)
        if os.path.isdir(path):
            for name in os.listdir(path):
                p = os.path.join(path, name)
                if os.path.isdir(p) and not name.startswith('.') and name not in out:
                    out.append(name)
    return sorted(out)


def main() -> None:
    p = argparse.ArgumentParser(description="Step 23: Compare co‑optimized vs fixed‑dispatch baselines")
    p.add_argument("--base-input-dir", default="data/loadprofiles")
    p.add_argument("--output-dir", default="analysis_results")
    p.add_argument("--housing-type", default="single-family-detached")
    p.add_argument("--counties", nargs="*")
    p.add_argument("--all-counties", action="store_true")
    p.add_argument("--electricity-variant", choices=["nem3", "retail"], default="nem3")
    p.add_argument("--no-open", action="store_true", help="Do not automatically open the generated dashboard in a browser")
    args = p.parse_args()

    # Restrict to Alameda County regardless of flags
    counties = ["Alameda County"]

    written = process(
        base_input_dir=args.base_input_dir,
        output_dir=args.output_dir,
        housing_type=args.housing_type,
        counties=counties,
        electricity_variant=args.electricity_variant,
    )
    if written:
        try:
            print(f"Compare dashboards written (first): {os.path.abspath(written[0])}")
            if not args.no_open:
                import webbrowser
                from pathlib import Path
                first = Path(written[0]).resolve().as_uri()
                print(f"Opening dashboard in browser: {first}")
                webbrowser.open_new_tab(first)
        except Exception:
            pass


if __name__ == "__main__":
    main()
