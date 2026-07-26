"""Collectors: run the model, return tidy DataFrames.

Follows the repo's established `collect_*` convention (see
`helpers/plot_scenario_comparison_helper.py`). The one collector here,
`collect_battery_capex_sweep`, is the properly-named replacement for the old
one-off `run_sweeps.py`: it sweeps battery capex for a county through the real
Step-9b co-optimization LP, holding solar's price fixed.
"""
from __future__ import annotations

import time
from typing import List, Optional

import pandas as pd

from figure_builder import SWEEP_DIR, sweep_csv_path
from figure_builder.dispatch import SWEEP_POINTS, county_dispatch_inputs
from figure_builder.pricing import live_prices

SWEEP_COLUMNS = ["battery_capex_kwh", "pv_kw", "batt_kwh", "total_cost", "coverage"]


def collect_battery_capex_sweep(
    slug: str,
    *,
    scenario: str = "full_electric_ev_coopt",
    points: List[int] = SWEEP_POINTS,
    pv_capex_per_kw: Optional[float] = None,
    cache: bool = True,
    force: bool = False,
    verbose: bool = True,
) -> pd.DataFrame:
    """Optimal PV/battery sizing across a battery-capex grid for one county.

    Columns: battery_capex_kwh, pv_kw, batt_kwh, total_cost, coverage
    (coverage = PV annual generation / annual load).

    Solar capex is fixed at `pv_capex_per_kw`, defaulting to the live net price
    for the current regime. Results cache to figure_builder/sweeps/; pass
    `force=True` to recompute.
    """
    path = sweep_csv_path(slug)
    if cache and not force and path.exists():
        df = pd.read_csv(path)
        if list(df.columns) == SWEEP_COLUMNS:
            return df.sort_values("battery_capex_kwh").reset_index(drop=True)

    from pipeline.steps.step9b_cooptimize_core import CooptInputs, _solve_lp

    c_pv = pv_capex_per_kw if pv_capex_per_kw is not None else live_prices().pv_net_per_kw
    di = county_dispatch_inputs(slug, scenario)
    inp = CooptInputs(load_kwh=di.load, pv_gen_per_kw=di.pv_gen_per_kw,
                      import_rates=di.p_imp, export_rates=di.p_exp)
    load, ypk = di.annual_load, di.yield_per_kw

    rows = []
    for cb in points:
        t0 = time.time()
        r = _solve_lp(
            inp, allow_grid_charging=False, allow_batt_export=True,
            c_pv_kw=c_pv, c_batt_kwh=float(cb), c_batt_kw=0.0,
            pv_life_yrs=25, batt_life_yrs=15, discount_rate=0.07,
            c_deg_per_kwh=0.0, weights=None, cycle_monthly=False,
        )
        rows.append({
            "battery_capex_kwh": cb, "pv_kw": r.pv_kw, "batt_kwh": r.batt_kwh,
            "total_cost": r.total_cost, "coverage": r.pv_kw * ypk / load,
        })
        if verbose:
            print(f"  {slug:12} cb=${cb:>6}  PV={r.pv_kw:6.2f}  batt={r.batt_kwh:9.1f}"
                  f"  cover={r.pv_kw * ypk / load:.2f}  ({time.time() - t0:.0f}s)", flush=True)

    df = pd.DataFrame(rows, columns=SWEEP_COLUMNS)
    if cache:
        SWEEP_DIR.mkdir(parents=True, exist_ok=True)
        df.to_csv(path, index=False)
    return df
