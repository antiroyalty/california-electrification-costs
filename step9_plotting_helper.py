"""
Plotting helper for Step 9 custom dispatch results.

Provides utilities to visualize the first week of January and the first week of
July similar to the figures in pvsamv1_battery.py:

Rows per column (two columns: Jan week and Jul week):
- Load breakdown (stacked area: PV→Load, Battery→Load, Grid→Load)
- Battery SOC (%)
- PV AC power (kWh per hour)
- Battery charging sources (stacked area: PV→Battery, Grid→Battery)

Usage example:
  from step9_plotting_helper import plot_first_weeks
  fig, axes = plot_first_weeks(
      load, pv_ac, batt_to_load, grid_to_load,
      grid_to_batt=grid_to_batt, pv_to_batt=None, soc_percent=soc_series
  )
"""

from __future__ import annotations

from typing import Iterable, Optional, Tuple

import numpy as np
import matplotlib.pyplot as plt


def _slice_week(arr: Iterable[float], start_hour: int, length: int = 24 * 7) -> np.ndarray:
    a = np.asarray(list(arr), dtype=float).ravel()
    end = min(start_hour + length, a.size)
    if start_hour >= end:
        return np.array([], dtype=float)
    return a[start_hour:end]


def _shade_peak(ax: plt.Axes, week_start_hour: int, hours_per_week: int = 168, peak_start: int = 16, peak_end: int = 21) -> None:
    # Shade 4–9 pm for each day in the displayed week
    for d in range(7):
        x0 = d * 24 + peak_start
        x1 = d * 24 + peak_end
        ax.axvspan(x0, x1, color="#f8b7b7", alpha=0.3, lw=0)


def _ensure_len(arr: Iterable[float], target_len: int = 8760) -> np.ndarray:
    a = np.asarray(list(arr), dtype=float).ravel()
    if a.size == target_len:
        return a
    if a.size == 0:
        return np.zeros(target_len)
    # Truncate or pad conservatively
    if a.size > target_len:
        return a[:target_len]
    out = np.zeros(target_len)
    out[: a.size] = a
    return out


def plot_first_weeks(
    load_kwh: Iterable[float],
    pv_ac_kwh: Iterable[float],
    batt_to_load_kwh: Iterable[float],
    grid_to_load_kwh: Iterable[float],
    *,
    grid_to_batt_kwh: Optional[Iterable[float]] = None,
    pv_to_batt_kwh: Optional[Iterable[float]] = None,
    soc_percent: Optional[Iterable[float]] = None,
    peak_start_hour: int = 16,
    peak_end_hour: int = 21,
    title: Optional[str] = None,
    show: bool = True,
    save_path: Optional[str] = None,
) -> Tuple[plt.Figure, np.ndarray]:
    """Create an 8-panel figure: two weeks (Jan and Jul), four rows of plots.

    Inputs are 8760-hour series (lists or arrays). Battery→Load should be the
    delivered energy to the load. PV→Load is computed internally as min(PV, Load).
    """
    # Normalize inputs to 8760
    load = _ensure_len(load_kwh)
    pv_ac = _ensure_len(pv_ac_kwh)
    bl = _ensure_len(batt_to_load_kwh)
    gl = _ensure_len(grid_to_load_kwh)
    gb = _ensure_len(grid_to_batt_kwh) if grid_to_batt_kwh is not None else np.zeros_like(load)
    pb = _ensure_len(pv_to_batt_kwh) if pv_to_batt_kwh is not None else np.zeros_like(load)
    soc = _ensure_len(soc_percent) if soc_percent is not None else None

    # Derived series
    pvl = np.minimum(pv_ac, load)

    # Week start indices (non-leap year): Jan 1 = 0, Jul 1 = 181*24
    jan_start = 0
    jul_start = 181 * 24
    week_len = 24 * 7

    # Prepare figure and axes: 4 rows x 2 cols (Jan | Jul)
    fig, axes = plt.subplots(4, 2, figsize=(16, 10), sharex=False)
    if title:
        fig.suptitle(title, fontsize=14)

    # Helper to plot one column for a given week
    def _plot_col(col_idx: int, week_start: int, col_title: str) -> None:
        # Row 1: Load breakdown
        ax = axes[0, col_idx]
        pvl_w = _slice_week(pvl, week_start, week_len)
        bl_w = _slice_week(bl, week_start, week_len)
        gl_w = _slice_week(gl, week_start, week_len)
        x = np.arange(pvl_w.size)
        ax.stackplot(x, pvl_w, bl_w, gl_w, labels=["PV→Load", "Battery→Load", "Grid→Load"], colors=["#66c2a5", "#fc8d62", "#8da0cb"], alpha=0.9)
        ax.set_ylabel("kWh")
        ax.set_title(col_title)
        ax.legend(loc="upper right", fontsize=8)
        _shade_peak(ax, week_start, week_len, peak_start_hour, peak_end_hour)

        # Row 2: Battery SOC (%) if provided
        ax = axes[1, col_idx]
        if soc is not None and soc.size >= week_start + week_len:
            s = _slice_week(soc, week_start, week_len)
            ax.plot(np.arange(s.size), s, color="#e78ac3", lw=1.5)
            ax.set_ylabel("SOC %")
        else:
            ax.text(0.5, 0.5, "No SOC provided", ha="center", va="center", transform=ax.transAxes)
        _shade_peak(ax, week_start, week_len, peak_start_hour, peak_end_hour)

        # Row 3: PV AC (kWh)
        ax = axes[2, col_idx]
        pv_w = _slice_week(pv_ac, week_start, week_len)
        ax.plot(np.arange(pv_w.size), pv_w, color="#1b9e77", lw=1.2)
        ax.set_ylabel("PV kWh")
        _shade_peak(ax, week_start, week_len, peak_start_hour, peak_end_hour)

        # Row 4: Battery charging sources
        ax = axes[3, col_idx]
        pb_w = _slice_week(pb, week_start, week_len)
        gb_w = _slice_week(gb, week_start, week_len)
        ax.stackplot(np.arange(pb_w.size), pb_w, gb_w, labels=["PV→Battery", "Grid→Battery"], colors=["#a6d854", "#ffd92f"], alpha=0.9)
        ax.set_ylabel("kWh")
        ax.set_xlabel("Hour of week")
        ax.legend(loc="upper right", fontsize=8)
        _shade_peak(ax, week_start, week_len, peak_start_hour, peak_end_hour)

    _plot_col(0, jan_start, "First Week of January")
    _plot_col(1, jul_start, "First Week of July")

    fig.tight_layout(rect=(0, 0, 1, 0.96))
    if save_path:
        fig.savefig(save_path, dpi=150)
    if show:
        plt.show()
    return fig, axes

