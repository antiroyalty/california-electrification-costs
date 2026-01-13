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
from scenarios import SCENARIOS


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
    base_input_dir: str, housing_type: str, county_slug: str, scen_base: str, scen_coopt: str
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

        imp_b, exp_b = load_monthly(scen_base)
        imp_c, exp_c = load_monthly(scen_coopt)
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
    base_input_dir: str, housing_type: str, county_slug: str, scen_base: str, scen_coopt: str, column: str = "Grid to Load"
) -> Optional[str]:
    """Overlay first 7×24 hours for a Step 9 column across baseline and co‑opt."""
    try:
        def first_week(path: Optional[str]) -> List[float]:
            if not path or not os.path.exists(path):
                return [0.0] * 168
            df = pd.read_csv(path)
            series = pd.to_numeric(df.get(column, pd.Series([0.0] * len(df))), errors="coerce").fillna(0.0)
            return series.iloc[:168].tolist() if len(series) >= 168 else series.tolist() + [0.0] * (168 - len(series))

        b_path = _sam_csv_path(base_input_dir, scen_base, housing_type, county_slug)
        c_path = _sam_csv_path(base_input_dir, scen_coopt, housing_type, county_slug)
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


def weekly_single_chart(
    base_input_dir: str, housing_type: str, county_slug: str, scenario: str, column: str = "Grid to Load"
) -> Optional[str]:
    """Render the first 7×24 hours for a single scenario and column as a small line chart."""
    try:
        import matplotlib.pyplot as plt
        path = _sam_csv_path(base_input_dir, scenario, housing_type, county_slug)
        if not path or not os.path.exists(path):
            return None
        df = pd.read_csv(path)
        series = pd.to_numeric(df.get(column, pd.Series([0.0] * len(df))), errors="coerce").fillna(0.0)
        y = series.iloc[:168].tolist() if len(series) >= 168 else series.tolist() + [0.0] * (168 - len(series))
        x = list(range(168))
        fig, ax = plt.subplots(figsize=(12, 3.2))
        ax.plot(x, y, label=scenario.replace('_', ' ').title(), linewidth=1.4, color="#1f77b4")
        ax.set_xlabel("Hour")
        ax.set_ylabel("kWh")
        ax.grid(True, axis="y", linestyle=":", alpha=0.4)
        ax.legend(frameon=False)
        fig.tight_layout()
        return _save_fig_as_b64(fig)
    except Exception:
        return None


def weekly_overlay_exports_chart(
    base_input_dir: str,
    housing_type: str,
    county_slug: str,
    scen_base: str,
    scen_coopt: str,
    period: str = "july",
) -> Optional[str]:
    """Overlay first week exports (hourly) for baseline vs co‑opt using Step 10 aggregator.

    Uses 'nem3.exports.kwh' when available, else 'retail.exports.kwh'.
    Period='july' plots 2018-07-01 through 2018-07-08 (exclusive).
    """
    try:
        import matplotlib.pyplot as plt
        import matplotlib.dates as mdates
        def load_week(scen: str) -> Optional[pd.Series]:
            path = _aggregator_csv_path(base_input_dir, scen, housing_type, county_slug)
            if not path or not os.path.exists(path):
                return None
            df = pd.read_csv(path)
            ts = pd.to_datetime(df['timestamp']) if 'timestamp' in df.columns else pd.date_range('2018-01-01', periods=len(df), freq='H')
            if 'nem3.exports.kwh' in df.columns:
                series = pd.to_numeric(df['nem3.exports.kwh'], errors='coerce').fillna(0.0)
            else:
                series = pd.to_numeric(df.get('retail.exports.kwh', pd.Series([0.0] * len(ts))), errors='coerce').fillna(0.0)
            s = pd.Series(series.values, index=ts)
            if (period or 'july').lower() == 'july':
                start, end = '2018-07-01', '2018-07-08'
            else:
                start, end = '2018-01-01', '2018-01-08'
            return s.loc[start:end]

        b = load_week(scen_base)
        c = load_week(scen_coopt)
        if b is None or c is None or b.empty or c.empty:
            return None
        # Align indexes
        idx = b.index.union(c.index)
        b = b.reindex(idx, fill_value=0.0)
        c = c.reindex(idx, fill_value=0.0)
        fig, ax = plt.subplots(figsize=(12, 3.8))
        ax.plot(b.index, b.values, label=scen_base.replace('_', ' ').title(), linewidth=1.4, color="#1f77b4")
        ax.plot(c.index, c.values, label=scen_coopt.replace('_', ' ').title(), linewidth=1.4, color="#ff7f0e")
        ax.set_ylabel("kWh (hourly)")
        ax.set_xlabel("Date")
        title_suffix = "July" if (period or 'july').lower() == 'july' else "January"
        ax.set_title(f"Exports to Grid — {title_suffix} (First Week)")
        ax.grid(True, axis='y', linestyle=':', alpha=0.4)
        ax.legend(frameon=False)
        ax.xaxis.set_major_locator(mdates.DayLocator())
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%m/%d"))
        ax.xaxis.set_minor_locator(mdates.HourLocator(interval=6))
        fig.autofmt_xdate()
        fig.tight_layout()
        return _save_fig_as_b64(fig)
    except Exception:
        return None


# ---------------- HTML ----------------

def _html_dashboard(
    county_slug: str,
    housing_type: str,
    sections: List[str],
) -> str:
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
                .card {{ background: white; border-radius: 8px; box-shadow: 0 1px 3px rgba(0,0,0,.08); padding: 12px; font-size: 0.94em; }}
                .card-sizes {{ background: #fffbe6; }}
                /* Scenario divider spanning all columns with a labeled horizontal rule */
                .scen-divider {{ grid-column: 1 / -1; display: flex; align-items: center; margin: 8px 0 8px; }}
                .scen-divider::before, .scen-divider::after {{ content: ""; flex: 1; border-bottom: 1px solid #ddd; }}
                .scen-divider:not(:empty)::before {{ margin-right: .75em; }}
                .scen-divider:not(:empty)::after {{ margin-left: .75em; }}
                .scen-title {{
                    font-weight: 600;
                    color: #fff;
                    font-size: 16px;
                    letter-spacing: .2px;
                    background: #6f42c1; /* purple background for scenario label */
                    padding: 2px 10px;
                    border-radius: 12px;
                }}
                .metric {{ display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 8px; }}
                .mrow {{ display: contents; }}
                .mhead {{ font-weight: 600; color: #2c3e50; }}
                .mhead div {{ text-align: center; }}
                .metric > div:first-child {{ text-align: left; }}
                /* Center numeric values so they sit visually under the column headers */
                .metric .val {{ font-weight: 400; color: #2c5aa0; text-align: center; }}
                .muted {{ color: #666; font-size: 0.9em; }}
                /* Softer card titles for readability */
                .card h3 {{
                    margin: 4px 0 8px;
                    font-size: 1.1em;
                    font-weight: 600; /* less bold than default h3 */
                    color: #2c3e50;
                }}
                /* Highlight for minimum cost cell in EAC tables */
                .highlight-min {{ background: #eaffea; }}
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

    # Insert pre-built sections for each scenario pair
    for sec in sections:
        parts.append(sec)

    parts.append("</div></body></html>")
    return "\n".join(parts)


# ---------------- Main process ----------------

def _total_eac_for_county(
    base_input_dir: str,
    housing_type: str,
    county_slug: str,
    scen_base: str,
    scen_coopt: str,
    variant: str = "nem3",
) -> Tuple[Optional[float], Optional[float]]:
    try:
        df = collect_eac_components_by_county(
            base_input_dir,
            housing_type,
            [scen_base, scen_coopt],
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
        return out.get(scen_base), out.get(scen_coopt)
    except Exception:
        return None, None


def _capex_totals_for_county(
    base_input_dir: str,
    housing_type: str,
    county_slug: str,
    scen_base: str,
    scen_coopt: str,
    variant: str = "nem3",
) -> Tuple[Optional[float], Optional[float]]:
    """Return (annualized capex total baseline, annualized capex total co‑opt) per county.

    Capex total = capex_pv + capex_storage + capex_electric + capex_gas
    """
    try:
        df = collect_eac_components_by_county(
            base_input_dir,
            housing_type,
            [scen_base, scen_coopt],
            [county_slug],
            electricity_variant=variant,
        )
        if df is None or df.empty:
            return None, None
        cap = {}
        for _, r in df.iterrows():
            cap_total = float(
                r.get("capex_pv", 0.0)
                + r.get("capex_storage", 0.0)
                + r.get("capex_electric", 0.0)
                + r.get("capex_gas", 0.0)
            )
            cap[str(r.get("scenario"))] = cap_total
        return cap.get(scen_base), cap.get(scen_coopt)
    except Exception:
        return None, None


def _raw_pv_storage_for_county(
    base_input_dir: str,
    housing_type: str,
    county_slug: str,
    scen_base: str,
    scen_coopt: str,
    incentive: str = "full_incentives",
) -> Tuple[Optional[float], Optional[float]]:
    """Return (raw upfront PV+Storage net of incentives) for baseline and co‑opt.

    Reads capital_costs_summary_with_pv_<scenario>_<housing>.csv and applies
    full/half/no incentives to compute net upfront.
    """
    import pandas as pd
    import os
    def one(scen: str) -> Optional[float]:
        cap_dir = os.path.join(base_input_dir, "capital_costs")
        fname = f"capital_costs_summary_with_pv_{scen}_{housing_type.replace('-', '_')}.csv"
        path = os.path.join(cap_dir, fname)
        if not os.path.exists(path):
            return None
        try:
            df = pd.read_csv(path)
        except Exception:
            return None
        if df is None or df.empty:
            return None
        sub = df[df['county_slug'].str.lower() == county_slug.lower()]
        if sub.empty:
            return None
        r = sub.iloc[0]
        pv_capex = float(r.get('pv_capex', 0.0))
        st_capex = float(r.get('storage_capex', 0.0))
        pv_inc_full = float(r.get('pv_incentives_full', 0.0)) if 'pv_incentives_full' in sub.columns else 0.0
        st_inc_full = float(r.get('storage_incentives_full', 0.0)) if 'storage_incentives_full' in sub.columns else 0.0
        inc = (incentive or '').lower()
        if inc == 'full_incentives':
            pv_net = pv_capex - pv_inc_full
            st_net = st_capex - st_inc_full
        elif inc == 'half_incentives':
            pv_net = pv_capex - (pv_inc_full * 0.5)
            st_net = st_capex - (st_inc_full * 0.5)
        else:
            pv_net = pv_capex
            st_net = st_capex
        return pv_net + st_net
    return one(scen_base), one(scen_coopt)


def _raw_other_assets_for_county(
    base_input_dir: str,
    housing_type: str,
    county_slug: str,
    scenario: str,
    incentive: str = "full_incentives",
) -> Tuple[float, float]:
    """Return (raw_other_electric, raw_gas) upfront costs from the capital ledger.

    - Other electric excludes PV/storage; uses 'net_cost'
    - Gas uses 'base_cost'
    """
    import pandas as pd
    import os
    cap_dir = os.path.join(base_input_dir, "capital_costs")
    fname = f"capital_costs_{scenario}_{housing_type.replace('-', '_')}.csv"
    path = os.path.join(cap_dir, fname)
    raw_elec = 0.0
    raw_gas = 0.0
    if not os.path.exists(path):
        return raw_elec, raw_gas
    try:
        df = pd.read_csv(path)
    except Exception:
        return raw_elec, raw_gas
    if df is None or df.empty:
        return raw_elec, raw_gas
    # Filter county (best-effort; expect 'county_slug')
    if 'county_slug' in df.columns:
        df = df[df['county_slug'].str.lower() == county_slug.lower()]
    # Filter incentive scenario (best-effort; expect 'incentive_scenario')
    if 'incentive_scenario' in df.columns:
        df['incentive_scenario'] = df['incentive_scenario'].str.lower()
        df = df[df['incentive_scenario'] == (incentive or '').lower()]
    if df.empty:
        return raw_elec, raw_gas
    # Sum raw costs
    import numpy as np
    # Other electrification (exclude solar/storage)
    try:
        mask_e = (df.get('appliance_category') == 'electric') & (~df.get('appliance_type').isin(['solar', 'storage']))
        raw_elec = float(pd.to_numeric(df.loc[mask_e, 'net_cost'], errors='coerce').fillna(0.0).sum())
    except Exception:
        raw_elec = 0.0
    # Gas assets
    try:
        mask_g = (df.get('appliance_category') == 'gas')
        raw_gas = float(pd.to_numeric(df.loc[mask_g, 'base_cost'], errors='coerce').fillna(0.0).sum())
    except Exception:
        raw_gas = 0.0
    return raw_elec, raw_gas


def _total_energy_denominator_kwh(
    base_input_dir: str,
    scenario: str,
    housing_type: str,
    county_slug: str,
) -> Optional[float]:
    """Return annual total energy (kWh) = electric load kWh + gas kWh equivalent.

    - Electric load: sum of 'Load Profile' from Step 9 SAM CSV
    - Gas: sum of 'solarstorage.gas.therms' from Step 10 aggregator × 29.3001 kWh/therm
    """
    try:
        import pandas as pd
        import os
        # Electric: from SAM CSV
        sam_path = _sam_csv_path(base_input_dir, scenario, housing_type, county_slug)
        if not sam_path or not os.path.exists(sam_path):
            return None
        df_sam = pd.read_csv(sam_path)
        if 'Load Profile' not in df_sam.columns:
            return None
        elec_kwh = float(pd.to_numeric(df_sam['Load Profile'], errors='coerce').fillna(0.0).sum())
        # Gas: from aggregator
        agg_path = _aggregator_csv_path(base_input_dir, scenario, housing_type, county_slug)
        if not agg_path or not os.path.exists(agg_path):
            gas_kwh = 0.0
        else:
            df_agg = pd.read_csv(agg_path)
            col = 'solarstorage.gas.therms'
            if col in df_agg.columns:
                therms = float(pd.to_numeric(df_agg[col], errors='coerce').fillna(0.0).sum())
                gas_kwh = therms * 29.3001
            else:
                gas_kwh = 0.0
        return elec_kwh + gas_kwh
    except Exception:
        return None


def _write(path: str, text: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def _scenario_pairs_all() -> List[Tuple[str, str]]:
    """Return list of (scenario, scenario_coopt) pairs present in SCENARIOS."""
    pairs: List[Tuple[str, str]] = []
    keys = set(SCENARIOS.keys())
    for s in sorted(keys):
        if s.endswith("_coopt"):
            continue
        c = f"{s}_coopt"
        if c in keys:
            pairs.append((s, c))
    return pairs


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
            pair_sections: List[str] = []
            rows_for_county: List[Dict] = []
            pair_infos: List[Dict] = []
            for scen_base, scen_coopt in _scenario_pairs_all():
                # Sizes
                size_b = _read_assets_for_county(base_input_dir, scen_base, housing_type, county_slug)
                size_c = _read_assets_for_county(base_input_dir, scen_coopt, housing_type, county_slug)

                # Flows
                flow_b = _flow_info_from_sources(base_input_dir, scen_base, housing_type, county_slug)
                flow_c = _flow_info_from_sources(base_input_dir, scen_coopt, housing_type, county_slug)

                # Costs
                cost_b = _cost_info(base_input_dir, scen_base, housing_type, county_slug, variant=electricity_variant)
                cost_c = _cost_info(base_input_dir, scen_coopt, housing_type, county_slug, variant=electricity_variant)

                # EAC totals (optional) and Capex totals
                eac_b, eac_c = _total_eac_for_county(base_input_dir, housing_type, county_slug, scen_base, scen_coopt, variant=electricity_variant)
                cap_b, cap_c = _capex_totals_for_county(base_input_dir, housing_type, county_slug, scen_base, scen_coopt, variant=electricity_variant)
                raw_cap_b, raw_cap_c = _raw_pv_storage_for_county(base_input_dir, housing_type, county_slug, scen_base, scen_coopt, incentive='full_incentives')
                # LCOE (total energy): (annualized capital + annual elec + gas bills) / (elec_load_kwh + gas_therms*29.3001)
                denom_b = _total_energy_denominator_kwh(base_input_dir, scen_base, housing_type, county_slug)
                denom_c = _total_energy_denominator_kwh(base_input_dir, scen_coopt, housing_type, county_slug)
                lcoe_b = None
                lcoe_c = None
                try:
                    if cap_b is not None and denom_b and denom_b > 0:
                        lcoe_b = (cap_b + (cost_b.electricity or 0.0) + (cost_b.gas or 0.0)) / float(denom_b)
                except Exception:
                    lcoe_b = None
                try:
                    if cap_c is not None and denom_c and denom_c > 0:
                        lcoe_c = (cap_c + (cost_c.electricity or 0.0) + (cost_c.gas or 0.0)) / float(denom_c)
                except Exception:
                    lcoe_c = None
                # lcoe_delta computed after pct_delta is defined
                raw_elec_b, raw_gas_b = _raw_other_assets_for_county(base_input_dir, housing_type, county_slug, scen_base, incentive='full_incentives')
                raw_elec_c, raw_gas_c = _raw_other_assets_for_county(base_input_dir, housing_type, county_slug, scen_coopt, incentive='full_incentives')

                # Charts for this pair
                monthly_b64 = monthly_imports_exports_chart(base_input_dir, housing_type, county_slug, scen_base, scen_coopt)
                weekly_b64 = weekly_overlay_chart(base_input_dir, housing_type, county_slug, scen_base, scen_coopt, column="Grid to Load")

                # Build pair section HTML (tables + charts)
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

                # Deltas for sizes, imports, exports, bills, EAC
                pv_delta = pct_delta(size_b.pv_kw, size_c.pv_kw)
                batt_delta = pct_delta(size_b.batt_kwh, size_c.batt_kwh)
                imports_delta = pct_delta(flow_b.grid_to_load_kwh, flow_c.grid_to_load_kwh)
                exports_delta = pct_delta(flow_b.exports_kwh, flow_c.exports_kwh)
                bill_delta = pct_delta(cost_b.total_bill, cost_c.total_bill)
                eac_delta = pct_delta(eac_b, eac_c) if (eac_b is not None and eac_c is not None) else "—"
                cap_delta = pct_delta(cap_b, cap_c) if (cap_b is not None and cap_c is not None) else "—"
                raw_cap_delta = pct_delta(raw_cap_b, raw_cap_c) if (raw_cap_b is not None and raw_cap_c is not None) else "—"
                raw_elec_delta = pct_delta(raw_elec_b, raw_elec_c)
                raw_gas_delta = pct_delta(raw_gas_b, raw_gas_c)
                raw_total_b = (raw_cap_b or 0.0) + raw_elec_b + raw_gas_b
                raw_total_c = (raw_cap_c or 0.0) + raw_elec_c + raw_gas_c
                raw_total_delta = pct_delta(raw_total_b, raw_total_c)
                lcoe_delta = pct_delta(lcoe_b, lcoe_c) if (lcoe_b is not None and lcoe_c is not None) else "—"

                # Detailed PV/battery/grid flow breakdown from SAM CSV
                sums_b = _sam_metric_sums(_sam_csv_path(base_input_dir, scen_base, housing_type, county_slug))
                sums_c = _sam_metric_sums(_sam_csv_path(base_input_dir, scen_coopt, housing_type, county_slug))
                pv_to_load_b = float(sums_b.get("System to Load", 0.0))
                pv_to_load_c = float(sums_c.get("System to Load", 0.0))
                pv_to_batt_b = float(sums_b.get("System to Battery", 0.0))
                pv_to_batt_c = float(sums_c.get("System to Battery", 0.0))
                pv_to_grid_b = float(sums_b.get("PV to Grid (kWh)", 0.0))
                pv_to_grid_c = float(sums_c.get("PV to Grid (kWh)", 0.0))
                batt_to_grid_b = float(sums_b.get("Battery to Grid (kWh)", 0.0))
                batt_to_grid_c = float(sums_c.get("Battery to Grid (kWh)", 0.0))
                pv_to_load_delta = pct_delta(pv_to_load_b, pv_to_load_c)
                pv_to_batt_delta = pct_delta(pv_to_batt_b, pv_to_batt_c)
                pv_to_grid_delta = pct_delta(pv_to_grid_b, pv_to_grid_c)
                batt_to_grid_delta = pct_delta(batt_to_grid_b, batt_to_grid_c)

                # Baseline + Co‑opt exports overlay for July
                weekly_exp_b64 = weekly_overlay_exports_chart(base_input_dir, housing_type, county_slug, scen_base, scen_coopt, period='july')

                # Collect for later rendering (to enable EAC min highlighting across pairs)
                pair_infos.append({
                    "title": scen_base.replace('_', ' ').title(),
                    "size_b": size_b,
                    "size_c": size_c,
                    "pv_delta": pv_delta,
                    "batt_delta": batt_delta,
                    "flow_b": flow_b,
                    "flow_c": flow_c,
                    "pv_to_load_b": pv_to_load_b,
                    "pv_to_load_c": pv_to_load_c,
                    "pv_to_batt_b": pv_to_batt_b,
                    "pv_to_batt_c": pv_to_batt_c,
                    "pv_to_grid_b": pv_to_grid_b,
                    "pv_to_grid_c": pv_to_grid_c,
                    "batt_to_grid_b": batt_to_grid_b,
                    "batt_to_grid_c": batt_to_grid_c,
                    "pv_to_load_delta": pv_to_load_delta,
                    "pv_to_batt_delta": pv_to_batt_delta,
                    "pv_to_grid_delta": pv_to_grid_delta,
                    "batt_to_grid_delta": batt_to_grid_delta,
                    "imports_delta": imports_delta,
                    "exports_delta": exports_delta,
                    "cost_b": cost_b,
                    "cost_c": cost_c,
                    "bill_delta": bill_delta,
                    "eac_b": eac_b,
                    "eac_c": eac_c,
                    "eac_delta": eac_delta,
                    "cap_b": cap_b,
                    "cap_c": cap_c,
                    "cap_delta": cap_delta,
                    "raw_cap_b": raw_cap_b,
                    "raw_cap_c": raw_cap_c,
                    "raw_cap_delta": raw_cap_delta,
                    "raw_elec_b": raw_elec_b,
                    "raw_elec_c": raw_elec_c,
                    "raw_elec_delta": raw_elec_delta,
                    "raw_gas_b": raw_gas_b,
                    "raw_gas_c": raw_gas_c,
                    "raw_gas_delta": raw_gas_delta,
                    "raw_total_b": raw_total_b,
                    "raw_total_c": raw_total_c,
                    "raw_total_delta": raw_total_delta,
                    "monthly_b64": monthly_b64,
                    "weekly_b64": weekly_b64,
                    "weekly_exp_b64": weekly_exp_b64,
                    "lcoe_b": lcoe_b,
                    "lcoe_c": lcoe_c,
                    "lcoe_delta": lcoe_delta,
                })

                # Per‑pair metrics row (for summary/CSV)
                def safe(x):
                    return None if x is None or (isinstance(x, float) and pd.isna(x)) else x
                rows_for_county.append({
                    "scenario": scen_base,
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
                })

            # Compute EAC minima across pairs (baseline and co‑opt separately)
            eac_vals_b = [pi["eac_b"] for pi in pair_infos if pi.get("eac_b") is not None]
            eac_vals_c = [pi["eac_c"] for pi in pair_infos if pi.get("eac_c") is not None]
            min_eac_b = min(eac_vals_b) if eac_vals_b else None
            min_eac_c = min(eac_vals_c) if eac_vals_c else None

            # Render sections with EAC minima highlighted
            pair_sections = []
            def table(rows: List[Tuple[str, str, str, str]], cell_classes: Tuple[str, str, str, str] | None = None) -> str:
                t = []
                t.append("<table style='width:100%; border-collapse:collapse;'>")
                t.append("<thead><tr><th style='text-align:left;'>Metric</th><th>Baseline</th><th>Co‑opt</th><th>Δ</th></tr></thead>")
                t.append("<tbody>")
                for idx, (label, vb, vc, vd) in enumerate(rows):
                    cls = ["", "", "", ""]
                    if cell_classes:
                        cls = list(cell_classes)
                    t.append(
                        "<tr>"
                        f"<td style='text-align:left; color:#666;'>{label}</td>"
                        f"<td class='{cls[1]}' style='text-align:center; color:#2c5aa0;'>{vb}</td>"
                        f"<td class='{cls[2]}' style='text-align:center; color:#2c5aa0;'>{vc}</td>"
                        f"<td style='text-align:center; color:#666;'>{vd or ''}</td>"
                        "</tr>"
                    )
                t.append("</tbody></table>")
                return "".join(t)

            for pi in pair_infos:
                title = pi["title"]
                section = []
                section.append(f"<div class='scen-divider'><span class='scen-title'>{title}</span></div>")
                # Sizes
                section.append('<div class="card card-sizes">')
                section.append(f"<h3>{title} — System Sizes</h3>")
                size_rows = [
                    ("PV Size", fmt(pi["size_b"].pv_kw, 'kW'), fmt(pi["size_c"].pv_kw, 'kW'), pi["pv_delta"]),
                    ("Battery Size", fmt(pi["size_b"].batt_kwh, 'kWh'), fmt(pi["size_c"].batt_kwh, 'kWh'), pi["batt_delta"]),
                    ("Flags", "n/a", f"grid_charging={pi['size_c'].allow_grid_charging} batt_export={pi['size_c'].allow_batt_export}", ""),
                ]
                section.append(table(size_rows))
                section.append("</div>")

                # Flows
                section.append('<div class="card">')
                section.append(f"<h3>{title} — Energy Flows (Annual)</h3>")
                flow_rows = [
                    ("PV AC", fmt(pi["flow_b"].pv_ac_kwh, 'kWh'), fmt(pi["flow_c"].pv_ac_kwh, 'kWh'), ""),
                    ("PV → Load", fmt(pi["pv_to_load_b"], 'kWh'), fmt(pi["pv_to_load_c"], 'kWh'), pi["pv_to_load_delta"]),
                    ("PV → Battery", fmt(pi["pv_to_batt_b"], 'kWh'), fmt(pi["pv_to_batt_c"], 'kWh'), pi["pv_to_batt_delta"]),
                    ("PV → Grid", fmt(pi["pv_to_grid_b"], 'kWh'), fmt(pi["pv_to_grid_c"], 'kWh'), pi["pv_to_grid_delta"]),
                    ("Battery → Grid", fmt(pi["batt_to_grid_b"], 'kWh'), fmt(pi["batt_to_grid_c"], 'kWh'), pi["batt_to_grid_delta"]),
                    ("Grid Imports", fmt(pi["flow_b"].grid_to_load_kwh, 'kWh'), fmt(pi["flow_c"].grid_to_load_kwh, 'kWh'), pi["imports_delta"]),
                ]
                section.append(table(flow_rows))
                section.append("</div>")

                # Bills
                section.append('<div class="card">')
                section.append(f"<h3>{title} — Annual Bills</h3>")
                bill_rows = [
                    ("Electricity", fmt(pi["cost_b"].electricity, '$'), fmt(pi["cost_c"].electricity, '$'), ""),
                    ("Gas", fmt(pi["cost_b"].gas, '$'), fmt(pi["cost_c"].gas, '$'), ""),
                    ("Total Annual Bill", fmt(pi["cost_b"].total_bill, '$'), fmt(pi["cost_c"].total_bill, '$'), pi["bill_delta"]),
                ]
                section.append(table(bill_rows))
                section.append("</div>")

                # Capital costs (annualized)
                section.append('<div class="card">')
                section.append(f"<h3>{title} — Capital Costs (Annualized)</h3>")
                cap_rows = [
                    ("Total Capital", fmt(pi.get("cap_b"), '$'), fmt(pi.get("cap_c"), '$'), pi.get("cap_delta")),
                ]
                section.append(table(cap_rows))
                section.append("<div class='muted'>Annualization parameters: PV 25 years, Storage 15 years, discount rate 7%. Other assets use per‑row lifetimes from the capital ledger (default 15 years).</div>")
                section.append("</div>")

                # Capital costs (upfront PV+Storage net of incentives)
                section.append('<div class="card">')
                section.append(f"<h3>{title} — Capital Costs (Upfront PV + Storage)</h3>")
                raw_rows = [
                    ("Upfront PV+Storage (net)", fmt(pi.get("raw_cap_b"), '$'), fmt(pi.get("raw_cap_c"), '$'), pi.get("raw_cap_delta")),
                ]
                section.append(table(raw_rows))
                section.append("</div>")

                # Capital costs (upfront — all assets)
                section.append('<div class="card">')
                section.append(f"<h3>{title} — Capital Costs (Upfront — All Assets)</h3>")
                up_rows = [
                    ("PV+Storage (net)", fmt(pi.get("raw_cap_b"), '$'), fmt(pi.get("raw_cap_c"), '$'), pi.get("raw_cap_delta")),
                    ("Other Electrification", fmt(pi.get("raw_elec_b"), '$'), fmt(pi.get("raw_elec_c"), '$'), pi.get("raw_elec_delta")),
                    ("Gas Assets", fmt(pi.get("raw_gas_b"), '$'), fmt(pi.get("raw_gas_c"), '$'), pi.get("raw_gas_delta")),
                    ("Total Upfront", fmt(pi.get("raw_total_b"), '$'), fmt(pi.get("raw_total_c"), '$'), pi.get("raw_total_delta")),
                ]
                section.append(table(up_rows))
                section.append("</div>")

                # EAC with minima highlighted
                section.append('<div class="card">')
                section.append(f"<h3>{title} — Equivalent Annual Cost (EAC)</h3>")
                cls_b = "highlight-min" if (min_eac_b is not None and pi.get("eac_b") == min_eac_b) else ""
                cls_c = "highlight-min" if (min_eac_c is not None and pi.get("eac_c") == min_eac_c) else ""
                section.append(table([("Total EAC", fmt(pi.get("eac_b"), '$'), fmt(pi.get("eac_c"), '$'), pi.get("eac_delta"))], cell_classes=("", cls_b, cls_c, "")))
                section.append("</div>")

                # Total Energy LCOE ($/kWh)
                section.append('<div class="card">')
                section.append(f"<h3>{title} — Total Energy LCOE</h3>")
                def fmt_rate(x):
                    try:
                        return f"{float(x):.3f} $/kWh"
                    except Exception:
                        return "N/A"
                lcoe_rows = [
                    ("LCOE (Total Energy)", fmt_rate(pi.get("lcoe_b")), fmt_rate(pi.get("lcoe_c")), pi.get("lcoe_delta")),
                ]
                section.append(table(lcoe_rows))
                section.append("<div class='muted'>Numerator = annualized capital (PV + storage + other electrification + gas) + annual electricity + gas bills. Denominator = annual household electric load + gas (therms × 29.3001 kWh/therm).</div>")
                section.append("</div>")

                # Charts
                if pi.get("monthly_b64"):
                    section.append('<div class="card">')
                    section.append(f"<h3>{title} — Monthly Imports / Exports</h3>")
                    section.append(f"<img src='data:image/png;base64,{pi['monthly_b64']}' alt='monthly' style='width:100%;height:auto;border-radius:6px;' />")
                    section.append("</div>")
                if pi.get("weekly_b64"):
                    section.append('<div class="card">')
                    section.append(f"<h3>{title} — Weekly Overlay — January (Grid to Load)</h3>")
                    section.append(f"<img src='data:image/png;base64,{pi['weekly_b64']}' alt='weekly' style='width:100%;height:auto;border-radius:6px;' />")
                    section.append("</div>")
                if pi.get("weekly_exp_b64"):
                    section.append('<div class="card">')
                    section.append(f"<h3>{title} — Weekly — July (Exports to Grid) — Baseline vs Co‑opt</h3>")
                    section.append(f"<img src='data:image/png;base64,{pi['weekly_exp_b64']}' alt='weekly exports overlay' style='width:100%;height:auto;border-radius:6px;' />")
                    section.append("</div>")

                pair_sections.append("\n".join(section))

            # Build one dashboard per county aggregating all scenario pairs
            html = _html_dashboard(
                county_slug,
                housing_type,
                sections=pair_sections,
            )
            out_html = os.path.join(
                output_dir,
                "compare_coopt_vs_fixed",
                housing_type,
                f"{county_slug}_compare_g{sha}.html",
            )
            _write(out_html, html)
            written.append(out_html)
            per_csv = os.path.join(
                output_dir,
                "compare_coopt_vs_fixed",
                housing_type,
                f"{county_slug}_metrics_g{sha}.csv",
            )
            if rows_for_county:
                pd.DataFrame(rows_for_county).to_csv(per_csv, index=False)
                rows_summary.extend(rows_for_county)
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
