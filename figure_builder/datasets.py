"""Collectors: run the model, return tidy DataFrames.

Follows the repo's established `collect_*` convention (see
`helpers/plot_scenario_comparison_helper.py`). The collectors replace the old
one-off `run_sweeps.py`: one builds the declared capex sensitivity and the other
builds the exact current-law 8,760-hour market observation used in publication
annotations.
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import List, Optional, Sequence

import pandas as pd

from figure_builder import SWEEP_DIR, market_observation_csv_path, sweep_csv_path
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

MARKET_OBSERVATION_COLUMNS = [
    *SWEEP_COLUMNS,
    "scenario",
    "policy_regime",
    "interval_count",
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


def select_market_observation(
    frame: pd.DataFrame,
    market_price: float,
) -> pd.Series:
    """Return the one solved row at ``market_price``, failing on ambiguity.

    Publication annotations use this primitive instead of interpolation or the
    nearest capex grid point. The strict checks prevent an old or incomplete
    cache from silently supplying a different modeled price.
    """

    missing = [column for column in SWEEP_COLUMNS if column not in frame.columns]
    if missing:
        raise ValueError(f"Market observation is missing columns: {missing}")
    numeric = frame[SWEEP_COLUMNS].apply(pd.to_numeric, errors="coerce")
    if numeric.isna().any().any():
        raise ValueError("Market observation contains non-numeric or missing values")
    if not pd.notna(numeric).all().all() or not all(
        math.isfinite(value) for value in numeric.to_numpy().ravel()
    ):
        raise ValueError("Market observation contains non-finite values")
    matches = numeric[
        numeric["battery_capex_kwh"].map(
            lambda value: math.isclose(
                value,
                float(market_price),
                rel_tol=0.0,
                abs_tol=1e-9,
            )
        )
    ]
    if len(matches) != 1:
        raise ValueError(
            "Expected exactly one solved observation at battery capex "
            f"${market_price:.6f}/kWh; found {len(matches)}"
        )
    row = matches.iloc[0]
    if row["pv_kw"] < 0.0 or row["batt_kwh"] < 0.0:
        raise ValueError("Market observation cannot contain negative capacity")
    if int(row["solver_rounds"]) < 1:
        raise ValueError("Market observation must record at least one solver round")
    return row


def collect_market_price_observation(
    slug: str,
    *,
    regime=None,
    scenario: str = DEFAULT_SCENARIO,
    max_battery_kwh: float = SWEEP_MODEL_SETTINGS.max_battery_kwh,
    cache: bool = True,
    force: bool = False,
    verbose: bool = True,
) -> pd.DataFrame:
    """Solve one exact market-price point using the full 8,760-hour chronology.

    The capex sensitivity curves remain the declared 12x24 approximation. This
    separate observation is the publication-grade check used for each market
    price annotation and Claim 1 headline statistic.
    """

    prices = live_prices(regime)
    market_price = prices.batt_net_per_kwh
    path = market_observation_csv_path(slug, prices.regime)
    if cache and not force and path.exists():
        cached = pd.read_csv(path)
        try:
            select_market_observation(cached, market_price)
        except ValueError:
            pass
        else:
            if (
                list(cached.columns) == MARKET_OBSERVATION_COLUMNS
                and len(cached) == 1
                and set(cached["max_battery_kwh"].astype(float))
                == {float(max_battery_kwh)}
                and set(cached["scenario"]) == {scenario}
                and set(cached["policy_regime"]) == {prices.regime}
                and set(cached["interval_count"].astype(int)) == {8760}
            ):
                return cached.reset_index(drop=True)

    frame = collect_battery_capex_sweep(
        slug,
        regime=regime,
        scenario=scenario,
        points=[market_price],
        max_battery_kwh=max_battery_kwh,
        fine=True,
        cache=False,
        force=True,
        verbose=verbose,
    )
    select_market_observation(frame, market_price)
    frame = frame.assign(
        scenario=scenario,
        policy_regime=prices.regime,
        interval_count=8760,
    )[MARKET_OBSERVATION_COLUMNS]
    if cache:
        SWEEP_DIR.mkdir(parents=True, exist_ok=True)
        frame.to_csv(path, index=False)
    return frame.reset_index(drop=True)


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
