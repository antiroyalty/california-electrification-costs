import os
import pandas as pd
import geopandas as gpd
from helpers import get_counties, get_scenario_path, slugify_county_name, norcal_counties, socal_counties, central_counties, log
from utility_helpers import get_utility_for_county
from maps_helpers import initialize_map, get_latest_csv_file
from capital_costs_helper import LIFETIMES, build_metric_map


CAPITAL_COSTS = {
    "solar": {
        # Back-calculated from PG&E's cost estimator website: https://pge.wattplan.com/PV/Wizard/?sector=residential&
        # https://www.energysage.com/local-data/solar-panel-cost/ca/
        "dollars_per_watt": 2.8,          # $/W for panels https://www.tesla.com/learn/solar-panel-cost-breakdown
        "installation_labor": 0,         # 7% extra cost for labor
        "design_eng_overhead_percent": 0 # 28% extra cost for design/engineering
    },
    "storage": {
        # Other papers suggest: 1200–$1600 per kilowatt-hour which would = $16320 - $21600 https://www.mdpi.com/2071-1050/16/23/10320#:~:text=residential%20solar%20and%20BESS%2C%20the,6%2FWh%20in%20Texas%20%28Figure%203d
        # https://energylibrary.tesla.com/docs/Public/EnergyStorage/Powerwall/3/Datasheet/en-us/Powerwall-3-Datasheet.pdf
        # https://www.solarreviews.com/blog/is-the-tesla-powerwall-the-best-solar-battery-available?utm_source=chatgpt.com
        # https://www.selfgenca.com/home/program_metrics/
        "powerwall_13.5kwh": 16853          # $16853 Cost for one Tesla Powerwall 3 before incentives. https://www.tesla.com/powerwall/design/overview
    },
    "heat_pump": {
        # Rewiring america: $19,000 https://www.rewiringamerica.org/research/home-electrification-cost-estimates
        # "average": 19000, # https://www.nrel.gov/docs/fy24osti/84775.pdf#:~:text=dwelling%20units,9%2C000%2C%20%2420%2C000%2C%20and%20%2424%2C000%20for
        # https://incentives.switchison.org/residents/incentives?state=CA&field_zipcode=90001&_gl=1*1ck7fcj*_gcl_au*OTAxNTQyNjA3LjE3NDQ1NjYxNzg.*_ga*MTEwMTk5ODQ0LjE3NDQ1NjYxNzg.*_ga_8NM1W0PLNN*MTc0NDU2NjE3OC4xLjEuMTc0NDU2NjIwNC4zNC4wLjA.
        # E3 cites single family residential heat pump cost to be $19,000 https://www.ethree.com/wp-content/uploads/2023/12/E3_Benefit-Cost-Analysis-of-Targeted-Electrification-and-Gas-Decommissioning-in-California.pdf#:~:text=%2419k%20%2415k%20%24154k%20The%20significant,commercial%20customers%20and%20therefore%20see
        "average": 19000,
    },
    "induction_stove": {
        # PG&E appliance guide also says $2000 https://guide.pge.com/browse/induction
        "average": 2000 # https://www.sce.com/factsheet/InductionCookingFactSheet
    },
    "water_heater": { # 55 gal
        "average": 1637,
    }
}

# INCENTIVES = {
#     "federal_tax_credit_2023_2032": 0.3, # 30% credit https://www.irs.gov/credits-deductions/residential-clean-energy-credit
#     # Federal tax incentives will decline in later years
#     "federal_tax_credit_2033": 0.26,
#     "federal_tax_credit_2034": 0.22,
#     "federal_tax_credit_2035": 0,
#     "PGE_SCE_SDGE_General_SGIP_Rebate": 2025, #  General Market SGIP rebate of
#         # approximately $150/kilowatt-hour https://www.cpuc.ca.gov/-/media/cpuc-website/files/uploadedfiles/cpucwebsite/content/news_room/newsupdates/2020/sgip-residential-web-120420.pdf
#     "storage": {
#         # "PG&E": {
#             # "storage_rebate": 7500, # Only for homes in wildfire-prone areas, as deemed by PG&E https://www.tesla.com/support/incentives#california-local-incentives
#         # },
#         # "SCE": {

#         # },
#         # "SDG&E": {
#         #     # https://www.sdge.com/solar/considering-solar
#         # }
#     },
#     "heat_pump": {
#         "other_rebates": 0, # 9500, # 9500, # 15200, # 10000, # needed to make it worthwhile
#         "max_federal_annual_tax_rebate": 2000, # 2000,
#         "california_TECH_incentive": 1500, #1500, # https://incentives.switchison.org/rebate-profile/tech-clean-california-single-family-hvac
#     },
#     "induction_stove": {
#         "max_federal_annual_tax_rebate": 420, # 420, # 1000, # 420, # https://www.geappliances.com/inflation-reduction-act
#     },
#     "water_heater": {
#         "max_federal_annual_tax_rebate": 2000,
#         "45-55gal": 700, # $700 rebate
#         # "55-75gal": 900 # $900 rebate https://incentives.switchison.org/residents/incentives?state=CA&field_zipcode=90001&_gl=1*1ck7fcj*_gcl_au*OTAxNTQyNjA3LjE3NDQ1NjYxNzg.*_ga*MTEwMTk5ODQ0LjE3NDQ1NjYxNzg.*_ga_8NM1W0PLNN*MTc0NDU2NjE3OC4xLjEuMTc0NDU2NjIwNC4zNC4wLjA.
#     },
# }

# NO INCENTIVES
INCENTIVES = {
    "federal_tax_credit_2023_2032": 0, # 30% credit https://www.irs.gov/credits-deductions/residential-clean-energy-credit
    # Federal tax incentives will decline in later years
    "federal_tax_credit_2033": 0,
    "federal_tax_credit_2034": 0,
    "federal_tax_credit_2035": 0,
    "PGE_SCE_SDGE_General_SGIP_Rebate": 0, #  General Market SGIP rebate of
        # approximately $150/kilowatt-hour https://www.cpuc.ca.gov/-/media/cpuc-website/files/uploadedfiles/cpucwebsite/content/news_room/newsupdates/2020/sgip-residential-web-120420.pdf
    "storage": {
        # "PG&E": {
            # "storage_rebate": 7500, # Only for homes in wildfire-prone areas, as deemed by PG&E https://www.tesla.com/support/incentives#california-local-incentives
        # },
        # "SCE": {

        # },
        # "SDG&E": {
        #     # https://www.sdge.com/solar/considering-solar
        # }
    },
    "heat_pump": {
        "other_rebates": 0, # 9500, # 9500, # 15200, # 10000, # needed to make it worthwhile
        "max_federal_annual_tax_rebate": 0, # 2000,
        "california_TECH_incentive": 0, #1500, # https://incentives.switchison.org/rebate-profile/tech-clean-california-single-family-hvac
    },
    "induction_stove": {
        "max_federal_annual_tax_rebate": 0, # 420, # 1000, # 420, # https://www.geappliances.com/inflation-reduction-act
    },
    "water_heater": {
        "max_federal_annual_tax_rebate": 0,
        "45-55gal": 0, # $700 rebate
        # "55-75gal": 900 # $900 rebate https://incentives.switchison.org/residents/incentives?state=CA&field_zipcode=90001&_gl=1*1ck7fcj*_gcl_au*OTAxNTQyNjA3LjE3NDQ1NjYxNzg.*_ga*MTEwMTk5ODQ0LjE3NDQ1NjYxNzg.*_ga_8NM1W0PLNN*MTc0NDU2NjE3OC4xLjEuMTc0NDU2NjIwNC4zNC4wLjA.
    },
    # "whole_building_electrification": 4250 # must include heat pump space heating, heat pump water heating, induction cooking, electric dryer https://caenergysmarthomes.com/alterations/#whole-building-eligibility
}

def apply_incentives(total_cost, utility):
    total_cost_after_incentives = total_cost * (1 - INCENTIVES["federal_tax_credit_2023_2032"]) - INCENTIVES["PGE_SCE_SDGE_General_SGIP_Rebate"] # 30% federal incentive, and $250/kwh SGIP rebate

    if utility in INCENTIVES["storage"]:
        total_cost_after_incentives -= INCENTIVES["storage"][utility]["storage_rebate"]
    return total_cost_after_incentives

def calculate_payback_period(total_cost, annual_savings, lifetime_limit=None):
    if annual_savings == 0:
        return float('inf')

    raw_payback = total_cost / annual_savings

    return raw_payback

def load_electrified_assets(scenario_path):
    assets_path = os.path.join(scenario_path, "CAPITAL_COSTS", "electrified_assets.csv")
    if not os.path.exists(assets_path):
        raise FileNotFoundError(f"Electrified assets file not found at {assets_path}")
    df = pd.read_csv(assets_path)
    if "County" not in df.columns or "Solar Capacity (kW)" not in df.columns:
        raise ValueError("CSV must contain 'County' and 'Solar Capacity (kW)' columns")
    
    return df.set_index("County")["Solar Capacity (kW)"].to_dict()

def calculate_solar_storage_cost(solar_kw, dollars_per_watt, labour_pct, design_pct, storage_cost):
    panel_cost = solar_kw * 1000 * dollars_per_watt
    solar_total_cost = panel_cost * (1 + labour_pct + design_pct)
    total_cost = solar_total_cost + storage_cost
    return total_cost, solar_total_cost

def apply_solar_storage_incentives(cost, utility):
    cost *= (1 - INCENTIVES["federal_tax_credit_2023_2032"])
    cost -= INCENTIVES["PGE_SCE_SDGE_General_SGIP_Rebate"]

    if utility in INCENTIVES["storage"]:
        cost -= INCENTIVES["storage"][utility]["storage_rebate"]
    return cost

def calculate_heat_pump_cost():
    base_cost = CAPITAL_COSTS["heat_pump"]["average"]
    federal_tax_credit = min(base_cost * 0.3, INCENTIVES["heat_pump"]["max_federal_annual_tax_rebate"]) 
    rebate = federal_tax_credit + INCENTIVES["heat_pump"]["california_TECH_incentive"] + INCENTIVES["heat_pump"]["other_rebates"]

    return base_cost - rebate

def calculate_induction_stove_cost():
    base_cost = CAPITAL_COSTS["induction_stove"]["average"]
    rebate = INCENTIVES["induction_stove"]["max_federal_annual_tax_rebate"]
    return base_cost - rebate

def calculate_water_heater_cost(tank_size: str = "55-75gal"):
    base_cost = CAPITAL_COSTS["water_heater"]["average"]
    federal_tax_credit = min(base_cost * 0.3, INCENTIVES["water_heater"]["max_federal_annual_tax_rebate"]) 
    rebate = federal_tax_credit + INCENTIVES["water_heater"]["45-55gal"]
    print("REBATE: ", rebate)
    return base_cost - rebate

def evaluate_custom_combo(
    include_solar: bool,
    include_heat_pump: bool,
    include_induction: bool,
    include_water_heater: bool,
    water_heater_tank_size: str,
    solar_kw: float,
    annual_savings: float,
    utility: str
) -> dict:
    """
    Evaluate total capital cost, annual savings, and payback period for a flexible combination
    of upgrades: solar + storage, heat pump, induction stove, water heater.
    
    Parameters:
        include_solar (bool): Include solar + storage upgrade
        include_heat_pump (bool): Include heat pump upgrade
        include_induction (bool): Include induction stove upgrade
        include_water_heater (bool): Include heat pump water heater
        water_heater_tank_size (str): Size category for water heater rebate ("54-55gal", "55-75gal")
        solar_kw (float): Solar system size (in kW)
        annual_savings (float): Expected annual utility bill savings
        utility (str): Utility provider ("PG&E", "SCE", etc.)
    
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
        base_solar_cost, _ = calculate_solar_storage_cost(
            solar_kw,
            CAPITAL_COSTS["solar"]["dollars_per_watt"],
            CAPITAL_COSTS["solar"]["installation_labor"],
            CAPITAL_COSTS["solar"]["design_eng_overhead_percent"],
            CAPITAL_COSTS["storage"]["powerwall_13.5kwh"]
        )
        solar_cost_after_incentives = apply_solar_storage_incentives(base_solar_cost, utility)
        print("Solar cost: ", solar_cost_after_incentives)
        total_cost += solar_cost_after_incentives
        components["solar_storage"] = solar_cost_after_incentives
        lifetimes.append(LIFETIMES["solar"])
        lifetimes.append(LIFETIMES["storage"])

    if include_heat_pump:
        hp_cost = calculate_heat_pump_cost()
        print("Heat pump cost: ", hp_cost)
        total_cost += hp_cost
        components["heat_pump"] = hp_cost
        lifetimes.append(LIFETIMES["heat_pump"])

    if include_induction:
        stove_cost = calculate_induction_stove_cost()
        print("Stove cost: ", stove_cost)
        total_cost += stove_cost
        components["induction_stove"] = stove_cost
        lifetimes.append(LIFETIMES["induction_stove"])

    if include_water_heater:
        water_heater_cost = calculate_water_heater_cost(water_heater_tank_size)
        print("Water heater cost: ", water_heater_cost)
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

def process(base_input_dir, base_output_dir, scenario, housing_type, counties, desired_rate_plans):
    """
    Constructs three individual maps (for payback period, total cost, and annual savings) based on the solar+storage system economics.
    Each map contains its choropleth layer as well as the county outlines with tooltip.
    
    For each county, the script:
        1. Looks up the solar capacity from the electrified assets file.
        2. Loads the latest cost CSV files (baseline and solar+storage) from the county folder.
        3. For the chosen utility, it computes annual savings, total system cost, the cost after incentives, and payback period.
        4. Merges the results with the California counties shapefile.
        5. Constructs three Folium maps (one for each metric) that are saved individually.
        
    Parameters:
        base_input_dir (str): Base input directory.
        base_output_dir (str): Directory where output HTML files will be saved.
        scenario (str): Scenario name.
        housing_type (str): Housing type.
        counties (list): List of counties to process.
        desired_rate_plans (dict): Dictionary of rate plans for utilities.
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
            # 1. Baseline (no heat pump, no solar)
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
                include_solar=False,
                water_heater_tank_size="45-55gal",
                solar_kw=0,
                annual_savings=savings_hp_only,
                utility=utility,
                **combo_flags
            )

            if county not in assets_mapping:
                print(f"Missing solar capacity for {county}; skipping solar combo.")
                continue

            solar_kw = assets_mapping[county]
            results_hp_solar = evaluate_custom_combo(
                include_solar=True,
                water_heater_tank_size="45-55gal",
                solar_kw=solar_kw,
                annual_savings=savings_hp_solar,
                utility=utility,
                **combo_flags
            )

            # === Display Results ===
            print(f"--- {county} ---")
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

    scenario_output_dir = os.path.join(base_output_dir, scenario, housing_type, "RESULTS")
    maps_dir = os.path.join(scenario_output_dir, "maps")
    geojson_dir = os.path.join(scenario_output_dir, "geojson")

    # Create directories if they don't exist
    os.makedirs(maps_dir, exist_ok=True)
    os.makedirs(geojson_dir, exist_ok=True)

    geojson_path = os.path.join(
        geojson_dir,
        f"{scenario}.geojson"             # e.g. induction_stove.geojson
    )
    merged_gdf.to_file(geojson_path, driver="GeoJSON")
    print(f"🗺️  Saved GeoJSON to {geojson_path}")
        
    metrics = ["Payback Period"] # , "Annual Savings"] # "Solar Size (kW)"] # "Total Cost", "Solar Size (kW)"] # "Annual Savings % Change", 
    variants = [f"{scenario}_only", f"{scenario}_solar"]

    for metric in metrics:
        for variant in variants:
            m = build_metric_map(
                merged_gdf,
                desired_rate_plans,
                metric=metric,
                variant=variant,
                title_prefix=f"{scenario.replace('_', ' ').title()}: "
            )
            filename = f"{metric.lower().replace(' ', '_')}_{variant}.html"
            output_path = os.path.join(maps_dir, filename)
            m.save(output_path)
            print(f"Saved map: {output_path}")
            os.system(f'open "{output_path}"')

if __name__ == '__main__':
    base_input_dir = "data/loadprofiles"
    base_output_dir = "data/loadprofiles"
    # scenario = "heat_pump_and_induction_stove" 
    scenario = "heat_pump_and_induction_stove_and_water_heating"
    housing_type = "single-family-detached"
    # List counties to process, these names must match the directory names in the scenario path.
    # counties = ["Los Angeles County", "Alameda County", "Contra Costa"]
    desired_rate_plans = {
        "PG&E": {"electricity": "E-TOU-D", "gas": "G-1"},
        "SCE": {"electricity": "TOU-D-4-9PM", "gas": "GR"},
        "SDG&E": {"electricity": "TOU-DR1", "gas": "GR"}
    }

    all_counties = norcal_counties + socal_counties + central_counties
    log(scenario = scenario)
    process(base_input_dir, base_output_dir, scenario, housing_type, all_counties, desired_rate_plans)