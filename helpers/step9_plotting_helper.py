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


def _draw_guides(ax: plt.Axes, length: int) -> None:
    """Draw vertical dashed guide lines at midnight (black) and noon (grey) for a week window.
    Expects x-axis to be 0..length-1 hours of the week.
    """
    for d in range(7):
        midnight = d * 24
        noon = midnight + 12
        if midnight < length:
            ax.axvline(midnight, color="black", linestyle="--", linewidth=0.8, alpha=0.5)
        if noon < length:
            ax.axvline(noon, color="grey", linestyle="--", linewidth=0.8, alpha=0.6)


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
    pv_used_kwh: Optional[Iterable[float]] = None,
    summary_stats: Optional[dict] = None,
    peak_start_hour: int = 16,
    peak_end_hour: int = 21,
    title: Optional[str] = None,
    show: bool = True,
    save_path: Optional[str] = None,
    close: bool = False,
) -> Tuple[plt.Figure, np.ndarray]:
    """Create an 8-panel figure: two weeks (Jan and Jul), four rows of plots.

    Inputs are 8760-hour series (lists or arrays). Battery→Load should be the
    delivered energy to the load. PV→Load is computed internally as min(PV, Load).
    Set ``close=True`` for fire-and-forget rendering loops; the default keeps
    the returned figure open for callers that need to inspect or embed it.
    """
    # Normalize inputs to 8760
    load = _ensure_len(load_kwh)
    pv_ac = _ensure_len(pv_ac_kwh)
    bl = _ensure_len(batt_to_load_kwh)
    gl = _ensure_len(grid_to_load_kwh)
    gb = _ensure_len(grid_to_batt_kwh) if grid_to_batt_kwh is not None else np.zeros_like(load)
    pb = _ensure_len(pv_to_batt_kwh) if pv_to_batt_kwh is not None else np.zeros_like(load)
    soc = _ensure_len(soc_percent) if soc_percent is not None else None

    try:
        print("[PlotHelper] lengths load/pv/bl/gl/gb/pb/soc:", load.size, pv_ac.size, bl.size, gl.size, gb.size, pb.size, (soc.size if soc is not None else None))
    except Exception:
        pass

    # Derived series
    pvl = np.minimum(pv_ac, load)

    # Week start indices (non-leap year): Jan 1 = 0, Jul 1 = 181*24
    jan_start = 0
    jul_start = 181 * 24
    week_len = 24 * 7

    # Prepare figure and axes: 5 rows x 2 cols (Jan | Jul)
    fig, axes = plt.subplots(5, 2, figsize=(16, 12), sharex=False)
    try:
        print("[PlotHelper] Figure and axes created.")
    except Exception:
        pass
    if title:
        # Position the title with modest extra headroom
        fig.suptitle(title, fontsize=14, y=0.99)
    # Add summary statistics box under the title
    if summary_stats:
        try:
            lines = []
            for k, v in summary_stats.items():
                if isinstance(v, float):
                    # choose units formatting heuristically
                    if 'kwh' in k.lower():
                        lines.append(f"{k}: {v:,.0f}")
                    elif 'kw' in k.lower():
                        lines.append(f"{k}: {v:,.2f}")
                    else:
                        lines.append(f"{k}: {v}")
                else:
                    lines.append(f"{k}: {v}")
            text = "\n".join(lines)
            # Place summary box just below the title
            fig.text(0.5, 0.955, text, ha='center', va='top', fontsize=10,
                      bbox=dict(boxstyle='round', facecolor='white', alpha=0.8, edgecolor='grey'))
        except Exception as e:
            print("[PlotHelper] summary_stats render failed:", e)

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
        _draw_guides(ax, pvl_w.size)
        try:
            print(f"[PlotHelper] Row1 {col_title}: sizes pvl/bl/gl:", pvl_w.size, bl_w.size, gl_w.size)
        except Exception:
            pass

        # Row 2: Battery SOC (%) if provided
        ax = axes[1, col_idx]
        if soc is not None and soc.size >= week_start + week_len:
            s = _slice_week(soc, week_start, week_len)
            ax.plot(np.arange(s.size), s, color="#e78ac3", lw=1.5)
            ax.set_ylabel("SOC %")
        else:
            ax.text(0.5, 0.5, "No SOC provided", ha="center", va="center", transform=ax.transAxes)
        _shade_peak(ax, week_start, week_len, peak_start_hour, peak_end_hour)
        _draw_guides(ax, week_len)
        try:
            print(f"[PlotHelper] Row2 {col_title}: SOC available=", soc is not None)
        except Exception:
            pass

        # Row 3: PV AC (kWh) — gross available
        ax = axes[2, col_idx]
        pv_w = _slice_week(pv_ac, week_start, week_len)
        ax.plot(np.arange(pv_w.size), pv_w, color="#1b9e77", lw=1.2)
        ax.set_ylabel("PV kWh")
        _shade_peak(ax, week_start, week_len, peak_start_hour, peak_end_hour)
        _draw_guides(ax, pv_w.size)
        try:
            print(f"[PlotHelper] Row3 {col_title}: pv_w size/sum:", pv_w.size, float(pv_w.sum()) if pv_w.size else 0)
        except Exception:
            pass

        # Row 4: PV Used (kWh) — on-site PV to load + battery
        ax = axes[3, col_idx]
        if pv_used_kwh is not None:
            pv_used = _slice_week(_ensure_len(pv_used_kwh), week_start, week_len)
            ax.plot(np.arange(pv_used.size), pv_used, color="#d95f02", lw=1.2)
        else:
            ax.text(0.5, 0.5, "No PV used series", ha="center", va="center", transform=ax.transAxes)
        ax.set_ylabel("PV Used kWh")
        _shade_peak(ax, week_start, week_len, peak_start_hour, peak_end_hour)
        _draw_guides(ax, week_len)
        try:
            print(f"[PlotHelper] Row4 {col_title}: pv_used present=", pv_used_kwh is not None)
        except Exception:
            pass

        # Row 5: Battery charging sources
        ax = axes[4, col_idx]
        pb_w = _slice_week(pb, week_start, week_len)
        gb_w = _slice_week(gb, week_start, week_len)
        ax.stackplot(np.arange(pb_w.size), pb_w, gb_w, labels=["PV→Battery", "Grid→Battery"], colors=["#a6d854", "#ffd92f"], alpha=0.9)
        ax.set_ylabel("kWh")
        ax.set_xlabel("Hour of week")
        ax.legend(loc="upper right", fontsize=8)
        _shade_peak(ax, week_start, week_len, peak_start_hour, peak_end_hour)
        _draw_guides(ax, pb_w.size)
        try:
            print(f"[PlotHelper] Row5 {col_title}: pb_w/gb_w sizes:", pb_w.size, gb_w.size)
        except Exception:
            pass

    _plot_col(0, jan_start, "First Week of January")
    _plot_col(1, jul_start, "First Week of July")

    # Reserve a bit of extra top margin for title + summary box
    fig.tight_layout(rect=(0, 0, 1, 0.90))
    try:
        if save_path:
            print("[PlotHelper] Saving figure to:", save_path)
            fig.savefig(save_path, dpi=150)
            print("[PlotHelper] Figure saved.")
        if show:
            print("[PlotHelper] Showing figure …")
            plt.show()
    except Exception as e:
        print("[PlotHelper] Save/show failed:", e)
    finally:
        if close:
            plt.close(fig)
    return fig, axes
