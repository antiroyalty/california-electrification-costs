import os
import pandas as pd
import geopandas as gpd
from helpers import get_counties, get_scenario_path, slugify_county_name, norcal_counties, socal_counties, central_counties, log
from utility_helpers import get_utility_for_county
from maps_helpers import initialize_map, get_latest_csv_file
from capital_costs_helper import LIFETIMES, build_metric_map
from payback_period_helper import INCENTIVES

# CAPITAL_COSTS_CRIS - 2025 Capital Costs Data
# Based on CARB data, TECH California, and NREL sources
# Note: Using 2025 specific costs from Cris's research, no inflation adjustment needed

# Gas appliance costs (2025 base costs from Cris's research)
GAS_SPACE_HEATER = 4500  # Gas furnace cost
GAS_WATER_HEATER = 900   # Gas water heater cost  
GAS_COOKSTOVE = 1600     # Gas cookstove cost

# Electric appliance costs (2025 costs from Cris's research)
INDUCTION_COOKSTOVE = 2400  # Induction cookstove cost
CENTRALIZED_AC_COST = 5930  # Centralized AC unit cost

# Heat pump costs from TECH California and NREL data (2025)
HP_SPACE_HEATING_COST_PER_TON = 3753.78  # ASHP cost per ton of heating
HP_WATER_HEATING_COST_PER_GAL = 169.60   # HPWH cost per gallon capacity
WATER_HEATER_CAPACITY_GAL = 55 / 3.785   # 55 liters converted to gallons (~14.54 gal)

# Efficiency data
GAS_FURNACE_EFFICIENCY = 0.83      # 83% efficiency
GAS_WATER_HEATER_EFFICIENCY = 0.83 # 83% efficiency
GAS_TO_INDUCTION_EFFICIENCY_GAIN = 3  # 3x efficiency gain from gas to induction

# Heat pump coefficients of performance (COP)
ASHP_COP_SPACE_HEATING = 3.375  # Air source heat pump COP for space heating
HPWH_COP_WATER_HEATING = 3.250  # Heat pump water heater COP

# Calculate actual costs
HP_WATER_HEATER_COST = HP_WATER_HEATING_COST_PER_GAL * WATER_HEATER_CAPACITY_GAL  # ~$2466.78

CAPITAL_COSTS_CRIS = {
    "solar": {
        "panel": {
            "base": {
                "value": 2.8,  # TODO: Update with actual 2025 solar cost data
                "unit": "$/W"
            },
            "markup": {
                "installation_labor": {
                    "value": 0,  # TODO: Update with actual markup data
                    "unit": "%"
                },
                "design_engineering": {
                    "value": 0,  # TODO: Update with actual markup data
                    "unit": "%"
                }
            },
            "sources": [
                "TBD - User will provide solar sources"
            ],
            "last_verified": "2025-01-01"
        }
    },
    "storage": {
        "tesla_powerwall_3": {
            "capacity_kwh": 13.5,
            "base": {
                "value": 16853,  # TODO: Update with actual 2025 storage cost data
                "unit": "$"
            },
            "sources": [
                "TBD - User will provide storage sources"
            ],
            "notes": "2025 pricing",
            "last_verified": "2025-01-01"
        }
    },
    "heat_pump": {
        "space_heating": {
            "base": {
                "value": HP_SPACE_HEATING_COST_PER_TON,  # $3753.78/ton
                "unit": "$/ton"
            },
            "cop": ASHP_COP_SPACE_HEATING,  # 3.375
            "sources": [
                "https://techcleanca.com/heat-pump-data/download-data/",
                "P. Jadun, C. McMillan, L. Vimmerstedt, and T. Mai, Electrification Futures Study Technology Data. NREL Data Catalog. National Renewable Energy Laboratory., Golden, CO, 2017. doi: 10.7799/1414279",
                "https://data.bls.gov/cgi-bin/cpicalc.pl",
                "https://www.philadelphiafed.org/surveys-and-data/real-time-data-research/spf-q2-2024"
            ],
            "notes": "TECH California median installation costs, NREL cost decline rates, adjusted to 2025 dollars. Heating capacity based on max daily gas usage converted to heating tons, calibrated so median capacity is 3 tons.",
            "last_verified": "2025-01-01"
        },
        "average_residential": {
            "base": {
                "value": HP_SPACE_HEATING_COST_PER_TON * 3,  # Assume 3-ton system for average home
                "unit": "$"
            },
            "cop": ASHP_COP_SPACE_HEATING,
            "sources": [
                "https://techcleanca.com/heat-pump-data/download-data/",
                "P. Jadun, C. McMillan, L. Vimmerstedt, and T. Mai, Electrification Futures Study Technology Data. NREL Data Catalog. National Renewable Energy Laboratory., Golden, CO, 2017. doi: 10.7799/1414279"
            ],
            "notes": "Assuming 3-ton system for average residential home, based on median heating capacity in TECH incentive program data",
            "last_verified": "2025-01-01"
        }
    },
    "induction_stove": {
        "average_residential": {
            "base": {
                "value": INDUCTION_COOKSTOVE,  # $2400
                "unit": "$"
            },
            "efficiency_gain_vs_gas": GAS_TO_INDUCTION_EFFICIENCY_GAIN,  # 3x
            "sources": [
                "https://ww2.arb.ca.gov/our-work/programs/technology-clearinghouse/technology-clearinghouse-tools/residential-appliance-comparison"
            ],
            "notes": "CARB data, 3x efficiency gain over gas cookstove",
            "last_verified": "2025-01-01"
        }
    },
    "water_heater": {
        "heat_pump_55L": {
            "base": {
                "value": HP_WATER_HEATER_COST,  # $169.60/gal * 14.54 gal = ~$2466.78
                "unit": "$"
            },
            "capacity_liters": 55,
            "capacity_gallons": WATER_HEATER_CAPACITY_GAL,
            "cop": HPWH_COP_WATER_HEATING,  # 3.250
            "cost_per_gallon": HP_WATER_HEATING_COST_PER_GAL,
            "sources": [
                "https://techcleanca.com/heat-pump-data/download-data/",
                "P. Jadun, C. McMillan, L. Vimmerstedt, and T. Mai, Electrification Futures Study Technology Data. NREL Data Catalog. National Renewable Energy Laboratory., Golden, CO, 2017. doi: 10.7799/1414279"
            ],
            "notes": f"TECH California median installation costs, NREL cost decline rates, {WATER_HEATER_CAPACITY_GAL:.1f} gallon capacity",
            "last_verified": "2025-01-01"
        },
        "electric_55gal": {
            "base": {
                "value": HP_WATER_HEATER_COST,  # Use heat pump water heater cost
                "unit": "$"
            },
            "sources": [
                "https://techcleanca.com/heat-pump-data/download-data/"
            ],
            "notes": "Using heat pump water heater cost for electric water heater",
            "last_verified": "2025-01-01"
        }
    },
    # Reference data for efficiency comparisons
    "efficiency_data": {
        "gas_furnace_efficiency": GAS_FURNACE_EFFICIENCY,      # 0.83
        "gas_water_heater_efficiency": GAS_WATER_HEATER_EFFICIENCY,  # 0.83
        "ashp_cop_space_heating": ASHP_COP_SPACE_HEATING,     # 3.375
        "hpwh_cop_water_heating": HPWH_COP_WATER_HEATING,     # 3.250
        "gas_to_induction_efficiency_gain": GAS_TO_INDUCTION_EFFICIENCY_GAIN  # 3.0
    },
    # Reference gas appliance costs for comparison
    "gas_appliances_reference": {
        "space_heater": {
            "value": GAS_SPACE_HEATER,  # $4500
            "unit": "$",
            "efficiency": GAS_FURNACE_EFFICIENCY,
            "sources": [
                "https://ww2.arb.ca.gov/our-work/programs/technology-clearinghouse/technology-clearinghouse-tools/residential-appliance-comparison"
            ]
        },
        "water_heater": {
            "value": GAS_WATER_HEATER,  # $900
            "unit": "$",
            "efficiency": GAS_WATER_HEATER_EFFICIENCY,
            "sources": [
                "https://ww2.arb.ca.gov/our-work/programs/technology-clearinghouse/technology-clearinghouse-tools/residential-appliance-comparison"
            ]
        },
        "cookstove": {
            "value": GAS_COOKSTOVE,  # $1600
            "unit": "$",
            "sources": [
                "https://ww2.arb.ca.gov/our-work/programs/technology-clearinghouse/technology-clearinghouse-tools/residential-appliance-comparison"
            ]
        },
        "centralized_ac": {
            "value": CENTRALIZED_AC_COST,  # $5930
            "unit": "$",
            "sources": [
                "https://escholarship.org/content/qt0818n68p/qt0818n68p.pdf",
                "https://www.forbes.com/home-improvement/hvac/central-ac-unit-cost/"
            ]
        }
    }
}

def apply_incentives(total_cost, utility):
    total_cost_after_incentives = total_cost * (1 - INCENTIVES["federal_tax_credit_2023_2032"]) - INCENTIVES["PGE_SCE_SDGE_General_SGIP_Rebate"]

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
    base_cost = CAPITAL_COSTS_CRIS["heat_pump"]["average_residential"]["base"]["value"]
    federal_tax_credit = min(base_cost * 0.3, INCENTIVES["heat_pump"]["max_federal_annual_tax_rebate"]) 
    rebate = federal_tax_credit + INCENTIVES["heat_pump"]["california_TECH_incentive"] + INCENTIVES["heat_pump"]["other_rebates"]

    return base_cost - rebate

def calculate_induction_stove_cost():
    base_cost = CAPITAL_COSTS_CRIS["induction_stove"]["average_residential"]["base"]["value"]
    rebate = INCENTIVES["induction_stove"]["max_federal_annual_tax_rebate"]
    return base_cost - rebate

def calculate_water_heater_cost(tank_size: str = "55-75gal"):
    base_cost = CAPITAL_COSTS_CRIS["water_heater"]["electric_55gal"]["base"]["value"]
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
    
    USING CRIS CAPITAL_COSTS_CRIS STRUCTURE (2025 DATA)
    
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
            CAPITAL_COSTS_CRIS["solar"]["panel"]["base"]["value"],
            CAPITAL_COSTS_CRIS["solar"]["panel"]["markup"]["installation_labor"]["value"] / 100,
            CAPITAL_COSTS_CRIS["solar"]["panel"]["markup"]["design_engineering"]["value"] / 100,
            CAPITAL_COSTS_CRIS["storage"]["tesla_powerwall_3"]["base"]["value"]
        )
        solar_cost_after_incentives = apply_solar_storage_incentives(base_solar_cost, utility)
        print("Solar cost (CRIS 2025): ", solar_cost_after_incentives)
        total_cost += solar_cost_after_incentives
        components["solar_storage"] = solar_cost_after_incentives
        lifetimes.append(LIFETIMES["solar"])
        lifetimes.append(LIFETIMES["storage"])

    if include_heat_pump:
        hp_cost = calculate_heat_pump_cost()
        print("Heat pump cost (CRIS 2025): ", hp_cost)
        total_cost += hp_cost
        components["heat_pump"] = hp_cost
        lifetimes.append(LIFETIMES["heat_pump"])

    if include_induction:
        stove_cost = calculate_induction_stove_cost()
        print("Stove cost (CRIS 2025): ", stove_cost)
        total_cost += stove_cost
        components["induction_stove"] = stove_cost
        lifetimes.append(LIFETIMES["induction_stove"])

    if include_water_heater:
        water_heater_cost = calculate_water_heater_cost(water_heater_tank_size)
        print("Water heater cost (CRIS 2025): ", water_heater_cost)
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
    
    USING CRIS CAPITAL_COSTS_CRIS STRUCTURE (2025 DATA)
    
    For each county, the script will:
        1. Look up the solar capacity from the electrified assets file.
        2. Load the latest cost CSV files (baseline and solar+storage) from the county folder.
        3. For the chosen utility, it computes annual savings, total system cost, the cost after incentives, and payback period.
        4. Merge the results with the California counties shapefile.
        5. Construct Folium maps (one for each metric) that are saved individually.
        
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
            print(f"--- {county} (CRIS 2025 CAPITAL COSTS) ---")
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

    scenario_output_dir = os.path.join(base_output_dir, scenario, housing_type, "RESULTS_CRIS_2025_CAPITAL_COSTS")
    maps_dir = os.path.join(scenario_output_dir, "maps")
    geojson_dir = os.path.join(scenario_output_dir, "geojson")

    # Create directories if they don't exist
    os.makedirs(maps_dir, exist_ok=True)
    os.makedirs(geojson_dir, exist_ok=True)

    geojson_path = os.path.join(
        geojson_dir,
        f"{scenario}_cris_2025_capital_costs.geojson"
    )

    merged_gdf.to_file(geojson_path, driver="GeoJSON")
    print(f"Saved CRIS 2025 CAPITAL COSTS GeoJSON to {geojson_path}")
        
    metrics = ["Payback Period", "Solar Size (kW)"]
    variants = [f"{scenario}_only", f"{scenario}_solar"]

    for metric in metrics:
        for variant in variants:
            m = build_metric_map(
                merged_gdf,
                desired_rate_plans,
                metric=metric,
                variant=variant,
                title_prefix=f"{scenario.replace('_', ' ').title()} (CRIS 2025 Capital Costs): "
            )
            filename = f"{metric.lower().replace(' ', '_')}_{variant}_cris_2025_capital_costs.html"
            output_path = os.path.join(maps_dir, filename)
            m.save(output_path)
            print(f"Saved CRIS 2025 CAPITAL COSTS map: {output_path}")
            os.system(f'open "{output_path}"')

if __name__ == '__main__':
    base_input_dir = "data/loadprofiles"
    base_output_dir = "data/loadprofiles"
    scenario = "heat_pump_and_induction_stove_and_water_heating" 
    housing_type = "single-family-detached"
    
    desired_rate_plans = {
        "PG&E": {"electricity": "E-TOU-D", "gas": "G-1"},
        "SCE": {"electricity": "TOU-D-4-9PM", "gas": "GR"},
        "SDG&E": {"electricity": "TOU-DR1", "gas": "GR"}
    }

    all_counties = norcal_counties + socal_counties + central_counties
    log(scenario = scenario)
    process(base_input_dir, base_output_dir, scenario, housing_type, all_counties, desired_rate_plans)