"""Collectors: run the model, return tidy DataFrames.

Follows the repo's established `collect_*` convention (see
`helpers/plot_scenario_comparison_helper.py`). The one collector here,
`collect_battery_capex_sweep`, is the properly-named replacement for the old
one-off `run_sweeps.py`: it sweeps battery capex for a county through the real
Step-9b co-optimization model, holding solar's price fixed.
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import List, Optional, Sequence

import pandas as pd

from figure_builder import SWEEP_DIR, sweep_csv_path
from figure_builder.dispatch import (
    DEFAULT_SCENARIO,
    SWEEP_POINTS,
    county_dispatch_inputs,
)
from figure_builder.pricing import live_prices


@dataclass(frozen=True)
class SweepModelSettings:
    """Fixed modeling choices shared by the sweep solver and run metadata."""

    billing_year: int = 2026
    max_battery_kwh: float = 40.0
    max_pv_to_annual_load_ratio: float = 1.5
    allow_grid_charging: bool = False
    allow_battery_export: bool = True
    battery_power_cost_usd_per_kw: float = 0.0
    battery_degradation_cost_usd_per_kwh: float = 0.0
    pv_lifetime_years: int = 25
    battery_lifetime_years: int = 15
    discount_rate: float = 0.07
    solver_backend: str = "highs"


SWEEP_MODEL_SETTINGS = SweepModelSettings()

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
    expected_points: Sequence[float],
    expected_columns: Optional[List[str]] = None,
) -> bool:
    """Whether cached results fully describe the requested sweep."""

    expected = normalize_battery_capex_points(expected_points)
    if "battery_capex_kwh" not in df.columns:
        return False
    actual = pd.to_numeric(df["battery_capex_kwh"], errors="coerce")

    return (
        list(df.columns) == (SWEEP_COLUMNS if expected_columns is None else expected_columns)
        and not df.empty
        and set(df["max_battery_kwh"].astype(float)) == {float(max_battery_kwh)}
        and not actual.isna().any()
        and not actual.duplicated().any()
        and sorted(actual.astype(float).tolist()) == expected
    )


def normalize_battery_capex_points(points: Sequence[float]) -> List[float]:
    """Validate, sort, and deduplicate an explicitly requested capex grid."""

    normalized = [float(point) for point in points]
    if not normalized:
        raise ValueError("Battery capex sweep points cannot be empty")
    if not all(math.isfinite(point) for point in normalized):
        raise ValueError("Battery capex sweep points must be finite")
    if any(point <= 0.0 for point in normalized):
        raise ValueError("Battery capex sweep points must be positive")
    return sorted(set(normalized))


def canonical_battery_capex_points(regime=None) -> List[float]:
    """Publication grid including the regime's exact modeled battery price."""

    return normalize_battery_capex_points(
        [*SWEEP_POINTS, live_prices(regime).batt_net_per_kwh]
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
    scenario: str = DEFAULT_SCENARIO,
    points: Optional[Sequence[float]] = None,
    pv_capex_per_kw: Optional[float] = None,
    max_battery_kwh: float = SWEEP_MODEL_SETTINGS.max_battery_kwh,
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
    law), or `pv_capex_per_kw` if given. The default publication grid includes
    the regime's exact modeled net battery price. An explicit ``points``
    argument is treated as a deliberate custom grid and is only validated,
    sorted, and deduplicated. Results cache per (county, regime) to
    figure_builder/sweeps/; pass `force=True` to recompute. Sensitivity grids
    use weighted 12x24 monthly-hour intervals by default; `fine=True` requests
    the substantially slower full 8,760-hour chronology.
    """
    prices = live_prices(regime)
    requested_points = (
        canonical_battery_capex_points(regime)
        if points is None
        else normalize_battery_capex_points(points)
    )
    resolution = "8760" if fine else "288"
    path = sweep_csv_path(slug, prices.regime, resolution)
    if cache and not force and path.exists():
        df = pd.read_csv(path)
        if sweep_cache_is_compatible(
            df,
            max_battery_kwh,
            expected_points=requested_points,
        ):
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
        inp, weights = build_monthly_hourly_inputs(
            inp,
            year=SWEEP_MODEL_SETTINGS.billing_year,
        )
        cycle_monthly = True

    rows = []
    for cb in requested_points:
        t0 = time.time()
        r = _solve_lp(
            inp,
            allow_grid_charging=SWEEP_MODEL_SETTINGS.allow_grid_charging,
            allow_batt_export=SWEEP_MODEL_SETTINGS.allow_battery_export,
            c_pv_kw=c_pv,
            c_batt_kwh=float(cb),
            c_batt_kw=SWEEP_MODEL_SETTINGS.battery_power_cost_usd_per_kw,
            pv_life_yrs=SWEEP_MODEL_SETTINGS.pv_lifetime_years,
            batt_life_yrs=SWEEP_MODEL_SETTINGS.battery_lifetime_years,
            discount_rate=SWEEP_MODEL_SETTINGS.discount_rate,
            c_deg_per_kwh=(
                SWEEP_MODEL_SETTINGS.battery_degradation_cost_usd_per_kwh
            ),
            weights=weights,
            cycle_monthly=cycle_monthly,
            max_battery_kwh=max_battery_kwh,
            max_pv_to_annual_load_ratio=(
                SWEEP_MODEL_SETTINGS.max_pv_to_annual_load_ratio
            ),
            solver_backend=SWEEP_MODEL_SETTINGS.solver_backend,
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
