from __future__ import annotations

"""
Run PV-size sweeps for all scenarios and render a single-page HTML dashboard
showing all plots (flows, EAC) grouped by scenario and county.

This is a non-intrusive experiment tool: it writes under `--experiments-root`
and does not modify the main pipeline's canonical outputs.

Examples:
  # Single mode (grid charging controlled by step9 constant, bills on)
  python -m experiments.run_solar_sweep_dashboard \
    --housing-type single-family-detached \
    --counties "Alameda County" \
    --compute-bills

  # Grid charging ON/OFF is controlled only by step9 constant.
"""

import argparse
import datetime as dt
import html
import os
from typing import Iterable, List, Optional

try:
    from .solar_size_sweep import run, SweepOptions  # type: ignore
except Exception:
    import sys
    sys.path.append(os.path.dirname(os.path.dirname(__file__)))
    from experiments.solar_size_sweep import run, SweepOptions  # type: ignore

from scenarios import SCENARIOS
from main_helpers import norcal_counties, socal_counties, central_counties, slugify_county_name
import step9_my_own_solar_storage as diy


def parse_args():
    p = argparse.ArgumentParser(description="Run PV-size sweeps for all scenarios and build a single-page HTML dashboard")
    p.add_argument("--base-input-dir", default="data/loadprofiles")
    p.add_argument("--experiments-root", default="data/experiments/solar_size_sweep")
    p.add_argument("--housing-type", default="single-family-detached")
    p.add_argument("--counties", nargs="*")
    p.add_argument("--all-counties", action="store_true")
    p.add_argument("--fractions", default=None, help="Comma-separated PV size fractions; default=0.1..2.0 by 0.1")
    p.add_argument("--enable-pv-surplus", action="store_true", default=None, help="Enable PV→Battery surplus charging (omit to use step9 default)")
    p.add_argument("--compute-bills", action="store_true", help="Compute total bills via Steps 10/11/13 into experiments tree")
    p.add_argument("--scenarios", nargs="*", help="Optional subset of scenarios to run; default uses scenarios.py keys")
    p.add_argument("--dashboard-name", default="sweep_dashboard.html", help="HTML filename to write within experiments root")
    return p.parse_args()


def _infer_fractions(arg: Optional[str]) -> List[float]:
    if arg:
        return [float(s) for s in arg.split(',') if s.strip()]
    return [i / 10.0 for i in range(1, 21)]  # 0.1 .. 2.0


def _gather_plot_paths(exp_root: str, scenario: str, housing: str, county: str) -> List[str]:
    cslug = slugify_county_name(county)
    base_dir = os.path.join(exp_root, scenario, housing, cslug)
    return [
        os.path.join(base_dir, f"sweep_flows_vs_fraction_{cslug}.png"),
        os.path.join(base_dir, f"sweep_eac_vs_fraction_{cslug}.png"),
    ]


def _html_escape(s: str) -> str:
    return html.escape(str(s))


def _write_dashboard(
    out_path: str,
    exp_root: str,
    scenarios: List[str],
    housing: str,
    counties: List[str],
    *,
    fractions: Iterable[float],
    compute_bills: bool,
) -> None:
    ts = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines: List[str] = []
    lines.append("<!doctype html>")
    lines.append("<html lang='en'>")
    lines.append("<head>")
    lines.append("  <meta charset='utf-8'>")
    lines.append("  <meta name='viewport' content='width=device-width, initial-scale=1'>")
    lines.append("  <title>PV-size Sweep Dashboard</title>")
    # Simple inline CSS grid for readability
    lines.append("  <style>")
    lines.append("    body { font-family: -apple-system,BlinkMacSystemFont,Segoe UI,Roboto,Helvetica,Arial,sans-serif; padding: 16px; }")
    lines.append("    .meta { color: #555; margin-bottom: 12px; }")
    lines.append("    .scenario { margin-top: 28px; }")
    lines.append("    .scenario h2 { margin-bottom: 6px; }")
    lines.append("    .county { margin-top: 14px; }")
    lines.append("    .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(360px, 1fr)); gap: 10px; align-items: start; }")
    lines.append("    img { max-width: 100%; height: auto; border: 1px solid #e6e6e6; }")
    lines.append("    .note { font-size: 13px; color: #666; }")
    lines.append("  </style>")
    lines.append("</head>")
    lines.append("<body>")
    lines.append("  <h1>PV-size Sweep Dashboard</h1>")
    lines.append(f"  <div class='meta'>Generated: {_html_escape(ts)} · Housing: {_html_escape(housing)} · Fractions: {_html_escape(','.join(str(f) for f in fractions))}</div>")
    # Grid charging state reflects step9 constant
    import step9_my_own_solar_storage as diy
    lines.append(
        f"  <div class='meta'>PV surplus→battery: {'on' if diy.ENABLE_PV_SURPLUS_TO_BATTERY else 'off'} · Grid charging: {'on' if diy.GRID_CHARGING_ENABLED else 'off'} · Compute bills: {'on' if compute_bills else 'off'}</div>"
    )

    for scen in scenarios:
        lines.append(f"  <div class='scenario'>")
        lines.append(f"    <h2>Scenario: {_html_escape(scen)}</h2>")
        for county in counties:
            lines.append(f"    <div class='county'>")
            lines.append(f"      <h3>County: {_html_escape(county)}</h3>")
            lines.append("      <div class='grid'>")
            for path in _gather_plot_paths(exp_root, scen, housing, county):
                rel = os.path.relpath(path, start=os.path.dirname(out_path))
                lines.append(f"        <div><img src='{_html_escape(rel)}' alt='{_html_escape(os.path.basename(path))}' /></div>")
            lines.append("      </div>")
            lines.append("    </div>")
        lines.append("  </div>")

    lines.append("  <p class='note'>Plots are generated by experiments/solar_size_sweep.py; totals CSVs live alongside the images.</p>")
    lines.append("</body>")
    lines.append("</html>")

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def _run_and_build(
    *,
    base_input: str,
    exp_root: str,
    scenarios: List[str],
    housing: str,
    counties: List[str],
    fracs: List[float],
    compute_bills: bool,
    dashboard_name: str,
):
    dispatch_label = "dispatch_dynamic" if getattr(diy, "USE_DYNAMIC_DISPATCH", False) else "dispatch_classic"
    eff_root = os.path.join(exp_root, dispatch_label)
    opts = SweepOptions(compute_bills=compute_bills)
    os.makedirs(eff_root, exist_ok=True)
    ran_counties: List[str] = []
    for scen in scenarios:
        results = run(
            base_input,
            scen,
            housing,
            counties=counties,
            fractions=fracs,
            options=opts,
            experiments_root=eff_root,
        )
        ran_counties = sorted(set(ran_counties) | set(results.keys()))
    out_html = os.path.join(eff_root, dashboard_name)
    _write_dashboard(
        out_html,
        eff_root,
        scenarios,
        housing,
        ran_counties or counties,
        fractions=fracs,
        compute_bills=compute_bills,
    )
    print(f"Dashboard written to: {os.path.abspath(out_html)}")


def main():
    args = parse_args()

    base_input = args.base_input_dir
    exp_root = args.experiments_root
    housing = args.housing_type
    if args.all_counties:
        counties = norcal_counties + socal_counties + central_counties
    else:
        counties = args.counties or ["Alameda County"]
    fracs = _infer_fractions(args.fractions)
    scenarios = args.scenarios or list(SCENARIOS.keys())
    # Single mode only; grid charging controlled solely by step9 constant
    _run_and_build(
        base_input=base_input,
        exp_root=exp_root,
        scenarios=scenarios,
        housing=housing,
        counties=counties,
        fracs=fracs,
        compute_bills=args.compute_bills,
        dashboard_name=args.dashboard_name,
    )


if __name__ == "__main__":
    main()
