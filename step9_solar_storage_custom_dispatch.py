"""
Step 9 (custom): Solar + simple battery dispatch using PySAM Pvsamv1 for PV

What this script does
- Uses PySAM.Pvsamv1 to generate hourly AC solar generation for each county
  using the existing weather files and a simple sizing heuristic (same pattern
  as other step9 scripts).
- Implements a simple, explicit battery dispatch outside SAM:
  - Battery usable capacity: 13.5 kWh
  - Round-trip efficiency: 96% (modeled as symmetric charge/discharge sqrt(RTE))
  - Max charge/discharge power: 3 kW
  - Charge allowed window: 06:00–16:00 (from grid only)
  - Discharge window: 16:00–21:00 to serve household load (after solar)

Outputs (8760 hourly values)
- Grid Demand (kWh): grid-to-load + grid-to-battery for each hour
- Battery Charge (kWh): energy stored into the battery (SoC increase)
- Battery Discharge (kWh): energy delivered from battery to the household load
- Grid to Household Load (kWh)
- Grid to Battery (kWh)
- Solar Generation (kWh)

Notes
- We do not charge from solar in this simple policy; solar offsets household load
  immediately and any excess is implicitly exported (not tracked here).
- Weather data (TMY) is shifted from UTC to Pacific Time by +8 hours to align with
  load profiles, following the convention in other steps.
"""

from __future__ import annotations

import json
import os
from math import sqrt
from typing import Dict, List, Optional, Tuple

import pandas as pd

import PySAM.Pvsamv1 as Pvsamv1
import PySAM.ResourceTools as ResourceTools

from main_helpers import (
    get_counties,
    get_scenario_path,
    log,
    format_load_profile,
    to_decimal_number,
    norcal_counties,
    central_counties,
    socal_counties,
)
from helpers import log_profiles


# Input/output constants (kept consistent with other step9 files)
LOADPROFILE_FILE_PREFIX = "combined_profiles"
TOTAL_LOAD_COLUMN_NAME = "electricity.real_and_simulated.for_typical_county_home.kwh"
OUTPUT_LOADPROFILE_FILE_PREFIX = "custom_dispatch_load_profiles"
SOLAR_STORAGE_CAPACITY_PREFIX = "electrified_assets"
CAPITAL_COSTS_FOLDER_NAME = "CAPITAL_COSTS"


# Battery and dispatch constants
BATTERY_CAPACITY_KWH = 13.5
ROUND_TRIP_EFFICIENCY = 0.96
ETA_CHARGE = sqrt(ROUND_TRIP_EFFICIENCY)  # per-path efficiency
ETA_DISCHARGE = sqrt(ROUND_TRIP_EFFICIENCY)
P_CHARGE_MAX_KW = 3.0
P_DISCHARGE_MAX_KW = 3.0
CHARGE_START_HOUR = 6
CHARGE_END_HOUR = 16  # exclusive (i.e., 6 <= h < 16)
DISCHARGE_START_HOUR = 16
DISCHARGE_END_HOUR = 21  # exclusive (i.e., 16 <= h < 21)
MIN_SOC_FRAC = 0.20
MAX_SOC_FRAC = 0.90


def _aggregate_to_hourly(series: List[float], expected_length: int = 8760) -> List[float]:
    """Aggregate sub-hourly series to hourly by averaging within each hour.

    PySAM may output sub-hourly arrays depending on configuration. If so, we
    aggregate by simple averaging per hour to preserve energy consistency over
    the hour (assuming values are average power per time step).
    """
    n = len(series)
    if n == expected_length:
        return list(series)
    if n % expected_length != 0:
        # Fallback: truncate or pad to 8760 conservatively
        return list(series[:expected_length])
    factor = n // expected_length
    hourly = []
    for i in range(expected_length):
        s = i * factor
        e = s + factor
        hourly.append(sum(series[s:e]) / factor)
    return hourly


def _compute_system_capacity_kW(solar_resource_data: Dict, load_profile: List[float]) -> float:
    """Simple sizing heuristic based on annual irradiance and typical PV performance.

    Mirrors the simplified approach used in other step9 scripts.
    """
    gh_w_per_m2 = solar_resource_data.get("gh", [0.0] * 8760)
    mean_gh_w_per_m2 = sum(gh_w_per_m2) / len(gh_w_per_m2)
    daily_irradiance_kWh_per_m2_per_day = mean_gh_w_per_m2 * 24 / 1000
    annual_irradiance_kWh_per_m2 = daily_irradiance_kWh_per_m2_per_day * 365

    pv_cell_efficiency = 0.206
    system_performance_ratio = 0.80
    annual_energy_production_kWh_per_m2 = (
        annual_irradiance_kWh_per_m2 * pv_cell_efficiency * system_performance_ratio
    )

    annual_load_kWh = sum(load_profile)
    panel_nameplate_power_density_kW_per_m2 = 0.193
    required_panel_area_m2 = (
        annual_load_kWh / annual_energy_production_kWh_per_m2 if annual_energy_production_kWh_per_m2 > 0 else 0.0
    )
    required_dc_capacity_kW = required_panel_area_m2 * panel_nameplate_power_density_kW_per_m2

    log(
        debug_required_panel_area_m2=required_panel_area_m2,
        debug_required_dc_capacity_kW=required_dc_capacity_kW,
    )
    return required_dc_capacity_kW


def _create_pvsamv1_model_for_pv(
    solar_resource_data: Dict, system_capacity_kW: float
) -> Pvsamv1.Pvsamv1:
    """Create a Pvsamv1 model for PV-only generation (battery disabled)."""
    pv = Pvsamv1.new()

    # Load preset JSON values for a reasonable PV configuration
    dir_path = "./SAM_Detailed_PV_Battery/"
    json_file = "untitled_pvsamv1.json"
    with open(os.path.join(dir_path, json_file), "r") as f:
        data = json.load(f)
        for k, v in data.items():
            if k != "number_inputs":
                try:
                    pv.value(k, v)
                except Exception:
                    pass

    # Set weather and system capacity. Ensure battery is off.
    pv.SolarResource.solar_resource_data = solar_resource_data
    pv.SystemDesign.system_capacity = float(system_capacity_kW)
    try:
        pv.value("en_standalone_batt", 0)
    except Exception:
        pass

    # For PV-only energy, clear any load context to avoid flow-based mixing
    try:
        pv.value("load", [0.0] * 8760)
        pv.value("crit_load", [0.0] * 8760)
    except Exception:
        pass

    return pv


def _pv_generation_kwh(pv: Pvsamv1.Pvsamv1) -> List[float]:
    """Return hourly PV AC generation (kWh) from Pvsamv1 outputs.

    Prefer flow-based reconstruction when available, else fall back to "gen" or "ac".
    """
    out = pv.Outputs.export()
    def arr(key: str) -> List[float]:
        return list(out.get(key, []))

    # Try to reconstruct AC from system flows if present
    pv_ac = None
    keys = ("system_to_batt", "system_to_load", "system_to_grid")
    if all(k in out for k in keys):
        pv_ac = [a + b + c for a, b, c in zip(arr(keys[0]), arr(keys[1]), arr(keys[2]))]

    # Fallbacks
    if pv_ac is None or len(pv_ac) == 0:
        if "gen" in out:  # Common energy output
            pv_ac = arr("gen")
        elif "ac" in out:
            pv_ac = arr("ac")
        else:
            pv_ac = [0.0] * 8760

    return _aggregate_to_hourly(pv_ac, 8760)


def _prepare_weather_and_load(weather_file: str, load_file: str) -> Tuple[Dict, List[float]]:
    """Load weather (shift to PT) and household load profile (8760)."""
    # Weather: SAM CSV -> dict, shift UTC->PT by 8h
    solar_resource_data = ResourceTools.SAM_CSV_to_solar_data(weather_file)
    weather_arrays = ["dn", "df", "gh", "tdry", "tdew", "rhum", "wdir", "wspd"]
    shift = 8
    for name in weather_arrays:
        if name in solar_resource_data:
            a = solar_resource_data[name]
            if len(a) >= 8760:
                solar_resource_data[name] = [a[(i + shift) % 8760] for i in range(8760)]

    # Load profile
    load_df = pd.read_csv(load_file)
    load_profile = load_df[TOTAL_LOAD_COLUMN_NAME].tolist()
    if len(load_profile) != 8760:
        load_profile = _aggregate_to_hourly(load_profile, 8760)

    log(
        debug_load_profile_sample=load_profile[:10],
        debug_annual_load_kwh=sum(load_profile),
    )
    return solar_resource_data, load_profile


def _simple_battery_dispatch(
    load_kwh: List[float],
    solar_kwh: List[float],
) -> Tuple[List[float], List[float], List[float], List[float], List[float]]:
    """
    Compute hourly flows for a 13.5 kWh battery with specified constraints.

    Returns
    - grid_demand_kwh: grid_to_load + grid_to_battery per hour
    - batt_charge_kwh: energy stored in battery (SoC increase) per hour
    - batt_discharge_kwh: energy delivered from battery to load per hour
    - grid_to_load_kwh: grid energy directly serving the household load per hour
    - grid_to_batt_kwh: grid energy used to charge the battery per hour
    """
    assert len(load_kwh) == 8760 and len(solar_kwh) == 8760

    soc_kwh = BATTERY_CAPACITY_KWH * MIN_SOC_FRAC
    min_soc_kwh = BATTERY_CAPACITY_KWH * MIN_SOC_FRAC
    max_soc_kwh = BATTERY_CAPACITY_KWH * MAX_SOC_FRAC
    grid_demand = [0.0] * 8760
    batt_charge = [0.0] * 8760  # stored energy (post-charge efficiency)
    batt_discharge = [0.0] * 8760  # delivered to load (pre-grid)
    grid_to_load = [0.0] * 8760
    grid_to_batt = [0.0] * 8760

    for h in range(8760):
        hod = h % 24

        # Solar offsets household load immediately; excess is implicit export (ignored here)
        net_after_solar = max(load_kwh[h] - solar_kwh[h], 0.0)

        # Discharge battery during 16:00–21:00 to serve remaining load
        if (
            DISCHARGE_START_HOUR <= hod < DISCHARGE_END_HOUR
            and net_after_solar > 0
            and soc_kwh > min_soc_kwh
        ):
            desired_to_load = min(P_DISCHARGE_MAX_KW, net_after_solar)
            # Energy to pull from battery accounting for discharge efficiency
            available_discharge_energy = max(soc_kwh - min_soc_kwh, 0.0)
            energy_from_batt = min(available_discharge_energy, desired_to_load / ETA_DISCHARGE)
            delivered = energy_from_batt * ETA_DISCHARGE
            soc_kwh -= energy_from_batt
            batt_discharge[h] = delivered
            net_after_solar -= delivered

        # Charge battery from grid during 06:00–16:00
        if CHARGE_START_HOUR <= hod < CHARGE_END_HOUR and soc_kwh < max_soc_kwh:
            # Grid energy limited by power and remaining capacity after efficiency
            remaining_capacity = max(max_soc_kwh - soc_kwh, 0.0)
            max_grid_energy = min(P_CHARGE_MAX_KW, remaining_capacity / ETA_CHARGE)
            if max_grid_energy > 0:
                stored = max_grid_energy * ETA_CHARGE
                soc_kwh += stored
                batt_charge[h] = stored
                grid_to_batt[h] = max_grid_energy

        # Whatever remains of household net load is served by grid
        grid_to_load[h] = max(net_after_solar, 0.0)
        grid_demand[h] = grid_to_load[h] + grid_to_batt[h]

    return grid_demand, batt_charge, batt_discharge, grid_to_load, grid_to_batt


def _validate_lengths(*series_lists: List[List[float]]) -> None:
    for s in series_lists:
        for arr in s:
            if len(arr) != 8760:
                raise ValueError("All output series must be 8760 elements long.")


def process(
    base_input_dir: str,
    base_output_dir: str,
    scenario: str,
    housing_type: str,
    counties: Optional[List[str]] = None,
    years_of_analysis: int = 1,
    force_recompute: bool = False,
):
    """Run PV generation and custom battery dispatch for selected counties."""
    scenario_path = get_scenario_path(base_input_dir, scenario, housing_type)
    counties_to_run = get_counties(scenario_path, counties)
    capacity_dict = {}

    for county in counties_to_run:
        try:
            log(county=county)

            weather_file = os.path.join(
                base_input_dir, scenario, housing_type, county, f"weather_TMY_{county}.csv"
            )
            load_file = os.path.join(
                scenario_path, county, f"{LOADPROFILE_FILE_PREFIX}_{scenario}_{county}.csv"
            )
            output_file = os.path.join(
                base_output_dir,
                scenario,
                housing_type,
                county,
                f"{OUTPUT_LOADPROFILE_FILE_PREFIX}_{county}.csv",
            )

            if not os.path.exists(weather_file):
                print(f"Weather file not found: {weather_file}. Skipping...")
                continue
            if not os.path.exists(load_file):
                print(f"Load file not found: {load_file}. Skipping...")
                continue
            if not force_recompute and os.path.exists(output_file):
                print(f"Output exists: {output_file}. Skipping (force_recompute=True to rebuild)")
                continue

            # Load weather + load
            solar_resource_data, load_profile = _prepare_weather_and_load(weather_file, load_file)

            # Size PV and simulate AC generation
            system_capacity_kW = _compute_system_capacity_kW(solar_resource_data, load_profile)
            pv = _create_pvsamv1_model_for_pv(solar_resource_data, system_capacity_kW)
            pv.execute(0)
            solar_gen = _pv_generation_kwh(pv)

            # Custom battery dispatch (grid-only charging, solar immediate offset)
            grid_demand, batt_charge, batt_discharge, grid_to_load, grid_to_batt = _simple_battery_dispatch(
                load_profile, solar_gen
            )

            _validate_lengths([solar_gen, grid_demand, batt_charge, batt_discharge, grid_to_load, grid_to_batt])

            # Human-readable summaries for verification
            log_profiles(
                {
                    "Solar Generation (kWh)": solar_gen,
                    "Battery Charge (kWh)": batt_charge,
                    "Battery Discharge (kWh)": batt_discharge,
                    "Grid to Household Load (kWh)": grid_to_load,
                    "Grid to Battery (kWh)": grid_to_batt,
                    "Grid Demand (kWh)": grid_demand,
                },
                title=f"Custom Dispatch Profiles — {county}",
            )

            # Save per-county outputs
            os.makedirs(os.path.dirname(output_file), exist_ok=True)
            date_range = pd.date_range(start="2018-01-01", periods=8760, freq="H")
            df = pd.DataFrame(
                {
                    "Solar Generation (kWh)": solar_gen,
                    "Grid to Household Load (kWh)": grid_to_load,
                    "Grid to Battery (kWh)": grid_to_batt,
                    "Battery Charge (kWh)": batt_charge,
                    "Battery Discharge (kWh)": batt_discharge,
                    "Grid Demand (kWh)": grid_demand,
                },
                index=date_range,
            )
            df.to_csv(output_file)

            # Save capacity summary for capital costs linkage
            capacity_dict[county] = {
                "Solar Capacity (kW)": to_decimal_number(system_capacity_kW),
                "Battery Capacity (kWh)": to_decimal_number(BATTERY_CAPACITY_KWH),
            }

            # Debug summary log
            log(
                at="step9_solar_storage_custom_dispatch",
                solar_profile=format_load_profile(solar_gen),
                grid_to_load=format_load_profile(grid_to_load),
                grid_to_batt=format_load_profile(grid_to_batt),
                batt_charge=format_load_profile(batt_charge),
                batt_discharge=format_load_profile(batt_discharge),
                grid_demand=format_load_profile(grid_demand),
                saved_to=output_file,
            )

        except Exception as e:
            print(f"Error processing {county}: {e}")

    # Persist capacity table under CAPITAL_COSTS
    capital_costs_folder = f"{base_input_dir}/{scenario}/{housing_type}/{CAPITAL_COSTS_FOLDER_NAME}"
    os.makedirs(capital_costs_folder, exist_ok=True)
    capacity_df = pd.DataFrame.from_dict(capacity_dict, orient="index").rename_axis("County")
    capacity_df.to_csv(f"{capital_costs_folder}/{SOLAR_STORAGE_CAPACITY_PREFIX}.csv")


# Example usage (aligns with other steps)
scenario = "heat_pump"
housing_type = "single-family-detached"

if __name__ == "__main__":
    process(
        "data/loadprofiles",
        "data/loadprofiles",
        scenario,
        housing_type,
        # norcal_counties + socal_counties + central_counties,
        ["Alameda County"],
        force_recompute=True,
    )

