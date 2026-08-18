"""Pure chart functions: (tidy data + params) -> matplotlib Figure.

No file IO, no HTML, no globals. Each returns `(fig, meta)` where `meta` is a
dict of the derived numbers a caption needs (so captions and charts can never
disagree). `plot_pv_batt_vs_capex` is the single dual-axis recipe used for both
the headline Figure A and each of the four county-grid panels.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Tuple

import numpy as np
import pandas as pd

# --- shared "designed document" palette -------------------------------------
INK = "#1E2A26"
INK_SOFT = "#5C6B66"
INK_FAINT = "#8A968F"
RULE = "#D9DDD5"
ACCENT = "#2B6E63"
ACCENT_INK = "#1D4B44"
POS = "#2E7D46"
NEG = "#A23B2E"
CAUT = "#8A5A12"
MONO = {"family": "monospace"}


def apply_style(serif_first: str = "Georgia") -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.rcParams.update({
        "figure.dpi": 150, "savefig.dpi": 150,
        "font.family": "serif",
        "font.serif": [serif_first, "Times New Roman", "DejaVu Serif"],
        "text.color": INK, "axes.edgecolor": RULE, "axes.labelcolor": INK,
        "xtick.color": INK_SOFT, "ytick.color": INK_SOFT, "axes.linewidth": 1.0,
        "font.size": 11,
    })


Meta = Dict[str, float | str | int]

EAC_CASE_ORDER = [
    "gas_ice_reference",
    "fixed_pv_electric",
    "cooptimized_electric",
]
EAC_CASE_LABELS = {
    "gas_ice_reference": "Gas appliances + ICE\n(fixed PV/storage)",
    "fixed_pv_electric": "Full electric + fixed PV",
    "cooptimized_electric": "Full electric + co-optimized PV/storage",
}
EAC_COMPONENT_STYLE = [
    ("capex_pv", "Solar capex", "#2B6E63"),
    ("capex_storage", "Storage capex", "#8A5A12"),
    ("capex_electric", "Electric equipment capex", "#5B7FA3"),
    ("capex_gas", "Gas equipment capex", "#9B7355"),
    ("annual_bill_electric", "Electricity bill", "#84B7A8"),
    ("annual_bill_gas", "Gas bill", "#D7A86E"),
    ("vehicle_om", "Vehicle O&M", "#8A968F"),
]


def solar_generation_weighted_export_rate(dispatch) -> float:
    """Average hourly export credit weighted by modeled PV production.

    An unweighted 8,760-hour mean gives nighttime prices weight even though
    rooftop solar cannot export at night. This metric describes the export
    value faced by an incremental PV production profile before accounting for
    household load, storage dispatch, or export-credit saturation.
    """
    pv_generation = np.asarray(dispatch.pv_gen_per_kw, dtype=float)
    export_rates = np.asarray(dispatch.p_exp, dtype=float)
    if pv_generation.ndim != 1 or export_rates.ndim != 1:
        raise ValueError("PV generation and export rates must be one-dimensional")
    if len(pv_generation) == 0 or len(pv_generation) != len(export_rates):
        raise ValueError(
            "PV generation and export rates must have identical non-zero lengths"
        )
    if not np.isfinite(pv_generation).all() or not np.isfinite(export_rates).all():
        raise ValueError("PV generation and export rates must contain only finite values")
    if (pv_generation < 0).any():
        raise ValueError("PV generation cannot be negative")
    if (export_rates < 0).any():
        raise ValueError("Export rates cannot be negative")
    if float(pv_generation.sum()) <= 0.0:
        raise ValueError("PV generation must have a positive annual total")
    return float(np.average(export_rates, weights=pv_generation))


def plot_pv_batt_vs_capex(
    sweep: pd.DataFrame,
    *,
    batt_price_net: float,
    market_observation: pd.Series,
    market_resolution_label: str,
    title: str,
    compact: bool = False,
    min_capex: float = 25.0,
) -> Tuple["object", Meta]:
    """Dual-axis: optimal solar (kW) and optimal battery (kWh) vs battery capex.

    Solar sits flat at its solar-only optimum while the battery is zero (today's
    price included), then both rise together as storage cheapens. `compact=True`
    renders the smaller, lightly-annotated county-grid panel; `compact=False`
    the fully-annotated headline figure. Only battery capex is swept; solar's
    price is fixed (the caption must say so).
    """
    apply_style()
    import matplotlib.pyplot as plt

    df = sweep.sort_values("battery_capex_kwh")
    df = df[df.battery_capex_kwh >= min_capex]
    figsize = (6.2, 4.2) if compact else (7.4, 4.5)
    fig, axL = plt.subplots(figsize=figsize)
    axR = axL.twinx()
    meta, (lP, lB) = _draw_pv_batt(axL, axR, df, batt_price_net,
                                   market_observation=market_observation,
                                   market_resolution_label=market_resolution_label,
                                   compact=compact, rich=not compact)
    axL.set_title(title, fontsize=11 if compact else 11.5, color=INK, pad=8, loc="left")
    axL.legend(handles=[lP, lB], loc="upper center", fontsize=8.5 if compact else 9.5,
               frameon=False, ncol=2, bbox_to_anchor=(0.5, -0.17 if compact else -0.16))
    return fig, meta


def _draw_pv_batt(axL, axR, df, batt_price_net, *, market_observation,
                  market_resolution_label,
                  compact, rich,
                  pv_ymax=None, bt_ymax=None, x_right=None,
                  price_marker_label="today's price"):
    """Draw the dual-axis PV/battery-vs-capex chart onto a given axis pair.

    Shared by the single-panel and the before/after comparison figures. Pass
    `pv_ymax`/`bt_ymax`/`x_right` to force identical scales across panels so a
    two-panel comparison is visually honest. `df` must be pre-filtered/sorted.
    """
    x = df.battery_capex_kwh.values
    pv = df.pv_kw.values
    bt = df.batt_kwh.values
    flat = pv[bt < 0.2]
    pv_flat = float(flat.mean()) if len(flat) else float(pv.min())
    if x_right is None:
        x_right = max(float(x.max()), batt_price_net) * 1.03
    lwP, lwB, ms = (2.4, 2.0, 3.2) if compact else (2.6, 2.2, 4.0)

    axR.fill_between(x, 0, bt, color=CAUT, alpha=0.10, zorder=1)
    lB, = axR.plot(x, bt, color=CAUT, lw=lwB, marker="o", ms=ms, zorder=3,
                   label="Optimal battery (kWh)")
    lP, = axL.plot(x, pv, color=ACCENT, lw=lwP, marker="o", ms=ms, zorder=4,
                   label="Optimal solar (kW)")

    axL.axhline(pv_flat, ls=(0, (4, 3)), color=ACCENT, lw=1.0, alpha=0.55, zorder=2)
    solar_lbl = f"solar-only  {pv_flat:.2f} kW" if compact else f"solar-only optimum  {pv_flat:.2f} kW"
    axL.text(x_right * 0.98, pv_flat + 0.04 * pv.max(), solar_lbl, ha="right",
             va="bottom", color=ACCENT_INK, fontsize=8.5 if compact else 9)

    market_price = float(market_observation["battery_capex_kwh"])
    market_pv = float(market_observation["pv_kw"])
    market_batt = float(market_observation["batt_kwh"])
    if not np.isclose(market_price, batt_price_net, rtol=0.0, atol=1e-9):
        raise ValueError(
            f"Market observation capex {market_price} does not match marker "
            f"price {batt_price_net}"
        )
    if not np.isfinite([market_pv, market_batt]).all():
        raise ValueError("Market observation capacities must be finite")
    if market_pv < 0.0 or market_batt < 0.0:
        raise ValueError("Market observation capacities cannot be negative")

    axL.axvline(batt_price_net, color=INK_FAINT, ls=(0, (2, 2)), lw=1.1, zorder=2)
    axL.scatter([market_price], [market_pv], marker="D", s=30, color=ACCENT,
                edgecolor="white", linewidth=0.7, zorder=6)
    axR.scatter([market_price], [market_batt], marker="D", s=30, color=CAUT,
                edgecolor="white", linewidth=0.7, zorder=6)
    if market_batt < 0.01 and market_batt > 1e-6:
        batt_label = "<0.01 kWh"
    else:
        batt_label = f"{market_batt:.2f} kWh"
    axL.text(batt_price_net - x_right * 0.014, pv.max() * 0.97,
             f"{price_marker_label}\n${batt_price_net:,.0f}/kWh\n"
             f"{market_resolution_label}: battery = {batt_label}",
             ha="right", va="top", color=INK_SOFT, fontsize=8 if compact else 9,
             linespacing=1.25)

    if rich and len(x) > 3:
        axL.annotate("cheaper storage\n" + r"$\rightarrow$ more solar",
                     xy=(x[2], pv[2]), xytext=(0.19 * x_right, pv.max() * 0.9),
                     color=ACCENT_INK, fontsize=9.5, ha="left", va="center",
                     fontweight="bold", linespacing=1.25,
                     arrowprops=dict(arrowstyle="->", color=ACCENT_INK, lw=1.4,
                                     connectionstyle="arc3,rad=-0.2"))

    axL.set_xlabel(r"Battery cost  (\$/kWh)   $\leftarrow$ cheaper",
                   fontsize=9.5 if compact else 10.5)
    axL.set_ylabel("Optimal solar (kW)", color=ACCENT_INK, fontsize=9.5 if compact else 10.5)
    axR.set_ylabel("Optimal battery (kWh)", color=CAUT, fontsize=9.5 if compact else 10.5)
    axL.set_ylim(0, pv_ymax if pv_ymax else pv.max() * 1.14)
    axR.set_ylim(0, bt_ymax if bt_ymax else max(bt.max(), 1) * 1.14)
    axL.set_xlim(0, x_right)
    axL.tick_params(labelsize=8.5 if compact else 9.5)
    axR.tick_params(labelsize=8.5 if compact else 9.5, colors=CAUT)
    axL.spines["top"].set_visible(False)
    axR.spines["top"].set_visible(False)
    return {
        "pv_flat": pv_flat,
        "pv_max": float(pv.max()),
        "market_price": market_price,
        "market_pv_kw": market_pv,
        "market_batt_kwh": market_batt,
        "market_resolution": market_resolution_label,
    }, (lP, lB)


def plot_pv_batt_vs_capex_compare(
    before: pd.DataFrame, after: pd.DataFrame, *,
    batt_before: float, batt_after: float, title: str,
    market_before: pd.Series, market_after: pd.Series,
    market_before_resolution: str, market_after_resolution: str,
    panel_labels: Tuple[str, str], min_capex: float = 25.0,
) -> Tuple["object", Dict[str, Meta]]:
    """Two side-by-side dual-axis panels on shared scales: a before/after
    comparison of the same county under two price regimes. Returns
    `(fig, {"before": meta, "after": meta})`."""
    apply_style()
    import matplotlib.pyplot as plt

    b = before.sort_values("battery_capex_kwh")
    b = b[b.battery_capex_kwh >= min_capex]
    a = after.sort_values("battery_capex_kwh")
    a = a[a.battery_capex_kwh >= min_capex]
    pv_ymax = max(b.pv_kw.max(), a.pv_kw.max()) * 1.14
    bt_ymax = max(b.batt_kwh.max(), a.batt_kwh.max(), 1) * 1.14
    x_right = max(b.battery_capex_kwh.max(), a.battery_capex_kwh.max(),
                  batt_before, batt_after) * 1.03

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12.6, 4.9))
    ax1R, ax2R = ax1.twinx(), ax2.twinx()
    mB, (lP, lB) = _draw_pv_batt(
                                 ax1, ax1R, b, batt_before,
                                 market_observation=market_before,
                                 market_resolution_label=market_before_resolution,
                                 compact=True, rich=False,
                                 pv_ymax=pv_ymax, bt_ymax=bt_ymax, x_right=x_right,
                                 price_marker_label="2025 price")
    mA, _ = _draw_pv_batt(
                          ax2, ax2R, a, batt_after,
                          market_observation=market_after,
                          market_resolution_label=market_after_resolution,
                          compact=True, rich=False,
                          pv_ymax=pv_ymax, bt_ymax=bt_ymax, x_right=x_right,
                          price_marker_label="today's price")
    # De-clutter shared inner labels: PV axis on the left panel, battery axis on the right.
    ax1R.set_ylabel("")
    ax2.set_ylabel("")
    ax1.set_title(panel_labels[0], fontsize=11, color=ACCENT_INK, pad=8, loc="left")
    ax2.set_title(panel_labels[1], fontsize=11, color=NEG, pad=8, loc="left")
    fig.suptitle(title, fontsize=12.5, color=INK, x=0.02, ha="left", y=1.03)
    fig.legend(handles=[lP, lB], loc="upper center", fontsize=9.5, frameon=False,
               ncol=2, bbox_to_anchor=(0.5, -0.01))
    fig.tight_layout()
    return fig, {"before": mB, "after": mA}


def plot_marginal_solar_value_ladder(
    dispatch, prices, *, discount_rate: float = 0.07, peak_quantile: float = 0.90,
    round_trip_eff: float = 0.90,
) -> Tuple["object", Meta]:
    """Bar chart: the value of the marginal kWh of rooftop solar, exported at the
    ACC rate vs. stored into the evening peak, against solar's own break-even."""
    apply_style()
    import matplotlib.pyplot as plt

    pv_lcoe = prices.pv_lcoe(dispatch.yield_per_kw, discount_rate, 25)
    p_imp = np.asarray(dispatch.p_imp)
    v_export = solar_generation_weighted_export_rate(dispatch)
    peak_import_rate = float(
        np.mean(p_imp[p_imp >= np.quantile(p_imp, peak_quantile)])
    )
    v_peak = peak_import_rate * round_trip_eff
    storage_margin_after_solar = v_peak - pv_lcoe
    peak_share_pct = (1.0 - peak_quantile) * 100.0
    round_trip_loss_pct = (1.0 - round_trip_eff) * 100.0

    fig, ax = plt.subplots(figsize=(7.4, 4.5))
    cats = ["Solar-coincident export:\nPV-generation-weighted credit",
            "Illustrative storage case:\nshift to top-price hours"]
    vals = [v_export, v_peak]
    xb = [0, 1]
    ax.bar(xb, vals, width=0.5, color=[NEG, POS], zorder=3, edgecolor="white", lw=1)
    ax.axhline(pv_lcoe, ls=(0, (5, 3)), color=INK, lw=1.4, zorder=4)
    ax.text(-0.50, pv_lcoe + 0.004, f"solar LCOE  ${pv_lcoe:.3f}/kWh",
            ha="left", va="bottom", color=INK, fontsize=9.5, **MONO)
    for xi, v in zip(xb, vals):
        ax.text(xi, v + 0.008, f"${v:.3f}", ha="center", va="bottom", fontsize=13,
                color=INK, **MONO)
    ax.text(0, v_export + 0.045, "below solar break-even",
            ha="center", va="bottom", color=NEG, fontsize=9, fontweight="bold", linespacing=1.25)
    ax.text(1, v_peak + 0.085,
            f"illustrative peak-shift value\nafter {round_trip_loss_pct:.0f}% battery loss",
            ha="center", va="top", color=POS, fontsize=9, fontweight="bold", linespacing=1.25)
    if storage_margin_after_solar > 0.0:
        ax.annotate(
            "",
            xy=(1.36, v_peak),
            xytext=(1.36, pv_lcoe),
            arrowprops=dict(arrowstyle="<->", color=CAUT, lw=1.5),
        )
        ax.text(
            1.41,
            (v_peak + pv_lcoe) / 2.0,
            f"${storage_margin_after_solar:.3f}/kWh\nleft to cover\nstorage cost",
            ha="left",
            va="center",
            color=CAUT,
            fontsize=8.7,
            fontweight="bold",
            linespacing=1.2,
        )
    ax.set_xticks(xb)
    ax.set_xticklabels(cats, fontsize=9.8, color=INK_SOFT, linespacing=1.3)
    ax.set_ylabel("Illustrative value of surplus rooftop solar  ($/kWh)", fontsize=10.3)
    ax.set_ylim(0, max(0.54, v_peak * 1.25))
    ax.set_xlim(-0.55, 1.82)
    for s in ["top", "right"]:
        ax.spines[s].set_visible(False)
    ax.tick_params(labelsize=9.5)
    ax.set_title("Energy-value illustration only — battery capital cost is excluded",
                 fontsize=11.5, color=INK, pad=10, loc="left")
    return fig, {
        "v_export": v_export,
        "peak_import_rate": peak_import_rate,
        "v_peak": v_peak,
        "pv_lcoe": pv_lcoe,
        "storage_margin_after_solar": storage_margin_after_solar,
        "peak_share_pct": peak_share_pct,
        "round_trip_eff": round_trip_eff,
    }


def plot_pv_ceiling(sweep: pd.DataFrame, dispatch, *, batt_price_net: float
                    ) -> Tuple["object", Meta]:
    """Log-x line: optimal solar rises then flattens against total annual load,
    with near-free storage in the representative-household sizing domain."""
    apply_style()
    import matplotlib.pyplot as plt

    df = sweep.sort_values("battery_capex_kwh")
    xc = df.battery_capex_kwh.values
    pvc = df.pv_kw.values
    btc = df.batt_kwh.values
    pv_100, pv_100_rte = dispatch.pv_kw_for_full_load()
    yield_kw = dispatch.yield_per_kw
    annual_load = dispatch.annual_load

    fig, axc = plt.subplots(figsize=(7.4, 4.5))
    axc.axhspan(pv_100, pv_100_rte, color=NEG, alpha=0.09, zorder=1)
    axc.axhline(pv_100, ls=(0, (5, 3)), color=NEG, lw=1.3, zorder=3)
    axc.text(1.05, pv_100_rte + 0.12,
             f"your entire annual load  ({pv_100:.1f}-{pv_100_rte:.1f} kW of solar)",
             ha="left", va="bottom", color=NEG, fontsize=9.5, fontweight="bold")
    axc.plot(xc, pvc, color=ACCENT, lw=2.6, marker="o", ms=4, zorder=4)
    axc.set_xscale("log")
    axc.axvline(batt_price_net, color=INK_FAINT, ls=(0, (2, 2)), lw=1.2, zorder=2)
    axc.text(batt_price_net * 1.06, 0.5, "today's\nprice", ha="left", va="bottom",
             color=INK_SOFT, fontsize=8.5, linespacing=1.2)
    imin = int(np.argmin(xc))
    axc.annotate(
        f"battery here = {btc[imin]:,.0f} kWh\n(the household-size limit),\n"
        f"yet solar is still only {pvc[imin]:.1f} kW",
        xy=(xc[imin], pvc[imin]), xytext=(2.4, pv_100_rte * 0.42),
        color=ACCENT_INK, fontsize=9, ha="left", va="center", fontweight="bold",
        linespacing=1.3,
        arrowprops=dict(arrowstyle="->", color=ACCENT_INK, lw=1.4,
                        connectionstyle="arc3,rad=0.2"))
    axc.set_xlabel(r"Battery capital cost  (\$/kWh, log scale)   $\leftarrow$ cheaper / nearly free",
                   fontsize=10.5)
    axc.set_ylabel("Optimal solar size (kW)", color=ACCENT_INK, fontsize=10.5)
    axc.set_ylim(0, pv_100_rte * 1.28)
    axc.set_xlim(0.8, 1500)
    axc.tick_params(labelsize=9.5)
    for s in ["top", "right"]:
        axc.spines[s].set_visible(False)
    axc.set_title("Near-free household storage still leaves a solar ceiling",
                  fontsize=11.5, color=INK, pad=10, loc="left")
    return fig, {"pv_100": pv_100, "pv_100_rte": pv_100_rte,
                 "batt_min": float(btc[imin]), "pv_min": float(pvc[imin]),
                 "cover_min": float(pvc[imin] * yield_kw / annual_load)}


def plot_case_study_eac(
    eac: pd.DataFrame,
    *,
    counties: tuple[str, ...] = (
        "alameda",
        "fresno",
        "los-angeles",
        "san-diego",
    ),
) -> Tuple["object", Meta]:
    """Four-panel stacked EAC comparison with one unobstructed shared legend."""

    apply_style()
    import matplotlib.pyplot as plt

    missing = set(counties) - set(eac["county_slug"])
    if missing:
        raise ValueError(f"Case-study EAC data missing counties: {sorted(missing)}")
    fig, axes = plt.subplots(2, 2, figsize=(12.8, 9.2))
    maximum = 0.0
    totals: dict[tuple[str, str], float] = {}
    for axis, county in zip(axes.ravel(), counties):
        rows = eac[eac["county_slug"] == county].set_index("case")
        if set(rows.index) != set(EAC_CASE_ORDER):
            raise ValueError(f"{county} does not contain all three EAC cases")
        rows = rows.loc[EAC_CASE_ORDER]
        bottom = np.zeros(len(rows))
        x = np.arange(len(rows))
        for column, label, color in EAC_COMPONENT_STYLE:
            values = rows[column].to_numpy(dtype=float)
            axis.bar(
                x,
                values,
                bottom=bottom,
                width=0.68,
                color=color,
                label=label,
                edgecolor="white",
                linewidth=0.4,
            )
            bottom += values
        maximum = max(maximum, float(bottom.max()))
        for xi, total in zip(x, bottom):
            axis.text(
                xi,
                total + 120.0,
                f"${total:,.0f}",
                ha="center",
                va="bottom",
                fontsize=8.5,
                color=INK,
                **MONO,
            )
        totals.update(
            {(county, case): float(total) for case, total in zip(EAC_CASE_ORDER, bottom)}
        )
        axis.set_xticks(x)
        axis.set_xticklabels(
            [EAC_CASE_LABELS[case] for case in EAC_CASE_ORDER],
            fontsize=8.4,
            linespacing=1.15,
        )
        axis.set_title(
            county.replace("-", " ").title() + " County",
            fontsize=11,
            loc="left",
            color=INK,
        )
        axis.spines["top"].set_visible(False)
        axis.spines["right"].set_visible(False)
        axis.grid(axis="y", color=RULE, linewidth=0.6, alpha=0.55)
        axis.set_axisbelow(True)
    for axis in axes.ravel():
        axis.set_ylim(0.0, maximum * 1.14)
        axis.set_ylabel("Equivalent annual cost ($/year)", fontsize=9.5)
    handles, labels = axes.ravel()[0].get_legend_handles_labels()
    fig.legend(
        handles,
        labels,
        loc="lower center",
        ncol=4,
        frameon=False,
        bbox_to_anchor=(0.5, 0.005),
        fontsize=8.7,
    )
    fig.suptitle(
        "Household energy and vehicle cost under three modeled choices",
        x=0.04,
        y=0.99,
        ha="left",
        fontsize=13,
        color=INK,
    )
    fig.tight_layout(rect=(0.0, 0.08, 1.0, 0.96))
    return fig, {
        "case_study_count": len(counties),
        "maximum_total_eac": max(totals.values()),
    }


def _plot_statewide_sorted_savings(
    summary: pd.DataFrame,
    *,
    column: str,
    title: str,
    xlabel: str,
    value_format,
) -> Tuple["object", Meta]:
    apply_style()
    import matplotlib.pyplot as plt

    if summary.empty or column not in summary:
        raise ValueError(f"Statewide savings data missing {column}")
    rows = summary.sort_values(column, ascending=True).reset_index(drop=True)
    values = rows[column].to_numpy(dtype=float)
    if not np.isfinite(values).all():
        raise ValueError(f"Statewide savings {column} contains non-finite values")
    labels = rows["county_slug"].str.replace("-", " ").str.title()
    colors = [POS if value > 0 else NEG if value < 0 else INK_FAINT for value in values]
    fig, axis = plt.subplots(figsize=(8.2, 11.2))
    y = np.arange(len(rows))
    axis.barh(y, values, color=colors, height=0.72, edgecolor="white", linewidth=0.3)
    axis.axvline(0.0, color=INK, linewidth=1.0)
    axis.set_yticks(y)
    axis.set_yticklabels(labels, fontsize=7.8)
    axis.set_xlabel(xlabel, fontsize=10)
    axis.set_title(title, fontsize=12, loc="left", color=INK, pad=10)
    axis.spines["top"].set_visible(False)
    axis.spines["right"].set_visible(False)
    axis.spines["left"].set_visible(False)
    axis.grid(axis="x", color=RULE, linewidth=0.6, alpha=0.7)
    axis.set_axisbelow(True)
    for index in {0, len(rows) - 1}:
        axis.text(
            values[index],
            index,
            "  " + value_format(values[index]),
            va="center",
            ha="left" if values[index] >= 0 else "right",
            fontsize=8.2,
            color=INK,
            **MONO,
        )
    fig.tight_layout()
    return fig, {
        "county_count": len(rows),
        "positive_count": int((values > 0.0).sum()),
        "zero_count": int((values == 0.0).sum()),
        "negative_count": int((values < 0.0).sum()),
        "mean": float(np.mean(values)),
        "median": float(np.median(values)),
        "minimum": float(np.min(values)),
        "maximum": float(np.max(values)),
        "minimum_county": str(rows.iloc[0]["county_slug"]),
        "maximum_county": str(rows.iloc[-1]["county_slug"]),
    }


def plot_statewide_electrification_savings(
    summary: pd.DataFrame,
) -> Tuple["object", Meta]:
    return _plot_statewide_sorted_savings(
        summary,
        column="gas_to_coopt_pct",
        title="Full electrification vs. gas-appliance + ICE reference",
        xlabel="Reduction in equivalent annual cost (%); positive = lower cost",
        value_format=lambda value: f"{value:.1f}%",
    )


def plot_statewide_cooptimization_savings(
    summary: pd.DataFrame,
) -> Tuple["object", Meta]:
    return _plot_statewide_sorted_savings(
        summary,
        column="fixed_to_coopt_savings",
        title="Value of co-optimizing PV/storage instead of using fixed sizing",
        xlabel="Annual EAC savings from co-optimization ($/year); positive = lower cost",
        value_format=lambda value: f"${value:,.0f}",
    )


@dataclass
class WaterfallStep:
    label: str
    cumulative: float


def plot_battery_value_waterfall(
    *,
    batt_annual_savings: float = 1037.0,      # $/yr, TOU + NEM 3.0, Step 9b dispatch
    batt_annual_savings_flat: float = 977.0,  # $/yr under a flat rate
    batt_kwh: float = 13.5,
    capex_ours_per_kwh: float = 1460.64,      # post-ITC gross, NREL ATB
    capex_energysage_total: float = 14500.0,  # EnergySage midpoint quote
    discount_rate: float = 0.07,
    batt_life_yrs: int = 15,
    horizon_yrs: int = 25,
    escalation: float = 0.071,
) -> Tuple["object", Meta]:
    """Assumption-bridge waterfall: net lifetime value of one home battery from
    the paper's accounting to EnergySage's, one bar per swapped assumption."""
    apply_style()
    import matplotlib.pyplot as plt

    capex_ours = batt_kwh * capex_ours_per_kwh
    annuity = (1 - (1 + discount_rate) ** -batt_life_yrs) / discount_rate
    escsum = ((1 + escalation) ** horizon_yrs - 1) / escalation

    S, Sf = batt_annual_savings, batt_annual_savings_flat
    vals = [
        S * annuity - capex_ours,
        Sf * annuity - capex_ours,
        Sf * batt_life_yrs - capex_ours,
        Sf * horizon_yrs - capex_ours,
        Sf * escsum - capex_ours,
        Sf * escsum - capex_energysage_total,
    ]
    labels = [
        f"Paper method\n(NPV @ {discount_rate:.0%}, {batt_life_yrs}-yr life,\n${capex_ours_per_kwh:,.0f}/kWh)",
        "Drop NEM 3.0 + TOU\n(flat rate)",
        "Simple payback,\nnot NPV",
        f"Stretch to {horizon_yrs}-yr window\n(no yr-{batt_life_yrs} replacement)",
        f"Add {escalation:.1%}/yr\nelectricity escalation",
        f"EnergySage battery price\n(${capex_energysage_total / batt_kwh:,.0f}/kWh)",
    ]

    fig, ax = plt.subplots(figsize=(10.4, 5.6))
    x = np.arange(len(vals))
    w = 0.62
    bottoms = [0]
    heights = [vals[0]]
    for i in range(1, len(vals)):
        bottoms.append(vals[i - 1])
        heights.append(vals[i] - vals[i - 1])
    colors = [NEG] + [POS if h >= 0 else NEG for h in heights[1:]]
    for i in range(len(vals)):
        ax.bar(x[i], heights[i], bottom=bottoms[i], width=w, color=colors[i],
               edgecolor="white", lw=1, zorder=3)
        if i > 0:
            ax.plot([x[i - 1] + w / 2, x[i] - w / 2], [vals[i - 1], vals[i - 1]],
                    color=INK_FAINT, lw=0.9, ls=(0, (3, 2)), zorder=2)
        d = vals[i] - vals[i - 1] if i > 0 else vals[i]
        if i == 1:
            ax.text(x[i], min(bottoms[i], vals[i]) - 900, f"-${abs(d):,.0f}",
                    ha="center", va="top", fontsize=8.5, fontweight="bold", color=INK_SOFT)
        else:
            vlbl = f"${vals[i]:,.0f}" if vals[i] >= 0 else f"-${abs(vals[i]):,.0f}"
            if i == 0:
                ax.text(x[i], vals[i] - 1600, vlbl, ha="center", va="top",
                        fontsize=10.5, fontweight="bold", color=INK)
            else:
                ax.text(x[i], vals[i] + 1300, vlbl, ha="center", va="bottom",
                        fontsize=10.5, fontweight="bold", color=INK)
                ax.text(x[i], bottoms[i] + heights[i] / 2,
                        f"+${d:,.0f}" if d >= 0 else f"-${abs(d):,.0f}",
                        ha="center", va="center", fontsize=8.5, color="white",
                        fontweight="bold")
    ax.set_ylim(-17000, 60000)
    ax.axhline(0, color=INK, lw=1.3, zorder=4)
    ax.text(len(vals) - 0.55, 900, "battery breaks even", ha="right", va="bottom",
            fontsize=8.5, color=INK_SOFT, style="italic")
    ax.axhspan(-17000, 0, color=NEG, alpha=0.04, zorder=0)
    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=8.4, color=INK_SOFT, linespacing=1.3)
    ax.set_ylabel("Net lifetime value of the 13.5 kWh battery  ($)", fontsize=10.5)
    for s in ["top", "right"]:
        ax.spines[s].set_visible(False)
    ax.tick_params(labelsize=9)
    ax.set_title("Same battery, same house. Different accounting methods?",
                 fontsize=12.5, color=INK, pad=12, loc="left")
    fig.text(0.5, -0.02,
             "Alameda / PG&E, 7.6 kW PV + one 13.5 kWh Powerwall. Battery annual "
             "savings from Step 9b dispatch. Steps applied in sequence (order-dependent).",
             ha="center", va="top", fontsize=7.8, color=INK_FAINT)
    fig.tight_layout()
    return fig, {"final_value": vals[-1], "paper_value": vals[0]}
