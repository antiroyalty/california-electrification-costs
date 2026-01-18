"""
Step 9 (DIY): PV + dynamic battery dispatch without PySAM

Computes PV AC generation directly from the weather CSV (simple PVWatts‑style)
and applies a single dispatch strategy: dynamic PV‑only charging with an evening
discharge window. Grid charging is never used.

PV model (simplified PVWatts‑style):
- AC_kW[h] = system_capacity_kW * (GHI[h] / 1000) * PR_base * temp_derate[h]
- temp_derate[h] = 1 + gamma_pdc * (Tcell[h] − 25°C)
- Tcell[h] ≈ Tamb[h] + ((NOCT − 20) / 800) * GHI[h]
  where NOCT = 46°C, PR_base = 0.85, gamma_pdc = −0.00280 / °C
- Clip at zero; no inverter clipping modeled (kept simple to match DIY intent).

Battery dispatch (dynamic only):
- Capacity 13.5 kWh, round‑trip eff 96% as symmetric sqrt(RTE), 3 kW charge/discharge
- Min SOC 20%, max SOC 90%
- PV‑only charging; at 16:00 if PV<load, discharge until min SOC or first hour PV≥load next day.

Outputs (columns used downstream by step10):
- "Load Profile", "System to Load", "Battery to Load", "Grid to Load",
  "Solar + Battery to Load", "Total Supply", "Difference",
  "System to Battery", "Grid to Battery", "Battery SOC"

Files:
- Reads weather: data/loadprofiles/<scenario>/<housing_type>/<county>/weather_TMY_<county>.csv
- Reads load:   data/loadprofiles/<scenario>/<housing_type>/<county>/combined_profiles_<scenario>_<county}.csv
- Writes:       data/loadprofiles/<scenario>/<housing_type>/<county>/solar_storage_dispatch_profiles_<county>.csv
                data/loadprofiles/<scenario>/<housing_type>/<county>/solar_storage_dispatch_profiles_with_exports_<county>.csv

"""

from __future__ import annotations

import os
from typing import List, Optional, Tuple

import pandas as pd

from helpers.main_helpers import (
    get_counties,
    get_scenario_path,
    log,
    format_load_profile,
    to_decimal_number,
    slugify_county_name,
    git_short_sha,
)
from helpers import log_profiles
from helpers.step9_plotting_helper import plot_first_weeks
from .step9_solar_storage_dispatch_core import (
    PR_BASE,
    NOCT_C,
    GAMMA_PDC,
    WEATHER_SHIFT_HOURS,
    BATTERY_CAPACITY_KWH,
    prepare_weather_and_load,
    compute_system_capacity_kW,
    pv_timeseries_ac_kwh,
    battery_dispatch_dynamic,
    temp_battery_capacity_kwh,
)
from helpers.step9_exports import (
    compute_excess_solar_exports,
    prepare_export_enabled_outputs,
)


# I/O constants
LOADPROFILE_FILE_PREFIX = "combined_profiles"
TOTAL_LOAD_COLUMN_NAME = "electricity.real_and_simulated.for_typical_county_home.kwh"
OUTPUT_LOADPROFILE_FILE_PREFIX = "solar_storage_dispatch_profiles"
# New: export-enabled companion file prefix (will not overwrite the non-export file)
OUTPUT_EXPORT_LOADPROFILE_FILE_PREFIX = "solar_storage_dispatch_profiles_with_exports"
SOLAR_STORAGE_CAPACITY_PREFIX = "electrified_assets"
CAPITAL_COSTS_FOLDER_NAME = "CAPITAL_COSTS"

# Shared run identifiers for repeatable, versioned outputs

GIT_SHORT_SHA = git_short_sha()


## Constants moved to step9_solar_storage_dispatch_core

# Sizing fraction relative to the "annual-energy match" anchor (1.0 = match).
# Pipeline default: 0.5 (50% of annual-load match). Change this constant to adjust.
PV_SIZE_FRACTION = 1

# Optional: use EAC sweep (PV×Battery) "best" sizes per scenario/county.
# Deterministic behavior: when enabled, Step 9 reads only the dynamic‑dispatch
# integrated dashboard CSV to size PV and battery; if missing, the county run
# fails (no fallback to other sources or default sizing).
USE_EAC_OPTIMAL_SIZING = False

# Deterministic source root for min‑EAC results (integrated dashboard)
# Dynamic dispatch is the only mode supported here.
DISPATCH_LABEL = "dispatch_dynamic"
EAC_DYNAMIC_RESULTS_ROOT = os.path.join(
    "data", "experiments", "integrated_dashboard", DISPATCH_LABEL, "combined"
)


## Weather/load helpers moved to step9_solar_storage_dispatch_core


def _find_eac_min_sizes(
    scenario: str,
    housing_type: str,
    county_dir_name: str,
) -> Optional[Tuple[float, float]]:
    """Return (solar_kw, battery_kwh) at min EAC from dynamic‑dispatch integrated CSV.

    Deterministic: uses only EAC_DYNAMIC_RESULTS_ROOT. Raises if missing.
    """
    slug = slugify_county_name(county_dir_name)
    csv_path = os.path.join(
        EAC_DYNAMIC_RESULTS_ROOT,
        scenario,
        housing_type,
        slug,
        f"combined_sweep_{slug}.csv",
    )
    if not os.path.exists(csv_path):
        raise FileNotFoundError(
            f"EAC sweep CSV not found (dynamic dispatch): {csv_path}. "
            f"Run the integrated combined sweep first."
        )
    df = pd.read_csv(csv_path)
    if df.empty:
        raise ValueError(f"EAC sweep CSV is empty: {csv_path}")
    if 'eac_total' not in df.columns:
        comp_cols = [
            'capex_pv_annual', 'capex_storage_annual', 'capex_electric',
            'capex_gas', 'vehicle_om', 'annual_bill_with_solar'
        ]
        for c in comp_cols:
            if c not in df.columns:
                df[c] = 0.0
        eac = (
            pd.to_numeric(df['capex_pv_annual'], errors='coerce').fillna(0)
            + pd.to_numeric(df['capex_storage_annual'], errors='coerce').fillna(0)
            + pd.to_numeric(df['capex_electric'], errors='coerce').fillna(0)
            + pd.to_numeric(df['capex_gas'], errors='coerce').fillna(0)
            + pd.to_numeric(df['vehicle_om'], errors='coerce').fillna(0)
            + pd.to_numeric(df['annual_bill_with_solar'], errors='coerce').fillna(0)
        )
        df['eac_total'] = pd.to_numeric(eac, errors='coerce').fillna(0)
    row = df.loc[df['eac_total'].idxmin()]
    solar_kw = float(row.get('solar_kw', float('nan')))
    batt_kwh = float(row.get('battery_kwh', float('nan')))
    if pd.isna(solar_kw) or pd.isna(batt_kwh):
        raise ValueError(
            f"EAC CSV missing required columns (solar_kw, battery_kwh): {csv_path}"
        )
    return (float(solar_kw), float(batt_kwh))


## PV sizing moved to step9_solar_storage_dispatch_core


## PV model moved to step9_solar_storage_dispatch_core


# --- Battery dispatch implementations ---

## Dynamic dispatch moved to step9_solar_storage_dispatch_core


def _validate_lengths(*series_lists: List[List[float]]) -> None:
    for s in series_lists:
        for arr in s:
            if len(arr) != 8760:
                raise ValueError("All output series must be 8760 elements long.")


# Export helpers now live in step9_exports


def process(
    base_input_dir: str,
    base_output_dir: str,
    scenario: str,
    housing_type: str,
    counties: Optional[List[str]] = None,
    years_of_analysis: int = 1,
    force_recompute: bool = False,
):
    scenario_path = get_scenario_path(base_input_dir, scenario, housing_type)
    counties_to_run = get_counties(scenario_path, counties)
    capacity_dict = {}

    for county in counties_to_run:
        try:
            log(county=county)
            weather_file = os.path.join(base_input_dir, scenario, housing_type, county, f"weather_TMY_{county}.csv")
            load_file = os.path.join(scenario_path, county, f"{LOADPROFILE_FILE_PREFIX}_{scenario}_{county}.csv")
            output_file = os.path.join(base_output_dir, scenario, housing_type, county, f"{OUTPUT_LOADPROFILE_FILE_PREFIX}_{county}.csv")

            if not os.path.exists(weather_file):
                print(f"Weather file not found: {weather_file}. Skipping...")
                continue
            if not os.path.exists(load_file):
                print(f"Load file not found: {load_file}. Skipping...")
                continue
            if not force_recompute and os.path.exists(output_file):
                print(f"Output exists: {output_file}. Skipping (force_recompute=True to rebuild)")
                continue

            # Weather + load
            weather_df, load_profile = prepare_weather_and_load(weather_file, load_file, TOTAL_LOAD_COLUMN_NAME)
            # Decide sizing approach
            base_capacity_kw = compute_system_capacity_kW(weather_df, load_profile)
            system_capacity_kW = base_capacity_kw * PV_SIZE_FRACTION
            selected_batt_kwh: Optional[float] = None
            if USE_EAC_OPTIMAL_SIZING:
                opt_solar_kw, opt_batt_kwh = _find_eac_min_sizes(scenario, housing_type, county)
                system_capacity_kW = float(opt_solar_kw)
                selected_batt_kwh = float(opt_batt_kwh)
                log(eac_optimal_sizing_applied=True, solar_kw=system_capacity_kW, battery_kwh=selected_batt_kwh)

            # Record the sizing that will be used for this county
            used_batt_kwh = float(selected_batt_kwh) if selected_batt_kwh is not None else float(BATTERY_CAPACITY_KWH)
            log(at="step9_sizing", county=county, solar_capacity_kw_used=system_capacity_kW, battery_capacity_kwh_used=used_batt_kwh)

            # Compute PV hourly AC (kWh)
            solar_gen = pv_timeseries_ac_kwh(weather_df, system_capacity_kW)

            # Battery dispatch (dynamic only; PV-only charging, evening discharge)
            if selected_batt_kwh is not None:
                with temp_battery_capacity_kwh(selected_batt_kwh):
                    grid_demand, batt_charge, batt_discharge, grid_to_load, grid_to_batt, pv_to_batt, soc_percent = battery_dispatch_dynamic(
                        load_profile, solar_gen
                    )
            else:
                grid_demand, batt_charge, batt_discharge, grid_to_load, grid_to_batt, pv_to_batt, soc_percent = battery_dispatch_dynamic(
                    load_profile, solar_gen
                )
            _validate_lengths([solar_gen, grid_demand, batt_charge, batt_discharge, grid_to_load, grid_to_batt, pv_to_batt, soc_percent])

            # Human-readable summaries for verification
            log_profiles(
                {
                    "Household Load (kWh)": load_profile,
                    "Solar Generation (kWh)": solar_gen,
                    "Battery Charge (kWh)": batt_charge,
                    "Battery Discharge (kWh)": batt_discharge,
                    "Grid to Household Load (kWh)": grid_to_load,
                    "Grid to Battery (kWh)": grid_to_batt,
                    "Grid Demand (kWh)": grid_demand,
                },
                title=f"DIY Dispatch Profiles — {county}",
            )

            # Detailed diagnostics comparable to PySAM step
            try:
                total_load = float(sum(load_profile))
                total_pv_gen = float(sum(solar_gen))
                system_to_load = [min(s, l) for s, l in zip(solar_gen, load_profile)]
                pv_to_load_sum = float(sum(system_to_load))
                pv_to_batt_sum = float(sum(pv_to_batt))
                pv_to_grid_implied = max(0.0, total_pv_gen - (pv_to_load_sum + pv_to_batt_sum))
                batt_to_load_sum = float(sum(batt_discharge))
                grid_to_load_sum = float(sum(grid_to_load))
                grid_to_batt_sum = float(sum(grid_to_batt))
                soc_min = min(soc_percent) if soc_percent else 0.0
                soc_max = max(soc_percent) if soc_percent else 0.0
                soc_end = soc_percent[-1] if soc_percent else 0.0
                mean_ghi = float(weather_df['ghi'].mean())
                sum_ghi_kwhm2 = float(weather_df['ghi'].sum()) / 1000.0
                jan_len = 31 * 24
                jan_idx = int(pd.Series(solar_gen[:jan_len]).idxmax()) if total_pv_gen > 0 else -1
                jan_hod = jan_idx % 24 if jan_idx >= 0 else -1
                print("\n[DIY PV Diagnostics]", county)
                print(f"  WEATHER_SHIFT_HOURS       = {WEATHER_SHIFT_HOURS}")
                print(f"  PR_BASE / NOCT / gamma    = {PR_BASE} / {NOCT_C}C / {GAMMA_PDC}/C")
                print(f"  mean_GHI_Wm2              = {mean_ghi:.1f}")
                print(f"  sum_GHI_kWh_per_m2        = {sum_ghi_kwhm2:.1f}")
                print(f"  system_capacity_kW        = {system_capacity_kW:.3f}")
                print(f"  battery_capacity_kWh      = {used_batt_kwh:.2f}")
                print(f"  total_pv_gen_kWh          = {total_pv_gen:.1f}")
                print(f"  pv_to_load_kWh            = {pv_to_load_sum:.1f}")
                print(f"  pv_to_batt_kWh            = {pv_to_batt_sum:.1f}")
                print(f"  pv_to_grid_kWh(derived)   = {pv_to_grid_implied:.1f}")
                print(f"  batt_to_load_kWh          = {batt_to_load_sum:.1f}")
                print(f"  grid_to_load_kWh          = {grid_to_load_sum:.1f}")
                print(f"  grid_to_batt_kWh          = {grid_to_batt_sum:.1f}")
                print(f"  total_load_kWh            = {total_load:.1f}")
                print(f"  batt_SOC[%] min/max/end   = {soc_min:.1f}/{soc_max:.1f}/{soc_end:.1f}")
                print(f"  Jan peak hour-of-day      = {jan_hod}")
            except Exception:
                pass

            # Save per-county outputs in the standard schema used by step10
            os.makedirs(os.path.dirname(output_file), exist_ok=True)
            date_range = pd.date_range(start="2018-01-01", periods=8760, freq="H")
            system_to_load = [min(s, l) for s, l in zip(solar_gen, load_profile)]
            batt_to_load = batt_discharge
            # Derive PV→Grid from PV AC and on-site PV uses (PV→Load, PV→Battery).
            # Keep non-negative and consistent with energy balance.
            pv_to_grid = [
                max(0.0, float(s) - float(a) - float(b))
                for s, a, b in zip(solar_gen, system_to_load, pv_to_batt)
            ]

            df = pd.DataFrame({
                "Load Profile": load_profile,
                "System to Load": system_to_load,
                "Battery to Load": batt_to_load,
                "Grid to Load": grid_to_load,
                "System to Grid": pv_to_grid,
                "Solar + Battery to Load": [a + b for a, b in zip(system_to_load, batt_to_load)],
                "Total Supply": [a + b + c for a, b, c in zip(system_to_load, batt_to_load, grid_to_load)],
                "Difference": [l - (a + b + c) for l, a, b, c in zip(load_profile, system_to_load, batt_to_load, grid_to_load)],
                "System to Battery": pv_to_batt,
                "Grid to Battery": grid_to_batt,
                "Battery SOC": soc_percent,
                # New columns to support NEM 3.0 accounting downstream
                "PV AC (kWh)": solar_gen,
                "PV to Grid (kWh)": pv_to_grid,
            }, index=date_range)
            df.to_csv(output_file)

            # Also write a companion export-enabled file that carries explicit export fields
            export_output_file = os.path.join(
                base_output_dir,
                scenario,
                housing_type,
                county,
                f"{OUTPUT_EXPORT_LOADPROFILE_FILE_PREFIX}_{county}.csv",
            )
            try:
                # Compute explicit PV export series via dedicated function
                pv_exports = compute_excess_solar_exports(
                    pv_ac_kwh=solar_gen,
                    system_to_load=system_to_load,
                    system_to_battery=pv_to_batt,
                )

                export_df = prepare_export_enabled_outputs(
                    load_profile=load_profile,
                    pv_ac_kwh=solar_gen,
                    system_to_load=system_to_load,
                    battery_to_load=batt_to_load,
                    grid_to_load=grid_to_load,
                    system_to_battery=pv_to_batt,
                    grid_to_battery=grid_to_batt,
                    battery_soc_percent=soc_percent,
                    # We do not currently model battery exports; provide zeros for schema stability
                    battery_to_grid_kwh=None,
                    battery_charge_stored_kwh=batt_charge,
                    grid_demand_kwh=grid_demand,
                    pv_to_grid_kwh=pv_exports,
                    start_timestamp="2018-01-01",
                )
                export_df.to_csv(export_output_file)
            except Exception as export_err:
                print(f"Export-enabled output generation failed for {county}: {export_err}")

            # Create and save Jan/Jul plots
            plots_path = os.path.join(
                base_output_dir,
                scenario,
                housing_type,
                county,
                f"step9_my_own_solar_storage_plots_{county}_g{GIT_SHORT_SHA}.png",
            )
            try:
                os.makedirs(os.path.dirname(plots_path), exist_ok=True)
                pv_used_series = [min(s, l) + pv for s, l, pv in zip(solar_gen, load_profile, pv_to_batt)]
                summary = {
                    "Solar size (kW)": float(system_capacity_kW),
                    "PV gross (kWh)": float(sum(solar_gen)),
                    "PV used (kWh)": float(sum(pv_used_series)),
                    "PV→Battery (kWh)": float(sum(pv_to_batt)),
                    "Battery→Load (kWh)": float(sum(batt_discharge)),
                    "Grid→Battery (kWh)": float(sum(grid_to_batt)),
                }
                plot_first_weeks(
                    load_kwh=load_profile,
                    pv_ac_kwh=solar_gen,
                    batt_to_load_kwh=batt_discharge,
                    grid_to_load_kwh=grid_to_load,
                    grid_to_batt_kwh=grid_to_batt,
                    pv_to_batt_kwh=pv_to_batt,
                    soc_percent=soc_percent,
                    pv_used_kwh=pv_used_series,
                    summary_stats=summary,
                    title=f"DIY Dispatch — {scenario} — {county}",
                    show=False,
                    save_path=plots_path,
                )
                print(f"Saved step9_my_own_solar_storage plots to: {plots_path}")
            except Exception as plot_err:
                print(f"Plotting failed for {county}: {plot_err}")

            # Track capacity for capital costs linkage
            capacity_dict[county] = {
                "Solar Capacity (kW)": to_decimal_number(system_capacity_kW),
                "Battery Capacity (kWh)": to_decimal_number(selected_batt_kwh if selected_batt_kwh is not None else BATTERY_CAPACITY_KWH),
            }

            # Compact log
            log(
                at="step9_my_own_solar_storage",
                solar_profile=format_load_profile(solar_gen),
                grid_to_load=format_load_profile(grid_to_load),
                batt_to_load=format_load_profile(batt_to_load),
                grid_to_batt=format_load_profile(grid_to_batt),
                saved_to=output_file,
            )

        except Exception as e:
            print(f"Error processing {county}: {e}")

    # Save capacity table
    capital_costs_folder = f"{base_input_dir}/{scenario}/{housing_type}/{CAPITAL_COSTS_FOLDER_NAME}"
    os.makedirs(capital_costs_folder, exist_ok=True)
    capacity_df = pd.DataFrame.from_dict(capacity_dict, orient="index").rename_axis("County")
    capacity_df.to_csv(f"{capital_costs_folder}/{SOLAR_STORAGE_CAPACITY_PREFIX}.csv")


# Example usage
scenario = "baseline"
housing_type = "single-family-detached"

if __name__ == "__main__":
    process(
        "data/loadprofiles",
        "data/loadprofiles",
        scenario,
        housing_type,
        ["Alameda County"], # norcal_counties, # + socal_counties + central_counties,
        force_recompute=True,
    )
