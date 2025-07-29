import os
import pandas as pd
import geopandas as gpd
from main_helpers import get_counties, get_scenario_path, slugify_county_name
from helpers.utility_helpers import get_utility_for_county
from helpers.maps_helpers import initialize_map, get_latest_csv_file
from capital_cost_map_builder import LIFETIMES, build_metric_map
from helpers.payback_period_helper import INCENTIVES


def apply_incentives(total_cost, utility):
    """Apply federal tax credit and SGIP rebates to total cost."""
    total_cost_after_incentives = total_cost * (1 - INCENTIVES["federal_tax_credit_2023_2032"]) - INCENTIVES["PGE_SCE_SDGE_General_SGIP_Rebate"]

    if utility in INCENTIVES["storage"]:
        total_cost_after_incentives -= INCENTIVES["storage"][utility]["storage_rebate"]
    return total_cost_after_incentives


def calculate_payback_period(total_cost, annual_savings, lifetime_limit=None):
    """Calculate payback period in years."""
    if annual_savings == 0:
        return float('inf')

    raw_payback = total_cost / annual_savings
    return raw_payback


def load_electrified_assets(scenario_path):
    """Load solar capacity data for counties from electrified assets CSV."""
    assets_path = os.path.join(scenario_path, "CAPITAL_COSTS", "electrified_assets.csv")
    if not os.path.exists(assets_path):
        raise FileNotFoundError(f"Electrified assets file not found at {assets_path}")
    df = pd.read_csv(assets_path)
    if "County" not in df.columns or "Solar Capacity (kW)" not in df.columns:
        raise ValueError("CSV must contain 'County' and 'Solar Capacity (kW)' columns")
    
    return df.set_index("County")["Solar Capacity (kW)"].to_dict()


def calculate_solar_storage_cost(solar_kw, dollars_per_watt, labour_pct, design_pct, storage_cost):
    """Calculate total solar + storage system cost before incentives."""
    panel_cost = solar_kw * 1000 * dollars_per_watt
    solar_total_cost = panel_cost * (1 + labour_pct + design_pct)
    total_cost = solar_total_cost + storage_cost
    return total_cost, solar_total_cost


def apply_solar_storage_incentives(cost, utility):
    """Apply incentives to solar + storage systems."""
    cost *= (1 - INCENTIVES["federal_tax_credit_2023_2032"])
    cost -= INCENTIVES["PGE_SCE_SDGE_General_SGIP_Rebate"]

    if utility in INCENTIVES["storage"]:
        cost -= INCENTIVES["storage"][utility]["storage_rebate"]
    return cost


def calculate_heat_pump_cost(capital_costs_structure):
    """Calculate heat pump cost after incentives using provided capital costs structure."""
    if "average_residential" in capital_costs_structure["heat_pump"]:
        # NEW/CRIS structure
        base_cost = capital_costs_structure["heat_pump"]["average_residential"]["base"]["value"]
    else:
        # OLD structure
        base_cost = capital_costs_structure["heat_pump"]["average"]
    
    federal_tax_credit = min(base_cost * 0.3, INCENTIVES["heat_pump"]["max_federal_annual_tax_rebate"]) 
    rebate = federal_tax_credit + INCENTIVES["heat_pump"]["california_TECH_incentive"] + INCENTIVES["heat_pump"]["other_rebates"]

    return base_cost - rebate


def calculate_induction_stove_cost(capital_costs_structure):
    """Calculate induction stove cost after incentives using provided capital costs structure."""
    if "average_residential" in capital_costs_structure["induction_stove"]:
        # NEW/CRIS structure
        base_cost = capital_costs_structure["induction_stove"]["average_residential"]["base"]["value"]
    else:
        # OLD structure
        base_cost = capital_costs_structure["induction_stove"]["average"]
    
    rebate = INCENTIVES["induction_stove"]["max_federal_annual_tax_rebate"]
    return base_cost - rebate


def calculate_water_heater_cost(capital_costs_structure, tank_size: str = "55-75gal"):
    """Calculate water heater cost after incentives using provided capital costs structure."""
    if "electric_55gal" in capital_costs_structure["water_heater"]:
        # NEW/CRIS structure
        base_cost = capital_costs_structure["water_heater"]["electric_55gal"]["base"]["value"]
    else:
        # OLD structure
        base_cost = capital_costs_structure["water_heater"]["average"]
    
    federal_tax_credit = min(base_cost * 0.3, INCENTIVES["water_heater"]["max_federal_annual_tax_rebate"]) 
    rebate = federal_tax_credit + INCENTIVES["water_heater"]["45-55gal"]
    print("REBATE: ", rebate)
    return base_cost - rebate


def get_solar_cost_params(capital_costs_structure):
    """Extract solar cost parameters from capital costs structure."""
    if "panel" in capital_costs_structure["solar"]:
        # NEW/CRIS structure
        dollars_per_watt = capital_costs_structure["solar"]["panel"]["base"]["value"]
        labour_pct = capital_costs_structure["solar"]["panel"]["markup"]["installation_labor"]["value"] / 100
        design_pct = capital_costs_structure["solar"]["panel"]["markup"]["design_engineering"]["value"] / 100
        storage_cost = capital_costs_structure["storage"]["tesla_powerwall_3"]["base"]["value"]
    else:
        # OLD structure
        dollars_per_watt = capital_costs_structure["solar"]["dollars_per_watt"]
        labour_pct = capital_costs_structure["solar"]["installation_labor"]
        design_pct = capital_costs_structure["solar"]["design_eng_overhead_percent"]
        storage_cost = capital_costs_structure["storage"]["powerwall_13.5kwh"]
    
    return dollars_per_watt, labour_pct, design_pct, storage_cost


def evaluate_custom_combo(
    capital_costs_structure,
    include_solar: bool,
    include_heat_pump: bool,
    include_induction: bool,
    include_water_heater: bool,
    water_heater_tank_size: str,
    solar_kw: float,
    annual_savings: float,
    utility: str,
    cost_label: str = ""
) -> dict:
    """
    Evaluate total capital cost, annual savings, and payback period for a flexible combination
    of upgrades: solar + storage, heat pump, induction stove, water heater.
    
    Parameters:
        capital_costs_structure: Capital costs data structure (NEW, CRIS, or OLD)
        include_solar (bool): Include solar + storage upgrade
        include_heat_pump (bool): Include heat pump upgrade
        include_induction (bool): Include induction stove upgrade
        include_water_heater (bool): Include heat pump water heater
        water_heater_tank_size (str): Size category for water heater rebate ("54-55gal", "55-75gal")
        solar_kw (float): Solar system size (in kW)
        annual_savings (float): Expected annual utility bill savings
        utility (str): Utility provider ("PG&E", "SCE", etc.)
        cost_label (str): Label for debug output (e.g., "NEW", "CRIS", "OLD")
    
    Returns:
        dict: {
            capital_cost (float),
            annual_savings (float),
            payback_period (float),
            component_breakdown (dict)
        }
    """
    total_cost = 0
    components = {}
    lifetimes = []

    if include_solar:
        dollars_per_watt, labour_pct, design_pct, storage_cost = get_solar_cost_params(capital_costs_structure)
        
        base_solar_cost, _ = calculate_solar_storage_cost(
            solar_kw, dollars_per_watt, labour_pct, design_pct, storage_cost
        )
        solar_cost_after_incentives = apply_solar_storage_incentives(base_solar_cost, utility)
        print(f"Solar cost ({cost_label}): ", solar_cost_after_incentives)
        total_cost += solar_cost_after_incentives
        components["solar_storage"] = solar_cost_after_incentives
        lifetimes.append(LIFETIMES["solar"])
        lifetimes.append(LIFETIMES["storage"])

    if include_heat_pump:
        hp_cost = calculate_heat_pump_cost(capital_costs_structure)
        print(f"Heat pump cost ({cost_label}): ", hp_cost)
        total_cost += hp_cost
        components["heat_pump"] = hp_cost
        lifetimes.append(LIFETIMES["heat_pump"])

    if include_induction:
        stove_cost = calculate_induction_stove_cost(capital_costs_structure)
        print(f"Stove cost ({cost_label}): ", stove_cost)
        total_cost += stove_cost
        components["induction_stove"] = stove_cost
        lifetimes.append(LIFETIMES["induction_stove"])

    if include_water_heater:
        water_heater_cost = calculate_water_heater_cost(capital_costs_structure, water_heater_tank_size)
        print(f"Water heater cost ({cost_label}): ", water_heater_cost)
        total_cost += water_heater_cost
        components["water_heater"] = water_heater_cost
        lifetimes.append(LIFETIMES["water_heater"])

    lifetime_limit = min(lifetimes) if lifetimes else None
    payback = calculate_payback_period(total_cost, annual_savings)

    return {
        "capital_cost": total_cost,
        "annual_savings": annual_savings,
        "payback_period": payback,
        "component_breakdown": components,
        "min_lifetime": lifetime_limit
    }


def flags_from_scenario(scenario: str) -> dict[str, bool]:
    """
    Return the keyword–arguments dict for evaluate_custom_combo
    that matches the appliance keywords present in `scenario`.
    """
    s = scenario.lower()

    return {
        "include_heat_pump":     "heat_pump"      in s,
        "include_induction":     "induction"      in s,
        "include_water_heater":  "water_heating"   in s,
    }


def process_payback_analysis(
    base_input_dir, base_output_dir, scenario, housing_type, counties, desired_rate_plans,
    capital_costs_structure, output_suffix, cost_label
):
    """
    Generic processing function for payback period analysis that works with any capital costs structure.
    
    Parameters:
        base_input_dir (str): Base input directory
        base_output_dir (str): Directory where output HTML files will be saved
        scenario (str): Scenario name
        housing_type (str): Housing type
        counties (list): List of counties to process
        desired_rate_plans (dict): Dictionary of rate plans for utilities
        capital_costs_structure: The capital costs data structure to use
        output_suffix (str): Suffix for output directory (e.g., "NEW_CAPITAL_COSTS")
        cost_label (str): Label for debug output (e.g., "NEW", "CRIS", "OLD")
    """
    scenario_path = get_scenario_path(base_input_dir, scenario, housing_type)
    valid_counties = get_counties(scenario_path, counties)
    assets_mapping = load_electrified_assets(scenario_path)
    
    records = []
    for county in valid_counties:
        county_slug = slugify_county_name(county)
        utility = get_utility_for_county(county)
        rate_elec = desired_rate_plans[utility]["electricity"]
        rate_gas = desired_rate_plans[utility]["gas"]
        cost_column = f"total.{utility}.{rate_elec}+{utility}.{rate_gas}"

        try:
            # === Load annual costs ===
            # 1. Baseline (no heat pump, no solar, etc.)
            baseline_dir = os.path.join(base_input_dir, "baseline", housing_type, county, "results", "totals")
            baseline_path = get_latest_csv_file(baseline_dir, f"RESULTS_total_annual_costs_{county_slug}_")
            baseline_df = pd.read_csv(baseline_path, index_col="scenario")
            baseline_cost = baseline_df.loc["baseline", cost_column]

            # 2. Heat pump only
            hp_dir = os.path.join(base_input_dir, scenario, housing_type, county, "results", "totals")
            hp_path = get_latest_csv_file(hp_dir, f"RESULTS_total_annual_costs_{county_slug}_")
            hp_df = pd.read_csv(hp_path, index_col="scenario")
            hp_cost = hp_df.loc[scenario, cost_column]

            # 3. Heat pump + solar
            hp_solar_dir = os.path.join(base_input_dir, scenario, housing_type, county, "results", "solarstorage")
            hp_solar_path = get_latest_csv_file(hp_solar_dir, f"RESULTS_total_annual_costs_{county_slug}_")
            hp_solar_df = pd.read_csv(hp_solar_path, index_col="scenario")
            hp_solar_cost = hp_solar_df.loc[f"{scenario}.solarstorage", cost_column]

            # === Annual savings relative to true baseline ===
            savings_hp_only = baseline_cost - hp_cost
            savings_hp_solar = baseline_cost - hp_solar_cost

            combo_flags = flags_from_scenario(scenario)

            # === Evaluate Capital Costs ===
            results_hp_only = evaluate_custom_combo(
                capital_costs_structure=capital_costs_structure,
                include_solar=False,
                water_heater_tank_size="45-55gal",
                solar_kw=0,
                annual_savings=savings_hp_only,
                utility=utility,
                cost_label=cost_label,
                **combo_flags
            )

            if county not in assets_mapping:
                print(f"Missing solar capacity for {county}; skipping solar combo.")
                continue

            solar_kw = assets_mapping[county]
            results_hp_solar = evaluate_custom_combo(
                capital_costs_structure=capital_costs_structure,
                include_solar=True,
                water_heater_tank_size="45-55gal",
                solar_kw=solar_kw,
                annual_savings=savings_hp_solar,
                utility=utility,
                cost_label=cost_label,
                **combo_flags
            )

            # === Display Results ===
            print(f"--- {county} ({cost_label} CAPITAL COSTS) ---")
            print(f"1) {scenario} Only")
            print(f"   Annual Cost: ${hp_cost:.2f}")
            print(f"   Annual Savings vs Baseline: ${savings_hp_only:.2f}")
            print(f"   Capital Cost: ${results_hp_only['capital_cost']:.2f}")
            print(f"   Payback: {results_hp_only['payback_period']:.2f} years")
            print(f"   Lifetime Limit: {results_hp_only['min_lifetime']:.2f} years")

            print(f"2) {scenario} + Solar + Storage")
            print(f"   Annual Cost: ${hp_solar_cost:.2f}")
            print(f"   Annual Savings vs Baseline: ${savings_hp_solar:.2f}")
            print(f"   Capital Cost: ${results_hp_solar['capital_cost']:.2f}")
            print(f"   Payback: {results_hp_solar['payback_period']:.2f} years")
            print(f"   Lifetime Limit: {results_hp_solar['min_lifetime']:.2f} years")
            print()

        except Exception as e:
            print(f"Error processing {county}: {e}")

        records.append({
            "County": county,
            "Payback Period (Electrification Only)": results_hp_only["payback_period"],
            "Lifetime Limit (Electrification Only)": results_hp_only["min_lifetime"],
            "Annual Savings (Electrification Only)": results_hp_only["annual_savings"],
            "Total Cost (Electrification Only)": results_hp_only["capital_cost"],
            "Solar Size (kW)": solar_kw,
            "Payback Period (Electrification + Solar + Storage)": results_hp_solar["payback_period"],
            "Lifetime Limit (Electrification + Solar + Storage)": results_hp_solar["min_lifetime"],
            "Annual Savings (Electrification + Solar + Storage)": results_hp_solar["annual_savings"],
            "Total Cost (Electrification + Solar + Storage)": results_hp_solar["capital_cost"],
            "Annual Savings % Change": (
                (results_hp_solar["annual_savings"] - results_hp_only["annual_savings"]) /
                abs(results_hp_only["annual_savings"]) * 100
                if results_hp_only["annual_savings"] != 0 else float('nan')
            )
        })

    # Create DataFrame from results
    df_metrics = pd.DataFrame(records).set_index("County")

    # Initialize California county shapes
    gdf = initialize_map()
    gdf["county_slug"] = gdf["NAME"].apply(slugify_county_name)

    # Merge metrics with GeoDataFrame
    merged_gdf = gdf.merge(df_metrics, left_on="county_slug", right_index=True, how="left")

    scenario_output_dir = os.path.join(base_output_dir, scenario, housing_type, f"RESULTS_{output_suffix}")
    maps_dir = os.path.join(scenario_output_dir, "maps")
    geojson_dir = os.path.join(scenario_output_dir, "geojson")

    # Create directories if they don't exist
    os.makedirs(maps_dir, exist_ok=True)
    os.makedirs(geojson_dir, exist_ok=True)

    geojson_path = os.path.join(
        geojson_dir,
        f"{scenario}_{output_suffix.lower()}.geojson"
    )

    merged_gdf.to_file(geojson_path, driver="GeoJSON")
    print(f"🗺️  Saved {cost_label} CAPITAL COSTS GeoJSON to {geojson_path}")
        
    metrics = ["Payback Period", "Solar Size (kW)"]
    variants = [f"{scenario}_only", f"{scenario}_solar"]

    for metric in metrics:
        for variant in variants:
            m = build_metric_map(
                merged_gdf,
                desired_rate_plans,
                metric=metric,
                variant=variant,
                title_prefix=f"{scenario.replace('_', ' ').title()} ({cost_label} Capital Costs): "
            )
            filename = f"{metric.lower().replace(' ', '_')}_{variant}_{output_suffix.lower()}.html"
            output_path = os.path.join(maps_dir, filename)
            m.save(output_path)
            print(f"Saved {cost_label} CAPITAL COSTS map: {output_path}")
            os.system(f'open "{output_path}"')

    return merged_gdf, df_metrics