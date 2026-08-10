"""Collectors: run the model, return tidy DataFrames.

Follows the repo's established `collect_*` convention (see
`helpers/plot_scenario_comparison_helper.py`). The one collector here,
`collect_battery_capex_sweep`, is the properly-named replacement for the old
one-off `run_sweeps.py`: it sweeps battery capex for a county through the real
Step-9b co-optimization model, holding solar's price fixed.
"""
from __future__ import annotations

import time
from typing import List, Optional

import pandas as pd

from figure_builder import SWEEP_DIR, sweep_csv_path
from figure_builder.dispatch import SWEEP_POINTS, county_dispatch_inputs
from figure_builder.pricing import live_prices

SWEEP_COLUMNS = [
    "battery_capex_kwh",
    "pv_kw",
    "batt_kwh",
    "total_cost",
    "coverage",
    "max_battery_kwh",
    "meter_binary_count",
    "solver_rounds",
]


def sweep_cache_is_compatible(
    df: pd.DataFrame,
    max_battery_kwh: float,
    *,
    expected_columns: Optional[List[str]] = None,
) -> bool:
    """Whether cached results fully describe the requested sizing domain."""

    return (
        list(df.columns) == (SWEEP_COLUMNS if expected_columns is None else expected_columns)
        and not df.empty
        and set(df["max_battery_kwh"].astype(float)) == {float(max_battery_kwh)}
    )


def resolve_pv_capex(pv_capex_per_kw=None, regime=None) -> float:
    """The fixed PV $/kW a claim-figure sweep uses: an explicit override if given,
    otherwise the live net price for the regime (the model's sourced, tested
    price).

    This binds the figure data path to the model price by default. It is the
    regression guard for the 2026-07-27 finding that an old figure was drawn at
    an unlabeled $4,000/kW sensitivity-sweep endpoint instead of the real price.
    Sensitivity sweeps may still pass an explicit price; the default cannot
    silently drift to an arbitrary constant.
    """
    if pv_capex_per_kw is not None:
        return float(pv_capex_per_kw)
    return live_prices(regime).pv_net_per_kw


def collect_battery_capex_sweep(
    slug: str,
    *,
    regime=None,
    scenario: str = "full_electric_ev_coopt",
    points: List[int] = SWEEP_POINTS,
    pv_capex_per_kw: Optional[float] = None,
    max_battery_kwh: float = 40.0,
    fine: bool = False,
    cache: bool = True,
    force: bool = False,
    verbose: bool = True,
) -> pd.DataFrame:
    """Optimal PV/battery sizing across a battery-capex grid for one county.

    Columns include battery_capex_kwh, pv_kw, batt_kwh, total_cost, coverage
    (PV annual generation / annual load), the battery-size domain bound, and
    solver diagnostics.

    Solar capex is fixed at the live net price for `regime` (default: current
    law), or `pv_capex_per_kw` if given. Results cache per (county, regime) to
    figure_builder/sweeps/; pass `force=True` to recompute. Sensitivity grids
    use weighted 12x24 monthly-hour intervals by default; `fine=True` requests
    the substantially slower full 8,760-hour chronology.
    """
    prices = live_prices(regime)
    resolution = "8760" if fine else "288"
    path = sweep_csv_path(slug, prices.regime, resolution)
    if cache and not force and path.exists():
        df = pd.read_csv(path)
        if sweep_cache_is_compatible(df, max_battery_kwh):
            return df.sort_values("battery_capex_kwh").reset_index(drop=True)

    from pipeline.steps.step9b_cooptimize_core import (
        CooptInputs,
        _solve_lp,
        build_monthly_hourly_inputs,
    )

    c_pv = resolve_pv_capex(pv_capex_per_kw, regime)
    di = county_dispatch_inputs(slug, scenario)
    inp = CooptInputs(load_kwh=di.load, pv_gen_per_kw=di.pv_gen_per_kw,
                      import_rates=di.p_imp, export_rates=di.p_exp)
    load, ypk = di.annual_load, di.yield_per_kw
    weights = None
    cycle_monthly = False
    if not fine:
        inp, weights = build_monthly_hourly_inputs(inp, year=2026)
        cycle_monthly = True

    rows = []
    for cb in points:
        t0 = time.time()
        r = _solve_lp(
            inp, allow_grid_charging=False, allow_batt_export=True,
            c_pv_kw=c_pv, c_batt_kwh=float(cb), c_batt_kw=0.0,
            pv_life_yrs=25, batt_life_yrs=15, discount_rate=0.07,
            c_deg_per_kwh=0.0, weights=weights, cycle_monthly=cycle_monthly,
            max_battery_kwh=max_battery_kwh,
        )
        rows.append({
            "battery_capex_kwh": cb, "pv_kw": r.pv_kw, "batt_kwh": r.batt_kwh,
            "total_cost": r.total_cost, "coverage": r.pv_kw * ypk / load,
            "max_battery_kwh": float(max_battery_kwh),
            "meter_binary_count": int(r.meter_binary_count),
            "solver_rounds": int(r.solver_rounds),
        })
        if verbose:
            print(f"  {slug:12} cb=${cb:>6}  PV={r.pv_kw:6.2f}  batt={r.batt_kwh:9.1f}"
                  f"  cover={r.pv_kw * ypk / load:.2f}  ({time.time() - t0:.0f}s)", flush=True)

    df = pd.DataFrame(rows, columns=SWEEP_COLUMNS)
    if cache:
        SWEEP_DIR.mkdir(parents=True, exist_ok=True)
        df.to_csv(path, index=False)
    return df
