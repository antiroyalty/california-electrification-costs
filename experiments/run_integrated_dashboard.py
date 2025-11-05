from __future__ import annotations

"""
Integrated dashboard: runs solar, battery, and combined sweeps (always with bills)
and renders a single HTML page that embeds all plots per scenario and county.

Outputs are written under an experiments root separated by dispatch mode:
  <root>/<dispatch_label>/{solar|battery|combined}/...
and the dashboard is written at:
  <root>/<dispatch_label>/integrated_dashboard.html

Dispatch label is derived from step9_my_own_solar_storage.USE_DYNAMIC_DISPATCH
("dispatch_dynamic" or "dispatch_classic").
"""

import argparse
import datetime as dt
import html
import os
from typing import Iterable, List, Optional
import subprocess

try:
    from scenarios import SCENARIOS
    from helpers.main_helpers import norcal_counties, socal_counties, central_counties, slugify_county_name
    import step9_my_own_solar_storage as diy
except Exception:
    import sys as _sys, os as _os
    _sys.path.append(_os.path.dirname(_os.path.dirname(__file__)))
    from scenarios import SCENARIOS
    from helpers.main_helpers import norcal_counties, socal_counties, central_counties, slugify_county_name
    import step9_my_own_solar_storage as diy

# Reuse sweep implementations and their option types
try:
    from .solar_size_sweep import run as run_solar, SweepOptions  # type: ignore
    from .battery_size_sweep import run as run_battery, BatterySweepOptions  # type: ignore
    from .combined_sweep import run as run_combined, CombinedSweepOptions  # type: ignore
except Exception:
    import sys
    sys.path.append(os.path.dirname(os.path.dirname(__file__)))
    from experiments.solar_size_sweep import run as run_solar, SweepOptions  # type: ignore
    from experiments.battery_size_sweep import run as run_battery, BatterySweepOptions  # type: ignore
    from experiments.combined_sweep import run as run_combined, CombinedSweepOptions  # type: ignore


def parse_args():
    p = argparse.ArgumentParser(description="Run solar+storage sweeps and build an integrated HTML dashboard (always computes bills)")
    p.add_argument("--base-input-dir", default="data/loadprofiles")
    p.add_argument("--experiments-root", default="data/experiments/integrated_dashboard")
    p.add_argument("--housing-type", default="single-family-detached")
    p.add_argument("--counties", nargs="*")
    p.add_argument("--all-counties", action="store_true")
    p.add_argument("--scenarios", nargs="*", help="Optional subset of scenarios to run; default uses scenarios.py keys")
    # PV→Battery surplus charging controlled by step9 constant only
    p.add_argument("--no-rerun", action="store_true", help="Do not rerun sweeps; just build dashboard from existing outputs")
    return p.parse_args()


def _html_escape(s: str) -> str:
    return html.escape(str(s))


def _gather_paths(
    solar_root: str,
    battery_root: str,
    combined_root: str,
    scenario: str,
    housing: str,
    county: str,
) -> dict:
    cslug = slugify_county_name(county)
    base_solar = os.path.join(solar_root, scenario, housing, cslug)
    base_batt = os.path.join(battery_root, scenario, housing, cslug)
    base_comb = os.path.join(combined_root, scenario, housing, cslug)
    return {
        "solar_flows": os.path.join(base_solar, f"sweep_flows_vs_fraction_{cslug}.png"),
        "solar_eac": os.path.join(base_solar, f"sweep_eac_vs_fraction_{cslug}.png"),
        "solar_two_days": os.path.join(base_solar, f"two_days_deployment_f100_{cslug}.png"),
        "batt_eac": os.path.join(base_batt, f"battery_sweep_eac_{cslug}.png"),
        "comb_eac": os.path.join(base_comb, f"combined_eac_heatmap_{scenario}_{cslug}.png"),
        "comb_csv": os.path.join(base_comb, f"combined_sweep_{cslug}.csv"),
    }


def _extract_min_row(csv_path: str) -> Optional[dict]:
    try:
        import pandas as pd  # local import to avoid hard dep at module import
        if not os.path.exists(csv_path):
            return None
        df = pd.read_csv(csv_path)
        if df.empty or 'eac_total' not in df.columns:
            return None
        row = df.loc[df['eac_total'].idxmin()]
        return {
            "fraction": float(row.get('fraction', float('nan'))),
            "battery_kwh": float(row.get('battery_kwh', float('nan'))),
            "eac_total": float(row.get('eac_total', float('nan'))),
            "battery_util_percent": float(row.get('battery_util_percent', float('nan'))),
        }
    except Exception:
        return None


def _write_dashboard(
    out_html: str,
    *,
    solar_root: str,
    battery_root: str,
    combined_root: str,
    scenarios: List[str],
    housing: str,
    counties: List[str],
    # PV surplus flag now drawn only from step9 constant (no CLI override)
) -> None:
    ts = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    dispatch_label = "dispatch_dynamic" if getattr(diy, "USE_DYNAMIC_DISPATCH", False) else "dispatch_classic"
    pv_flag = diy.ENABLE_PV_SURPLUS_TO_BATTERY

    lines: List[str] = []
    lines.append("<!doctype html>")
    lines.append("<html lang='en'>")
    lines.append("<head>")
    lines.append("  <meta charset='utf-8'>")
    lines.append("  <meta name='viewport' content='width=device-width, initial-scale=1'>")
    lines.append("  <title>Integrated PV+Battery Sweep Dashboard</title>")
    lines.append("  <style>")
    lines.append("    body { font-family: -apple-system,BlinkMacSystemFont,Segoe UI,Roboto,Helvetica,Arial,sans-serif; padding: 16px; }")
    lines.append("    .meta { color: #555; margin-bottom: 12px; }")
    lines.append("    .scenario { margin-top: 28px; }")
    lines.append("    .scenario h2 { margin-bottom: 6px; }")
    lines.append("    .county { margin-top: 14px; }")
    lines.append("    .grid { display: grid; grid-template-columns: repeat(2, minmax(360px, 1fr)); gap: 10px; align-items: start; }")
    lines.append("    img { max-width: 100%; height: auto; border: 1px solid #e6e6e6; }")
    lines.append("    .note { font-size: 13px; color: #666; }")
    lines.append("  </style>")
    lines.append("</head>")
    lines.append("<body>")
    lines.append("  <h1>Integrated PV+Battery Sweep Dashboard</h1>")
    lines.append(f"  <div class='meta'>Generated: {_html_escape(ts)} · Housing: {_html_escape(housing)} · Dispatch: {_html_escape(dispatch_label)}</div>")
    lines.append(f"  <div class='meta'>PV surplus→battery: {'on' if diy.ENABLE_PV_SURPLUS_TO_BATTERY else 'off'} · Grid charging: {'on' if diy.GRID_CHARGING_ENABLED else 'off'} · Bills: on</div>")
    # Dispatch mode descriptions
    lines.append("  <div class='note'>")
    lines.append("    <strong>Dispatch modes</strong>:")
    lines.append("    <ul>")
    lines.append("      <li><em>Classic</em>: Discharge between 16:00–21:00 up to residual load (3 kW cap, SOC 20–90%). PV surplus may charge any hour. Grid top-up 14:00–16:00 is available but defaults off.</li>")
    lines.append("      <li><em>Dynamic</em>: PV-only charging; at 16:00 if PV &lt; load, discharge until min SOC or the first hour PV ≥ load (typically next morning). No grid charging to battery.</li>")
    lines.append("    </ul>")
    lines.append("  </div>")

    for scen in scenarios:
        lines.append(f"  <div class='scenario'>")
        lines.append(f"    <h2>Scenario: {_html_escape(scen)}</h2>")
        for county in counties:
            paths = _gather_paths(solar_root, battery_root, combined_root, scen, housing, county)
            cslug = slugify_county_name(county)
            lines.append(f"    <div class='county'>")
            lines.append(f"      <h3>County: {_html_escape(county)}</h3>")
            # Mini-summary (combined min EAC)
            summary = _extract_min_row(paths['comb_csv'])
            if summary:
                lines.append("      <div class='meta'>")
                lines.append(
                    f"        Best EAC: PV={summary['fraction']:.2f}×, Batt={summary['battery_kwh']:.1f} kWh, EAC=${summary['eac_total']:.0f}/yr, Util={summary['battery_util_percent']:.0f}%"
                )
                lines.append("      </div>")
            # Plots grid
            lines.append("      <div class='grid'>")
            # Order: start with the focused two-day view (PV=1.0), then other plots
            for key in ["solar_two_days", "solar_flows", "solar_eac", "batt_eac", "comb_eac"]:
                path = paths[key]
                rel = os.path.relpath(path, start=os.path.dirname(out_html))
                alt = os.path.basename(path)
                lines.append(f"        <div><img src='{_html_escape(rel)}' alt='{_html_escape(alt)}' /></div>")
            lines.append("      </div>")
            # CSV link
            rel_csv = os.path.relpath(paths['comb_csv'], start=os.path.dirname(out_html))
            lines.append(f"      <div class='note'>Combined CSV: <code>{_html_escape(rel_csv)}</code></div>")
            lines.append("    </div>")
        lines.append("  </div>")

    lines.append("  <p class='note'>Sweeps invoked via experiments.solar_size_sweep, battery_size_sweep, and combined_sweep with compute_bills=True.</p>")
    lines.append("</body>")
    lines.append("</html>")

    os.makedirs(os.path.dirname(out_html), exist_ok=True)
    with open(out_html, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def main():
    args = parse_args()
    base_input = args.base_input_dir
    exp_root = args.experiments_root
    housing = args.housing_type
    if args.all_counties:
        counties = norcal_counties + socal_counties + central_counties
    else:
        counties = args.counties or ["Alameda County"]
    scenarios = args.scenarios or list(SCENARIOS.keys())
    # Dispatch-specific root
    dispatch_label = "dispatch_dynamic" if getattr(diy, "USE_DYNAMIC_DISPATCH", False) else "dispatch_classic"
    eff_root = os.path.join(exp_root, dispatch_label)
    solar_root = os.path.join(eff_root, "solar")
    battery_root = os.path.join(eff_root, "battery")
    combined_root = os.path.join(eff_root, "combined")

    # Prepare options (always compute bills). PV surplus follows step9 constant.

    if not args.no_rerun:
        # Run solar sweep (default fractions)
        s_opts = SweepOptions(compute_bills=True)
        os.makedirs(solar_root, exist_ok=True)
        for scen in scenarios:
            run_solar(base_input, scen, housing, counties=counties, fractions=None, options=s_opts, experiments_root=solar_root)
        # Run battery sweep (default capacities)
        b_opts = BatterySweepOptions(compute_bills=True)
        os.makedirs(battery_root, exist_ok=True)
        for scen in scenarios:
            run_battery(base_input, scen, housing, counties=counties, capacities_kwh=None, options=b_opts, experiments_root=battery_root)
        # Run combined sweep (default grids)
        c_opts = CombinedSweepOptions(compute_bills=True)
        os.makedirs(combined_root, exist_ok=True)
        for scen in scenarios:
            run_combined(base_input, scen, housing, counties=counties, fractions=None, capacities_kwh=None, options=c_opts, experiments_root=combined_root)

    # Include current git short SHA in the dashboard filename for traceability
    try:
        sha = subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], stderr=subprocess.DEVNULL).decode().strip()
        sha = sha or "nogit"
    except Exception:
        sha = "nogit"
    out_html = os.path.join(eff_root, f"integrated_dashboard_g{sha}.html")
    _write_dashboard(
        out_html,
        solar_root=solar_root,
        battery_root=battery_root,
        combined_root=combined_root,
        scenarios=scenarios,
        housing=housing,
        counties=counties,
        # PV surplus status is shown in dashboard from step9 constant
    )
    print(f"Integrated dashboard written to: {os.path.abspath(out_html)}")


if __name__ == "__main__":
    main()
