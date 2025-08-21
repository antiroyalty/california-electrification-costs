"""
Step 14: Build Capital Costs, Lifetimes, Incentives

Build Capital Costs, Lifetimes, Incentives for my numbers.
Define each technology as a class that can be configured. It has a capital cost, 
a lifetime, and associated incentives at the state, federal, and utility level.
"""

import os
import pandas as pd
from main_helpers import log, slugify_county_name, get_scenario_path, norcal_counties, socal_counties, central_counties
from helpers.capital_costs_helper import load_electrified_assets
from scenarios import SCENARIOS
from typing import Dict, Tuple
# Electric Appliances
from appliances.electric_base import ElectricAppliance, Incentive, IncentiveScenario
from appliances.electric_heating import ElectricHeatingAppliance
from appliances.electric_cooking import ElectricCookingAppliance
from appliances.electric_water_heating import ElectricWaterHeatingAppliance
from appliances.electric_vehicle import ElectricVehicleAppliance
# Gas Appliances
from appliances.gas_heating import GasHeatingAppliance
from appliances.gas_stove import GasStoveAppliance
from appliances.ice_vehicle import ICEVehicleAppliance
from appliances.gas_water_heating import GasWaterHeatingAppliance
# Zero Cost Appliance
from appliances.zero_cost import ZeroCostAppliance

# Solar + Storage
from appliances.solar_system import SolarSystemAppliance
from appliances.battery_storage import BatteryStorageAppliance

BUILDERS = {
    ("heating", "electric"): ElectricHeatingAppliance.for_county,
    ("heating", "gas"):      GasHeatingAppliance,

    ("hot_water", "electric"): ElectricWaterHeatingAppliance.for_county,
    ("hot_water", "gas"):      GasWaterHeatingAppliance,

    ("cooking", "electric"): ElectricCookingAppliance,
    ("cooking", "gas"):      GasStoveAppliance,

    ("vehicle_charging", "electric"): ElectricVehicleAppliance,
    ("vehicle_fuel", "gas"):          ICEVehicleAppliance,

    ("appliances", "electric"): lambda: ZeroCostAppliance(name="appliances"),
    ("misc", "electric"):       lambda: ZeroCostAppliance(name="misc"),
}

def build_for_county(builder, county_slug: str):
    # Try county-aware builder first; fall back to zero-arg
    try:
        return builder(county_slug)
    except TypeError:
        return builder()

def build_appliances_from_config(scenario: str):
    fuels = resolve_fuels_for_scenario(scenario)
    electric_builders, gas_builders = {}, {}
    for end_use, fuel in fuels.items():
        builder = BUILDERS.get((end_use, fuel))
        if not builder:
            continue
        (electric_builders if fuel == "electric" else gas_builders)[end_use] = builder
    return electric_builders, gas_builders

def resolve_fuels_for_scenario(scenario: str) -> dict[str, str]:
    cfg = SCENARIOS[scenario]  # e.g. {"gas": {...}, "electric": {...}}
    mapping = {}
    for eu in cfg["electric"]:
        mapping[eu] = "electric"
    for eu in cfg["gas"]:
        mapping[eu] = "gas"
    return mapping  # e.g. {"heating":"electric","hot_water":"gas","cooking":"gas","appliances":"electric","misc":"electric"}

def sum_electric_net(
    electric: Dict[str, ElectricAppliance],
    sc: IncentiveScenario,
) -> float:
    return sum(appliance.get_net_cost(sc) for appliance in electric.values())

def sum_gas_base(gas: Dict[str, ElectricAppliance]) -> float:
    return sum(appliance.base_cost for appliance in gas.values())

def pv_storage_net_for_county(
    solar_appliances: Dict[str, ElectricAppliance],
    storage_appliances: Dict[str, ElectricAppliance],
    county_slug: str,
    sc: IncentiveScenario,
) -> float:
    total = 0.0
    if solar_appliances and county_slug in solar_appliances:
        total += solar_appliances[county_slug].get_net_cost(sc)
    if storage_appliances and county_slug in storage_appliances:
        total += storage_appliances[county_slug].get_net_cost(sc)
    return total

def scenario_total_incremental_capex(
    *,
    electric: Dict[str, ElectricAppliance],
    gas: Dict[str, ElectricAppliance],
    incentive: IncentiveScenario = IncentiveScenario.FULL_INCENTIVES,
    county_slug: str,
    solar_appliances: Dict[str, ElectricAppliance] | None = None,
    storage_appliances: Dict[str, ElectricAppliance] | None = None,
    include_pv_storage: bool = False,
) -> float:
    """
    Returns the incremental capital outlay for ONE scenario at ONE county:
        total = (electric_net [+ pv_net]) - gas_base
    "Give me the total incremental outlay for one scenario at one county under one incentive level."
    """
    electric_net = sum_electric_net(electric, incentive)
    gas_base     = sum_gas_base(gas)

    pv_net = 0.0
    if include_pv_storage and county_slug:
        pv_net = pv_storage_net_for_county(
            solar_appliances, storage_appliances, county_slug, incentive
        )

    return (electric_net + pv_net) - gas_base

def compare_baseline_vs_scenario(
    *,
    counties: list[str],
    baseline: Dict[str, Dict[str, ElectricAppliance]],  # {"electric":..., "gas":..., "solar":..., "storage":...} TODO: Ana, making solar and storage explicit is a good idea. But not implemented right now. Do this.
    scenario: Dict[str, Dict[str, ElectricAppliance]],
    incentive: IncentiveScenario = IncentiveScenario.FULL_INCENTIVES,
) -> pd.DataFrame:
    """
    Returns a DataFrame with, per county:
      - baseline_no_pv, scenario_no_pv, delta_no_pv
      - baseline_with_pv, scenario_with_pv, delta_with_pv
    """
    rows = []
    solar_b = baseline.get("solar", {})
    store_b = baseline.get("storage", {})
    # solar_s = scenario.get("solar", {})
    # store_s = scenario.get("storage", {})

    for county in counties:
        county_slug = slugify_county_name(county)

        # --- baseline ---
        base_no_pv = scenario_total_incremental_capex(
            electric=baseline["electric"],
            gas=baseline["gas"],
            incentive=incentive,
            county_slug=county_slug,
            include_pv_storage=False,               # explicit
        )
        base_with_pv = scenario_total_incremental_capex(
            electric=baseline["electric"],
            gas=baseline["gas"],
            incentive=incentive,
            county_slug=county_slug,
            # solar_appliances=solar_b,
            # storage_appliances=store_b, # No such thing as solar appliances right now
            include_pv_storage=True,
        )

        # --- scenario ---
        scen_no_pv = scenario_total_incremental_capex(
            electric=scenario["electric"],
            gas=scenario["gas"],
            incentive=incentive,
            county_slug=county_slug,
            include_pv_storage=False,
        )
        scen_with_pv = scenario_total_incremental_capex(
            electric=scenario["electric"],
            gas=scenario["gas"],
            incentive=incentive,
            county_slug=county_slug,
            # solar_appliances=solar_s,
            # storage_appliances=store_s,
            include_pv_storage=True,
        )

        rows.append({
            "county": county,
            "county_slug": county_slug,
            "incentive_scenario": incentive.value,
            "baseline_no_pv": base_no_pv,
            "scenario_no_pv": scen_no_pv,
            "delta_no_pv": scen_no_pv - base_no_pv,
            "baseline_with_pv": base_with_pv,
            "scenario_with_pv": scen_with_pv,
            "delta_with_pv": scen_with_pv - base_with_pv,
        })

    return pd.DataFrame(rows).sort_values(["county_slug"])

def save_comparison_csv(df: pd.DataFrame, base_output_dir: str, scenario: str, housing_type: str):
    out_dir = os.path.join(base_output_dir, "capital_costs")
    os.makedirs(out_dir, exist_ok=True)
    fname = f"capex_delta_{scenario}_vs_baseline_{housing_type.replace('-', '_')}.csv"
    path = os.path.join(out_dir, fname)
    df.to_csv(path, index=False)
    log(at="save_comparison_csv", info="saved", csv_path=path)

def build_capex_ledger_df(
    *,
    scenario: str,
    housing_type: str,
    counties: list[str],
    electric_appliances: dict[str, ElectricAppliance],
    gas_appliances: dict[str, ElectricAppliance],
    incentive_scenarios: list[IncentiveScenario],
) -> pd.DataFrame:
    """
    One row per (county, appliance_category, appliance_type, incentive_scenario).
    Includes electric, solar, storage, AND gas (with zero incentives).
    """
    rows = []
    for county in counties:
        county_slug = slugify_county_name(county)

        elec_instances = {name: build_for_county(b, county_slug) for name, b in electric_appliances.items()}
        gas_instances = {name: build_for_county(b, county_slug) for name, b in gas_appliances.items()}

        for incentive_scenario in incentive_scenarios:
            # electric rows
            for appliance_name, appliance in elec_instances.items():
                rows.append({
                    'county': county,
                    'county_slug': county_slug,
                    'scenario': scenario,
                    'housing_type': housing_type,
                    'appliance_category': 'electric',
                    'appliance_type': appliance_name,
                    'appliance_name': f"electric_{appliance_name}",
                    'incentive_scenario': incentive_scenario.value,
                    'base_cost': appliance.base_cost,
                    'total_incentives': appliance.calculate_total_incentives(incentive_scenario),
                    'net_cost': appliance.get_net_cost(incentive_scenario),
                    'lifetime_years': appliance.lifetime_years,
                })
            # gas rows (no incentives)
            for appliance_name, appliance in gas_instances.items():
                rows.append({
                    'county': county,
                    'county_slug': county_slug,
                    'scenario': scenario,
                    'housing_type': housing_type,
                    'appliance_category': 'gas',
                    'appliance_type': appliance_name,
                    'appliance_name': f"gas_{appliance_name}",
                    'incentive_scenario': incentive_scenario.value,
                    'base_cost': appliance.base_cost,
                    'total_incentives': 0.0,
                    'net_cost': appliance.base_cost,
                    'lifetime_years': appliance.lifetime_years,
                })
    return pd.DataFrame(rows).sort_values(
        ['county', 'appliance_category', 'appliance_type', 'incentive_scenario']
    )

def build_pv_storage_adjustments_df(
    *,
    base_input_dir: str,
    scenario: str,
    housing_type: str,
    incentive_scenarios: list[IncentiveScenario],
) -> pd.DataFrame:
    """
    Returns rows per (county, incentive_scenario):
      pv_capex, storage_capex, pv_incentives, storage_incentives, pv_storage_net
    If a county has no PV capacity, row values are zeros.
    """
    cap = load_solar_capacity_data(base_input_dir, scenario, housing_type)  # {county_slug: kW}

    rows = []
    # Pre-create one battery per site, and a PV system per kW
    for county_slug, solar_kw in cap.items():
        if solar_kw and solar_kw > 0:
            pv  = SolarSystemAppliance(capacity_kw=solar_kw, lifetime_years=25)
            bat = BatteryStorageAppliance(num_units=1, lifetime_years=15)

            # capex (constant across incentives)
            pv_capex = pv.base_cost
            st_capex = bat.base_cost

            # only FULL incentives (sanity check)
            pv_inc_full = pv.calculate_total_incentives(IncentiveScenario.FULL_INCENTIVES)
            st_inc_full = bat.calculate_total_incentives(IncentiveScenario.FULL_INCENTIVES)

            # nets for all three incentive scenarios
            net_full = pv.get_net_cost(IncentiveScenario.FULL_INCENTIVES) + bat.get_net_cost(IncentiveScenario.FULL_INCENTIVES)
            net_half = pv.get_net_cost(IncentiveScenario.HALF_INCENTIVES) + bat.get_net_cost(IncentiveScenario.HALF_INCENTIVES)
            net_none = pv.get_net_cost(IncentiveScenario.NO_INCENTIVES)   + bat.get_net_cost(IncentiveScenario.NO_INCENTIVES)

            rows.append({
                "county_slug": county_slug,
                "solar_kw": solar_kw,
                "pv_capex": pv_capex,
                "storage_capex": st_capex,
                "pv_incentives_full": pv_inc_full,
                "storage_incentives_full": st_inc_full,
                "pv_storage_net_full": net_full,
                "pv_storage_net_half": net_half,
                "pv_storage_net_none": net_none,
            })
        else:
            rows.append({
                "county_slug": county_slug,
                "solar_kw": 0.0,
                "pv_capex": 0.0,
                "storage_capex": 0.0,
                "pv_incentives_full": 0.0,
                "storage_incentives_full": 0.0,
                "pv_storage_net_full": 0.0,
                "pv_storage_net_half": 0.0,
                "pv_storage_net_none": 0.0,
            })

    return pd.DataFrame(rows)

def summary_from_ledger(df: pd.DataFrame) -> pd.DataFrame:
    """
    Produces per-county summary with:
      capital_cost_electric, capital_cost_gas,
      incentives_full / half / none,
      net_outlay_full / half / none.

    Simplified: only sums net_cost per county instead of splitting by category/scenario.
    """
    # Capital costs: just sum electric vs gas base_cost (use 'full' to avoid duplication)
    full_key = IncentiveScenario.FULL_INCENTIVES.value
    df_full = df[df['incentive_scenario'] == full_key]

    by_cat = (
        df_full.groupby(['county_slug', 'appliance_category'], as_index=False)['base_cost']
        .sum()
        .pivot(index='county_slug', columns='appliance_category', values='base_cost')
        .fillna(0.0)
    )
    by_cat = by_cat.reindex(columns=['electric','gas'], fill_value=0.0)
    by_cat = by_cat.rename(columns={
        'electric': 'capital_cost_electric',
        'gas': 'capital_cost_gas'
    })

    # Incentives: just sum per county per incentive scenario
    inc = (
        df.groupby(['county_slug','incentive_scenario'], as_index=False)['total_incentives']
          .sum()
          .pivot(index='county_slug', columns='incentive_scenario', values='total_incentives')
          .fillna(0.0)
          .rename(columns={
              IncentiveScenario.FULL_INCENTIVES.value: 'incentives_full',
              IncentiveScenario.HALF_INCENTIVES.value: 'incentives_half',
              IncentiveScenario.NO_INCENTIVES.value:   'incentives_none',
          })
    )

    # Total "electric-side capex": just sum net_cost for electric appliances
    elec_total = (
        df_full[df_full['appliance_category'] == 'electric']
        .groupby('county_slug', as_index=False)['net_cost']
        .sum()
        .rename(columns={'net_cost': 'total_capital_cost_electric'})
        .set_index('county_slug')
    )

    out = by_cat.join(elec_total, how='left').fillna(0.0).join(inc, how='left').fillna(0.0)
    # Net outlay = electric cost - gas cost - incentives
    out['net_outlay_full'] = out['total_capital_cost_electric'] - out['capital_cost_gas'] - out['incentives_full']
    out['net_outlay_half'] = out['total_capital_cost_electric'] - out['capital_cost_gas'] - out['incentives_half']
    out['net_outlay_none'] = out['total_capital_cost_electric'] - out['capital_cost_gas']

    return out.reset_index().sort_values('county_slug')

# def summary_from_ledger(df: pd.DataFrame) -> pd.DataFrame:
#     """
#     Produces per-county summary with:
#       capital_cost_electric / solar / storage / gas,
#       incentives_full / half / none,
#       net_outlay_full / half / none.
#     """
#     # For convenience, split by category and scenario level
#     # Base costs by category (pick 'full' to avoid triple-counting; base_cost is invariant)
#     full_key = IncentiveScenario.FULL_INCENTIVES.value
#     df_full = df[df['incentive_scenario'] == full_key]

#     # Base costs by category
#     by_cat = (
#         df_full.groupby(['county_slug', 'appliance_category'], as_index=False)['base_cost'].sum()
#         .pivot(index='county_slug', columns='appliance_category', values='base_cost')
#         .fillna(0.0)
#     )
#     by_cat = by_cat.reindex(columns=['electric','gas'], fill_value=0.0)
#     by_cat = by_cat.rename(columns={
#         'electric': 'capital_cost_electric',
#         'gas': 'capital_cost_gas'
#     })

#     # Incentives (electric side only)
#     inc = (
#         df[df['appliance_category'].isin(['electric'])]
#           .groupby(['county_slug','incentive_scenario'], as_index=False)['total_incentives'].sum()
#           .pivot(index='county_slug', columns='incentive_scenario', values='total_incentives')
#           .fillna(0.0)
#           .rename(columns={
#               IncentiveScenario.FULL_INCENTIVES.value: 'incentives_full',
#               IncentiveScenario.HALF_INCENTIVES.value: 'incentives_half',
#               IncentiveScenario.NO_INCENTIVES.value:   'incentives_none',
#           })
#     )

#     # Total “electric-side capex” (no PV/storage yet)
#     elec_total = (
#         df_full[df_full['appliance_category'].isin(['electric'])]
#         .groupby('county_slug', as_index=False)['base_cost'].sum()
#         .rename(columns={'base_cost': 'total_capital_cost_electric'})
#         .set_index('county_slug')
#     )

#     breakpoint()

#     out = by_cat.join(elec_total, how='left').fillna(0.0).join(inc, how='left').fillna(0.0)
#     # Net outlay columns (no PV/storage)
#     out['net_outlay_full'] = out['total_capital_cost_electric'] - out['capital_cost_gas'] - out['incentives_full']
#     out['net_outlay_half'] = out['total_capital_cost_electric'] - out['capital_cost_gas'] - out['incentives_half']
#     out['net_outlay_none'] = out['total_capital_cost_electric'] - out['capital_cost_gas']
#     return out.reset_index().sort_values('county_slug')

def apply_pv_storage_to_summary(
    summary_df: pd.DataFrame,
    pv_df: pd.DataFrame,
) -> pd.DataFrame:
    """
    Returns a copy of summary_df with *_with_pv columns added.
    """
    out = summary_df.copy()

    base_cols = [
        "solar_kw", "pv_capex", "storage_capex",
        "pv_incentives_full", "storage_incentives_full",
        "pv_storage_net_full", 'pv_storage_net_half', 'pv_storage_net_none',
    ]

    # Ensure columns exist even if pv_df is empty
    if pv_df.empty:
        for c in base_cols:
            out[c] = 0.0
        out["total_capital_cost_electric_with_pv"] = out["total_capital_cost_electric"]
        out["net_outlay_full_with_pv"] = out["net_outlay_full"]
        out["net_outlay_half_with_pv"] = out["net_outlay_half"]
        out["net_outlay_none_with_pv"] = out["net_outlay_none"]
        return out

    # Join FULL-only PV/Storage info (one row per county)
    pv_base = pv_df.set_index("county_slug")[base_cols]
    out = (
        out.set_index("county_slug")
           .join(pv_base, how="left")
           .fillna(0.0)
    )

    # Total capital cost of electrification and solar and storage
    out["total_capital_cost_electric_with_pv_st"] = (
        out["total_capital_cost_electric"] + out["pv_capex"] + out["storage_capex"]
    )
    # Net outlays with PV/Storage (add the PV+Storage net to base net)
    out["net_outlay_full_with_pv"] = out["net_outlay_full"] + out["pv_storage_net_full"]
    out["net_outlay_half_with_pv"] = out["net_outlay_half"] + out["pv_storage_net_half"]
    out["net_outlay_none_with_pv"] = out["net_outlay_none"] + out["pv_storage_net_none"]

    return out.reset_index().sort_values("county_slug")

def write_capex_outputs(
    *,
    base_output_dir: str,
    scenario: str,
    housing_type: str,
    ledger_df: pd.DataFrame,
):
    out_dir = os.path.join(base_output_dir, "capital_costs")
    os.makedirs(out_dir, exist_ok=True)

    # detailed
    detailed_name = f"capital_costs_{scenario}_{housing_type.replace('-', '_')}.csv"
    detailed_path = os.path.join(out_dir, detailed_name)
    ledger_df.to_csv(detailed_path, index=False)
    log(at="write_capex_outputs", info="detailed_capital_costs_saved", csv_path=detailed_path)

    # summary
    summary_df = summary_from_ledger(ledger_df)
    summary_name = f"capital_costs_summary_{scenario}_{housing_type.replace('-', '_')}.csv"
    summary_path = os.path.join(out_dir, summary_name)
    summary_df.to_csv(summary_path, index=False)
    log(at="write_capex_outputs", info="capital_costs_summary_saved", csv_path=summary_path)

def load_solar_capacity_data(base_input_dir: str, scenario: str, housing_type: str) -> dict:
    scenario_path = get_scenario_path(base_input_dir, scenario, housing_type)
    assets_mapping = load_electrified_assets(scenario_path)
    
    # Convert county names to slugs for consistency
    slug_mapping = {}
    for county_name, solar_kw in assets_mapping.items():
        county_slug = slugify_county_name(county_name)
        slug_mapping[county_slug] = solar_kw
    
    log(
        at="load_solar_capacity_data",
        info="solar_capacity_loaded",
        counties_count=len(slug_mapping)
    )
    return slug_mapping

def process(
    base_input_dir: str,
    base_output_dir: str,
    scenario: str,
    housing_type: str,
    counties: list[str],
):
    log(
        at="step14_build_capital_costs_lifetimes_incentives",
        info="starting_capital_costs_build",
        scenario=scenario, 
        housing_type=housing_type,
        log_level="debug"
        )

    # 1) instantiate
    electric_appliances, gas_appliances = build_appliances_from_config(scenario)

    # 2) incentive regimes
    incentive_scenarios = [
        IncentiveScenario.FULL_INCENTIVES,
        IncentiveScenario.HALF_INCENTIVES,
        IncentiveScenario.NO_INCENTIVES,
    ]

    # 3) build ledger (no PV/storage)
    ledger_df = build_capex_ledger_df(
        scenario=scenario,
        housing_type=housing_type,
        counties=counties,
        electric_appliances=electric_appliances,
        gas_appliances=gas_appliances,
        incentive_scenarios=incentive_scenarios,
    )

    # 4) PV/storage adjustments (separate)
    pv_adj_df = build_pv_storage_adjustments_df(
        base_input_dir=base_input_dir,
        scenario=scenario,
        housing_type=housing_type,
        incentive_scenarios=incentive_scenarios,
    )

    # 5) summaries
    summary = summary_from_ledger(ledger_df)
    summary_with_pv = apply_pv_storage_to_summary(summary, pv_adj_df)

    # 6) write outputs
    out_dir = os.path.join(base_output_dir, "capital_costs")
    os.makedirs(out_dir, exist_ok=True)

    detailed_name = f"capital_costs_{scenario}_{housing_type.replace('-', '_')}.csv"
    ledger_df.to_csv(os.path.join(out_dir, detailed_name), index=False)
    print(os.path.join(out_dir, detailed_name))

    summary_name = f"capital_costs_summary_{scenario}_{housing_type.replace('-', '_')}.csv"
    summary.to_csv(os.path.join(out_dir, summary_name), index=False)
    print(os.path.join(out_dir, summary_name))

    summary_pv_name = f"capital_costs_summary_with_pv_{scenario}_{housing_type.replace('-', '_')}.csv"
    summary_with_pv.to_csv(os.path.join(out_dir, summary_pv_name), index=False)
    print(os.path.join(out_dir, summary_pv_name))

    log(
        at="process", 
        info="capital_costs_build_completed",
        electric_appliances_initialized=len(electric_appliances),
        gas_appliances_initialized=len(gas_appliances),
        counties=len(counties),
        rows_ledger=len(ledger_df),
        rows_summary=len(summary),
        rows_summary_with_pv=len(summary_with_pv),
        log_level="debug"
    )

    result = {
        "electric": electric_appliances,
        "gas": gas_appliances,
        "ledger_df": ledger_df,
        "summary_df": summary,
        "summary_with_pv_df": summary_with_pv,
        "pv_adjustments_df": pv_adj_df,
    }

    return result

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Build capital costs, lifetimes, and incentives for electrification scenarios")
    parser.add_argument("scenario", 
                       choices=list(SCENARIOS.keys()),
                       help="Electrification scenario to analyze")
    parser.add_argument("--include-solar-storage", action="store_true",
                       help="Include solar and storage capital costs based on electrified_assets.csv")
    
    args = parser.parse_args()
    
    housing_type = "single-family-detached"
    all_counties = norcal_counties + socal_counties + central_counties

    result = process(
        base_input_dir="data/loadprofiles",
        base_output_dir="data/loadprofiles", 
        scenario=args.scenario,
        housing_type=housing_type,
        counties=norcal_counties + socal_counties + central_counties # ["Alameda County"] # ["Alameda County"], #all_counties,
    )
    
