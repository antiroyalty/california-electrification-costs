"""Recipes: compose collectors + charts + docio into specific document figures.

Each recipe is idempotent and rewrites its target file in place. The HTML
fragments (objective box, captions) live here because they are document content,
not reusable plumbing.
"""
from __future__ import annotations

from pathlib import Path

from figure_builder import FIG_DIR, current_claims_doc
from figure_builder import docio
from figure_builder.charts import (
    plot_battery_value_waterfall, plot_marginal_solar_value_ladder,
    plot_pv_batt_vs_capex, plot_pv_batt_vs_capex_compare, plot_pv_ceiling,
)
from figure_builder.datasets import collect_battery_capex_sweep
from figure_builder.dispatch import CLAIM1_COUNTIES, county_dispatch_inputs
from figure_builder.pricing import live_prices

MECH_ANCHOR = "Battery capex ($25-$1,200/kWh) is the swept variable itself.</div>"

_MECH_CSS = """.obj-box{ border:1px solid var(--rule); border-radius:10px; background:var(--surface); padding:20px 22px; margin:0 0 24px; box-shadow:var(--shadow); }
.obj-label{ font-family:var(--mono); font-size:11px; text-transform:uppercase; letter-spacing:.06em; color:var(--ink-faint); margin-bottom:12px; }
.obj-eq{ font-family:var(--mono); font-size:15px; line-height:2.0; color:var(--ink); text-align:center; padding:6px 4px 12px; overflow-x:auto; white-space:nowrap; }
.obj-eq .op{ color:var(--ink-faint); margin:0 4px; }
.obj-eq .ot-cap{ color:var(--ink-soft); }
.obj-eq .ot-imp{ color:var(--accent-ink); background:var(--accent-soft); border-radius:4px; padding:2px 6px; font-weight:600; }
.obj-eq .ot-exp{ color:var(--caution); background:var(--caution-soft); border-radius:4px; padding:2px 6px; font-weight:600; }
.obj-eq .ot-plain{ color:var(--ink-faint); }
.obj-gloss{ list-style:none; margin:4px 0 12px; padding:0; }
.obj-gloss li{ font-size:14px; color:var(--ink-soft); padding:5px 0; line-height:1.5; }
.obj-gloss .chip{ font-family:var(--mono); font-size:12px; border-radius:4px; padding:2px 7px; margin-right:8px; white-space:nowrap; }
.obj-gloss .chip-cap{ color:var(--ink-soft); background:var(--surface-2); border:1px solid var(--rule); }
.obj-gloss .chip-imp{ color:var(--accent-ink); background:var(--accent-soft); }
.obj-gloss .chip-exp{ color:var(--caution); background:var(--caution-soft); }
.obj-punch{ font-size:14.5px; color:var(--ink); line-height:1.6; margin:6px 0 0; border-top:1px solid var(--rule); padding-top:12px; }"""

# Per-county captions for the four-panel grid.
_COUNTY_CAPTIONS = {
    "alameda": ("Left, 2025 with the 30% federal ITC; right, current law. The "
                "battery is zero at market prices in both regimes, and solar and "
                "storage rise together only as storage cheapens."),
    "fresno": "Same pattern in a hotter inland Central Valley climate zone.",
    "los-angeles": "Holds in SCE territory, so the finding is not PG&amp;E-specific.",
    "san-diego": "Holds in all three California investor-owned utility territories.",
}


def _read(doc) -> str:
    return Path(doc).read_text()


def _write(doc, html: str) -> None:
    Path(doc).write_text(html)


def _mechanism_fragment(prices_now, prices_2025, mA, mB, mC, b64A, b64B, b64C) -> str:
    b_2025 = f"${prices_2025.batt_net_per_kwh:,.0f}/kWh net"
    b_now = f"${prices_now.batt_net_per_kwh:,.0f}/kWh net"
    s_2025 = f"${prices_2025.pv_net_per_kw:,.0f}/kW"
    s_now = f"${prices_now.pv_net_per_kw:,.0f}/kW"
    return f'''  <div class="callout" style="border-left-color:var(--accent-ink);">
    <strong>Why this happens: the LP&rsquo;s own logic.</strong> The result looks paradoxical only if solar and storage are substitutes. In the objective function they are <strong>complements</strong>, and the reason is two terms:
  </div>

  <div class="obj-box">
    <div class="obj-label">Objective: minimize annual cost ($/yr)</div>
    <div class="obj-eq"><span class="ot-cap">PV&middot;c<sub>pv</sub>&middot;&alpha;<sub>pv</sub></span> <span class="op">+</span> <span class="ot-cap">B&middot;c<sub>batt</sub>&middot;&alpha;<sub>batt</sub></span> <span class="op">+</span> <span class="ot-imp">&sum;<sub>h</sub> w<sub>h</sub>&middot;(grid&rarr;load)<sub>h</sub>&middot;p<sub>imp,h</sub></span> <span class="op">&minus;</span> <span class="ot-exp">&sum;<sub>h</sub> w<sub>h</sub>&middot;(pv&rarr;grid)<sub>h</sub>&middot;p<sub>exp,h</sub></span> <span class="op">+</span> <span class="ot-plain">deg</span></div>
    <ul class="obj-gloss">
      <li><span class="chip chip-cap">capex</span> annualized cost of the solar and battery you build.</li>
      <li><span class="chip chip-imp">p<sub>imp</sub></span> solar is paid the <strong>full retail price</strong> (~$0.40/kWh at peak) on every kWh it lets you <em>not</em> import.</li>
      <li><span class="chip chip-exp">p<sub>exp</sub></span> but only the low <strong>ACC export credit</strong> (~$0.05/kWh) on what it sends to the grid.</li>
    </ul>
    <p class="obj-punch">A battery earns only the <strong>difference</strong> between those two prices, net of ~10% round-trip loss and a mid-life replacement. So the battery only enters when it is cheap. The moment it does, it lets surplus midday solar reach the evening peak, lifting the value of the marginal kWh of solar from p<sub>exp</sub> to p<sub>imp</sub>. Cheaper storage <strong>raises</strong> the optimal amount of solar. It never replaces it.</p>
  </div>

  <figure class="fig"><img src="data:image/png;base64,{b64A}" alt="Optimal solar and battery vs battery cost, 2025 with ITC versus current law, Alameda" /><figcaption><strong>2025 vs. now: removing the federal ITC.</strong> Left, 2025, with the 30% ITC (battery {b_2025}): the solar-only optimum sat at {mA['before']['pv_flat']:.2f}&nbsp;kW, rising toward {mA['before']['pv_max']:.2f}&nbsp;kW as cheaper storage enters. Right, current law, the ITC expired (battery {b_now}): pricier storage pushes the battery firmly to zero at market prices and the solar-only optimum settles at {mA['after']['pv_flat']:.2f}&nbsp;kW. Removing the credit makes storage pencil out <em>less</em>, so Claim&nbsp;1 strengthens. Both panels share axes. Only battery capex is swept; <strong>solar&rsquo;s price is fixed at its net installed cost within each panel: {s_2025} in 2025 (gross $3,300/kW less the 30% ITC), {s_now} under current law (ITC repealed, net = gross)</strong>. Real Step&nbsp;9b co-optimization, Alameda / PG&amp;E, full-electrification load.</figcaption></figure>

  <div class="fig-grid">
    <figure class="fig"><img src="data:image/png;base64,{b64B}" alt="A battery raises the value of the marginal kWh of solar" /><figcaption><strong>The mechanism.</strong> The last kWh of solar is worth only <strong>${mB['v_export']:.3f}</strong> if exported at the ACC rate, below solar&rsquo;s own ${mB['pv_lcoe']:.3f}/kWh break-even, so the LP stops building. A battery shifts that same kWh into the evening peak, where it offsets a <strong>${mB['v_peak']:.3f}</strong> import (after round-trip loss). That is well above break-even, so the LP builds more. Alameda / PG&amp;E, current law.</figcaption></figure>
    <figure class="fig"><img src="data:image/png;base64,{b64C}" alt="Even a free unlimited battery caps optimal solar at annual load coverage" /><figcaption><strong>The ceiling.</strong> Drive the battery toward free and let it grow without limit: optimal solar rises, then flattens against total annual consumption ({mC['pv_100']:.1f}&ndash;{mC['pv_100_rte']:.1f}&nbsp;kW) and stops. At $1/kWh the model builds a {mC['batt_min']:,.0f}&nbsp;kWh seasonal battery, yet solar is still only {mC['pv_min']:.1f}&nbsp;kW ({mC['cover_min'] * 100:.0f}% of load), because past full load coverage the next panel only earns the $0.05 export rate. A free battery raises the ceiling to your annual load; it never removes it.</figcaption></figure>
  </div>

  <div class="callout"><strong>One sentence for the skeptic:</strong> the battery is not a substitute for solar. It is what lets the marginal kWh of solar reach the peak price instead of the export price, which is exactly why optimal solar goes <em>up</em>, not down, as storage gets cheaper.</div>'''


def build_mechanism_block(doc=None, *, county="alameda") -> Path:
    """Rebuild the Claim-1 mechanism block and patch it into the combined doc
    (the current commit's claims-<sha>.html by default). The headline figure is a
    2025-vs-current-law before/after; the mechanism and ceiling panels are drawn
    at current law. Idempotent."""
    from appliances.incentive_policy import PolicyRegime

    doc = Path(doc) if doc is not None else current_claims_doc()
    prices_now = live_prices()
    prices_2025 = live_prices(PolicyRegime.ITC_2025)
    sweep_now = collect_battery_capex_sweep(county)
    sweep_2025 = collect_battery_capex_sweep(county, regime=PolicyRegime.ITC_2025)
    di = county_dispatch_inputs(county)

    figA, mA = plot_pv_batt_vs_capex_compare(
        sweep_2025, sweep_now,
        batt_before=prices_2025.batt_net_per_kwh, batt_after=prices_now.batt_net_per_kwh,
        title="Alameda (PG&E): storage economics before and after the federal ITC expired",
        panel_labels=(f"2025 — 30% ITC · solar ${prices_2025.pv_net_per_kw:,.0f}/kW",
                      f"Now — ITC expired · solar ${prices_now.pv_net_per_kw:,.0f}/kW"))
    figB, mB = plot_marginal_solar_value_ladder(di, prices_now)
    figC, mC = plot_pv_ceiling(sweep_now, di, batt_price_net=prices_now.batt_net_per_kwh)

    frag = _mechanism_fragment(prices_now, prices_2025, mA, mB, mC,
                               docio.embed_png(figA), docio.embed_png(figB),
                               docio.embed_png(figC))
    html = _read(doc)
    html = docio.upsert_marked_block(html, "MECH-BLOCK", frag, anchor=MECH_ANCHOR)
    html = docio.inject_css(html, "MECH-CSS", _MECH_CSS)
    _write(doc, html)
    return Path(doc)


def build_county_grid(doc=None) -> Path:
    """Rebuild the four-county Claim-1 grid as 2025-vs-current-law before/after
    comparisons, stacked full-width, and patch it into the combined doc.
    Idempotent."""
    from appliances.incentive_policy import PolicyRegime

    doc = Path(doc) if doc is not None else current_claims_doc()
    prices_now = live_prices()
    prices_2025 = live_prices(PolicyRegime.ITC_2025)
    cells = []
    for slug, label, util in CLAIM1_COUNTIES:
        sweep_now = collect_battery_capex_sweep(slug)
        sweep_2025 = collect_battery_capex_sweep(slug, regime=PolicyRegime.ITC_2025)
        fig, _ = plot_pv_batt_vs_capex_compare(
            sweep_2025, sweep_now,
            batt_before=prices_2025.batt_net_per_kwh, batt_after=prices_now.batt_net_per_kwh,
            title=f"{label} ({util})",
            panel_labels=(f"2025 · ITC · PV ${prices_2025.pv_net_per_kw:,.0f}/kW",
                          f"now · no ITC · PV ${prices_now.pv_net_per_kw:,.0f}/kW"))
        caption = f"<strong>{label} ({util}).</strong> {_COUNTY_CAPTIONS[slug]}"
        cells.append(docio.figure_html(
            docio.embed_png(fig), caption,
            f"Before/after battery-capex sweep, {label}"))
    grid_inner = "\n  ".join(cells)

    html = _read(doc)
    if docio.has_markers(html, "COUNTY-GRID"):
        html = docio.replace_between_markers(html, "COUNTY-GRID", grid_inner)
    else:
        html = docio.replace_first(
            html, r'<div class="fig-grid">.*?San Diego County.*?</div>',
            docio.wrap_markers("COUNTY-GRID", grid_inner))
    _write(doc, html)
    return Path(doc)


def build_bridge(out=None) -> Path:
    """Render the assumption-bridge waterfall to a standalone PNG."""
    out = Path(out) if out else FIG_DIR / "bridge_waterfall.png"
    fig, _ = plot_battery_value_waterfall()
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, bbox_inches="tight", facecolor="white")
    import matplotlib.pyplot as plt
    plt.close(fig)
    return out


# --- Claim-1 robustness: the installer-heuristic question (Duncan, 2026-07) -----
# Kept as one self-contained recipe rather than a full collector/chart/grid build,
# since it is a single robustness figure. It caches its own sweep so it is
# reproducible and not a lost one-off.
def _entry_threshold(cap, batt) -> float:
    """Highest battery cost at which the optimal battery is still non-trivial."""
    import numpy as np
    m = np.asarray(batt) > 0.1
    return float(np.asarray(cap)[m].max()) if m.any() else float("nan")


def _installer_rule_fixed_pv_sweep(county, pv_offset, prices):
    """Optimal battery vs battery cost with PV FIXED at the annual-offset size.
    Cached to figure_builder/sweeps/sweep_8760_<county>_fixedpv_<regime>.csv."""
    import pandas as pd
    from figure_builder import SWEEP_DIR
    from figure_builder.dispatch import SWEEP_POINTS
    from pipeline.steps.step9b_cooptimize_core import CooptInputs, _solve_lp

    path = SWEEP_DIR / f"sweep_8760_{county}_fixedpv_{prices.regime}.csv"
    if path.exists():
        return pd.read_csv(path)
    di = county_dispatch_inputs(county)
    inp = CooptInputs(load_kwh=di.load, pv_gen_per_kw=di.pv_gen_per_kw,
                      import_rates=di.p_imp, export_rates=di.p_exp)
    rows = []
    for cb in SWEEP_POINTS:
        r = _solve_lp(inp, allow_grid_charging=False, allow_batt_export=True,
                      c_pv_kw=prices.pv_net_per_kw, c_batt_kwh=float(cb), c_batt_kw=0.0,
                      pv_life_yrs=25, batt_life_yrs=15, discount_rate=0.07,
                      c_deg_per_kwh=0.0, weights=None, cycle_monthly=False,
                      fixed_pv_kw=pv_offset)
        rows.append({"battery_capex_kwh": cb, "batt_kwh": max(r.batt_kwh, 0.0)})
    df = pd.DataFrame(rows)
    SWEEP_DIR.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)
    return df


def _plot_installer_rule(free, fixed, prices, pv_offset, title):
    from figure_builder import charts as ch
    ch.apply_style()
    import matplotlib.pyplot as plt

    fr = free[free.battery_capex_kwh >= 25].sort_values("battery_capex_kwh")
    fx = fixed[fixed.battery_capex_kwh >= 25].sort_values("battery_capex_kwh")
    thr_free = _entry_threshold(fr.battery_capex_kwh, fr.batt_kwh)
    thr_fix = _entry_threshold(fx.battery_capex_kwh, fx.batt_kwh)
    today = prices.batt_net_per_kwh
    ymax = max(fx.batt_kwh.max(), fr.batt_kwh.max()) * 1.15

    fig, ax = plt.subplots(figsize=(7.8, 4.9))
    ax.plot(fr.battery_capex_kwh, fr.batt_kwh, color=ch.ACCENT, lw=2.6, marker="o",
            ms=4, label="PV economically optimized (co-optimized)")
    ax.plot(fx.battery_capex_kwh, fx.batt_kwh, color=ch.CAUT, lw=2.6, marker="s",
            ms=4, label=f"PV fixed to 100% annual offset ({pv_offset:.1f} kW, installer rule)")
    ax.axvline(today, color=ch.INK_FAINT, ls=(0, (2, 2)), lw=1.3)
    ax.text(today - 16, ymax * 0.60,
            f"today's battery price\n${today:,.0f}/kWh\n" + r"$\rightarrow$ zero under either rule",
            ha="right", va="top", color=ch.INK_SOFT, fontsize=9, linespacing=1.3)
    # entry thresholds as light ticks just above the axis
    for thr, col in [(thr_free, ch.ACCENT_INK), (thr_fix, ch.CAUT)]:
        ax.plot([thr, thr], [0, ymax * 0.05], color=col, lw=2.0)
        ax.text(thr, ymax * 0.075, f"${thr:,.0f}", ha="center", va="bottom",
                color=col, fontsize=8.5, fontweight="bold")
    ax.text(thr_fix + (today - thr_fix) / 2, ymax * 0.16,
            "battery only pencils\nbelow these prices", ha="center", va="bottom",
            color=ch.INK_SOFT, fontsize=8.5, style="italic", linespacing=1.2)
    ax.set_xlabel(r"Battery cost  (\$/kWh)   $\leftarrow$ cheaper", fontsize=10.5)
    ax.set_ylabel("Optimal battery size (kWh)", fontsize=10.5)
    ax.set_xlim(0, max(fx.battery_capex_kwh.max(), today) * 1.03)
    ax.set_ylim(0, ymax)
    for s in ["top", "right"]:
        ax.spines[s].set_visible(False)
    ax.set_title(title, fontsize=11, color=ch.INK, pad=10, loc="left")
    ax.legend(loc="upper right", fontsize=9.5, frameon=False)
    return fig, {"thr_free": thr_free, "thr_fix": thr_fix}


def _installer_rule_fragment(prices, pv_offset, m, b64) -> str:
    return f'''  <!-- INSTALLER-RULE body -->
  <div class="callout" style="border-left-color:var(--accent-ink);">
    <strong>Robustness: what if installers oversize solar?</strong> In practice a system is often sized to offset 100% of annual consumption, not to the economic optimum. That larger array (here {pv_offset:.1f}&nbsp;kW, versus the ~2&nbsp;kW optimum) spills far more midday surplus, which under NEM&nbsp;3.0 exports at only ~$0.05/kWh, so a battery has more to store. Does storage then pencil?
  </div>

  <figure class="fig"><img src="data:image/png;base64,{b64}" alt="Optimal battery vs battery cost, PV economically optimized versus PV fixed at annual offset, Alameda" /><figcaption><strong>Oversizing raises the battery threshold, but not to today&rsquo;s price.</strong> With PV fixed to the installer rule, a battery pencils out at a higher price (~${m['thr_fix']:,.0f}/kWh) than under the economic optimum (~${m['thr_free']:,.0f}/kWh), exactly as intuition suggests. But today&rsquo;s net battery price (${prices.batt_net_per_kwh:,.0f}/kWh) is still well above both thresholds, so the optimal battery is zero under either sizing rule. Alameda / PG&amp;E, current law, PV fixed at its ${prices.pv_net_per_kw:,.0f}/kW net cost. <em>Caveat:</em> the thresholds depend on the NEM&nbsp;3.0 export values, which are flat in the model (max ~$0.10/kWh); if the real ACC has higher-value evening hours, a battery could pencil at somewhat higher prices than shown.</figcaption></figure>
  <!-- /INSTALLER-RULE body -->'''


def build_installer_rule_figure(doc=None, county="alameda", label="Alameda (PG&E)") -> Path:
    """Add the installer-heuristic robustness figure to the Claim-1 block: optimal
    battery vs battery cost, PV economically optimized vs PV fixed at 100% annual
    offset. Answers Duncan's 2026-07 question. Idempotent; inserted after the
    mechanism block."""
    doc = Path(doc) if doc is not None else current_claims_doc()
    prices = live_prices()
    di = county_dispatch_inputs(county)
    pv_offset = di.annual_load / di.yield_per_kw
    free = collect_battery_capex_sweep(county)
    fixed = _installer_rule_fixed_pv_sweep(county, pv_offset, prices)
    fig, m = _plot_installer_rule(
        free, fixed, prices, pv_offset,
        f"{label}: oversizing solar to the installer rule raises the battery threshold, "
        f"not to today's price")
    frag = _installer_rule_fragment(prices, pv_offset, m, docio.embed_png(fig))
    html = _read(doc)
    html = docio.upsert_marked_block(html, "INSTALLER-RULE", frag,
                                     anchor=docio.end_marker("MECH-BLOCK"))
    _write(doc, html)
    return doc


# --- document split ---------------------------------------------------------
_NAV_ITEMS = [
    ("claim1.html", "Claim 1 &middot; Storage"),
    ("claim2.html", "Claim 2 &middot; Electrification vs. gas"),
    ("claim3.html", "Claim 3 &middot; Co-optimization value"),
]
_TITLES = {
    "claim1.html": "Claim 1: Storage economics under NEM 3.0",
    "claim2.html": "Claim 2: Electrification vs. gas",
    "claim3.html": "Claim 3: Co-optimization value",
}


def _nav(active: str, src_name: str) -> str:
    out = ['  <nav class="toc">']
    for href, label in _NAV_ITEMS:
        st = ' style="color:var(--accent-ink);border-color:var(--accent);"' if href == active else ""
        out.append(f'    <a href="{href}"{st}>{label}</a>')
    out.append(f'    <a href="{src_name}#limitations">Full doc &middot; Limitations</a>')
    out.append("  </nav>")
    return "\n".join(out)


def split_claims(doc=None) -> list:
    """Split the combined review doc into standalone claim1/2/3.html files with
    per-file nav and title. Non-destructive: the combined doc is left intact."""
    import re

    src = Path(doc) if doc is not None else current_claims_doc()
    src_name = src.name
    h = src.read_text()

    p1 = h.index('<section class="claim" id="claim-1">')
    p2 = h.index('<section class="claim" id="claim-2">')
    p3 = h.index('<section class="claim" id="claim-3">')
    pL = h.index('<section class="claim" id="limitations">')
    pF = h.index('<footer class="end">')

    preamble = docio.strip_trailing_comment(h[:p1])
    claims = {
        "claim1.html": docio.strip_trailing_comment(h[p1:p2]),
        "claim2.html": docio.strip_trailing_comment(h[p2:p3]),
        "claim3.html": docio.strip_trailing_comment(h[p3:pL]),
    }
    footer = h[pF:]

    written = []
    for active, body in claims.items():
        pre = re.sub(r'  <nav class="toc">.*?</nav>', _nav(active, src_name),
                     preamble, count=1, flags=re.S)
        pre = re.sub(r"<title>.*?</title>", f"<title>{_TITLES[active]}</title>",
                     pre, count=1, flags=re.S)
        out = src.parent / active
        out.write_text(pre + "\n\n" + body + "\n\n" + footer)
        written.append(out)
    return written
