"""
Step 9b — Co‑Optimize PV size, Battery size (kWh,kW), and hourly dispatch.

This module builds a linear program (LP) to minimize annual total cost:
  annualized capex (PV + battery) + retail imports − NEM3 export credits (+ optional degradation cost)

Notes
- CSV‑only NEM3 export tables are loaded via helpers.nem3_export_rates
- Retail import price is built from helpers.electricity_rate_helpers plans
- Weather→PV per‑kW yield is computed using Step 9 core helpers (GHI‑based PVWatts‑style)

Outputs (per county)
- solar_storage_dispatch_profiles_<county>.csv
- solar_storage_dispatch_profiles_with_exports_<county>.csv

These match Step 9 column conventions so Step 10 can build aggregator files for Step 12 without changes.

Usage examples
- Separate co‑opt scenario (recommended), e.g., `baseline_coopt`:
    python3 step9b_cooptimize_pv_battery.py \
      --base-input-dir data/loadprofiles \
      --base-output-dir data/loadprofiles \
      --scenario baseline_coopt \
      --housing-type single-family-detached \
      --counties alameda los-angeles

- Override retail plan and allow grid charging and battery exports (if desired):
    python3 step9b_cooptimize_pv_battery.py \
      --scenario baseline_coopt \
      --housing-type single-family-detached \
      --counties alameda \
      --plan E-TOU-D \
      --allow-grid-charging \
      --allow-batt-export

Flags / configuration
- --base-input-dir (default: data/loadprofiles)
  Root where county inputs live: weather_TMY_<county>.csv and combined_profiles_<scenario>_<county>.csv
- --base-output-dir (default: data/loadprofiles)
  Root where step outputs are written under <scenario>/<housing_type>/<county>
- --scenario (required)
  Scenario folder to read/write (use a separate scenario like baseline_coopt to keep results clean)
- --housing-type (default: single-family-detached)
- --counties <list>
  County slugs or names; if omitted, auto-discovers folders under the scenario path
- --plan <name>
  Retail plan for the resolved utility (e.g., PG&E: E-TOU-D; SCE: TOU-D-4-9PM; SDG&E: TOU-ELEC). Defaults to the first plan found for the utility.
- --allow-grid-charging
  Enable Grid→Battery charging (off by default)
- --allow-batt-export / --disallow-batt-export
  Enable or disable Battery→Grid exports (default: enabled)
- --discount-rate (default: DEFAULT_DISCOUNT_RATE, evaluations/constants.py)
- --pv-capex-kw (default: SolarSystemAppliance.per_kw_cost_net(FULL_INCENTIVES), $3,300/kW
  under the default POST_ITC_2026 regime; $2,310/kW under the expired ITC_2025 regime)
- --batt-capex-kwh (default: BatteryStorageAppliance.per_kwh_cost_net(FULL_INCENTIVES),
  ~$1,461/kWh under the default POST_ITC_2026 regime; ~$1,022/kWh under the expired ITC)
- --batt-capex-kw (default: 0.0 $/kW)
- --pv-life-yrs (default: 25)
- --batt-life-yrs (default: 15)
- --batt-degrade-cost-kwh (default: 0.0 $/kWh throughput)

Assumptions
- Full‑year (8760) optimization for fidelity (SOC chronology). A 12×24 time‑slice variant can be added later.
- Annualized capex via CRF with discount rate and lifetimes above.
- Solver: PuLP (CBC). If PuLP is missing, a clear error is raised with installation instructions.
"""

from __future__ import annotations

import argparse
import os
from typing import List, Optional

import pandas as pd

from helpers.main_helpers import (
    get_counties,
    get_scenario_path,
    slugify_county_name,
)
from helpers.utility_helpers import get_utility_for_county
from helpers.nem3_export_rates import get_export_rate_table_for_county
from helpers.electricity_rate_helpers import PGE_RATE_PLANS, SCE_RATE_PLANS, SDGE_RATE_PLANS

from .step9_solar_storage_dispatch_core import (
    prepare_weather_and_load,
    pv_timeseries_ac_kwh,
)
from .step9b_cooptimize_core import (
    CooptInputs,
    FlowSeries,
    build_monthly_hourly_inputs,
    _hourly_import_rate,
    _solve_lp,
    _timestamp_index_8760,
)
from evaluations.constants import DEFAULT_DISCOUNT_RATE
from appliances.solar_system import SolarSystemAppliance
from appliances.battery_storage import BatteryStorageAppliance
from appliances.electric_base import IncentiveScenario

# Net (after-incentive, full_incentives scenario) $/kW and $/kWh, derived from
# the same appliance classes step14 uses to report capex. The LP's sizing
# objective must use a price consistent with what's actually reported for the
# scenario being modeled:
#   - Bug found 2026-07-06: the LP sized against stale hardcoded defaults
#     ($2,830/kW, $800/kWh) while step14 reported capex at the appliance
#     classes' real gross values (~$3,300/kW, ~$1,461/kWh) — fixed by
#     reconciling to the same appliance classes.
#   - Refinement 2026-07-07: reconciling to *gross* cost left a second,
#     smaller inconsistency — the paper's default/headline scenario reports
#     capex net of the 30% ITC (full_incentives), so a decision-maker sizing
#     against gross cost is using a price ~45% higher than what they'd
#     actually pay. The LP's sizing signal should match whichever incentive
#     scenario is actually being reported. These defaults (used when a caller
#     doesn't specify otherwise) assume full_incentives, matching Config's
#     own default; real production runs (mod_solar_storage.run) pass the net
#     cost for whichever incentive scenario Config actually specifies.
#   - Update 2026-07-17: the ITC net vs gross distinction above is now moot
#     under the default regime. incentive_policy.py's DEFAULT_POLICY_REGIME is
#     POST_ITC_2026 (IRC 25D repealed by OBBBA), so per_*_cost_net(FULL) now
#     returns gross for PV and storage. The invariant these defaults encode
#     (LP sizes against the same price step14 reports) is unchanged; only the
#     value moved, from ~$1,022 to ~$1,461/kWh and $2,310 to $3,300/kW.
DEFAULT_PV_CAPEX_PER_KW = SolarSystemAppliance.per_kw_cost_net(IncentiveScenario.FULL_INCENTIVES)
DEFAULT_BATT_CAPEX_PER_KWH = BatteryStorageAppliance.per_kwh_cost_net(IncentiveScenario.FULL_INCENTIVES)


RATE_PLANS = {
    "PG&E": PGE_RATE_PLANS,
    "SCE": SCE_RATE_PLANS,
    "SDG&E": SDGE_RATE_PLANS,
}

# ---------------------------------------------------------------------------
# Default sweep values — used when --use-defaults is passed.
# Covers the range from very cheap future batteries to current market prices.
# ---------------------------------------------------------------------------
DEFAULT_BATT_CAPEX_SWEEP: List[float] = [
    25, 50, 75, 100, 125, 150, 175, 200, 250, 300,
    350, 400, 500, 600, 700, 750, 800, 900, 1000, 1200,
]
DEFAULT_BATT_SIZE_SWEEP: List[float] = [
    0, 2, 4, 6, 8, 10, 12, 15, 20, 25, 30, 40, 50,
]
DEFAULT_PV_SIZE_SWEEP: List[float] = [
    0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 4.5, 5.0, 5.5, 6.0,
]


def _format_pv_capex_tag(value: float) -> str:
    tag = f"pv{value}"
    return tag.replace(".", "p")


def _write_step9_outputs(
    out_dir: str,
    county: str,
    timestamps: List[pd.Timestamp],
    L: List[float],
    G: List[float],
    PV_kw: float,
    flows: FlowSeries,
):
    # flows unpack
    pv2load = flows.pv_to_load
    pv2batt = flows.pv_to_batt
    pv2grid = flows.pv_to_grid
    batt2load = flows.batt_to_load
    batt2grid = flows.batt_to_grid
    grid2load = flows.grid_to_load
    grid2batt = flows.grid_to_batt
    soc = flows.soc
    pv_ac = [PV_kw * g for g in G]
    total_supply = [pl + bl + gl for pl, bl, gl in zip(pv2load, batt2load, grid2load)]
    diff = [ts - ll for ts, ll in zip(total_supply, L)]

    base_cols = {
        "timestamp": timestamps,
        "Load Profile": L,
        "System to Load": pv2load,
        "Battery to Load": batt2load,
        "Grid to Load": grid2load,
        "Solar + Battery to Load": [pl + bl for pl, bl in zip(pv2load, batt2load)],
        "Total Supply": total_supply,
        "Difference": diff,
        "System to Battery": pv2batt,
        "Grid to Battery": grid2batt,
        "Battery SOC": soc,
        "PV AC (kWh)": pv_ac,
        "PV to Grid (kWh)": pv2grid,
        # New: write battery export flow explicitly for downstream accounting
        "Battery to Grid (kWh)": batt2grid,
    }
    base_df = pd.DataFrame(base_cols)

    # Write base
    out_base = os.path.join(out_dir, f"solar_storage_dispatch_profiles_{county}.csv")
    base_df.to_csv(out_base, index=False)

    # Exports file (preferred by Step 10)
    # Exports = PV→Grid + Battery→Grid when battery export is allowed
    exp_df = pd.DataFrame({
        "timestamp": timestamps,
        "Exports to Grid (kWh)": [pg + bg for pg, bg in zip(pv2grid, batt2grid)],
    })
    out_exp = os.path.join(out_dir, f"solar_storage_dispatch_profiles_with_exports_{county}.csv")
    exp_df.to_csv(out_exp, index=False)


def _write_price_diagnostics(
    out_dir: str,
    county: str,
    timestamps: List[pd.Timestamp],
    p_imp: List[float],
    p_exp: List[float],
) -> None:
    if len(p_imp) != len(p_exp) or len(p_imp) != len(timestamps):
        raise ValueError("Price diagnostics requires aligned timestamps and price arrays.")

    diag_df = pd.DataFrame({
        "timestamp": timestamps,
        "import_price_usd_per_kwh": p_imp,
        "export_price_usd_per_kwh": p_exp,
    })
    diag_path = os.path.join(out_dir, f"coopt_price_series_{county}.csv")
    diag_df.to_csv(diag_path, index=False)

    stats = diag_df[["import_price_usd_per_kwh", "export_price_usd_per_kwh"]].describe(
        percentiles=[0.05, 0.5, 0.95]
    )
    stats_path = os.path.join(out_dir, f"coopt_price_stats_{county}.csv")
    stats.to_csv(stats_path)

    print(
        f"[step9b] Price stats for {county} "
        f"(import min/median/max=${stats.loc['min', 'import_price_usd_per_kwh']:.3f}/"
        f"{stats.loc['50%', 'import_price_usd_per_kwh']:.3f}/"
        f"{stats.loc['max', 'import_price_usd_per_kwh']:.3f}, "
        f"export min/median/max=${stats.loc['min', 'export_price_usd_per_kwh']:.3f}/"
        f"{stats.loc['50%', 'export_price_usd_per_kwh']:.3f}/"
        f"{stats.loc['max', 'export_price_usd_per_kwh']:.3f})"
    )

    try:
        import matplotlib.pyplot as plt

        diag_df["month"] = diag_df["timestamp"].dt.month
        monthly = diag_df.groupby("month")[["import_price_usd_per_kwh", "export_price_usd_per_kwh"]].mean()

        fig, axes = plt.subplots(2, 1, figsize=(10, 6), tight_layout=True)
        axes[0].plot(monthly.index, monthly["import_price_usd_per_kwh"], label="Import ($/kWh)", color="#1f77b4")
        axes[0].plot(monthly.index, monthly["export_price_usd_per_kwh"], label="Export ($/kWh)", color="#ff7f0e")
        axes[0].set_xlabel("Month")
        axes[0].set_ylabel("Avg Price ($/kWh)")
        axes[0].set_title("Monthly Average Prices")
        axes[0].legend()

        axes[1].hist(
            p_imp,
            bins=40,
            alpha=0.7,
            label="Import ($/kWh)",
            color="#1f77b4",
        )
        axes[1].hist(
            p_exp,
            bins=40,
            alpha=0.7,
            label="Export ($/kWh)",
            color="#ff7f0e",
        )
        axes[1].set_xlabel("Price ($/kWh)")
        axes[1].set_ylabel("Hours")
        axes[1].set_title("Price Distribution")
        axes[1].legend()

        fig_path = os.path.join(out_dir, f"coopt_price_diagnostics_{county}.png")
        fig.savefig(fig_path, dpi=150)
        plt.close(fig)
    except Exception as e:
        raise RuntimeError(f"Failed to write price diagnostics plot: {e}")


def _write_batt_capex_sweep(
    out_dir: str,
    county: str,
    inputs: CooptInputs,
    *,
    allow_grid_charging: bool,
    allow_batt_export: bool,
    batt_capex_values: List[float],
    pv_capex_per_kw: float,
    batt_capex_per_kw: float,
    pv_life_yrs: int,
    batt_life_yrs: int,
    discount_rate: float,
    batt_degrade_cost_per_kwh: float,
    weights: Optional[List[float]] = None,
    cycle_monthly: bool = False,
    file_tag: Optional[str] = None,
) -> None:
    records = []
    for capex_kwh in batt_capex_values:
        result = _solve_lp(
            inputs,
            allow_grid_charging=allow_grid_charging,
            allow_batt_export=allow_batt_export,
            c_pv_kw=pv_capex_per_kw,
            c_batt_kwh=capex_kwh,
            c_batt_kw=batt_capex_per_kw,
            pv_life_yrs=pv_life_yrs,
            batt_life_yrs=batt_life_yrs,
            discount_rate=discount_rate,
            c_deg_per_kwh=batt_degrade_cost_per_kwh,
            weights=weights,
            cycle_monthly=cycle_monthly,
        )
        records.append(
            {
                "battery_capex_kwh": float(capex_kwh),
                "pv_kw": result.pv_kw,
                "batt_kwh": result.batt_kwh,
                "batt_kw": result.batt_kw,
                "total_cost": result.total_cost,
                "capex_annual": result.capex_annual,
                "import_cost": result.import_cost,
                "export_credit": result.export_credit,
                "degradation_cost": result.degradation_cost,
            }
        )

    if not records:
        return
    df = pd.DataFrame(records)
    tag = f"_{file_tag}" if file_tag else ""
    csv_path = os.path.join(out_dir, f"coopt_batt_capex_sweep_{county}{tag}.csv")
    df.to_csv(csv_path, index=False)

    try:
        import matplotlib.pyplot as plt

        fig, axes = plt.subplots(2, 1, figsize=(10, 7), tight_layout=True)

        axes[0].plot(df["battery_capex_kwh"], df["batt_kwh"], label="Battery Size (kWh)", color="#1f77b4")
        axes[0].plot(df["battery_capex_kwh"], df["batt_kw"], label="Battery Power (kW)", color="#ff7f0e")
        axes[0].set_xlabel("Battery Capex ($/kWh)")
        axes[0].set_ylabel("Battery Size")
        axes[0].set_title("Battery Size vs Capex")
        axes[0].legend()

        axes[1].plot(df["battery_capex_kwh"], df["total_cost"], label="Total Cost (annual)", color="#2ca02c")
        axes[1].set_xlabel("Battery Capex ($/kWh)")
        axes[1].set_ylabel("Annual Cost ($)")
        axes[1].set_title("Co‑opt Objective vs Capex")
        axes[1].legend()

        fig_path = os.path.join(out_dir, f"coopt_batt_capex_sweep_{county}{tag}.png")
        fig.savefig(fig_path, dpi=150)
        plt.close(fig)
    except Exception as e:
        raise RuntimeError(f"Failed to write battery capex sweep plot: {e}")


def _write_batt_size_vs_capex_by_pv(
    out_dir: str,
    county: str,
    pv_capex_values: List[float],
    batt_capex_values: List[float],
    *,
    base_pv_capex: Optional[float] = None,
) -> None:
    if not pv_capex_values or not batt_capex_values:
        return
    try:
        import matplotlib.pyplot as plt
        import numpy as np

        pv_vals = sorted(set(float(v) for v in pv_capex_values))
        fig, ax = plt.subplots(1, 1, figsize=(10, 6), tight_layout=True)
        if pv_vals:
            vmin, vmax = min(pv_vals), max(pv_vals)
        else:
            vmin, vmax = 0.0, 1.0
        def _color_for_pv(val: float):
            if vmax == vmin:
                t = 0.6
            else:
                t = (float(val) - vmin) / (vmax - vmin)
            # Map to light→dark blue for low→high PV capex
            return plt.cm.Blues(0.3 + 0.6 * t)

        for idx, pv_capex in enumerate(pv_vals):
            tag = _format_pv_capex_tag(pv_capex)
            csv_path = os.path.join(out_dir, f"coopt_batt_capex_sweep_{county}_{tag}.csv")
            if not os.path.exists(csv_path):
                raise RuntimeError(f"Missing PV capex sweep CSV: {csv_path}")
            df = pd.read_csv(csv_path)
            if "battery_capex_kwh" not in df.columns or "batt_kwh" not in df.columns:
                raise RuntimeError(f"Missing columns in PV capex sweep CSV: {csv_path}")
            df = df.sort_values("battery_capex_kwh")
            ax.plot(
                df["battery_capex_kwh"],
                df["batt_kwh"],
                label=f"PV Capex ${pv_capex:,.0f}/kW",
                color=_color_for_pv(pv_capex),
                linewidth=2,
            )

        if base_pv_capex is not None:
            base_df = None
            base_csv = os.path.join(out_dir, f"coopt_batt_capex_sweep_{county}.csv")
            if os.path.exists(base_csv):
                base_df = pd.read_csv(base_csv)
            else:
                tag = _format_pv_capex_tag(base_pv_capex)
                sweep_csv = os.path.join(out_dir, f"coopt_batt_capex_sweep_{county}_{tag}.csv")
                if os.path.exists(sweep_csv):
                    base_df = pd.read_csv(sweep_csv)
            if base_df is not None and "battery_capex_kwh" in base_df.columns and "batt_kwh" in base_df.columns:
                base_df = base_df.sort_values("battery_capex_kwh")
                ax.plot(
                    base_df["battery_capex_kwh"],
                    base_df["batt_kwh"],
                    label=f"Main PV Capex ${base_pv_capex:,.0f}/kW",
                    color="#ff1493",
                    linewidth=2.5,
                )

        ax.set_xlabel("Battery Capex ($/kWh)")
        ax.set_ylabel("Optimal Battery Size (kWh) from LP")
        ax.set_title("Battery Size vs Battery Capex (PV Capex Sensitivity)")
        ax.text(
            0.5,
            -0.18,
            "Each line is the LP‑optimal battery size for a fixed PV capex.",
            transform=ax.transAxes,
            ha="center",
            va="top",
            fontsize=9,
            color="#555",
        )
        ax.legend(loc="best", fontsize=9)

        fig_path = os.path.join(out_dir, f"coopt_batt_size_vs_capex_by_pv_{county}.png")
        fig.savefig(fig_path, dpi=150)
        plt.close(fig)
    except Exception as e:
        raise RuntimeError(f"Failed to write PV capex battery-size sweep plot: {e}")


def _write_pv_size_vs_capex_by_pv(
    out_dir: str,
    county: str,
    pv_capex_values: List[float],
    batt_capex_values: List[float],
    *,
    base_pv_capex: Optional[float] = None,
) -> None:
    if not pv_capex_values or not batt_capex_values:
        return
    try:
        import matplotlib.pyplot as plt
        import numpy as np

        pv_vals = sorted(set(float(v) for v in pv_capex_values))
        fig, ax = plt.subplots(1, 1, figsize=(10, 6), tight_layout=True)
        if pv_vals:
            vmin, vmax = min(pv_vals), max(pv_vals)
        else:
            vmin, vmax = 0.0, 1.0
        def _color_for_pv(val: float):
            if vmax == vmin:
                t = 0.6
            else:
                t = (float(val) - vmin) / (vmax - vmin)
            return plt.cm.Greens(0.3 + 0.6 * t)

        for pv_capex in pv_vals:
            tag = _format_pv_capex_tag(pv_capex)
            csv_path = os.path.join(out_dir, f"coopt_batt_capex_sweep_{county}_{tag}.csv")
            if not os.path.exists(csv_path):
                raise RuntimeError(f"Missing PV capex sweep CSV: {csv_path}")
            df = pd.read_csv(csv_path)
            if "battery_capex_kwh" not in df.columns or "pv_kw" not in df.columns:
                raise RuntimeError(f"Missing columns in PV capex sweep CSV: {csv_path}")
            df = df.sort_values("battery_capex_kwh")
            ax.plot(
                df["battery_capex_kwh"],
                df["pv_kw"],
                label=f"PV Capex ${pv_capex:,.0f}/kW",
                color=_color_for_pv(pv_capex),
                linewidth=2,
            )

        if base_pv_capex is not None:
            base_df = None
            base_csv = os.path.join(out_dir, f"coopt_batt_capex_sweep_{county}.csv")
            if os.path.exists(base_csv):
                base_df = pd.read_csv(base_csv)
            else:
                tag = _format_pv_capex_tag(base_pv_capex)
                sweep_csv = os.path.join(out_dir, f"coopt_batt_capex_sweep_{county}_{tag}.csv")
                if os.path.exists(sweep_csv):
                    base_df = pd.read_csv(sweep_csv)
            if base_df is not None and "battery_capex_kwh" in base_df.columns and "pv_kw" in base_df.columns:
                base_df = base_df.sort_values("battery_capex_kwh")
                ax.plot(
                    base_df["battery_capex_kwh"],
                    base_df["pv_kw"],
                    label=f"Main PV Capex ${base_pv_capex:,.0f}/kW",
                    color="#ff1493",
                    linewidth=2.5,
                )

        ax.set_xlabel("Battery Capex ($/kWh)")
        ax.set_ylabel("Optimal PV Size (kW) from LP")
        ax.set_title("PV Size vs Battery Capex (PV Capex Sensitivity)")
        ax.legend(loc="best", fontsize=9)

        fig_path = os.path.join(out_dir, f"coopt_pv_size_vs_capex_by_pv_{county}.png")
        fig.savefig(fig_path, dpi=150)
        plt.close(fig)
    except Exception as e:
        raise RuntimeError(f"Failed to write PV capex PV-size sweep plot: {e}")


def _write_batt_adoption_curve(
    out_dir: str,
    county: str,
    *,
    base_pv_capex: float,
    scenario: str,
    reference_lines: List[tuple[float, str, str]],
) -> None:
    csv_path = os.path.join(out_dir, f"coopt_batt_capex_sweep_{county}.csv")
    if not os.path.exists(csv_path):
        raise RuntimeError(f"Missing base battery capex sweep CSV: {csv_path}")
    try:
        import matplotlib.pyplot as plt

        df = pd.read_csv(csv_path)
        required = {"battery_capex_kwh", "batt_kwh", "pv_kw"}
        if not required.issubset(set(df.columns)):
            raise RuntimeError(f"Missing columns in base sweep CSV: {csv_path}")
        df = df.sort_values("battery_capex_kwh")

        fig, (ax_top, ax_bottom) = plt.subplots(
            2, 1, figsize=(10, 7), sharex=True, tight_layout=True
        )

        ax_top.plot(
            df["battery_capex_kwh"],
            df["batt_kwh"],
            color="#1f77b4",
            linewidth=2,
            label="Optimal Battery Size (kWh)",
        )
        ax_top.set_ylabel("Optimal Battery Size (kWh)")
        ax_top.set_title(f"Battery Adoption Curve Under NEM 3.0. {scenario}. {county}.")
        ax_top.grid(True, alpha=0.3)

        ax_bottom.plot(
            df["battery_capex_kwh"],
            df["pv_kw"],
            color="#2ca02c",
            linewidth=2,
            label="Optimal PV Size (kW)",
        )
        ax_bottom.set_ylabel("Optimal PV Size (kW)")
        ax_bottom.set_xlabel("Battery Capex ($/kWh)")
        ax_bottom.grid(True, alpha=0.3)

        for val, label, color in reference_lines:
            ax_top.axvline(val, color=color, linestyle="--", linewidth=1.6, label=label)
            ax_bottom.axvline(val, color=color, linestyle="--", linewidth=1.6, label="_nolegend_")

        ax_top.legend(loc="best", fontsize=9)

        fig_path = os.path.join(out_dir, f"coopt_batt_adoption_curve_{county}.png")
        fig.savefig(fig_path, dpi=150)
        plt.close(fig)
    except Exception as e:
        raise RuntimeError(f"Failed to write battery adoption curve plot: {e}")


def _write_objective_vs_capex_by_pv(
    out_dir: str,
    county: str,
    pv_capex_values: List[float],
    batt_capex_values: List[float],
    *,
    base_pv_capex: Optional[float] = None,
) -> None:
    if not pv_capex_values or not batt_capex_values:
        return
    try:
        import matplotlib.pyplot as plt
        import numpy as np

        pv_vals = sorted(set(float(v) for v in pv_capex_values))
        fig, ax = plt.subplots(1, 1, figsize=(10, 6), tight_layout=True)
        if pv_vals:
            vmin, vmax = min(pv_vals), max(pv_vals)
        else:
            vmin, vmax = 0.0, 1.0
        def _color_for_pv(val: float):
            if vmax == vmin:
                t = 0.6
            else:
                t = (float(val) - vmin) / (vmax - vmin)
            # Map to light→dark red for low→high PV capex
            return plt.cm.Reds(0.3 + 0.6 * t)

        for pv_capex in pv_vals:
            tag = _format_pv_capex_tag(pv_capex)
            csv_path = os.path.join(out_dir, f"coopt_batt_capex_sweep_{county}_{tag}.csv")
            if not os.path.exists(csv_path):
                raise RuntimeError(f"Missing PV capex sweep CSV: {csv_path}")
            df = pd.read_csv(csv_path)
            if "battery_capex_kwh" not in df.columns or "total_cost" not in df.columns:
                raise RuntimeError(f"Missing columns in PV capex sweep CSV: {csv_path}")
            df = df.sort_values("battery_capex_kwh")
            ax.plot(
                df["battery_capex_kwh"],
                df["total_cost"],
                label=f"PV Capex ${pv_capex:,.0f}/kW",
                color=_color_for_pv(pv_capex),
                linewidth=2,
            )

        if base_pv_capex is not None:
            base_df = None
            base_csv = os.path.join(out_dir, f"coopt_batt_capex_sweep_{county}.csv")
            if os.path.exists(base_csv):
                base_df = pd.read_csv(base_csv)
            else:
                tag = _format_pv_capex_tag(base_pv_capex)
                sweep_csv = os.path.join(out_dir, f"coopt_batt_capex_sweep_{county}_{tag}.csv")
                if os.path.exists(sweep_csv):
                    base_df = pd.read_csv(sweep_csv)
            if base_df is not None and "battery_capex_kwh" in base_df.columns and "total_cost" in base_df.columns:
                base_df = base_df.sort_values("battery_capex_kwh")
                ax.plot(
                    base_df["battery_capex_kwh"],
                    base_df["total_cost"],
                    label=f"Main PV Capex ${base_pv_capex:,.0f}/kW",
                    color="#ff1493",
                    linewidth=2.5,
                )

        ax.set_xlabel("Battery Capex ($/kWh)")
        ax.set_ylabel("Annual Cost ($)")
        ax.set_title("Co‑Opt Objective vs Battery Capex (PV Capex Sensitivity)")
        ax.legend(loc="best", fontsize=9)

        fig_path = os.path.join(out_dir, f"coopt_objective_vs_capex_by_pv_{county}.png")
        fig.savefig(fig_path, dpi=150)
        plt.close(fig)
    except Exception as e:
        raise RuntimeError(f"Failed to write PV capex objective sweep plot: {e}")


def _write_batt_cost_heatmap(
    out_dir: str,
    county: str,
    inputs: CooptInputs,
    *,
    allow_grid_charging: bool,
    allow_batt_export: bool,
    batt_capex_values: List[float],
    batt_size_values: List[float],
    pv_capex_per_kw: float,
    batt_capex_per_kw: float,
    pv_life_yrs: int,
    batt_life_yrs: int,
    discount_rate: float,
    batt_degrade_cost_per_kwh: float,
    marker_batt_kwh: Optional[float] = None,
    marker_capex_kwh: Optional[float] = None,
    weights: Optional[List[float]] = None,
    cycle_monthly: bool = False,
    file_tag: Optional[str] = None,
) -> None:
    records = []
    for capex_kwh in batt_capex_values:
        for batt_kwh in batt_size_values:
            result = _solve_lp(
                inputs,
                fixed_batt_kwh=batt_kwh,
                allow_grid_charging=allow_grid_charging,
                allow_batt_export=allow_batt_export,
                c_pv_kw=pv_capex_per_kw,
                c_batt_kwh=capex_kwh,
                c_batt_kw=batt_capex_per_kw,
                pv_life_yrs=pv_life_yrs,
                batt_life_yrs=batt_life_yrs,
                discount_rate=discount_rate,
                c_deg_per_kwh=batt_degrade_cost_per_kwh,
                weights=weights,
                cycle_monthly=cycle_monthly,
            )
            records.append(
                {
                    "battery_capex_kwh": float(capex_kwh),
                    "battery_kwh": float(batt_kwh),
                    "pv_kw": result.pv_kw,
                    "batt_kw": result.batt_kw,
                    "total_cost": result.total_cost,
                }
            )

    if not records:
        return
    df = pd.DataFrame(records)
    tag = f"_{file_tag}" if file_tag else ""
    csv_path = os.path.join(out_dir, f"coopt_batt_cost_heatmap_{county}{tag}.csv")
    df.to_csv(csv_path, index=False)

    try:
        _plot_batt_cost_heatmap_from_df(
            df,
            out_dir,
            county,
            tag=tag,
            marker_batt_kwh=marker_batt_kwh,
            marker_capex_kwh=marker_capex_kwh,
        )
    except Exception as e:
        raise RuntimeError(f"Failed to write battery cost heatmap plot: {e}")


def _plot_batt_cost_heatmap_from_df(
    df: pd.DataFrame,
    out_dir: str,
    county: str,
    *,
    tag: str,
    vmin: Optional[float] = None,
    vmax: Optional[float] = None,
    marker_batt_kwh: Optional[float] = None,
    marker_capex_kwh: Optional[float] = None,
) -> None:
    import matplotlib.pyplot as plt
    import numpy as np

    pivot = df.pivot(index="battery_kwh", columns="battery_capex_kwh", values="total_cost")
    vals = pivot.values
    fig, ax = plt.subplots(figsize=(9, 6), tight_layout=True)
    im = ax.imshow(vals, origin="lower", aspect="auto", cmap="viridis", vmin=vmin, vmax=vmax)
    ax.set_xticks(range(len(pivot.columns)))
    ax.set_yticks(range(len(pivot.index)))
    capex_vals = pivot.columns.tolist()
    size_vals = pivot.index.tolist()
    ax.set_xticklabels([f"{c:.0f}" for c in capex_vals])
    ax.set_yticklabels([f"{r:.1f}" for r in size_vals])
    ax.set_xlabel("Battery Capex ($/kWh)")
    ax.set_ylabel("Battery Size (kWh)")
    ax.set_title("Co‑opt Total Cost Heatmap")
    cbar = fig.colorbar(im, ax=ax)
    cbar.set_label("Annual Cost ($)")

    if marker_batt_kwh is not None and marker_capex_kwh is not None and capex_vals and size_vals:
        try:
            capex_arr = np.array(capex_vals, dtype=float)
            size_arr = np.array(size_vals, dtype=float)
            x_idx = int(np.argmin(np.abs(capex_arr - float(marker_capex_kwh))))
            y_idx = int(np.argmin(np.abs(size_arr - float(marker_batt_kwh))))
            ax.scatter([x_idx], [y_idx], color="#e41a1c", s=70, marker="x", label="Current")
            ax.legend(loc="upper right")
        except Exception:
            pass
    fig_path = os.path.join(out_dir, f"coopt_batt_cost_heatmap_{county}{tag}.png")
    fig.savefig(fig_path, dpi=150)
    plt.close(fig)


def _rescale_batt_cost_heatmaps_by_pv(
    out_dir: str,
    county: str,
    pv_capex_values: List[float],
) -> None:
    if not pv_capex_values:
        return
    csvs: List[tuple[str, pd.DataFrame]] = []
    for pv_capex in sorted(set(float(v) for v in pv_capex_values)):
        tag = _format_pv_capex_tag(pv_capex)
        csv_path = os.path.join(out_dir, f"coopt_batt_cost_heatmap_{county}_{tag}.csv")
        if not os.path.exists(csv_path):
            raise RuntimeError(f"Missing PV capex heatmap CSV: {csv_path}")
        df = pd.read_csv(csv_path)
        required = {"battery_kwh", "battery_capex_kwh", "total_cost"}
        if not required.issubset(set(df.columns)):
            raise RuntimeError(f"Missing columns in PV capex heatmap CSV: {csv_path}")
        csvs.append((f"_{tag}", df))
    if not csvs:
        return
    vmin = min(float(df["total_cost"].min()) for _, df in csvs)
    vmax = max(float(df["total_cost"].max()) for _, df in csvs)
    for tag, df in csvs:
        _plot_batt_cost_heatmap_from_df(
            df,
            out_dir,
            county,
            tag=tag,
            vmin=vmin,
            vmax=vmax,
        )


def _write_pv_batt_cost_heatmap(
    out_dir: str,
    county: str,
    inputs: CooptInputs,
    *,
    allow_grid_charging: bool,
    allow_batt_export: bool,
    pv_size_values: List[float],
    batt_size_values: List[float],
    pv_capex_per_kw: float,
    batt_capex_per_kwh: float,
    batt_capex_per_kw: float,
    pv_life_yrs: int,
    batt_life_yrs: int,
    discount_rate: float,
    batt_degrade_cost_per_kwh: float,
    marker_pv_kw: Optional[float] = None,
    marker_batt_kwh: Optional[float] = None,
    weights: Optional[List[float]] = None,
    cycle_monthly: bool = False,
    file_tag: Optional[str] = None,
) -> None:
    records = []
    for pv_kw in pv_size_values:
        for batt_kwh in batt_size_values:
            result = _solve_lp(
                inputs,
                fixed_pv_kw=pv_kw,
                fixed_batt_kwh=batt_kwh,
                allow_grid_charging=allow_grid_charging,
                allow_batt_export=allow_batt_export,
                c_pv_kw=pv_capex_per_kw,
                c_batt_kwh=batt_capex_per_kwh,
                c_batt_kw=batt_capex_per_kw,
                pv_life_yrs=pv_life_yrs,
                batt_life_yrs=batt_life_yrs,
                discount_rate=discount_rate,
                c_deg_per_kwh=batt_degrade_cost_per_kwh,
                weights=weights,
                cycle_monthly=cycle_monthly,
            )
            records.append(
                {
                    "pv_kw": float(pv_kw),
                    "battery_kwh": float(batt_kwh),
                    "batt_kw": result.batt_kw,
                    "total_cost": result.total_cost,
                }
            )

    if not records:
        return
    df = pd.DataFrame(records)
    tag = f"_{file_tag}" if file_tag else ""
    csv_path = os.path.join(out_dir, f"coopt_pv_batt_cost_heatmap_{county}{tag}.csv")
    df.to_csv(csv_path, index=False)

    try:
        _plot_pv_batt_cost_heatmap_from_df(
            df,
            out_dir,
            county,
            tag=tag,
            marker_pv_kw=marker_pv_kw,
            marker_batt_kwh=marker_batt_kwh,
        )
    except Exception as e:
        raise RuntimeError(f"Failed to write PV vs battery cost heatmap plot: {e}")


def _plot_pv_batt_cost_heatmap_from_df(
    df: pd.DataFrame,
    out_dir: str,
    county: str,
    *,
    tag: str,
    vmin: Optional[float] = None,
    vmax: Optional[float] = None,
    marker_pv_kw: Optional[float] = None,
    marker_batt_kwh: Optional[float] = None,
) -> None:
    import matplotlib.pyplot as plt
    import numpy as np

    pivot = df.pivot(index="battery_kwh", columns="pv_kw", values="total_cost")
    vals = pivot.values
    fig, ax = plt.subplots(figsize=(9, 6), tight_layout=True)
    im = ax.imshow(vals, origin="lower", aspect="auto", cmap="viridis", vmin=vmin, vmax=vmax)
    pv_vals = pivot.columns.tolist()
    batt_vals = pivot.index.tolist()
    ax.set_xticks(range(len(pv_vals)))
    ax.set_yticks(range(len(batt_vals)))
    ax.set_xticklabels([f"{c:.2f}" for c in pv_vals])
    ax.set_yticklabels([f"{r:.1f}" for r in batt_vals])
    ax.set_xlabel("PV Size (kW)")
    ax.set_ylabel("Battery Size (kWh)")
    ax.set_title("Co‑opt Total Cost Heatmap (PV × Battery)")
    cbar = fig.colorbar(im, ax=ax)
    cbar.set_label("Annual Cost ($)")

    if marker_pv_kw is not None and marker_batt_kwh is not None and pv_vals and batt_vals:
        try:
            pv_arr = np.array(pv_vals, dtype=float)
            batt_arr = np.array(batt_vals, dtype=float)
            x_idx = int(np.argmin(np.abs(pv_arr - float(marker_pv_kw))))
            y_idx = int(np.argmin(np.abs(batt_arr - float(marker_batt_kwh))))
            ax.scatter([x_idx], [y_idx], color="#e41a1c", s=70, marker="x", label="Current")
            ax.legend(loc="upper right")
        except Exception:
            pass

    fig_path = os.path.join(out_dir, f"coopt_pv_batt_cost_heatmap_{county}{tag}.png")
    fig.savefig(fig_path, dpi=150)
    plt.close(fig)


def _rescale_pv_batt_cost_heatmaps_by_pv(
    out_dir: str,
    county: str,
    pv_capex_values: List[float],
) -> None:
    if not pv_capex_values:
        return
    csvs: List[tuple[str, pd.DataFrame]] = []
    for pv_capex in sorted(set(float(v) for v in pv_capex_values)):
        tag = _format_pv_capex_tag(pv_capex)
        csv_path = os.path.join(out_dir, f"coopt_pv_batt_cost_heatmap_{county}_{tag}.csv")
        if not os.path.exists(csv_path):
            raise RuntimeError(f"Missing PV capex PV×battery heatmap CSV: {csv_path}")
        df = pd.read_csv(csv_path)
        required = {"pv_kw", "battery_kwh", "total_cost"}
        if not required.issubset(set(df.columns)):
            raise RuntimeError(f"Missing columns in PV capex PV×battery heatmap CSV: {csv_path}")
        csvs.append((f"_{tag}", df))
    if not csvs:
        return
    vmin = min(float(df["total_cost"].min()) for _, df in csvs)
    vmax = max(float(df["total_cost"].max()) for _, df in csvs)
    for tag, df in csvs:
        _plot_pv_batt_cost_heatmap_from_df(
            df,
            out_dir,
            county,
            tag=tag,
            vmin=vmin,
            vmax=vmax,
        )


def _default_plan_for_utility(util: str) -> str:
    plans = list(RATE_PLANS.get(util, {}).keys())
    if not plans:
        return ""
    return plans[0]


def process(
    base_input_dir: str,
    base_output_dir: str,
    scenario: str,
    housing_type: str,
    counties: Optional[List[str]] = None,
    *,
    plan_override: Optional[str] = None,
    allow_grid_charging: bool = False,
    allow_batt_export: bool = True,
    debug_prices: bool = False,
    batt_capex_sweep: Optional[List[float]] = None,
    batt_size_sweep: Optional[List[float]] = None,
    pv_size_sweep: Optional[List[float]] = None,
    pv_capex_sweep: Optional[List[float]] = None,
    coarse_sweeps: bool = False,
    discount_rate: float = DEFAULT_DISCOUNT_RATE,
    pv_capex_per_kw: float = DEFAULT_PV_CAPEX_PER_KW,
    batt_capex_per_kwh: float = DEFAULT_BATT_CAPEX_PER_KWH,
    batt_capex_per_kw: float = 0.0,
    pv_life_yrs: int = 25,
    batt_life_yrs: int = 15,
    batt_degrade_cost_per_kwh: float = 0.0,
) -> None:
    scenario_path = get_scenario_path(base_input_dir, scenario, housing_type)
    counties_to_run = get_counties(scenario_path, counties)
    capacity_records = []

    for county in counties_to_run:
        county_slug = slugify_county_name(county)
        out_dir = os.path.join(base_output_dir, scenario, housing_type, county_slug)
        os.makedirs(out_dir, exist_ok=True)

        # Weather + load (aligned to 8760)
        weather_file = os.path.join(base_input_dir, scenario, housing_type, county_slug, f"weather_TMY_{county_slug}.csv")
        load_file = os.path.join(scenario_path, county_slug, f"combined_profiles_{scenario}_{county_slug}.csv")
        if not (os.path.exists(weather_file) and os.path.exists(load_file)):
            print(f"[step9b] Missing inputs for {county_slug}; skipping.")
            continue

        weather_df, load_kwh = prepare_weather_and_load(weather_file, load_file, "electricity.real_and_simulated.for_typical_county_home.kwh")
        if len(load_kwh) != 8760:
            print(f"[step9b] Non‑8760 load for {county_slug}; length={len(load_kwh)} — skipping.")
            continue
        # PV per‑kW AC energy
        G = pv_timeseries_ac_kwh(weather_df, 1.0)
        if len(G) != 8760:
            print(f"[step9b] Non‑8760 weather for {county_slug}; length={len(G)} — skipping.")
            continue

        # Utility + rates
        util = get_utility_for_county(county_slug)
        if not util:
            print(f"[step9b] No utility for county {county_slug}; skipping.")
            continue
        plan_name = plan_override or _default_plan_for_utility(util)
        plan_details = RATE_PLANS.get(util, {}).get(plan_name)
        if not plan_details:
            print(f"[step9b] No plan details found for utility={util}, plan={plan_name}; skipping.")
            continue

        # NEM3 export table month×hour
        export_table = get_export_rate_table_for_county(base_dir=os.path.join("data", "NEM3"), utility=util, county_name_or_slug=county_slug)

        # Prices per hour
        ts_index = _timestamp_index_8760(2018)
        p_imp = [_hourly_import_rate(plan_details, ts) for ts in ts_index]
        p_exp = [float(export_table[ts.month][ts.hour]) for ts in ts_index]

        if debug_prices:
            _write_price_diagnostics(out_dir, county_slug, ts_index, p_imp, p_exp)

        # Solve LP
        inputs = CooptInputs(
            load_kwh=load_kwh,
            pv_gen_per_kw=G,
            import_rates=p_imp,
            export_rates=p_exp,
        )
        result = _solve_lp(
            inputs,
            allow_grid_charging=allow_grid_charging,
            allow_batt_export=allow_batt_export,
            c_pv_kw=pv_capex_per_kw,
            c_batt_kwh=batt_capex_per_kwh,
            c_batt_kw=batt_capex_per_kw,
            pv_life_yrs=pv_life_yrs,
            batt_life_yrs=batt_life_yrs,
            discount_rate=discount_rate,
            c_deg_per_kwh=batt_degrade_cost_per_kwh,
        )

        sweep_inputs = inputs
        sweep_weights = None
        sweep_cycle = False
        if coarse_sweeps:
            try:
                sweep_inputs, sweep_weights = build_monthly_hourly_inputs(inputs, year=2018)
                sweep_cycle = True
            except Exception as e:
                print(f"[step9b] Coarse sweep aggregation failed for {county_slug}: {e}")
                sweep_inputs, sweep_weights, sweep_cycle = inputs, None, False

        # Write outputs (Step 9 compatibility)
        _write_step9_outputs(out_dir, county_slug, ts_index, load_kwh, G, result.pv_kw, result.flows)
        print(f"[step9b] {county_slug}: PV={result.pv_kw:.2f} kW, Battery={result.batt_kwh:.2f} kWh")

        if batt_capex_sweep:
            _write_batt_capex_sweep(
                out_dir,
                county_slug,
                sweep_inputs,
                allow_grid_charging=allow_grid_charging,
                allow_batt_export=allow_batt_export,
                batt_capex_values=batt_capex_sweep,
                pv_capex_per_kw=pv_capex_per_kw,
                batt_capex_per_kw=batt_capex_per_kw,
                pv_life_yrs=pv_life_yrs,
                batt_life_yrs=batt_life_yrs,
                discount_rate=discount_rate,
                batt_degrade_cost_per_kwh=batt_degrade_cost_per_kwh,
                weights=sweep_weights,
                cycle_monthly=sweep_cycle,
            )
            _write_batt_adoption_curve(
                out_dir,
                county_slug,
                base_pv_capex=pv_capex_per_kw,
                scenario=scenario,
                reference_lines=[
                    (1248.0, "Powerwall 3 (pre-incentive) ~$1,248/kWh", "#f28e2b"),
                    (874.0, "ITC only ~$874/kWh", "#f5a742"),
                    (724.0, "ITC + SGIP ~$724/kWh", "#f9bf64"),
                ],
            )

        if batt_capex_sweep and batt_size_sweep:
            _write_batt_cost_heatmap(
                out_dir,
                county_slug,
                sweep_inputs,
                allow_grid_charging=allow_grid_charging,
                allow_batt_export=allow_batt_export,
                batt_capex_values=batt_capex_sweep,
                batt_size_values=batt_size_sweep,
                pv_capex_per_kw=pv_capex_per_kw,
                batt_capex_per_kw=batt_capex_per_kw,
                pv_life_yrs=pv_life_yrs,
                batt_life_yrs=batt_life_yrs,
                discount_rate=discount_rate,
                batt_degrade_cost_per_kwh=batt_degrade_cost_per_kwh,
                marker_batt_kwh=result.batt_kwh,
                marker_capex_kwh=batt_capex_per_kwh,
                weights=sweep_weights,
                cycle_monthly=sweep_cycle,
            )

        if pv_size_sweep and batt_size_sweep:
            _write_pv_batt_cost_heatmap(
                out_dir,
                county_slug,
                sweep_inputs,
                allow_grid_charging=allow_grid_charging,
                allow_batt_export=allow_batt_export,
                pv_size_values=pv_size_sweep,
                batt_size_values=batt_size_sweep,
                pv_capex_per_kw=pv_capex_per_kw,
                batt_capex_per_kwh=batt_capex_per_kwh,
                batt_capex_per_kw=batt_capex_per_kw,
                pv_life_yrs=pv_life_yrs,
                batt_life_yrs=batt_life_yrs,
                discount_rate=discount_rate,
                batt_degrade_cost_per_kwh=batt_degrade_cost_per_kwh,
                marker_pv_kw=result.pv_kw,
                marker_batt_kwh=result.batt_kwh,
                weights=sweep_weights,
                cycle_monthly=sweep_cycle,
            )

        if pv_capex_sweep:
            for pv_capex in pv_capex_sweep:
                tag = _format_pv_capex_tag(pv_capex)
                sweep_result = _solve_lp(
                    sweep_inputs,
                    allow_grid_charging=allow_grid_charging,
                    allow_batt_export=allow_batt_export,
                    c_pv_kw=pv_capex,
                    c_batt_kwh=batt_capex_per_kwh,
                    c_batt_kw=batt_capex_per_kw,
                    pv_life_yrs=pv_life_yrs,
                    batt_life_yrs=batt_life_yrs,
                    discount_rate=discount_rate,
                    c_deg_per_kwh=batt_degrade_cost_per_kwh,
                    weights=sweep_weights,
                    cycle_monthly=sweep_cycle,
                )

                if batt_capex_sweep:
                    _write_batt_capex_sweep(
                        out_dir,
                        county_slug,
                        sweep_inputs,
                        allow_grid_charging=allow_grid_charging,
                        allow_batt_export=allow_batt_export,
                        batt_capex_values=batt_capex_sweep,
                        pv_capex_per_kw=pv_capex,
                        batt_capex_per_kw=batt_capex_per_kw,
                        pv_life_yrs=pv_life_yrs,
                        batt_life_yrs=batt_life_yrs,
                        discount_rate=discount_rate,
                        batt_degrade_cost_per_kwh=batt_degrade_cost_per_kwh,
                        file_tag=tag,
                        weights=sweep_weights,
                        cycle_monthly=sweep_cycle,
                    )
                if batt_capex_sweep and batt_size_sweep:
                    _write_batt_cost_heatmap(
                        out_dir,
                        county_slug,
                        sweep_inputs,
                        allow_grid_charging=allow_grid_charging,
                        allow_batt_export=allow_batt_export,
                        batt_capex_values=batt_capex_sweep,
                        batt_size_values=batt_size_sweep,
                        pv_capex_per_kw=pv_capex,
                        batt_capex_per_kw=batt_capex_per_kw,
                        pv_life_yrs=pv_life_yrs,
                        batt_life_yrs=batt_life_yrs,
                        discount_rate=discount_rate,
                        batt_degrade_cost_per_kwh=batt_degrade_cost_per_kwh,
                        marker_batt_kwh=sweep_result.batt_kwh,
                        marker_capex_kwh=batt_capex_per_kwh,
                        file_tag=tag,
                        weights=sweep_weights,
                        cycle_monthly=sweep_cycle,
                    )
                if pv_size_sweep and batt_size_sweep:
                    _write_pv_batt_cost_heatmap(
                        out_dir,
                        county_slug,
                        sweep_inputs,
                        allow_grid_charging=allow_grid_charging,
                        allow_batt_export=allow_batt_export,
                        pv_size_values=pv_size_sweep,
                        batt_size_values=batt_size_sweep,
                        pv_capex_per_kw=pv_capex,
                        batt_capex_per_kwh=batt_capex_per_kwh,
                        batt_capex_per_kw=batt_capex_per_kw,
                        pv_life_yrs=pv_life_yrs,
                        batt_life_yrs=batt_life_yrs,
                        discount_rate=discount_rate,
                        batt_degrade_cost_per_kwh=batt_degrade_cost_per_kwh,
                        marker_pv_kw=sweep_result.pv_kw,
                        marker_batt_kwh=sweep_result.batt_kwh,
                        file_tag=tag,
                        weights=sweep_weights,
                        cycle_monthly=sweep_cycle,
                    )

        if pv_capex_sweep and batt_capex_sweep:
            _write_batt_size_vs_capex_by_pv(
                out_dir,
                county_slug,
                pv_capex_values=pv_capex_sweep,
                batt_capex_values=batt_capex_sweep,
                base_pv_capex=pv_capex_per_kw,
            )
            _write_pv_size_vs_capex_by_pv(
                out_dir,
                county_slug,
                pv_capex_values=pv_capex_sweep,
                batt_capex_values=batt_capex_sweep,
                base_pv_capex=pv_capex_per_kw,
            )
            _write_objective_vs_capex_by_pv(
                out_dir,
                county_slug,
                pv_capex_values=pv_capex_sweep,
                batt_capex_values=batt_capex_sweep,
                base_pv_capex=pv_capex_per_kw,
            )
            if batt_size_sweep:
                _rescale_batt_cost_heatmaps_by_pv(
                    out_dir,
                    county_slug,
                    pv_capex_values=pv_capex_sweep,
                )
            if pv_size_sweep and batt_size_sweep:
                _rescale_pv_batt_cost_heatmaps_by_pv(
                    out_dir,
                    county_slug,
                    pv_capex_values=pv_capex_sweep,
                )

        # Collect capacity summary for diagnostics cards
        capacity_records.append({
            "County": county_slug,
            "Solar Capacity (kW)": round(result.pv_kw, 2),
            "Battery Capacity (kWh)": round(result.batt_kwh, 2),
            "Battery Power Capacity (kW)": round(result.batt_kw, 2),
            "Coopt Total Cost": round(result.total_cost, 4),
            "Coopt Capex Annual": round(result.capex_annual, 4),
            "Coopt Import Cost": round(result.import_cost, 4),
            "Coopt Export Credit": round(result.export_credit, 4),
            "Coopt Degradation Cost": round(result.degradation_cost, 4),
            "Allow Grid Charging": bool(allow_grid_charging),
            "Allow Battery Export": bool(allow_batt_export),
        })

    # Write/merge capacity summary CSV for the scenario (compatible path with Step 9 diagnostics)
    try:
        if capacity_records:
            cap_dir = os.path.join(base_output_dir, scenario, housing_type, "CAPITAL_COSTS")
            os.makedirs(cap_dir, exist_ok=True)
            cap_path = os.path.join(cap_dir, "electrified_assets.csv")
            new_df = pd.DataFrame(capacity_records)
            if os.path.exists(cap_path):
                try:
                    old_df = pd.read_csv(cap_path)
                except Exception:
                    old_df = pd.DataFrame()
                # Merge on County (slug)
                if not old_df.empty:
                    # Drop overlapping counties in old, then append new
                    keep = [
                        r for _, r in old_df.iterrows()
                        if str(r.get("County", "")).strip().lower() not in set(new_df["County"].astype(str).str.lower())
                    ]
                    if keep:
                        old_kept = pd.DataFrame(keep)
                        merged = pd.concat([old_kept, new_df], ignore_index=True)
                    else:
                        merged = new_df
                else:
                    merged = new_df
                merged.to_csv(cap_path, index=False)
            else:
                new_df.to_csv(cap_path, index=False)
    except Exception as e:
        print(f"[step9b] Warning: could not write/merge capacity summary CSV: {e}")


def main():
    p = argparse.ArgumentParser(description="Step 9b: Co‑optimize PV/Battery sizing and hourly dispatch")
    p.add_argument("--base-input-dir", default="data/loadprofiles")
    p.add_argument("--base-output-dir", default="data/loadprofiles")
    p.add_argument("--scenario", required=True)
    p.add_argument("--counties", nargs="*")
    p.add_argument("--use-defaults", action="store_true",
                   help="Use built-in sweep values (DEFAULT_BATT_CAPEX_SWEEP, "
                        "DEFAULT_BATT_SIZE_SWEEP, DEFAULT_PV_SIZE_SWEEP)")
    p.add_argument("--coarse-sweeps", action="store_true",
                   help="Use 12×24 monthly-hourly averages for sweep plots (faster)")
    p.add_argument("--discount-rate", type=float, default=DEFAULT_DISCOUNT_RATE)
    p.add_argument("--pv-capex-kw", type=float, default=DEFAULT_PV_CAPEX_PER_KW)
    p.add_argument("--batt-capex-kwh", type=float, default=DEFAULT_BATT_CAPEX_PER_KWH)
    args = p.parse_args()

    sweep_vals = list(DEFAULT_BATT_CAPEX_SWEEP) if args.use_defaults else None
    size_vals  = list(DEFAULT_BATT_SIZE_SWEEP)  if args.use_defaults else None
    pv_vals    = list(DEFAULT_PV_SIZE_SWEEP)    if args.use_defaults else None

    process(
        base_input_dir=args.base_input_dir,
        base_output_dir=args.base_output_dir,
        scenario=args.scenario,
        housing_type="single-family-detached",
        counties=args.counties,
        plan_override=None,
        allow_grid_charging=False,
        allow_batt_export=True,
        debug_prices=False,
        batt_capex_sweep=sweep_vals,
        batt_size_sweep=size_vals,
        pv_size_sweep=pv_vals,
        pv_capex_sweep=None,
        coarse_sweeps=args.coarse_sweeps,
        discount_rate=args.discount_rate,
        pv_capex_per_kw=args.pv_capex_kw,
        batt_capex_per_kwh=args.batt_capex_kwh,
        batt_capex_per_kw=0.0,
        pv_life_yrs=25,
        batt_life_yrs=15,
        batt_degrade_cost_per_kwh=0.0,
    )


if __name__ == "__main__":
    main()
