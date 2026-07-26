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


Meta = Dict[str, float]


def plot_pv_batt_vs_capex(
    sweep: pd.DataFrame,
    *,
    batt_price_net: float,
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
    x = df.battery_capex_kwh.values
    pv = df.pv_kw.values
    bt = df.batt_kwh.values
    flat = pv[bt < 0.2]
    pv_flat = float(flat.mean()) if len(flat) else float(pv.min())
    x_right = max(float(x.max()), batt_price_net) * 1.03

    figsize = (6.2, 4.2) if compact else (7.4, 4.5)
    lwP, lwB, ms = (2.4, 2.0, 3.2) if compact else (2.6, 2.2, 4.0)
    fig, axL = plt.subplots(figsize=figsize)
    axR = axL.twinx()

    axR.fill_between(x, 0, bt, color=CAUT, alpha=0.10, zorder=1)
    lB, = axR.plot(x, bt, color=CAUT, lw=lwB, marker="o", ms=ms, zorder=3,
                   label="Optimal battery (kWh)")
    lP, = axL.plot(x, pv, color=ACCENT, lw=lwP, marker="o", ms=ms, zorder=4,
                   label="Optimal solar (kW)")

    axL.axhline(pv_flat, ls=(0, (4, 3)), color=ACCENT, lw=1.0, alpha=0.55, zorder=2)
    solar_lbl = f"solar-only  {pv_flat:.2f} kW" if compact else f"solar-only optimum  {pv_flat:.2f} kW"
    axL.text(x_right * 0.98, pv_flat + 0.04 * pv.max(), solar_lbl, ha="right",
             va="bottom", color=ACCENT_INK, fontsize=8.5 if compact else 9)

    axL.axvline(batt_price_net, color=INK_FAINT, ls=(0, (2, 2)), lw=1.1, zorder=2)
    axL.text(batt_price_net - x_right * 0.014, pv.max() * 0.97,
             f"today's price\n${batt_price_net:,.0f}/kWh\n" + r"$\rightarrow$ battery = 0",
             ha="right", va="top", color=INK_SOFT, fontsize=8 if compact else 9,
             linespacing=1.25)

    if not compact and len(x) > 3:
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
    axL.set_ylim(0, pv.max() * 1.14)
    axR.set_ylim(0, max(bt.max(), 1) * 1.14)
    axL.set_xlim(0, x_right)
    axL.tick_params(labelsize=8.5 if compact else 9.5)
    axR.tick_params(labelsize=8.5 if compact else 9.5, colors=CAUT)
    axL.spines["top"].set_visible(False)
    axR.spines["top"].set_visible(False)
    axL.set_title(title, fontsize=11 if compact else 11.5, color=INK, pad=8, loc="left")
    axL.legend(handles=[lP, lB], loc="upper center", fontsize=8.5 if compact else 9.5,
               frameon=False, ncol=2, bbox_to_anchor=(0.5, -0.17 if compact else -0.16))
    return fig, {"pv_flat": pv_flat, "pv_max": float(pv.max())}


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
    p_exp = np.asarray(dispatch.p_exp)
    v_export = float(p_exp.mean())
    v_peak = float(np.mean(p_imp[p_imp >= np.quantile(p_imp, peak_quantile)]) * round_trip_eff)

    fig, ax = plt.subplots(figsize=(7.4, 4.5))
    cats = ["No battery:\nsurplus solar exported",
            "With battery:\nsurplus solar " + r"$\rightarrow$ evening peak"]
    vals = [v_export, v_peak]
    xb = [0, 1]
    ax.bar(xb, vals, width=0.5, color=[NEG, POS], zorder=3, edgecolor="white", lw=1)
    ax.axhline(pv_lcoe, ls=(0, (5, 3)), color=INK, lw=1.4, zorder=4)
    ax.text(1.46, pv_lcoe + 0.004, f"solar's break-even (LCOE)  ${pv_lcoe:.3f}/kWh",
            ha="right", va="bottom", color=INK, fontsize=9.5, **MONO)
    for xi, v in zip(xb, vals):
        ax.text(xi, v + 0.008, f"${v:.3f}", ha="center", va="bottom", fontsize=13,
                color=INK, **MONO)
    ax.text(0, v_export + 0.045, "below the line\n" + r"$\rightarrow$ NOT worth building",
            ha="center", va="bottom", color=NEG, fontsize=9, fontweight="bold", linespacing=1.25)
    ax.text(1, v_peak + 0.028, "above the line\n" + r"$\rightarrow$ build 2-3$\times$ more solar",
            ha="center", va="bottom", color=POS, fontsize=9, fontweight="bold", linespacing=1.25)
    ax.set_xticks(xb)
    ax.set_xticklabels(cats, fontsize=9.8, color=INK_SOFT, linespacing=1.3)
    ax.set_ylabel("Value of the last kWh of rooftop solar  ($/kWh)", fontsize=10.3)
    ax.set_ylim(0, max(0.44, v_peak * 1.15))
    ax.set_xlim(-0.55, 1.55)
    for s in ["top", "right"]:
        ax.spines[s].set_visible(False)
    ax.tick_params(labelsize=9.5)
    ax.set_title("Why: a battery flips the marginal kWh of solar from a loss to a profit",
                 fontsize=11.5, color=INK, pad=10, loc="left")
    return fig, {"v_export": v_export, "v_peak": v_peak, "pv_lcoe": pv_lcoe}


def plot_pv_ceiling(sweep: pd.DataFrame, dispatch, *, batt_price_net: float
                    ) -> Tuple["object", Meta]:
    """Log-x line: optimal solar rises then flattens against total annual load,
    even as a near-free battery grows into a seasonal reservoir."""
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
        f"battery here = {btc[imin]:,.0f} kWh\n(a seasonal reservoir),\n"
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
    axc.set_title("Even a free, unlimited battery can't push solar past your annual load",
                  fontsize=11.5, color=INK, pad=10, loc="left")
    return fig, {"pv_100": pv_100, "pv_100_rte": pv_100_rte,
                 "batt_min": float(btc[imin]), "pv_min": float(pvc[imin]),
                 "cover_min": float(pvc[imin] * yield_kw / annual_load)}


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
