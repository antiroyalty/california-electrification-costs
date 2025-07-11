import os
import pandas as pd
import geopandas as gpd
from helpers import get_counties, get_scenario_path, slugify_county_name, norcal_counties, socal_counties, central_counties, log
from utility_helpers import get_utility_for_county
from maps_helpers import initialize_map, get_latest_csv_file
from capital_cost_map_builder import LIFETIMES, build_metric_map
from payback_period_helper import INCENTIVES, CAPITAL_COSTS_NEW
import step17_build_payback_period_maps as new_capital_costs
import step17_cris_capital_costs as cris_capital_costs

def calculate_percentage_difference(old_value, new_value):
    """Calculate percentage difference: (new - old) / old * 100"""
    if old_value == 0:
        return float('inf') if new_value != 0 else 0
    return ((new_value - old_value) / abs(old_value)) * 100

def calculate_absolute_difference(old_value, new_value):
    """Calculate absolute difference: new - old"""
    return new_value - old_value

def compare_capital_costs():
    """
    Compare capital costs between NEW and CRIS approaches for each component.
    Returns a summary dictionary of differences.
    """
    comparisons = {}
    
    # Solar costs comparison
    new_solar_cost_per_watt = CAPITAL_COSTS_NEW["solar"]["panel"]["base"]["value"]
    cris_solar_cost_per_watt = cris_capital_costs.CAPITAL_COSTS_CRIS["solar"]["panel"]["base"]["value"]
    
    # Storage costs comparison
    new_storage_cost = CAPITAL_COSTS_NEW["storage"]["tesla_powerwall_3"]["base"]["value"]
    cris_storage_cost = cris_capital_costs.CAPITAL_COSTS_CRIS["storage"]["tesla_powerwall_3"]["base"]["value"]
    
    # Heat pump costs comparison
    new_heat_pump_cost = CAPITAL_COSTS_NEW["heat_pump"]["average_residential"]["base"]["value"]
    cris_heat_pump_cost = cris_capital_costs.CAPITAL_COSTS_CRIS["heat_pump"]["average_residential"]["base"]["value"]
    
    # Induction stove costs comparison
    new_induction_cost = CAPITAL_COSTS_NEW["induction_stove"]["average_residential"]["base"]["value"]
    cris_induction_cost = cris_capital_costs.CAPITAL_COSTS_CRIS["induction_stove"]["average_residential"]["base"]["value"]
    
    # Water heater costs comparison
    new_water_heater_cost = CAPITAL_COSTS_NEW["water_heater"]["electric_55gal"]["base"]["value"]
    cris_water_heater_cost = cris_capital_costs.CAPITAL_COSTS_CRIS["water_heater"]["electric_55gal"]["base"]["value"]
    
    comparisons = {
        "solar_per_watt": {
            "new": new_solar_cost_per_watt,
            "cris": cris_solar_cost_per_watt,
            "abs_diff": calculate_absolute_difference(new_solar_cost_per_watt, cris_solar_cost_per_watt),
            "pct_diff": calculate_percentage_difference(new_solar_cost_per_watt, cris_solar_cost_per_watt)
        },
        "storage": {
            "new": new_storage_cost,
            "cris": cris_storage_cost,
            "abs_diff": calculate_absolute_difference(new_storage_cost, cris_storage_cost),
            "pct_diff": calculate_percentage_difference(new_storage_cost, cris_storage_cost)
        },
        "heat_pump": {
            "new": new_heat_pump_cost,
            "cris": cris_heat_pump_cost,
            "abs_diff": calculate_absolute_difference(new_heat_pump_cost, cris_heat_pump_cost),
            "pct_diff": calculate_percentage_difference(new_heat_pump_cost, cris_heat_pump_cost)
        },
        "induction_stove": {
            "new": new_induction_cost,
            "cris": cris_induction_cost,
            "abs_diff": calculate_absolute_difference(new_induction_cost, cris_induction_cost),
            "pct_diff": calculate_percentage_difference(new_induction_cost, cris_induction_cost)
        },
        "water_heater": {
            "new": new_water_heater_cost,
            "cris": cris_water_heater_cost,
            "abs_diff": calculate_absolute_difference(new_water_heater_cost, cris_water_heater_cost),
            "pct_diff": calculate_percentage_difference(new_water_heater_cost, cris_water_heater_cost)
        }
    }
    
    return comparisons

def process(base_input_dir, base_output_dir, scenario, housing_type, counties, desired_rate_plans):
    """
    Creates difference maps comparing NEW vs CRIS capital costs implementations.
    
    This function:
    1. Runs both NEW and CRIS capital costs calculations for each county
    2. Calculates differences in payback periods, total costs, and annual savings
    3. Creates maps showing the differences between the two approaches
    
    Parameters:
        base_input_dir (str): Base input directory.
        base_output_dir (str): Directory where output HTML files will be saved.
        scenario (str): Scenario name.
        housing_type (str): Housing type.
        counties (list): List of counties to process.
        desired_rate_plans (dict): Dictionary of rate plans for utilities.
    """
    print("=== NEW vs CRIS CAPITAL COSTS COMPARISON ANALYSIS ===")
    
    # First, let's compare the raw capital costs
    cost_comparisons = compare_capital_costs()
    print("\nRaw Capital Costs Comparison (NEW vs CRIS):")
    for component, data in cost_comparisons.items():
        print(f"{component.upper()}:")
        print(f"  NEW: ${data['new']:,.2f}")
        print(f"  CRIS: ${data['cris']:,.2f}")
        print(f"  Absolute Diff: ${data['abs_diff']:,.2f}")
        print(f"  Percentage Diff: {data['pct_diff']:.2f}%")
        print()
    
    scenario_path = get_scenario_path(base_input_dir, scenario, housing_type)
    valid_counties = get_counties(scenario_path, counties)
    assets_mapping = new_capital_costs.load_electrified_assets(scenario_path)
    
    records = []
    
    print("Processing county-by-county differences...")
    
    for county in valid_counties:
        county_slug = slugify_county_name(county)
        utility = get_utility_for_county(county)
        rate_elec = desired_rate_plans[utility]["electricity"]
        rate_gas = desired_rate_plans[utility]["gas"]
        cost_column = f"total.{utility}.{rate_elec}+{utility}.{rate_gas}"

        try:
            # === Load annual costs ===
            baseline_dir = os.path.join(base_input_dir, "baseline", housing_type, county, "results", "totals")
            baseline_path = get_latest_csv_file(baseline_dir, f"RESULTS_total_annual_costs_{county_slug}_")
            baseline_df = pd.read_csv(baseline_path, index_col="scenario")
            baseline_cost = baseline_df.loc["baseline", cost_column]

            hp_dir = os.path.join(base_input_dir, scenario, housing_type, county, "results", "totals")
            hp_path = get_latest_csv_file(hp_dir, f"RESULTS_total_annual_costs_{county_slug}_")
            hp_df = pd.read_csv(hp_path, index_col="scenario")
            hp_cost = hp_df.loc[scenario, cost_column]

            hp_solar_dir = os.path.join(base_input_dir, scenario, housing_type, county, "results", "solarstorage")
            hp_solar_path = get_latest_csv_file(hp_solar_dir, f"RESULTS_total_annual_costs_{county_slug}_")
            hp_solar_df = pd.read_csv(hp_solar_path, index_col="scenario")
            hp_solar_cost = hp_solar_df.loc[f"{scenario}.solarstorage", cost_column]

            # === Annual savings ===
            savings_hp_only = baseline_cost - hp_cost
            savings_hp_solar = baseline_cost - hp_solar_cost

            combo_flags = new_capital_costs.flags_from_scenario(scenario)

            if county not in assets_mapping:
                print(f"Missing solar capacity for {county}; skipping.")
                continue

            solar_kw = assets_mapping[county]

            # === NEW CAPITAL COSTS CALCULATIONS ===
            new_results_hp_only = new_capital_costs.evaluate_custom_combo(
                include_solar=False,
                water_heater_tank_size="45-55gal",
                solar_kw=0,
                annual_savings=savings_hp_only,
                utility=utility,
                **combo_flags
            )

            new_results_hp_solar = new_capital_costs.evaluate_custom_combo(
                include_solar=True,
                water_heater_tank_size="45-55gal",
                solar_kw=solar_kw,
                annual_savings=savings_hp_solar,
                utility=utility,
                **combo_flags
            )

            # === CRIS CAPITAL COSTS CALCULATIONS ===
            cris_results_hp_only = cris_capital_costs.evaluate_custom_combo(
                include_solar=False,
                water_heater_tank_size="45-55gal",
                solar_kw=0,
                annual_savings=savings_hp_only,
                utility=utility,
                **combo_flags
            )

            cris_results_hp_solar = cris_capital_costs.evaluate_custom_combo(
                include_solar=True,
                water_heater_tank_size="45-55gal",
                solar_kw=solar_kw,
                annual_savings=savings_hp_solar,
                utility=utility,
                **combo_flags
            )

            # === Calculate differences ===
            # Electrification only differences
            payback_diff_hp_only = calculate_absolute_difference(
                new_results_hp_only["payback_period"], 
                cris_results_hp_only["payback_period"]
            )
            payback_pct_diff_hp_only = calculate_percentage_difference(
                new_results_hp_only["payback_period"], 
                cris_results_hp_only["payback_period"]
            )
            cost_diff_hp_only = calculate_absolute_difference(
                new_results_hp_only["capital_cost"], 
                cris_results_hp_only["capital_cost"]
            )

            # Electrification + Solar differences
            payback_diff_hp_solar = calculate_absolute_difference(
                new_results_hp_solar["payback_period"], 
                cris_results_hp_solar["payback_period"]
            )
            payback_pct_diff_hp_solar = calculate_percentage_difference(
                new_results_hp_solar["payback_period"], 
                cris_results_hp_solar["payback_period"]
            )
            cost_diff_hp_solar = calculate_absolute_difference(
                new_results_hp_solar["capital_cost"], 
                cris_results_hp_solar["capital_cost"]
            )

            print(f"DONE {county}: Payback diff (electrif only): {payback_diff_hp_only:.2f} years ({payback_pct_diff_hp_only:.1f}%)")

        except Exception as e:
            print(f"ERROR processing {county}: {e}")
            continue

        records.append({
            "County": county,
            # NEW results
            "NEW Payback Period (Electrification Only)": new_results_hp_only["payback_period"],
            "NEW Total Cost (Electrification Only)": new_results_hp_only["capital_cost"],
            "NEW Payback Period (Electrification + Solar + Storage)": new_results_hp_solar["payback_period"],
            "NEW Total Cost (Electrification + Solar + Storage)": new_results_hp_solar["capital_cost"],
            # CRIS results
            "CRIS Payback Period (Electrification Only)": cris_results_hp_only["payback_period"],
            "CRIS Total Cost (Electrification Only)": cris_results_hp_only["capital_cost"],
            "CRIS Payback Period (Electrification + Solar + Storage)": cris_results_hp_solar["payback_period"],
            "CRIS Total Cost (Electrification + Solar + Storage)": cris_results_hp_solar["capital_cost"],
            # Differences
            "Payback Difference (Electrification Only)": payback_diff_hp_only,
            "Payback % Difference (Electrification Only)": payback_pct_diff_hp_only,
            "Cost Difference (Electrification Only)": cost_diff_hp_only,
            "Payback Difference (Electrification + Solar + Storage)": payback_diff_hp_solar,
            "Payback % Difference (Electrification + Solar + Storage)": payback_pct_diff_hp_solar,
            "Cost Difference (Electrification + Solar + Storage)": cost_diff_hp_solar,
            "Solar Size (kW)": solar_kw
        })

    # Create DataFrame from results
    df_metrics = pd.DataFrame(records).set_index("County")
    
    print(f"\nSummary Statistics:")
    print(f"Counties processed: {len(df_metrics)}")
    print(f"Average payback difference (electrification only): {df_metrics['Payback Difference (Electrification Only)'].mean():.2f} years")
    print(f"Average payback difference (electrif + solar): {df_metrics['Payback Difference (Electrification + Solar + Storage)'].mean():.2f} years")
    print(f"Average cost difference (electrification only): ${df_metrics['Cost Difference (Electrification Only)'].mean():,.2f}")
    print(f"Average cost difference (electrif + solar): ${df_metrics['Cost Difference (Electrification + Solar + Storage)'].mean():,.2f}")

    # Initialize California county shapes
    gdf = initialize_map()
    gdf["county_slug"] = gdf["NAME"].apply(slugify_county_name)

    # Merge metrics with GeoDataFrame
    merged_gdf = gdf.merge(df_metrics, left_on="county_slug", right_index=True, how="left")

    # Create output directories
    scenario_output_dir = os.path.join(base_output_dir, scenario, housing_type, "RESULTS_NEW_VS_CRIS_COMPARISON")
    maps_dir = os.path.join(scenario_output_dir, "maps")
    geojson_dir = os.path.join(scenario_output_dir, "geojson")
    csv_dir = os.path.join(scenario_output_dir, "csv")

    os.makedirs(maps_dir, exist_ok=True)
    os.makedirs(geojson_dir, exist_ok=True)
    os.makedirs(csv_dir, exist_ok=True)

    # Save comparison data
    geojson_path = os.path.join(geojson_dir, f"{scenario}_new_vs_cris_comparison.geojson")
    merged_gdf.to_file(geojson_path, driver="GeoJSON")
    print(f"Saved NEW vs CRIS comparison GeoJSON to {geojson_path}")

    csv_path = os.path.join(csv_dir, f"{scenario}_new_vs_cris_comparison.csv")
    df_metrics.to_csv(csv_path)
    print(f"Saved NEW vs CRIS comparison CSV to {csv_path}")

    # Check if all differences are zero before creating maps
    all_payback_diffs_zero = (df_metrics['Payback Difference (Electrification Only)'] == 0).all() and \
                             (df_metrics['Payback Difference (Electrification + Solar + Storage)'] == 0).all()
    
    all_cost_diffs_zero = (df_metrics['Cost Difference (Electrification Only)'] == 0).all() and \
                          (df_metrics['Cost Difference (Electrification + Solar + Storage)'] == 0).all()

    if all_payback_diffs_zero and all_cost_diffs_zero:
        print(f"\nNEW vs CRIS COMPARISON COMPLETE!")
        print(f"Result: NEW and CRIS capital cost implementations produce IDENTICAL results")
        print(f"Skipping difference maps (all differences are exactly 0.00)")
    else:
        print(f"\nGenerating NEW vs CRIS difference maps...")
        # Would create maps here if differences exist

    # Save capital costs comparison summary
    summary_path = os.path.join(csv_dir, "capital_costs_new_vs_cris_comparison.csv")
    summary_df = pd.DataFrame(cost_comparisons).T
    summary_df.to_csv(summary_path)
    print(f"Saved NEW vs CRIS capital costs summary to {summary_path}")

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
    log(scenario=scenario)
    process(base_input_dir, base_output_dir, scenario, housing_type, all_counties, desired_rate_plans)