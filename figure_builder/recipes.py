"""Recipes: compose collectors + charts + docio into specific document figures.

Each recipe is idempotent and rewrites its target file in place. The HTML
fragments (objective box, captions) live here because they are document content,
not reusable plumbing.
"""
from __future__ import annotations

from datetime import datetime, timezone
import math
from pathlib import Path
import re

from figure_builder import (
    FIG_DIR,
    current_claims_doc,
    git_short_sha,
    market_observation_csv_path,
    sweep_csv_path,
)
from figure_builder import docio
from figure_builder.charts import (
    plot_battery_value_waterfall,
    plot_case_study_eac,
    plot_marginal_solar_value_ladder,
    plot_policy_matrix_optimal_sizes,
    plot_pv_batt_vs_capex,
    plot_pv_batt_vs_capex_compare,
    plot_pv_ceiling,
    plot_statewide_cooptimization_savings,
    plot_statewide_electrification_savings,
    solar_generation_weighted_export_rate,
)
from figure_builder.datasets import (
    collect_battery_capex_sweep,
    collect_claims_eac_results,
    collect_market_price_observation,
    collect_policy_matrix_results,
    claims_eac_source_path,
    expected_claim_counties,
    select_market_observation,
    summarize_claims_eac,
    validate_policy_matrix_exact_check,
)
from figure_builder.dispatch import CLAIM1_COUNTIES, county_dispatch_inputs
from figure_builder.metadata import (
    capital_cost_metadata,
    file_identity,
    optimization_metadata,
    tariff_metadata,
    write_run_metadata,
)
from figure_builder.policy_cases import POLICY_CASES
from figure_builder.pricing import live_prices
from tariffs import ExportCompensationRegime

MECH_ANCHOR = "Battery capex ($25-$1,200/kWh) is the swept variable itself.</div>"
POLICY_MATRIX_CSV = FIG_DIR / "policy_matrix_optimal_sizes.csv"
POLICY_MATRIX_PNG = FIG_DIR / "policy_matrix_optimal_sizes.png"
POLICY_MATRIX_METADATA = FIG_DIR / "policy_matrix_metadata.json"
_POLICY_MATRIX_CSS = """.data-table{width:100%;border-collapse:collapse;margin:0 0 24px;font-size:13px}.data-table th,.data-table td{padding:9px 10px;border-bottom:1px solid var(--rule);text-align:left}.data-table th{color:var(--ink-soft);font-size:11px;text-transform:uppercase;letter-spacing:.04em}"""

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

# Per-county context; modeled results are always generated from solved rows.
_COUNTY_CONTEXT = {
    "alameda": "Coastal PG&amp;E case study.",
    "fresno": "Hot inland PG&amp;E case study.",
    "los-angeles": "SCE case study.",
    "san-diego": "SDG&amp;E case study.",
}


def _format_battery_capacity(value: float) -> str:
    if value < 0.01 and value > 1e-6:
        return "&lt;0.01&nbsp;kWh"
    return f"{value:.2f}&nbsp;kWh"


def _market_result_sentence(before_meta: dict, after_meta: dict) -> str:
    return (
        "At the exact market prices, the 12&times;24 sensitivity chooses "
        f"{_format_battery_capacity(before_meta['market_batt_kwh'])} in the "
        "2025 ITC regime; the full 8,760-hour current-law solve chooses "
        f"{_format_battery_capacity(after_meta['market_batt_kwh'])} under "
        "current law."
    )


def _claim1_summary_fragment(
    before_meta: list[dict],
    after_meta: list[dict],
    current_thresholds: list[float],
) -> str:
    """Claim 1 headline derived from declared-resolution solved observations."""

    if len(before_meta) != 4 or len(after_meta) != 4 or len(current_thresholds) != 4:
        raise ValueError("Claim 1 summary requires all four case-study counties")
    before_batt = [row["market_batt_kwh"] for row in before_meta]
    after_batt = [row["market_batt_kwh"] for row in after_meta]
    positive_before = [value for value in before_batt if value > 0.1]
    before_nontrivial = sum(value > 0.1 for value in before_batt)
    after_nontrivial = sum(value > 0.1 for value in after_batt)
    if not positive_before:
        raise ValueError(
            "Claim 1 summary cannot describe the 2025 storage range because "
            "no case-study solve exceeds 0.1 kWh"
        )
    if any(not math.isfinite(value) for value in current_thresholds):
        raise ValueError(
            "Claim 1 summary requires a finite current-law entry-grid point "
            "for every case-study county"
        )
    threshold_low = min(current_thresholds)
    threshold_high = max(current_thresholds)
    current_max = max(after_batt)

    return f'''  <h2 class="claim-title">At current 2026 costs, batteries do not pencil out in the four NEM&nbsp;3.0 case studies. The 2025 ITC changed that result in {before_nontrivial} cases</h2>
  <p class="claim-sub">The full 8,760-hour co-optimization chooses <strong>no material battery capacity</strong> under current law in all four case-study counties ({after_nontrivial} of 4 above 0.1&nbsp;kWh). In the weighted 12&times;24 sensitivity, the lower 2025 ITC-adjusted capital cost produces more than 0.1&nbsp;kWh in {before_nontrivial} of 4 cases, reaching {min(positive_before):.2f}&ndash;{max(positive_before):.2f}&nbsp;kWh. The sensitivity curves show the mechanism: as storage becomes cheaper, optimal storage and PV rise together.</p>

  <div class="stat-row">
    <div class="stat"><span class="num">{after_nontrivial} of 4</span><span class="lbl">current-law exact 8,760-hour solves with more than 0.1&nbsp;kWh of storage; maximum modeled capacity is {_format_battery_capacity(current_max)}</span></div>
    <div class="stat"><span class="num">{before_nontrivial} of 4</span><span class="lbl">2025 ITC weighted 12&times;24 observations with more than 0.1&nbsp;kWh of storage</span></div>
    <div class="stat"><span class="num">${threshold_low:,.0f}&ndash;${threshold_high:,.0f}</span><span class="lbl">per kWh, the highest tested current-law 12&times;24 sensitivity-grid price still producing more than 0.1&nbsp;kWh of storage</span></div>
  </div>'''


def _claim1_cost_scope_fragment(prices_now, prices_2025) -> str:
    """Describe the two policy-regime inputs used by the county panels."""

    return f'''<div class="callout"><strong>Cost scope used above:</strong> PV is held fixed within each policy panel&mdash;${prices_2025.pv_net_per_kw:,.0f}/kW with the 2025 ITC and ${prices_now.pv_net_per_kw:,.0f}/kW under current law. The displayed battery-capex sensitivity spans $25&ndash;$1,500/kWh and includes solved grid observations at both modeled market prices (${prices_2025.batt_net_per_kwh:,.3f}/kWh and ${prices_now.batt_net_per_kwh:,.2f}/kWh). The current-law diamond additionally reports the dedicated 8,760-hour solve.</div>'''


def _read(doc) -> str:
    return Path(doc).read_text()


def _write(doc, html: str) -> None:
    Path(doc).write_text(html)


def _mechanism_fragment(
    prices_now,
    prices_2025,
    mA,
    mB,
    mC,
    b64A,
    b64B,
    b64C,
    resolution_label,
) -> str:
    b_2025 = f"${prices_2025.batt_net_per_kwh:,.0f}/kWh net"
    b_now = f"${prices_now.batt_net_per_kwh:,.0f}/kWh net"
    s_2025 = f"${prices_2025.pv_net_per_kw:,.0f}/kW"
    s_now = f"${prices_now.pv_net_per_kw:,.0f}/kW"
    return f'''  <div class="callout" style="border-left-color:var(--accent-ink);">
    <strong>Why this happens: the optimization model&rsquo;s own logic.</strong> The result looks paradoxical only if solar and storage are substitutes. In the objective function they are <strong>complements</strong>, and the reason is two terms:
  </div>

  <div class="obj-box">
    <div class="obj-label">Objective: minimize annual cost ($/yr)</div>
    <div class="obj-eq"><span class="ot-cap">PV&middot;c<sub>pv</sub>&middot;&alpha;<sub>pv</sub></span> <span class="op">+</span> <span class="ot-cap">B&middot;c<sub>batt</sub>&middot;&alpha;<sub>batt</sub></span> <span class="op">+</span> <span class="ot-imp">&sum;<sub>h</sub> w<sub>h</sub>&middot;(grid&rarr;load)<sub>h</sub>&middot;p<sub>imp,h</sub></span> <span class="op">&minus;</span> <span class="ot-exp">&sum;<sub>h</sub> w<sub>h</sub>&middot;(pv&rarr;grid)<sub>h</sub>&middot;p<sub>exp,h</sub></span> <span class="op">+</span> <span class="ot-plain">deg</span></div>
    <ul class="obj-gloss">
      <li><span class="chip chip-cap">capex</span> annualized cost of the solar and battery you build.</li>
      <li><span class="chip chip-imp">p<sub>imp</sub></span> solar is paid the <strong>full retail price</strong> (averaging ~${mB['peak_import_rate']:.3f}/kWh across the top {mB['peak_share_pct']:.0f}% of modeled import-price hours) on every kWh it lets you <em>not</em> import.</li>
      <li><span class="chip chip-exp">p<sub>exp</sub></span> but only the lower <strong>ACC export credit</strong> (~${mB['v_export']:.3f}/kWh when hourly prices are weighted by modeled PV generation) on what it sends to the grid.</li>
    </ul>
    <p class="obj-punch">A battery earns only the <strong>difference</strong> between those two prices, net of ~{(1.0 - mB['round_trip_eff']) * 100:.0f}% round-trip loss and a mid-life replacement. So the battery only enters when it is cheap. When it does, it can let surplus midday solar reach higher-valued hours instead of being exported immediately. Cheaper storage <strong>raises</strong> the optimal amount of solar in the modeled sweeps. It never replaces it.</p>
  </div>

  <figure class="fig"><img src="data:image/png;base64,{b64A}" alt="Optimal solar and battery vs battery cost, 2025 with ITC versus current law, Alameda" /><figcaption><strong>2025 vs. now: removing the federal ITC.</strong> {_market_result_sentence(mA['before'], mA['after'])} The lines show the declared capex sensitivity: the solar-only optimum is {mA['before']['pv_flat']:.2f}&nbsp;kW in the 2025 panel and {mA['after']['pv_flat']:.2f}&nbsp;kW under current law, rising as cheaper storage enters. Both panels share axes. Only battery capex is swept; <strong>solar&rsquo;s price is fixed at its net installed cost within each panel: {s_2025} in 2025 (gross $3,300/kW less the 30% ITC), {s_now} under current law (ITC repealed, net = gross)</strong>. The 2025 market diamond is a weighted 12&times;24 sensitivity observation; the current-law market diamond is a separate full 8,760-hour chronological solve. The sensitivity lines use the Step&nbsp;9b {resolution_label}. Alameda / PG&amp;E, full-electrification load.</figcaption></figure>

  <div class="fig-grid">
    <figure class="fig"><img src="data:image/png;base64,{b64B}" alt="Illustrative values for solar-coincident export and storage-mediated peak shifting" /><figcaption><strong>The value spread behind the mechanism.</strong> Weighting the hourly ACC schedule by Alameda&rsquo;s modeled PV generation gives a solar-coincident export value of <strong>${mB['v_export']:.3f}/kWh</strong>, below solar&rsquo;s ${mB['pv_lcoe']:.3f}/kWh break-even. For comparison, an illustrative surplus kWh shifted to the top {mB['peak_share_pct']:.0f}% of import-price hours would have an effective avoided-import value of <strong>${mB['v_peak']:.3f}/kWh</strong> after {(1.0 - mB['round_trip_eff']) * 100:.0f}% round-trip loss. The difference between that value and solar LCOE&mdash;<strong>${mB['storage_margin_after_solar']:.3f}/kWh</strong>&mdash;is merely the illustrative margin left to cover storage, not profit. This is not a solar-plus-storage LCOE: storage cost per delivered kWh depends on realized cycling. The full optimization applies annualized battery capex and hourly physical constraints directly; at today&rsquo;s modeled <strong>{b_now}</strong>, the exact solve chooses {_format_battery_capacity(mA['after']['market_batt_kwh'])}. Alameda / PG&amp;E, current law.</figcaption></figure>
    <figure class="fig"><img src="data:image/png;base64,{b64C}" alt="Even a near-free household battery caps optimal solar near annual load coverage" /><figcaption><strong>The ceiling.</strong> Drive battery cost toward zero within the model&rsquo;s explicit 40&nbsp;kWh representative-household sizing domain: optimal solar rises, then flattens near total annual consumption ({mC['pv_100']:.1f}&ndash;{mC['pv_100_rte']:.1f}&nbsp;kW). At $1/kWh the solution reaches a {mC['batt_min']:,.0f}&nbsp;kWh battery, while solar is {mC['pv_min']:.1f}&nbsp;kW ({mC['cover_min'] * 100:.0f}% of load), because additional generation primarily earns the much lower export rate. Near-free household storage raises the solar ceiling; it does not remove it.</figcaption></figure>
  </div>

  <div class="callout"><strong>One sentence for the skeptic:</strong> the battery is not a substitute for solar. It is what lets the marginal kWh of solar reach the peak price instead of the export price, which is exactly why optimal solar goes <em>up</em>, not down, as storage gets cheaper.</div>'''


def build_mechanism_block(doc=None, *, county="alameda", fine: bool = False) -> Path:
    """Rebuild the Claim-1 mechanism block and patch it into the combined doc
    (the current commit's claims-<sha>.html by default). The headline figure is a
    2025-vs-current-law before/after; the mechanism and ceiling panels are drawn
    at current law. Idempotent."""
    from appliances.incentive_policy import PolicyRegime

    doc = Path(doc) if doc is not None else current_claims_doc()
    prices_now = live_prices()
    prices_2025 = live_prices(PolicyRegime.ITC_2025)
    sweep_now = collect_battery_capex_sweep(county, fine=fine)
    sweep_2025 = collect_battery_capex_sweep(
        county, regime=PolicyRegime.ITC_2025, fine=fine
    )
    market_now = select_market_observation(
        collect_market_price_observation(county),
        prices_now.batt_net_per_kwh,
    )
    market_2025 = select_market_observation(
        sweep_2025,
        prices_2025.batt_net_per_kwh,
    )
    di = county_dispatch_inputs(county)

    figA, mA = plot_pv_batt_vs_capex_compare(
        sweep_2025, sweep_now,
        batt_before=prices_2025.batt_net_per_kwh, batt_after=prices_now.batt_net_per_kwh,
        market_before=market_2025, market_after=market_now,
        market_before_resolution="12×24",
        market_after_resolution="8,760 h",
        title="Alameda (PG&E): storage economics before and after the federal ITC expired",
        panel_labels=(f"2025 — 30% ITC · solar ${prices_2025.pv_net_per_kw:,.0f}/kW",
                      f"Now — ITC expired · solar ${prices_now.pv_net_per_kw:,.0f}/kW"))
    figB, mB = plot_marginal_solar_value_ladder(di, prices_now)
    figC, mC = plot_pv_ceiling(sweep_now, di, batt_price_net=prices_now.batt_net_per_kwh)

    resolution_label = (
        "full 8,760-hour chronological sensitivity model"
        if fine
        else "weighted 12&times;24 monthly-hour sensitivity model"
    )
    frag = _mechanism_fragment(
        prices_now,
        prices_2025,
        mA,
        mB,
        mC,
        docio.embed_png(figA),
        docio.embed_png(figB),
        docio.embed_png(figC),
        resolution_label,
    )
    html = _read(doc)
    html = docio.upsert_marked_block(html, "MECH-BLOCK", frag, anchor=MECH_ANCHOR)
    html = docio.inject_css(html, "MECH-CSS", _MECH_CSS)
    _write(doc, html)
    return Path(doc)


def build_county_grid(doc=None, *, fine: bool = False) -> Path:
    """Rebuild the four-county Claim-1 grid as 2025-vs-current-law before/after
    comparisons, stacked full-width, and patch it into the combined doc.
    Idempotent."""
    from appliances.incentive_policy import PolicyRegime

    doc = Path(doc) if doc is not None else current_claims_doc()
    prices_now = live_prices()
    prices_2025 = live_prices(PolicyRegime.ITC_2025)
    cells = []
    before_meta = []
    after_meta = []
    current_thresholds = []
    for slug, label, util in CLAIM1_COUNTIES:
        sweep_now = collect_battery_capex_sweep(slug, fine=fine)
        sweep_2025 = collect_battery_capex_sweep(
            slug, regime=PolicyRegime.ITC_2025, fine=fine
        )
        market_now = select_market_observation(
            collect_market_price_observation(slug),
            prices_now.batt_net_per_kwh,
        )
        market_2025 = select_market_observation(
            sweep_2025,
            prices_2025.batt_net_per_kwh,
        )
        fig, meta = plot_pv_batt_vs_capex_compare(
            sweep_2025, sweep_now,
            batt_before=prices_2025.batt_net_per_kwh, batt_after=prices_now.batt_net_per_kwh,
            market_before=market_2025, market_after=market_now,
            market_before_resolution="12×24",
            market_after_resolution="8,760 h",
            title=f"{label} ({util})",
            panel_labels=(f"2025 · ITC · PV ${prices_2025.pv_net_per_kw:,.0f}/kW",
                          f"now · no ITC · PV ${prices_now.pv_net_per_kw:,.0f}/kW"))
        resolution = "8,760-hour" if fine else "weighted 12×24 monthly-hour"
        caption = (
            f"<strong>{label} ({util}).</strong> {_COUNTY_CONTEXT[slug]} "
            f"{_market_result_sentence(meta['before'], meta['after'])} "
            "The lines are the capex sensitivity, not interpolated market results. "
            f"Sensitivity resolution: {resolution}."
        )
        cells.append(docio.figure_html(
            docio.embed_png(fig), caption,
            f"Before/after battery-capex sweep, {label}"))
        before_meta.append(meta["before"])
        after_meta.append(meta["after"])
        current_thresholds.append(
            _entry_threshold(
                sweep_now["battery_capex_kwh"],
                sweep_now["batt_kwh"],
            )
        )
    grid_inner = "\n  ".join(cells)

    html = _read(doc)
    summary = _claim1_summary_fragment(
        before_meta,
        after_meta,
        current_thresholds,
    )
    if docio.has_markers(html, "CLAIM1-SUMMARY"):
        html = docio.replace_between_markers(html, "CLAIM1-SUMMARY", summary)
    else:
        html = docio.replace_first(
            html,
            r'  <h2 class="claim-title">.*?</h2>\n'
            r'  <p class="claim-sub">.*?</p>\n\n'
            r'  <div class="stat-row">.*?\n  </div>',
            docio.wrap_markers("CLAIM1-SUMMARY", summary),
        )
    if docio.has_markers(html, "COUNTY-GRID"):
        html = docio.replace_between_markers(html, "COUNTY-GRID", grid_inner)
    else:
        html = docio.replace_first(
            html, r'<div class="fig-grid">.*?San Diego County.*?</div>',
            docio.wrap_markers("COUNTY-GRID", grid_inner))
    cost_scope = _claim1_cost_scope_fragment(prices_now, prices_2025)
    if docio.has_markers(html, "CLAIM1-COST-SCOPE"):
        html = docio.replace_between_markers(
            html,
            "CLAIM1-COST-SCOPE",
            cost_scope,
        )
    else:
        html = docio.replace_first(
            html,
            r'<!-- COUNTY-GRID-END -->\s*<div class="callout">.*?</div>',
            '<!-- COUNTY-GRID-END -->\n\n'
            + docio.wrap_markers("CLAIM1-COST-SCOPE", cost_scope),
        )
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
def installer_rule_sweep_path(county: str, regime: str) -> Path:
    from figure_builder import SWEEP_DIR

    return SWEEP_DIR / f"sweep_288_{county}_fixedpv_{regime}.csv"


def _entry_threshold(cap, batt) -> float:
    """Highest battery cost at which the optimal battery is still non-trivial."""
    import numpy as np
    m = np.asarray(batt) > 0.1
    return float(np.asarray(cap)[m].max()) if m.any() else float("nan")


def _installer_rule_fixed_pv_sweep(county, pv_offset, prices):
    """Optimal battery vs battery cost with PV FIXED at the annual-offset size.
    Cached as a weighted 12x24 sensitivity sweep."""
    import pandas as pd
    from figure_builder.datasets import (
        canonical_battery_capex_points,
        sweep_cache_is_compatible,
    )
    from pipeline.steps.step9b_cooptimize_core import (
        CooptInputs,
        _solve_lp,
        build_monthly_hourly_inputs,
    )

    max_battery_kwh = 40.0
    requested_points = canonical_battery_capex_points(prices.regime)
    path = installer_rule_sweep_path(county, prices.regime)
    if path.exists():
        cached = pd.read_csv(path)
        required_columns = [
            "battery_capex_kwh",
            "batt_kwh",
            "max_battery_kwh",
            "meter_binary_count",
            "solver_rounds",
        ]
        if sweep_cache_is_compatible(
            cached,
            max_battery_kwh,
            expected_points=requested_points,
            expected_columns=required_columns,
        ):
            return cached
    di = county_dispatch_inputs(county)
    inp = CooptInputs(load_kwh=di.load, pv_gen_per_kw=di.pv_gen_per_kw,
                      import_rates=di.p_imp, export_rates=di.p_exp)
    inp, weights = build_monthly_hourly_inputs(inp, year=2026)
    rows = []
    for cb in requested_points:
        r = _solve_lp(inp, allow_grid_charging=False, allow_batt_export=True,
                      c_pv_kw=prices.pv_net_per_kw, c_batt_kwh=float(cb), c_batt_kw=0.0,
                      pv_life_yrs=25, batt_life_yrs=15, discount_rate=0.07,
                      c_deg_per_kwh=0.0, weights=weights, cycle_monthly=True,
                      fixed_pv_kw=pv_offset, max_battery_kwh=max_battery_kwh)
        rows.append({
            "battery_capex_kwh": cb,
            "batt_kwh": max(r.batt_kwh, 0.0),
            "max_battery_kwh": max_battery_kwh,
            "meter_binary_count": int(r.meter_binary_count),
            "solver_rounds": int(r.solver_rounds),
        })
    df = pd.DataFrame(rows)
    path.parent.mkdir(parents=True, exist_ok=True)
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


def _installer_rule_fragment(prices, pv_offset, solar_weighted_export_rate, m, b64) -> str:
    return f'''  <!-- INSTALLER-RULE body -->
  <div class="callout" style="border-left-color:var(--accent-ink);">
    <strong>Robustness: what if installers oversize solar?</strong> In practice a system is often sized to offset 100% of annual consumption, not to the economic optimum. That larger array (here {pv_offset:.1f}&nbsp;kW, versus the ~2&nbsp;kW optimum) spills far more midday surplus; the modeled PV-generation-weighted export credit is ~${solar_weighted_export_rate:.3f}/kWh, so a battery has more to store. Does storage then pencil?
  </div>

  <figure class="fig"><img src="data:image/png;base64,{b64}" alt="Optimal battery vs battery cost, PV economically optimized versus PV fixed at annual offset, Alameda" /><figcaption><strong>Oversizing raises the battery threshold, but not to today&rsquo;s price.</strong> With PV fixed to the installer rule, a battery pencils out at a higher price (~${m['thr_fix']:,.0f}/kWh) than under the economic optimum (~${m['thr_free']:,.0f}/kWh), exactly as intuition suggests. But today&rsquo;s net battery price (${prices.batt_net_per_kwh:,.0f}/kWh) is still well above both thresholds, so the optimal battery is zero under either sizing rule. Alameda / PG&amp;E, current law, PV fixed at its ${prices.pv_net_per_kw:,.0f}/kW net cost. Weighted 12&times;24 monthly-hour sensitivity using the modeled 2026 hourly EEC and ACC&nbsp;Plus schedule.</figcaption></figure>
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
    frag = _installer_rule_fragment(
        prices,
        pv_offset,
        solar_generation_weighted_export_rate(di),
        m,
        docio.embed_png(fig),
    )
    html = _read(doc)
    html = docio.upsert_marked_block(html, "INSTALLER-RULE", frag,
                                     anchor=docio.end_marker("MECH-BLOCK"))
    _write(doc, html)
    return doc


def _policy_matrix_fragment(results, chart_meta, exact_check, image: str) -> str:
    summaries = chart_meta["case_summaries"]
    rows = []
    labels = {
        "nbt_2026__post_itc_2026": "NBT 2026 / post-ITC",
        "nbt_2026__itc_2025": "NBT 2026 / 2025 ITC",
        "nem2_at_2026_retail_rates__post_itc_2026": (
            "NEM 2 at 2026 rates / post-ITC"
        ),
        "nem2_at_2026_retail_rates__itc_2025": (
            "NEM 2 at 2026 rates / 2025 ITC"
        ),
    }
    for case in POLICY_CASES:
        summary = summaries[case.case_id]
        rows.append(
            "<tr>"
            f"<td>{labels[case.case_id]}</td>"
            f"<td>{summary['median_pv_kw']:.2f}&nbsp;kW</td>"
            f"<td>{summary['median_battery_kwh']:.2f}&nbsp;kWh</td>"
            f"<td>{summary['pv_sizing_limit_count']} of "
            f"{chart_meta['county_count']}</td>"
            "</tr>"
        )
    nontrivial_battery = int((results["battery_kwh"] > 0.1).sum())
    nem2_rows = results[
        results["export_compensation_regime"]
        == ExportCompensationRegime.NEM2_AT_2026_RETAIL_RATES.value
    ]
    nem2_at_limit = int(nem2_rows["at_pv_sizing_limit"].sum())
    return f'''  <div class="callout" style="border-left-color:var(--accent-ink);">
    <strong>Policy counterfactual: what would optimal sizing look like under NEM&nbsp;2?</strong> This comparison holds the 2026 retail tariff snapshot and household profiles fixed. It changes export compensation and the federal solar/storage ITC as two separate axes. It is not a historical reconstruction of a pre-2023 bill.
  </div>

  <figure class="fig"><img src="data:image/png;base64,{image}" alt="Optimal solar and battery size across NEM 2 and NBT export compensation with and without the 2025 federal ITC" /><figcaption><strong>NEM&nbsp;2 supports more solar, but does not make an expensive battery necessary.</strong> Retail-rate annual netting drives PV to its tariff sizing limit in <strong>{nem2_at_limit} of {len(nem2_rows)}</strong> NEM&nbsp;2 county/capital-policy cases. Across all 16 case-study results, only <strong>{nontrivial_battery}</strong> select more than 0.1&nbsp;kWh of storage at the modeled market cost. NEM&nbsp;2 values exported solar at retail until annual true-up; that makes the PV itself more valuable and reduces the need to shift every surplus kWh through a battery. Every panel uses the same weighted 12&times;24 resolution.</figcaption></figure>

  <table class="data-table"><thead><tr><th>Policy case</th><th>Median optimal PV</th><th>Median optimal battery</th><th>Count at PV sizing cap</th></tr></thead><tbody>{''.join(rows)}</tbody></table>

  <div class="method"><h3>Interpretation and full-year check</h3>
    <p>The NEM&nbsp;2 model applies annual retail-dollar credit netting, interval non-bypassable charges, positive monthly net-consumption recovery charges, credit expiration at true-up, and monthly net-surplus compensation. NBT uses the source-locked hourly Energy Export Credit plus ACC&nbsp;Plus schedules.</p>
    <p>A targeted Alameda NEM&nbsp;2/post-ITC 8,760-hour solve selected {exact_check['exact_pv_kw']:.3f}&nbsp;kW PV and {exact_check['exact_battery_kwh']:.3f}&nbsp;kWh storage. The common-resolution panel differs by {abs(exact_check['pv_difference_kw']):.4f}&nbsp;kW PV and {abs(exact_check['battery_difference_kwh']):.4f}&nbsp;kWh storage. This check supports the panel&rsquo;s sizing result without mixing resolutions across the four-cell comparison.</p>
    <p>Sources and exact input fingerprints are recorded in <code>figure_builder/figures/policy_matrix_metadata.json</code>. The normalized results are in <code>figure_builder/figures/policy_matrix_optimal_sizes.csv</code>.</p>
  </div>'''


def build_policy_matrix_figure(
    doc=None,
    *,
    force_sweeps: bool = False,
    force_exact: bool = False,
) -> list[Path]:
    """Build, validate, document, and patch the four-case policy matrix."""

    from appliances.incentive_policy import PolicyRegime

    doc = Path(doc) if doc is not None else current_claims_doc()
    results = collect_policy_matrix_results(force=force_sweeps)
    exact = collect_market_price_observation(
        "alameda",
        regime=PolicyRegime.POST_ITC_2026,
        export_compensation_regime=(
            ExportCompensationRegime.NEM2_AT_2026_RETAIL_RATES
        ),
        cache=True,
        force=force_exact,
    )
    exact_check = validate_policy_matrix_exact_check(results, exact)

    FIG_DIR.mkdir(parents=True, exist_ok=True)
    results.to_csv(POLICY_MATRIX_CSV, index=False)
    figure, chart_meta = plot_policy_matrix_optimal_sizes(results)
    figure.savefig(POLICY_MATRIX_PNG, dpi=180, bbox_inches="tight")
    image = docio.embed_png(figure)
    import matplotlib.pyplot as plt

    plt.close(figure)

    input_paths = [
        sweep_csv_path(
            slug,
            live_prices(case.capital_policy_regime).regime,
            "288",
            case.export_compensation_regime,
        )
        for case in POLICY_CASES
        for slug, _name, _utility in CLAIM1_COUNTIES
    ]
    exact_path = market_observation_csv_path(
        "alameda",
        live_prices(PolicyRegime.POST_ITC_2026).regime,
        ExportCompensationRegime.NEM2_AT_2026_RETAIL_RATES,
    )
    metadata = {
        "schema_version": 1,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "model_git_sha": git_short_sha(),
        "command_argv": [
            "python3",
            "-m",
            "figure_builder",
            "policy-matrix",
            *(["--force"] if force_sweeps and force_exact else []),
        ],
        "force_sweeps": bool(force_sweeps),
        "force_exact_validation": bool(force_exact),
        "scenario": "full_electric_ev_coopt",
        "research_design": (
            "Controlled current-rate counterfactual. Both export-compensation "
            "regimes use the source-locked 2026 retail tariff snapshot."
        ),
        "common_temporal_resolution": {
            "name": "weighted_12x24_monthly_hour",
            "interval_count": 288,
            "soc_cycle": "monthly",
        },
        "policy_cases": [case.case_id for case in POLICY_CASES],
        "capital_costs": capital_cost_metadata(),
        "tariffs": tariff_metadata(),
        "optimization": optimization_metadata(fine=False),
        "input_sweep_caches": [file_identity(path) for path in input_paths],
        "exact_validation_input": file_identity(exact_path),
        "exact_validation": exact_check,
        "result_summary": chart_meta,
        "outputs": [
            file_identity(POLICY_MATRIX_CSV),
            file_identity(POLICY_MATRIX_PNG),
        ],
    }
    write_run_metadata(POLICY_MATRIX_METADATA, metadata)

    fragment = _policy_matrix_fragment(results, chart_meta, exact_check, image)
    html = _read(doc)
    html = docio.upsert_marked_block(
        html,
        "POLICY-MATRIX",
        fragment,
        anchor=docio.end_marker("INSTALLER-RULE"),
    )
    html = docio.inject_css(
        html,
        "POLICY-MATRIX-CSS",
        _POLICY_MATRIX_CSS,
    )
    _write(doc, html)
    return [doc, POLICY_MATRIX_CSV, POLICY_MATRIX_PNG, POLICY_MATRIX_METADATA]


_LEGACY_TARIFF_STATUS_PATTERN = (
    r'    <li>Retail rate and export-credit data have a mix of resolved and open '
    r'staleness gaps.*?      </ul>\n    </li>'
)


def _tariff_status_fragment(metadata: dict) -> str:
    scenario = metadata["scenario"]
    utilities = metadata["utilities"]
    comparison = metadata["comparison"]
    nem2_scenario = comparison["nem2_scenario"]
    nem2_utilities = nem2_scenario["utilities"]
    if len(utilities) != 3:
        raise ValueError(
            "Claim 1 tariff status requires exactly three utility records; "
            f"found {len(utilities)}"
        )
    if len(nem2_utilities) != 3:
        raise ValueError(
            "NEM 2 tariff status requires exactly three utility records; "
            f"found {len(nem2_utilities)}"
        )

    import_items = []
    export_items = []
    for record in utilities:
        utility = record["utility"].replace("&", "&amp;")
        import_schedule = record["import"]
        export_schedule = record["export"]
        acc_plus = record["acc_plus"]
        import_items.append(
            f"{utility} {import_schedule['plan_name']} "
            f"(<code>{import_schedule['source_id']}</code>)"
        )
        export_items.append(
            f"{utility} <code>{', '.join(export_schedule['source_ids'])}</code> "
            f"plus ACC Plus <code>{acc_plus['source_id']}</code>"
        )

    customer_segment = scenario["customer_segment"].replace("_", " ")
    scenario_line = (
        f"billing year {scenario['billing_year']}, NBT {scenario['nbt_vintage']} "
        f"application vintage, {customer_segment}, bundled service, tariff snapshot "
        f"{scenario['tariff_snapshot_date']}"
    )
    import_line = "; ".join(import_items)
    export_line = "; ".join(export_items)
    nem2_items = []
    for record in nem2_utilities:
        utility = record["utility"].replace("&", "&amp;")
        settlement = record["settlement"]
        nem2_items.append(
            f"{utility} rules <code>{settlement['utility_rules_source_id']}</code>, "
            f"billing <code>{settlement['billing_method_source_id']}</code>, "
            f"NSC <code>{settlement['nsc_rate_source_id']}</code>"
        )
    nem2_line = "; ".join(nem2_items)

    return f'''    <li>Claim 1 uses source-locked 2026 NBT schedules and a source-locked NEM 2 current-rate counterfactual.
      <ul class="sub-limitations">
        <li>Scenario: {scenario_line}.</li>
        <li>Import schedules: {import_line}.</li>
        <li>Export schedules: {export_line}.</li>
        <li>NEM 2 comparison: {nem2_scenario['research_label']}, tariff snapshot {nem2_scenario['tariff_snapshot_date']}; {nem2_line}.</li>
        <li>Annual NSC settlement is not part of the NBT sizing-sweep objective. The NEM 2 objective applies annual credit expiration and source-selected NSC.</li>
      </ul>
    </li>'''


def build_tariff_status_block(doc=None) -> Path:
    """Replace Claim 1's tariff-status limitation with current model sources."""
    doc = Path(doc) if doc is not None else current_claims_doc()
    fragment = _tariff_status_fragment(tariff_metadata())
    html = _read(doc)
    if docio.has_markers(html, "TARIFF-STATUS"):
        html = docio.replace_between_markers(html, "TARIFF-STATUS", fragment)
    else:
        html = docio.replace_first(
            html,
            _LEGACY_TARIFF_STATUS_PATTERN,
            docio.wrap_markers("TARIFF-STATUS", fragment),
        )
    _write(doc, html)
    return doc


def _claim1_support_fragment(prices_now, prices_2025) -> str:
    """Current evidence and capital-cost scope for the Claim 1 section."""

    return f'''<div class="sources">
    <h3>Checks tied to this claim</h3>
    <ul>
      <li><code>tests/lp_cooptimize_test.py</code> checks that sizing uses the configured capital costs and the repository&rsquo;s annualization primitives.</li>
      <li><code>tests/solar_storage_dispatch_test.py</code> checks hourly energy balance, state of charge, and physical meter direction.</li>
      <li><code>tests/tariffs_source_test.py</code> checks the source-locked import, NBT export, ACC Plus, and NBC tariff primitives.</li>
      <li><code>figure_builder/tests/test_datasets.py</code> checks exact market-point selection and complete source coverage; <code>figure_builder/tests/test_recipes.py</code> checks that captions are derived from current modeled values.</li>
    </ul>
  </div>

  <div class="sources">
    <h3>Capital-cost inputs, not market findings</h3>
    <ul>
      <li><strong>Current law:</strong> PV is ${prices_now.pv_net_per_kw:,.0f}/kW and battery storage is ${prices_now.batt_net_per_kwh:,.2f}/kWh net of modeled federal incentives.</li>
      <li><strong>2025 ITC sensitivity:</strong> PV is ${prices_2025.pv_net_per_kw:,.0f}/kW and battery storage is ${prices_2025.batt_net_per_kwh:,.3f}/kWh net of the 30% federal ITC.</li>
      <li>These are declared model inputs. The figures test economics at those costs; a separate capital-cost benchmark review is needed before treating them as estimates of today&rsquo;s market price.</li>
    </ul>
  </div>'''


def _limitations_fragment(metadata: dict, county_count: int) -> str:
    """Publication scope and limitations that match the rebuilt claims."""

    tariff_status = _tariff_status_fragment(metadata)
    return f'''<section class="claim" id="limitations">
  <p class="subhead">Known limitations &amp; interpretation boundaries</p>
  <ol class="limitations">
    <li>Claim 1 is a four-county case-study result, not a statewide storage-adoption estimate.
      <p>The capex sensitivities cover Alameda, Fresno, Los Angeles, and San Diego. The current-law market observations use the full 8,760-hour chronology; the 2025 ITC observations use the weighted 12&times;24 sensitivity model. That resolution difference is disclosed in every Claim 1 comparison and limits causal interpretation of the before/after contrast.</p>
    </li>
{tariff_status}
    <li>The Claim 1 NBT sizing objective does not reproduce every monthly NBT settlement rule.
      <p>Its NBT panels value hourly imports and exports using the source-locked schedules. The separate NEM 2 policy matrix applies annual retail-dollar netting, utility-specific non-bypassable and recovery charges, credit expiration, and annual net-surplus compensation. The annual-bill path used by Claims 2 and 3 separately applies the complete NBT generation/delivery and true-up primitives.</p>
    </li>
    <li>Claims 2 and 3 are annualized modeled counterfactuals for one representative household per county.
      <p>They combine standardized 8,760-hour household profiles with one source-locked 2026 tariff snapshot. They are not a longitudinal pre/post study, an adoption forecast, or evidence about household heterogeneity within a county.</p>
    </li>
    <li>The statewide distributions are unweighted across {county_count} modeled counties.
      <p>Eleven California counties are outside the repository&rsquo;s current input domain. The summaries do not population-weight counties, and SDG&amp;E is represented by San Diego County alone, so utility-level differences should be treated as descriptive rather than utility-wide estimates.</p>
    </li>
    <li>The gas-appliance + ICE reference is not a no-solar household.
      <p><code>baseline_ice_car</code> retains the fixed PV/storage convention used by the non-co-optimized scenario family. Claim 2 therefore isolates the complete modeled scenario difference; Claim 3 separately isolates the fixed-sizing versus co-optimization choice for the all-electric household.</p>
    </li>
  </ol>
</section>'''


def build_publication_scope(doc=None) -> Path:
    """Remove inherited draft claims and install current report boundaries."""

    from appliances.incentive_policy import PolicyRegime

    doc = Path(doc) if doc is not None else current_claims_doc()
    prices_now = live_prices()
    prices_2025 = live_prices(PolicyRegime.ITC_2025)
    support = docio.wrap_markers(
        "CLAIM1-SUPPORT",
        _claim1_support_fragment(prices_now, prices_2025),
    )
    html = _read(doc)
    support_anchor = (
        docio.end_marker("POLICY-MATRIX")
        if docio.has_markers(html, "POLICY-MATRIX")
        else docio.end_marker("INSTALLER-RULE")
    )
    html = docio.replace_first(
        html,
        re.escape(support_anchor) + r'.*?'
        r'(?=\n</section>\s*<!-- =+\s*CLAIM 2\s*=+ -->)',
        support_anchor + '\n\n' + support,
    )
    html = docio.replace_first(
        html,
        r'<section class="claim" id="limitations">.*?</section>',
        _limitations_fragment(tariff_metadata(), len(expected_claim_counties())),
    )
    html = docio.set_commit_label(html, git_short_sha())
    _write(doc, html)
    return doc


def _claim2_fragment(
    source_label: str,
    case_image: str,
    statewide_image: str,
    statewide_meta: dict,
) -> str:
    total = statewide_meta["county_count"]
    wins = statewide_meta["positive_count"]
    median = statewide_meta["median"]
    low = statewide_meta["minimum"]
    high = statewide_meta["maximum"]
    qualifier = "all" if wins == total else f"{wins} of"
    return f'''<section class="claim" id="claim-2">
  <div class="claim-head"><span class="claim-num">CLAIM 2</span></div>
  <h2 class="claim-title">Full electrification with co-optimized PV/storage has lower modeled annual cost than the gas-appliance + ICE reference in {qualifier} {total} counties</h2>
  <p class="claim-sub">This is a like-for-like comparison of the repository&rsquo;s <code>baseline_ice_car</code> reference and <code>full_electric_ev_coopt</code> case. The reference retains gas space/water heating and cooking plus an internal-combustion vehicle; it also retains the fixed PV/storage convention used by the non-co-optimized scenario family, so it is <strong>not</strong> a no-solar household.</p>

  <div class="stat-row">
    <div class="stat"><span class="num">{wins} of {total}</span><span class="lbl">counties where the co-optimized all-electric case has lower equivalent annual cost</span></div>
    <div class="stat"><span class="num">{median:.1f}%</span><span class="lbl">median modeled annual-cost reduction</span></div>
    <div class="stat"><span class="num">{low:.1f}% to {high:.1f}%</span><span class="lbl">county range; negative values mean the all-electric case costs more</span></div>
  </div>

  <figure class="fig"><img src="data:image/png;base64,{case_image}" alt="Equivalent annual cost components for three modeled choices in four case-study counties" /><figcaption><strong>What is included in equivalent annual cost.</strong> Annualized solar, storage, electric-equipment, and gas-equipment capital costs are stacked with annual electricity, gas, and vehicle O&amp;M costs. All bars come from the same refreshed Step&nbsp;18 source. The shared legend sits below the four panels so it does not obscure a bar.</figcaption></figure>

  <figure class="fig"><img src="data:image/png;base64,{statewide_image}" alt="Sorted statewide annual-cost reduction from full electrification with co-optimized solar and storage" /><figcaption><strong>Statewide distribution, not four selected examples.</strong> Every one of the {total} modeled counties is shown and sorted by the percent reduction relative to the gas-appliance + ICE reference. Green bars favor the all-electric case; red bars favor the reference.</figcaption></figure>

  <div class="method">
    <h3>Calculation</h3>
    <p><code>EAC = annualized PV + annualized storage + annualized electric equipment + annualized gas equipment + electricity bill + gas bill + vehicle O&amp;M</code>. Claim&nbsp;2 reports <code>100 &times; (reference EAC &minus; co-optimized electric EAC) / reference EAC</code>.</p>
    <p>Source: <code>{source_label}</code>. The builder requires exactly one finite, non-negative row for each of the three cases in every one of the repository&rsquo;s 47 counties; missing or duplicate coverage fails the build.</p>
  </div>

  <div class="evidence"><h3>Checks tied to this claim</h3><ul>
    <li><code>tests/total_annual_costs_test.py</code> checks EAC reconciliation and NaN propagation.</li>
    <li><code>tests/capital_costs_test.py</code> checks annualized capital-cost inputs.</li>
    <li><code>tests/tariffs_source_test.py</code> checks the source-locked import, export, ACC Plus, and NBC tariff primitives used in annual bills.</li>
    <li><code>figure_builder/tests/test_datasets.py</code> checks complete scenario/county coverage and exact comparison arithmetic.</li>
  </ul></div>
</section>'''


def _claim3_fragment(
    source_label: str,
    statewide_image: str,
    statewide_meta: dict,
) -> str:
    total = statewide_meta["county_count"]
    wins = statewide_meta["positive_count"]
    mean = statewide_meta["mean"]
    median = statewide_meta["median"]
    low = statewide_meta["minimum"]
    high = statewide_meta["maximum"]
    qualifier = "all" if wins == total else f"{wins} of"
    return f'''<section class="claim" id="claim-3">
  <div class="claim-head"><span class="claim-num">CLAIM 3</span></div>
  <h2 class="claim-title">Co-optimizing PV/storage lowers modeled annual cost relative to fixed sizing in {qualifier} {total} counties</h2>
  <p class="claim-sub">The appliance mix is held fixed at full electrification plus an EV. The comparison changes the solar/storage sizing and dispatch convention: <code>full_electric_ev</code> uses the fixed-system path, while <code>full_electric_ev_coopt</code> chooses PV and battery capacity jointly with hourly dispatch under the same current tariff and capital-cost assumptions.</p>

  <div class="stat-row">
    <div class="stat"><span class="num">${mean:,.0f}/yr</span><span class="lbl">mean EAC reduction from co-optimization</span></div>
    <div class="stat"><span class="num">${median:,.0f}/yr</span><span class="lbl">median EAC reduction</span></div>
    <div class="stat"><span class="num">${low:,.0f} to ${high:,.0f}</span><span class="lbl">county range; negative values mean fixed sizing costs less</span></div>
  </div>

  <figure class="fig"><img src="data:image/png;base64,{statewide_image}" alt="Sorted statewide annual EAC savings from co-optimizing solar and storage" /><figcaption><strong>The value of choosing system size rather than imposing it.</strong> Each bar is <code>fixed-system EAC &minus; co-optimized EAC</code> for the same county and full-electric appliance/vehicle mix. The chart shows all {total} counties, rather than only the four case studies.</figcaption></figure>

  <div class="method">
    <h3>Calculation and interpretation</h3>
    <p>Claim&nbsp;3 is an incremental modeling result, not a claim that rooftop PV or storage is free. Positive savings mean the optimized capacity/dispatch combination has lower total EAC after its own capital cost is included. Source: <code>{source_label}</code>.</p>
  </div>

  <div class="evidence"><h3>Checks tied to this claim</h3><ul>
    <li><code>tests/solar_storage_dispatch_test.py</code> checks hourly energy balance, state of charge, and physical meter direction.</li>
    <li><code>tests/total_annual_costs_test.py</code> checks that the component sum used here reconciles to total EAC.</li>
    <li><code>figure_builder/tests/test_datasets.py</code> checks that fixed and co-optimized rows cover identical counties and that savings are computed from exact paired totals.</li>
  </ul></div>
</section>'''


def build_statewide_claims(doc=None, *, source=None) -> Path:
    """Rebuild Claims 2 and 3 from one strict, current Step 18 source."""

    doc = Path(doc) if doc is not None else current_claims_doc()
    source_path = Path(source) if source is not None else claims_eac_source_path()
    eac = collect_claims_eac_results(source_path)
    summary = summarize_claims_eac(eac)
    fig_cases, _ = plot_case_study_eac(eac)
    fig_claim2, meta_claim2 = plot_statewide_electrification_savings(summary)
    fig_claim3, meta_claim3 = plot_statewide_cooptimization_savings(summary)
    source_label = str(source_path.relative_to(source_path.parents[1]))
    claim2 = _claim2_fragment(
        source_label,
        docio.embed_png(fig_cases),
        docio.embed_png(fig_claim2),
        meta_claim2,
    )
    claim3 = _claim3_fragment(
        source_label,
        docio.embed_png(fig_claim3),
        meta_claim3,
    )
    html = _read(doc)
    html = docio.replace_first(
        html,
        r'<section class="claim" id="claim-2">.*?'
        r'(?=<section class="claim" id="claim-3">)',
        claim2 + "\n\n",
    )
    html = docio.replace_first(
        html,
        r'<section class="claim" id="claim-3">.*?'
        r'(?=<section class="claim" id="limitations">)',
        claim3 + "\n\n",
    )
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
