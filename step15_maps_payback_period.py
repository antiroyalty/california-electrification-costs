"""
Step 15 Maps: Build Payback Period Maps

Build maps showing payback periods for electrification scenarios based on:
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

Maps Generated:
- Payback period by county for full incentives
- Payback period by county for half incentives  
- Payback period by county for no incentives
- Comparison maps between incentive scenarios
"""

import os
import pandas as pd
import numpy as np
import geopandas as gpd
import folium
from main_helpers import log, slugify_county_name, get_scenario_path, norcal_counties, socal_counties, central_counties
from helpers.maps_helpers import initialize_map, get_latest_csv_file, create_folium_map

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
                at="step15_maps_payback_period",
                info="scenario_not_found",
                county=county_name,
                scenario=scenario,
                available_scenarios=list(df.index)
            )
            return 0.0
            
    except (FileNotFoundError, Exception) as e:
        log(
            at="step15_maps_payback_period", 
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
                at="step15_maps_payback_period",
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


def create_payback_period_map(payback_df: pd.DataFrame, incentive_scenario: str, 
                             output_path: str) -> None:
    """
    Create a folium map showing payback periods by county.
    
    Args:
        payback_df: DataFrame with payback period data
        incentive_scenario: Incentive scenario to map
        output_path: Output HTML file path
    """
    # Filter data for the specific incentive scenario
    scenario_data = payback_df[payback_df['incentive_scenario'] == incentive_scenario].copy()
    
    if scenario_data.empty:
        log(
            at="step15_maps_payback_period",
            info="no_data_for_incentive_scenario",
            incentive_scenario=incentive_scenario
        )
        return
    
    # Load California counties geodata
    gdf = initialize_map()
    
    # Merge payback data with geodata
    gdf = gdf.merge(scenario_data, left_on='NAME', right_on='county_slug', how='left')
    
    # Create color mapping based on payback periods
    # Cap payback periods at 30 years for color mapping
    max_payback = min(scenario_data['payback_period_years'].max(), 30.0)
    min_payback = scenario_data['payback_period_years'].min()
    
    def get_payback_color(payback_years):
        if pd.isna(payback_years) or payback_years == float('inf'):
            return "#cccccc"  # Gray for no data or infinite payback
        
        # Normalize payback period to 0-1 range
        normalized = (payback_years - min_payback) / (max_payback - min_payback) if max_payback > min_payback else 0
        normalized = max(0, min(1, normalized))  # Clamp to 0-1
        
        # Color scale: Green (short payback) to Red (long payback)
        # Green: (0, 128, 0), Red: (255, 0, 0)
        r = int(255 * normalized)
        g = int(128 * (1 - normalized))
        b = 0
        
        return f"#{r:02x}{g:02x}{b:02x}"
    
    # Create map
    center_lat, center_lon = 36.7783, -119.4179  # California center
    m = folium.Map(location=[center_lat, center_lon], zoom_start=6)
    
    # Add choropleth layer
    for _, row in gdf.iterrows():
        if pd.notna(row.get('payback_period_years')):
            color = get_payback_color(row['payback_period_years'])
            popup_text = f"""
            <b>{row['NAME']} County</b><br>
            Payback Period: {row['payback_period_years']:.1f} years<br>
            Annual Savings: ${row['annual_savings']:,.0f}<br>
            Capital Cost: ${row['net_capital_cost']:,.0f}<br>
            Incentive Scenario: {incentive_scenario.replace('_', ' ').title()}
            """
        else:
            color = "#cccccc"
            popup_text = f"<b>{row['NAME']} County</b><br>No data available"
        
        folium.GeoJson(
            row['geometry'],
            style_function=lambda x, color=color: {
                'fillColor': color,
                'color': 'black',
                'weight': 1,
                'fillOpacity': 0.7
            },
            popup=folium.Popup(popup_text, max_width=300)
        ).add_to(m)
    
    # Add legend
    legend_html = f"""
    <div style="position: fixed; 
                bottom: 50px; left: 50px; width: 200px; height: 120px; 
                background-color: white; border:2px solid grey; z-index:9999; 
                font-size:14px; padding: 10px">
    <b>Payback Period (Years)</b><br>
    <i style="background: #00ff00; width: 20px; height: 20px; float: left; margin-right: 8px;"></i>
    {min_payback:.1f} (Best)<br>
    <i style="background: #ff0000; width: 20px; height: 20px; float: left; margin-right: 8px;"></i>
    {max_payback:.1f}+ (Worst)<br>
    <i style="background: #cccccc; width: 20px; height: 20px; float: left; margin-right: 8px;"></i>
    No data
    </div>
    """
    m.get_root().html.add_child(folium.Element(legend_html))
    
    # Save map
    m.save(output_path)
    log(
        at="step15_maps_payback_period",
        info="map_created",
        incentive_scenario=incentive_scenario,
        output_path=output_path,
        counties_with_data=len(scenario_data)
    )


def process(base_input_dir: str, base_output_dir: str, scenario: str, housing_type: str, counties: list):
    """
    Build payback period maps for the specified electrification scenario.
    
    Args:
        base_input_dir: Input directory path
        base_output_dir: Output directory path
        scenario: Electrification scenario name
        housing_type: Housing type
        counties: List of counties to process
    """
    log(
        at="step15_maps_payback_period",
        info="starting_payback_maps",
        scenario=scenario,
        housing_type=housing_type,
        counties_count=len(counties)
    )
    
    # Calculate payback periods
    payback_df = calculate_payback_periods(base_input_dir, base_output_dir, scenario, housing_type, counties)

    if payback_df.empty:
        log(
            at="step15_maps_payback_period",
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
    
    # Create maps directory
    maps_output_dir = os.path.join(base_output_dir, "maps", "payback_periods")
    os.makedirs(maps_output_dir, exist_ok=True)
    
    # Create maps for each incentive scenario
    incentive_scenarios = payback_df['incentive_scenario'].unique()
    
    for incentive_scenario in incentive_scenarios:
        map_filename = f"payback_period_map_{scenario}_{incentive_scenario}_{housing_type.replace('-', '_')}.html"
        map_path = os.path.join(maps_output_dir, map_filename)
        
        create_payback_period_map(payback_df, incentive_scenario, map_path)
        print(f"Payback period map created: {map_path}")
    
    # Auto-open the first map in the browser
    if len(incentive_scenarios) > 0:
        import webbrowser
        first_map_filename = f"payback_period_map_{scenario}_{incentive_scenarios[0]}_{housing_type.replace('-', '_')}.html"
        first_map_path = os.path.join(maps_output_dir, first_map_filename)
        webbrowser.open('file://' + os.path.abspath(first_map_path))
    
    log(
        at="step15_maps_payback_period",
        info="payback_maps_completed",
        scenario=scenario,
        maps_created=len(incentive_scenarios),
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