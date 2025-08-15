"""
Step 15: Calculate Payback Period Data

Calculate payback periods for electrification scenarios and save to CSV files.
Based on:
- Annual savings from operational cost differences
- Capital costs from appliances and equipment
- County-specific data variations

Data Sources:
1. Capital Costs: data/loadprofiles/capital_costs/capital_costs_{scenario}_{housing_type}.csv
   - Created by step15_build_capital_costs_lifetimes_incentives.py
   - Contains: net_cost, total_cost_of_ownership by county and appliance
   
2. Annual Costs (Baseline): 
   - Electricity: {county_dir}/results/electricity/RESULTS_electricity_annual_costs_{county}_{timestamp}.csv
   - Gas: {county_dir}/results/gas/RESULTS_gas_annual_costs_{county}_{timestamp}.csv
   - Total: {county_dir}/results/totals/RESULTS_total_annual_costs_{county}_{timestamp}.csv
   
3. Annual Costs (Scenario):
   - Same structure as baseline, but for the specified electrification scenario
   
Payback Period Calculation:
- Annual Savings = Baseline Annual Costs - Scenario Annual Costs
- Payback Period = Net Capital Costs / Annual Savings (in years)

Output:
- CSV file: data/results/{housing_type}/payback_periods_{scenario}.csv
  Contains payback period data by county and incentive scenario
"""

import os
import pandas as pd
import numpy as np
from main_helpers import log, slugify_county_name, get_scenario_path, norcal_counties, socal_counties, central_counties
from helpers.maps_helpers import get_latest_csv_file

def load_capital_costs(base_output_dir: str, scenario: str, housing_type: str) -> pd.DataFrame:
    capital_costs_dir = os.path.join(base_output_dir, "capital_costs")
    csv_filename = f"capital_costs_{scenario}_{housing_type.replace('-', '_')}.csv"
    csv_path = os.path.join(capital_costs_dir, csv_filename)
    
    if not os.path.exists(csv_path):
        raise FileNotFoundError(f"Capital costs file not found: {csv_path}")
    
    return pd.read_csv(csv_path)

def load_annual_costs(county_dir: str, service: str, scenario: str) -> float:
    results_dir = os.path.join(county_dir, "results", service)
    county_name = os.path.basename(county_dir)
    
    # Use different prefixes based on service type
    if service == "electricity":
        prefix = f"RESULTS_electricity_annual_costs_{county_name}_"
    elif service == "gas":
        prefix = f"RESULTS_gas_annual_costs_{county_name}_"
    elif service in ["totals", "solarstorage"]:
        prefix = f"RESULTS_total_annual_costs_{county_name}_"
    else:
        raise ValueError(f"Unknown service type: {service}")
    
    try:
        latest_file = get_latest_csv_file(results_dir, prefix)
        df = pd.read_csv(latest_file, index_col="scenario")
        
        if scenario in df.index:
            return float(df.loc[scenario].iloc[0] if hasattr(df.loc[scenario], 'iloc') else df.loc[scenario])
        else:
            log(
                at="step15_payback_period_calculations",
                info="scenario_not_found",
                county=county_name,
                scenario=scenario,
                available_scenarios=list(df.index)
            )
            return 0.0
            
    except (FileNotFoundError, Exception) as e:
        log(
            at="step15_payback_period_calculations", 
            info="failed_to_load_annual_costs",
            county=county_name,
            service=service,
            scenario=scenario,
            error=str(e)
        )
        return 0.0

def calculate_payback_periods(base_input_dir: str, base_output_dir: str, scenario: str, 
                            housing_type: str, counties: list) -> pd.DataFrame:
    try:
        capital_costs_df = load_capital_costs(base_output_dir, scenario, housing_type)
        print(f"DEBUG: Loaded capital costs DataFrame with {len(capital_costs_df)} rows")
        print(f"DEBUG: Capital costs columns: {capital_costs_df.columns.tolist()}")
        if not capital_costs_df.empty:
            print(f"DEBUG: Unique counties in capital costs: {capital_costs_df['county'].unique()}")
            print(f"DEBUG: Unique incentive scenarios: {capital_costs_df['incentive_scenario'].unique()}")
    except FileNotFoundError as e:
        print(f"DEBUG: Capital costs file not found: {e}")
        log(
            at="step15_maps_payback_period",
            info="no_capital_costs_found",
            scenario=scenario,
            error=str(e),
            note="Run step15_build_capital_costs_lifetimes_incentives.py first"
        )
        return pd.DataFrame()
    
    if capital_costs_df.empty:
        print(f"DEBUG: Capital costs DataFrame is empty for scenario {scenario}")
        return pd.DataFrame()
    
    # Aggregate capital costs by county and incentive scenario
    capital_summary = capital_costs_df.groupby(['county', 'incentive_scenario']).agg({
        'net_cost': 'sum',
        'total_cost_of_ownership': 'sum'
    }).reset_index()
    
    print(f"DEBUG: Capital summary has {len(capital_summary)} rows")
    if not capital_summary.empty:
        print(f"DEBUG: Capital summary counties: {capital_summary['county'].unique()}")
    
    payback_data = []
    counties_processed = 0
    counties_with_data = 0
    
    for county in counties:
        county_slug = slugify_county_name(county)
        
        # Use get_scenario_path helper to get correct directory structure
        baseline_scenario_dir = get_scenario_path(base_input_dir, "baseline", housing_type)
        scenario_scenario_dir = get_scenario_path(base_input_dir, scenario, housing_type)
        
        # Add county to the path
        baseline_county_dir = os.path.join(baseline_scenario_dir, county_slug)
        scenario_county_dir = os.path.join(scenario_scenario_dir, county_slug)
        
        counties_processed += 1
        
        if not os.path.exists(baseline_county_dir):
            print(f"DEBUG: Baseline county directory not found: {baseline_county_dir}")
            continue
            
        if not os.path.exists(scenario_county_dir):
            print(f"DEBUG: Scenario county directory not found: {scenario_county_dir}")
            continue
        
        # Load annual costs for baseline and scenario
        baseline_total_cost = load_annual_costs(baseline_county_dir, "totals", "baseline")
        scenario_total_cost = load_annual_costs(scenario_county_dir, "totals", scenario)
        
        print(f"DEBUG: {county} - Baseline cost: {baseline_total_cost}, Scenario cost: {scenario_total_cost}")
        
        # Calculate annual savings (baseline - scenario)
        annual_savings = baseline_total_cost - scenario_total_cost
        
        if annual_savings <= 0:
            print(f"DEBUG: {county} - No savings (baseline: {baseline_total_cost}, scenario: {scenario_total_cost})")
            log(
                at="step15_payback_period_calculations",
                info="no_annual_savings",
                county=county,
                baseline_cost=baseline_total_cost,
                scenario_cost=scenario_total_cost,
                note="Payback period undefined when savings <= 0"
            )
            # Set payback to a very high number to indicate no savings
            annual_savings = 0.01  # Avoid division by zero
        
        # Get capital costs for this county
        county_capital = capital_summary[capital_summary['county'] == county]
        
        if county_capital.empty:
            print(f"DEBUG: No capital costs found for county: {county}")
            continue
        
        print(f"DEBUG: {county} - Found {len(county_capital)} capital cost entries")
        counties_with_data += 1
        
        for _, row in county_capital.iterrows():
            incentive_scenario = row['incentive_scenario']
            net_capital_cost = row['net_cost']
            
            # Calculate payback period in years
            payback_years = net_capital_cost / annual_savings if annual_savings > 0 else float('inf')
            
            print(f"DEBUG: {county} {incentive_scenario} - Capital: {net_capital_cost}, Savings: {annual_savings}, Payback: {payback_years}")
            
            payback_data.append({
                'county': county,
                'county_slug': county_slug,
                'scenario': scenario,
                'incentive_scenario': incentive_scenario,
                'baseline_annual_cost': baseline_total_cost,
                'scenario_annual_cost': scenario_total_cost,
                'annual_savings': annual_savings,
                'net_capital_cost': net_capital_cost,
                'payback_period_years': payback_years
            })
    
    print(f"DEBUG: Processed {counties_processed} counties, {counties_with_data} had capital cost data")
    print(f"DEBUG: Generated {len(payback_data)} payback data entries")
    
    return pd.DataFrame(payback_data)

def process(base_input_dir: str, base_output_dir: str, scenario: str, housing_type: str, counties: list):
    """
    Calculate payback period data for the specified electrification scenario and save to CSV.
    
    Args:
        base_input_dir: Input directory path
        base_output_dir: Output directory path
        scenario: Electrification scenario name
        housing_type: Housing type
        counties: List of counties to process
    """
    log(
        at="step15_payback_period_calculations",
        info="starting_payback_calculations",
        scenario=scenario,
        housing_type=housing_type,
        counties_count=len(counties)
    )
    
    # Calculate payback periods
    payback_df = calculate_payback_periods(base_input_dir, base_output_dir, scenario, housing_type, counties)

    if payback_df.empty:
        log(
            at="step15_payback_period_calculations",
            info="no_payback_data_calculated",
            scenario=scenario
        )
        return
    
    # Save payback data to CSV in data/results/single-family-detached/
    payback_output_dir = os.path.join("data", "results", housing_type)
    os.makedirs(payback_output_dir, exist_ok=True)
    
    payback_csv_path = os.path.join(payback_output_dir, f"payback_periods_{scenario}.csv")
    payback_df.to_csv(payback_csv_path, index=False)
    print(f"Payback period data saved: {payback_csv_path}")
    
    log(
        at="step15_payback_period_calculations",
        info="payback_data_completed",
        scenario=scenario,
        csv_path=payback_csv_path,
        average_payback=payback_df['payback_period_years'].mean()
    )

if __name__ == "__main__":
    import argparse
    from scenarios import SCENARIOS
    from main_helpers import norcal_counties, socal_counties, central_counties
    
    parser = argparse.ArgumentParser(description="Build payback period maps for electrification scenarios")
    parser.add_argument("scenario", 
                       choices=list(SCENARIOS.keys()),
                       help="Electrification scenario to analyze")
    
    args = parser.parse_args()

    # Fixed parameters
    housing_type = "single-family-detached"
    all_counties = norcal_counties + socal_counties + central_counties
    
    result = process(
        base_input_dir="data/loadprofiles",
        base_output_dir="data/loadprofiles", 
        scenario=args.scenario,
        housing_type=housing_type,
        counties=all_counties
    )