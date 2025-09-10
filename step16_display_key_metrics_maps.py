"""
Step 16: Display Key Metrics Maps

Display diagnostic maps for key metrics in a single HTML file:
- Average solar panel size in county
- Total annual electricity bill in county, in $
- Total annual gas bill in county, in $
- Total annual energy consumption (electricity kWh, gas therms)
- Solar+storage annual savings vs non-solar deployment, in $
- Capital costs (net outlay with full incentives) for scenario appliances, in $
- Payback period (years) for electrification investments with full incentives
- Net grid consumption (kWh) - what the meter sees after solar+storage
- Total energy consumption (kWh) - gross load before solar offset
"""

import os
import pandas as pd
import folium
from folium import plugins
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import io
import base64
from helpers.maps_helpers import (
    initialize_map, load_cost_data, add_choropleth_layer, 
    add_centroid_labels, add_map_title, export_geojson_and_html,
    get_latest_csv_file
)
from main_helpers import log, slugify_county_name, to_decimal_number, norcal_counties, central_counties, socal_counties


def format_currency_with_sign(value: float) -> str:
    """Format currency values with appropriate sign for savings/costs."""
    if value > 0:
        return f"+${to_decimal_number(abs(value))}"
    elif value < 0:
        return f"-${to_decimal_number(abs(value))}"
    else:
        return "$0"


def format_payback_period(years: float) -> str:
    """Format payback period with appropriate handling for edge cases."""
    if years >= 100:
        return ">100 years"
    elif years <= -100 or years < 0:
        return "No payback (costs more)"
    else:
        return f"{years:.1f} years"


# Bin ranges for map visualizations
SOLAR_SIZE_BINS = [0, 2, 4, 6, 8, 10, 12, 15, 20]
ENERGY_CONSUMPTION_BINS = [0, 10000, 20000, 30000, 40000, 50000, 60000, 80000, 100000]
ELECTRICITY_BILL_BINS = [0, 1000, 2000, 3000, 4000, 5000, 6000, 8000, 10000]
GAS_BILL_BINS = [0, 500, 1000, 1500, 2000, 2500, 3000, 4000]
SAVINGS_BINS = [-2000, -1000, -500, 0, 500, 1000, 1500, 2000, 3000]
CAPITAL_COSTS_BINS = [-1000, 0, 5000, 10000, 15000, 20000, 25000, 30000, 40000, 50000, 100000]
PAYBACK_PERIOD_BINS = [0, 5, 10, 15, 20, 25, 30, 50, 100]
NET_GRID_CONSUMPTION_BINS = [0, 5000, 10000, 15000, 20000, 25000, 30000, 40000, 50000]
TOTAL_ELECTRICITY_CONSUMPTION_BINS = [0, 2000, 4000, 6000, 8000, 10000, 12000, 14000, 16000],
BATTERY_ENERGY_BINS = [0, 1000, 2000, 3000, 4000, 5000, 6000, 8000, 10000]
SOLAR_ENERGY_BINS = [0, 5000, 10000, 15000, 20000, 25000, 30000, 40000, 50000]


def load_solar_data(base_input_dir: str, scenario: str, housing_type: str, county_slug: str) -> float:
    """
    Load solar capacity data from electrified assets CSV using capital_costs_helper.
    """
    try:
        from helpers.capital_costs_helper import load_electrified_assets
        from main_helpers import get_scenario_path, slugify_county_name
        
        # Get the scenario path and load electrified assets
        scenario_path = get_scenario_path(base_input_dir, scenario, housing_type)
        assets_mapping = load_electrified_assets(scenario_path)
        
        if county_slug in assets_mapping:
            return float(assets_mapping[county_slug])
        else:
            return 0.0
            
    except Exception as e:
        print(f"Warning: Could not load solar data for {county_name}: {e}")
        return 0.0


def load_energy_consumption_data(
    base_input_dir: str,
    scenario: str,
    housing_type: str,
    county_slug: str
) -> tuple[float, float]:
    """
    Load annual energy consumption data for county.
    Returns (electricity_kwh, gas_therms)
    """
    county_dir = os.path.join(base_input_dir, scenario, housing_type, county_slug)
    file_name = f"loadprofiles_for_rates_{county_slug}.csv"
    file_path = os.path.join(county_dir, file_name)

    if not os.path.isfile(file_path):
        print(f"Warning: Cannot find {file_path}")
        return 0.0, 0.0

    try:
        df = pd.read_csv(file_path, low_memory=False)
        electricity_kwh = float(df["default.electricity.kwh"].sum())
        gas_therms = float(df["default.gas.therms"].sum())
        return electricity_kwh, gas_therms
    except Exception as exc:
        print(f"Warning: could not parse {file_path}: {exc}")
        return 0.0, 0.0


def load_solar_savings_data(
    base_input_dir: str,
    scenario: str,
    housing_type: str,
    county_slug: str,
    rate_plan: str = "PG&E.E-TOU-D+PG&E.G-1"
) -> float:
    """
    Load annual cost difference between solar+storage and non-solar scenarios.
    Returns savings (positive) or extra costs (negative) in dollars.
    """
    county_dir = os.path.join(base_input_dir, scenario, housing_type, county_slug)
    
    # Find the latest total annual costs file
    results_dir = os.path.join(county_dir, "results", "totals")
    if not os.path.exists(results_dir):
        print(f"Warning: Results directory not found: {results_dir}")
        return 0.0
    
    file_path = get_latest_csv_file(results_dir, f"RESULTS_total_annual_costs_{county_slug}")
    if not file_path:
        print(f"Warning: No total costs file found for {county_slug}")
        return 0.0
    
    try:
        df = pd.read_csv(file_path, low_memory=False)
        
        # Find baseline and solar+storage costs
        baseline_cost = None
        solar_cost = None
        
        column_name = f"total.{rate_plan}"
        if column_name not in df.columns:
            # Use first available column
            column_name = [col for col in df.columns if col.startswith("total.")][0]
        
        for _, row in df.iterrows():
            scenario_name = row['scenario']
            if scenario_name == scenario:
                baseline_cost = float(row[column_name])
            elif scenario_name == f"{scenario}.solarstorage":
                solar_cost = float(row[column_name])
        
        if baseline_cost is not None and solar_cost is not None:
            # Return savings (positive = savings, negative = extra cost)
            return baseline_cost - solar_cost
        else:
            print(f"Warning: Could not find both baseline and solar costs for {county_slug}")
            return 0.0
            
    except Exception as exc:
        print(f"Warning: could not parse {file_path}: {exc}")
        return 0.0


def load_capital_costs_data(
    base_input_dir: str,
    scenario: str,
    housing_type: str,
    county_slug: str
) -> float:
    """
    Load capital costs for the scenario from step15 capital costs files.
    Returns the total net cost for all appliances with full incentives.
    """
    # Capital costs files are in base_input_dir/capital_costs/
    capital_costs_dir = os.path.join(base_input_dir, "capital_costs")
    if not os.path.exists(capital_costs_dir):
        print(f"Warning: Capital costs directory not found: {capital_costs_dir}")
        return 0.0
    
    # Look for the detailed file: capital_costs_{scenario}_{housing_type}.csv
    base_name = f"{scenario}_{housing_type.replace('-', '_')}"
    capital_costs_file = f"capital_costs_{base_name}.csv"
    file_path = os.path.join(capital_costs_dir, capital_costs_file)
    
    if not os.path.exists(file_path):
        print(f"Warning: Capital costs file not found: {file_path}")
        return 0.0
    
    try:
        df = pd.read_csv(file_path, low_memory=False)
        
        # Convert county_slug back to county name for matching
        county_name = county_slug.replace("-", " ").title()
        if not county_name.endswith(" County"):
            county_name += " County"
        
        # Filter for this county and full incentives scenario
        county_data = df[
            (df['county'].str.contains(county_name.replace(" County", ""), case=False, na=False)) &
            (df['incentive_scenario'] == 'full_incentives')
        ]
        
        if county_data.empty:
            print(f"Warning: No capital costs data found for {county_name} with full incentives")
            return 0.0
        
        # Check if net_cost column exists
        if 'net_cost' not in df.columns:
            print(f"Warning: net_cost column not found in {file_path}")
            return 0.0
        
        # Sum up all net costs for this county with full incentives
        total_net_cost = county_data['net_cost'].sum()
        return float(total_net_cost)
        
    except Exception as exc:
        print(f"Warning: could not parse capital costs file {file_path}: {exc}")
        return 0.0


def load_payback_period_data(
    scenario: str,
    housing_type: str,
    county_slug: str
) -> float:
    """
    Load payback period data from step16_payback_periods.py output.
    Returns payback period in years with full incentives.
    """
    # Payback period files are in data/results/{housing_type}/
    payback_file = os.path.join("data", "results", housing_type, f"payback_periods_{scenario}.csv")
    
    if not os.path.exists(payback_file):
        print(f"Warning: Payback periods file not found: {payback_file}")
        return 0.0
    
    try:
        df = pd.read_csv(payback_file, low_memory=False)
        
        # Convert county_slug back to county name for matching
        county_name = county_slug.replace("-", " ").title()
        if not county_name.endswith(" County"):
            county_name += " County"
        
        # Filter for this county and full incentives scenario
        county_data = df[
            (df['county'].str.contains(county_name.replace(" County", ""), case=False, na=False)) &
            (df['incentive_scenario'] == 'full_incentives')
        ]
        
        if county_data.empty:
            print(f"Warning: No payback period data found for {county_name} with full incentives")
            return 0.0
        
        # Check if payback_period_years column exists
        if 'payback_period_years' not in df.columns:
            print(f"Warning: payback_period_years column not found in {payback_file}")
            return 0.0
        
        # Get payback period (should be only one row per county-incentive combination)
        payback_years = county_data['payback_period_years'].iloc[0]
        
        # Handle infinite payback periods
        if payback_years == float('inf') or payback_years > 100:
            return 100.0  # Cap at 100 years for display purposes
        
        return float(payback_years)
        
    except Exception as exc:
        print(f"Warning: could not parse payback periods file {payback_file}: {exc}")
        return 0.0


def load_net_grid_consumption_data(
    base_input_dir: str,
    scenario: str,
    housing_type: str,
    county_slug: str
) -> float:
    """
    Load net grid consumption (what the meter sees after solar+storage).
    Returns annual kWh consumed from the grid.
    """
    county_dir = os.path.join(base_input_dir, scenario, housing_type, county_slug)
    
    # Try to find SAM optimized load profiles file
    sam_file_patterns = [
        f"sam_optimized_load_profiles_{county_slug}.csv",
        f"sam_optimized_load_profiles_{scenario}_{county_slug}.csv"
    ]
    
    for pattern in sam_file_patterns:
        sam_file_path = os.path.join(county_dir, pattern)
        if os.path.exists(sam_file_path):
            try:
                df = pd.read_csv(sam_file_path)
                if 'Grid to Load' in df.columns:
                    # Sum hourly values to get annual kWh
                    annual_net_grid = df['Grid to Load'].sum()
                    return float(annual_net_grid)
            except Exception as e:
                print(f"Warning: Error reading {sam_file_path}: {e}")
                continue
    
    # Fallback: try loadprofiles_for_rates file
    rates_file = os.path.join(county_dir, f"loadprofiles_for_rates_{county_slug}.csv")
    if os.path.exists(rates_file):
        try:
            df = pd.read_csv(rates_file)
            if 'solarstorage.electricity.kwh' in df.columns:
                annual_net_grid = df['solarstorage.electricity.kwh'].sum()
                return float(annual_net_grid)
        except Exception as e:
            print(f"Warning: Error reading {rates_file}: {e}")
    
    print(f"Warning: Could not find net grid consumption data for {county_slug} in scenario {scenario}")
    return 0.0


def load_total_consumption_data(
    base_input_dir: str,
    scenario: str,
    housing_type: str,
    county_slug: str
) -> float:
    """
    Load total energy consumption (gross load before solar offset).
    Returns annual kWh of total consumption.
    """
    county_dir = os.path.join(base_input_dir, scenario, housing_type, county_slug)
    
    # Try to find SAM optimized load profiles file
    sam_file_patterns = [
        f"sam_optimized_load_profiles_{county_slug}.csv",
        f"sam_optimized_load_profiles_{scenario}_{county_slug}.csv"
    ]
    
    for pattern in sam_file_patterns:
        sam_file_path = os.path.join(county_dir, pattern)
        if os.path.exists(sam_file_path):
            try:
                df = pd.read_csv(sam_file_path)
                if 'Load Profile' in df.columns:
                    # Sum hourly values to get annual kWh
                    annual_total = df['Load Profile'].sum()
                    return float(annual_total)
            except Exception as e:
                print(f"Warning: Error reading {sam_file_path}: {e}")
                continue
    
    # Fallback: try loadprofiles_for_rates file (baseline consumption)
    rates_file = os.path.join(county_dir, f"loadprofiles_for_rates_{county_slug}.csv")
    if os.path.exists(rates_file):
        try:
            df = pd.read_csv(rates_file)
            if 'default.electricity.kwh' in df.columns:
                annual_total = df['default.electricity.kwh'].sum()
                return float(annual_total)
        except Exception as e:
            print(f"Warning: Error reading {rates_file}: {e}")
    
    # Last fallback: combined profiles file
    combined_file = os.path.join(county_dir, f"combined_profiles_{scenario}_{county_slug}.csv")
    if os.path.exists(combined_file):
        try:
            df = pd.read_csv(combined_file)
            if 'electricity.real_and_simulated.for_typical_county_home.kwh' in df.columns:
                annual_total = df['electricity.real_and_simulated.for_typical_county_home.kwh'].sum()
                return float(annual_total)
        except Exception as e:
            print(f"Warning: Error reading {combined_file}: {e}")
    
    print(f"Warning: Could not find total consumption data for {county_slug} in scenario {scenario}")
    return 0.0


def load_battery_energy_data(
    base_input_dir: str,
    scenario: str,
    housing_type: str,
    county_slug: str
) -> float:
    """
    Load annual energy supported by battery (discharged to load).
    Returns annual kWh discharged from battery to load.
    """
    county_dir = os.path.join(base_input_dir, scenario, housing_type, county_slug)
    
    # Try to find SAM optimized load profiles file
    sam_file_patterns = [
        f"sam_optimized_load_profiles_{county_slug}.csv",
        f"sam_optimized_load_profiles_{scenario}_{county_slug}.csv"
    ]
    
    for pattern in sam_file_patterns:
        sam_file_path = os.path.join(county_dir, pattern)
        if os.path.exists(sam_file_path):
            try:
                df = pd.read_csv(sam_file_path)
                if 'Battery to Load' in df.columns:
                    # Sum hourly values to get annual kWh
                    annual_battery_energy = df['Battery to Load'].sum()
                    return float(annual_battery_energy)
            except Exception as e:
                print(f"Warning: Error reading {sam_file_path}: {e}")
                continue
    
    print(f"Warning: Could not find battery energy data for {county_slug} in scenario {scenario}")
    return 0.0


def load_solar_energy_data(
    base_input_dir: str,
    scenario: str,
    housing_type: str,
    county_slug: str
) -> float:
    """
    Load annual energy supported by solar (directly to load, not including battery charging).
    Returns annual kWh from solar directly to load.
    """
    county_dir = os.path.join(base_input_dir, scenario, housing_type, county_slug)
    
    # Try to find SAM optimized load profiles file
    sam_file_patterns = [
        f"sam_optimized_load_profiles_{county_slug}.csv",
        f"sam_optimized_load_profiles_{scenario}_{county_slug}.csv"
    ]
    
    for pattern in sam_file_patterns:
        sam_file_path = os.path.join(county_dir, pattern)
        if os.path.exists(sam_file_path):
            try:
                df = pd.read_csv(sam_file_path)
                if 'System to Load' in df.columns:
                    # Sum hourly values to get annual kWh
                    annual_solar_energy = df['System to Load'].sum()
                    return float(annual_solar_energy)
            except Exception as e:
                print(f"Warning: Error reading {sam_file_path}: {e}")
                continue
    
    # Fallback: try to get total solar generation from PV system if available
    # This would be total solar generation, not just direct to load
    try:
        # Look for solar generation files
        sam_results_dir = os.path.join(county_dir, "results", "solarstorage")
        if os.path.exists(sam_results_dir):
            # Try to find latest solar generation file
            for file in os.listdir(sam_results_dir):
                if file.startswith("RESULTS_solar_generation_") and file.endswith(".csv"):
                    solar_file_path = os.path.join(sam_results_dir, file)
                    df = pd.read_csv(solar_file_path)
                    # Look for solar generation column
                    for col in df.columns:
                        if 'solar' in col.lower() and 'generation' in col.lower():
                            return float(df[col].iloc[0]) if len(df) > 0 else 0.0
    except Exception as e:
        pass
    
    print(f"Warning: Could not find solar energy data for {county_slug} in scenario {scenario}")
    return 0.0


def load_appliance_breakdown_data(
    base_input_dir: str,
    scenario: str, 
    housing_type: str,
    county_slug: str
) -> dict:
    """
    Load appliance breakdown data by end-use category with proper time series handling.
    
    IMPORTANT: Only loads ELECTRIFIED end-uses for pie charts:
    - For baseline: Shows only electricity end-uses (lighting, appliances, cooling, etc.) - NO gas appliances
    - For electrified scenarios: Shows electricity end-uses + electrified appliances (Heat Pump, Induction, etc.)
    
    This approach provides meaningful comparison of electric load patterns across scenarios.
    Gas appliances are intentionally excluded to focus on electric consumption breakdown.
    
    Returns dictionary with appliance categories and their annual kWh consumption.
    """
    appliance_data = {}
    
    # Define appliance categories based on the actual data structure
    electricity_categories = {
        "Cooling": ["ceiling_fan"],
        "Appliances": ["clothes_dryer", "dishwasher", "freezer", "refrigerator"],
        "Lighting": ["lighting_garage", "lighting_interior"],
        "Plug Loads": ["plug_loads"],
        "Pool/Spa": ["permanent_spa_heat", "permanent_spa_pump", "pool_heater", "pool_pump"],
        "Other Electric": ["mech_vent"]
    }
    
    gas_categories = {
        "Heating": ["heating"],
        "Hot Water": ["hot_water"], 
        "Cooking": ["range_oven"],
        "Other Gas": ["clothes_dryer", "fireplace"]
    }
    
    # Define which gas appliances remain in each scenario (based on step7 SCENARIO_DATA_MAP)
    scenario_gas_appliances = {
        "baseline": ["heating", "hot_water", "range_oven"],
        "baseline_ev_car": ["heating", "hot_water", "range_oven"], 
        "baseline_ice_car": ["heating", "hot_water", "range_oven"],
        "heat_pump": ["hot_water", "range_oven"],  # heating becomes electric
        "induction_stove": ["heating", "hot_water"],  # cooking becomes electric
        "heat_pump_and_induction_stove": ["hot_water"],  # heating and cooking become electric
        "water_heating": ["heating", "range_oven"],  # hot water becomes electric
        "heat_pump_and_induction_stove_and_water_heating": [],  # all become electric
        "full_electric_ev": [],  # all electric
    }
    
    # For electricity loads, ALWAYS use baseline data (individual appliance breakdown only exists in baseline)
    baseline_electricity_dir = os.path.join(base_input_dir, "baseline", housing_type, county_slug)
    electricity_file = os.path.join(baseline_electricity_dir, f"electricity_loads_{county_slug}.csv")
    
    if os.path.exists(electricity_file):
        try:
            # Load with timestamp parsing and indexing
            df = pd.read_csv(electricity_file, parse_dates=['timestamp'])
            df.set_index('timestamp', inplace=True)
            
            for category, appliances in electricity_categories.items():
                category_consumption = pd.Series(0.0, index=df.index)
                for appliance in appliances:
                    col_name = f"out.electricity.{appliance}.energy_consumption"
                    if col_name in df.columns:
                        category_consumption += df[col_name]
                
                if category_consumption.sum() > 0:
                    appliance_data[category] = float(category_consumption.sum())
                    
        except Exception as e:
            print(f"Warning: Error reading baseline electricity loads for {county_slug}: {e}")
    else:
        print(f"Warning: Baseline electricity loads file not found: {electricity_file}")
    
    # IMPORTANT: For pie charts, we only show ELECTRIFIED end-uses, not gas appliances
    # Gas appliances are excluded from the pie chart to show only electric consumption breakdown
    # This makes the chart meaningful for understanding electric load patterns
    
    # Skip gas appliances entirely - pie chart shows only electrified end-uses
    print(f"Note: Excluding gas appliances from pie chart for {scenario} - showing only electrified end-uses")
    
    # Load simulated electric appliances for electrified scenarios
    if not scenario.startswith("baseline"):
        # For electrified scenarios, check scenario directory first, then fallback to baseline
        scenario_dir = os.path.join(base_input_dir, scenario, housing_type, county_slug)
        simulated_file = os.path.join(scenario_dir, f"electricity_loads_simulated_{county_slug}.csv")
        
        if not os.path.exists(simulated_file):
            # Fallback to baseline simulated data
            baseline_dir = os.path.join(base_input_dir, "baseline", housing_type, county_slug)
            simulated_file = os.path.join(baseline_dir, f"electricity_loads_simulated_{county_slug}.csv")
        
        if os.path.exists(simulated_file):
            try:
                # Load with timestamp parsing and resample 15-min to hourly
                df = pd.read_csv(simulated_file, parse_dates=['timestamp'])
                df.set_index('timestamp', inplace=True)
                df = df.resample('H').sum()  # Critical: resample 15-min intervals to hourly
                
                # Map simulated appliances to categories based on scenario
                simulated_categories = {
                    "Heat Pump": "simulated.electricity.heat_pump.energy_consumption.electricity.kwh",
                    "Induction Cooking": "simulated.electricity.induction_stove.energy_consumption.electricity.kwh",
                    "Electric Hot Water": "simulated.electricity.hot_water.energy_consumption.electricity.kwh"
                }
                
                for category, col_name in simulated_categories.items():
                    if col_name in df.columns:
                        consumption = df[col_name].sum()
                        if consumption > 0:
                            # Add electrified appliances based on scenario
                            if category == "Heat Pump" and scenario in ["heat_pump", "heat_pump_and_induction_stove", "heat_pump_and_induction_stove_and_water_heating", "full_electric_ev"]:
                                appliance_data["Heat Pump"] = float(consumption)
                            elif category == "Induction Cooking" and scenario in ["induction_stove", "heat_pump_and_induction_stove", "heat_pump_and_induction_stove_and_water_heating", "full_electric_ev"]:
                                appliance_data["Induction Cooking"] = float(consumption)
                            elif category == "Electric Hot Water" and scenario in ["water_heating", "heat_pump_and_induction_stove_and_water_heating", "full_electric_ev"]:
                                appliance_data["Electric Hot Water"] = float(consumption)
                                
            except Exception as e:
                print(f"Warning: Error reading simulated loads for {county_slug}: {e}")
    
    # Fallback: if no data found, return placeholder data for testing
    if not appliance_data:
        print(f"Warning: No appliance data found for {county_slug}. Using placeholder data.")
        appliance_data = {
            "Data Not Available": 1.0
        }
    
    return appliance_data


def create_appliance_breakdown_chart(
    base_input_dir: str,
    scenario: str,
    housing_type: str,
    county_slug: str
) -> str:
    """
    Create a pie chart showing appliance breakdown by end-use category.
    Returns base64 encoded PNG image string or HTML table if matplotlib not available.
    """
    appliance_data = load_appliance_breakdown_data(base_input_dir, scenario, housing_type, county_slug)
    
    try:
        if not appliance_data or "Data Not Available" in appliance_data:
            # Create empty chart
            fig, ax = plt.subplots(figsize=(8, 6))
            ax.text(0.5, 0.5, 'No appliance data available', 
                    ha='center', va='center', fontsize=14)
            ax.set_xlim(0, 1)
            ax.set_ylim(0, 1)
            ax.axis('off')
        else:
            # Create pie chart
            fig, ax = plt.subplots(figsize=(10, 8))
            
            categories = list(appliance_data.keys())
            values = list(appliance_data.values())
            
            # Define colors for different categories
            color_map = {
                "Heating": "#FF6B6B",
                "Heat Pump": "#FF8E53", 
                "Cooling": "#4ECDC4",
                "Hot Water": "#45B7D1",
                "Electric Hot Water": "#96CEB4",
                "Cooking": "#FFEAA7",
                "Induction Cooking": "#DDA0DD",
                "Appliances": "#FD79A8",
                "Lighting": "#FDCB6E",
                "Plug Loads": "#6C5CE7",
                "Pool/Spa": "#00B894",
                "Other Electric": "#A29BFE",
                "Other Gas": "#E17055"
            }
            
            colors = [color_map.get(cat, "#BDC3C7") for cat in categories]
            
            # Create pie chart
            wedges, texts, autotexts = ax.pie(values, labels=categories, colors=colors, autopct='%1.1f%%',
                                            startangle=90, textprops={'fontsize': 10})
            
            # Improve readability
            for autotext in autotexts:
                autotext.set_color('white')
                autotext.set_fontweight('bold')
            
            county_name = county_slug.replace('-', ' ').title()
            scenario_name = scenario.replace('_', ' ').title()
            ax.set_title(f'Annual Electricity Consumption by End-Use\n{county_name} County - {scenario_name} Scenario\n(Electrified End-Uses Only)', 
                        fontsize=14, fontweight='bold', pad=20)
            
            # Add total consumption
            total_kwh = sum(values)
            ax.text(0, -1.3, f'Total: {total_kwh:,.0f} kWh/year', 
                   ha='center', fontsize=12, fontweight='bold')
        
        # Convert to base64
        buffer = io.BytesIO()
        plt.tight_layout()
        plt.savefig(buffer, format='png', dpi=150, bbox_inches='tight')
        buffer.seek(0)
        image_base64 = base64.b64encode(buffer.getvalue()).decode()
        plt.close()
        
        return image_base64
        
    except ImportError:
        # Fallback to HTML table if matplotlib not available
        return create_appliance_html_table(appliance_data, county_slug, scenario)
    except Exception as e:
        print(f"Error creating chart: {e}")
        return create_appliance_html_table(appliance_data, county_slug, scenario)


def create_appliance_html_table(appliance_data: dict, county_slug: str, scenario: str) -> str:
    """
    Create an HTML table showing appliance breakdown when charts are not available.
    Returns HTML table as string.
    """
    county_name = county_slug.replace('-', ' ').title()
    scenario_name = scenario.replace('_', ' ').title()
    
    if not appliance_data or "Data Not Available" in appliance_data:
        return f"""
        <div style="text-align: center; padding: 40px; border: 1px solid #ddd; border-radius: 8px;">
            <h3>{county_name} County - {scenario_name} Scenario</h3>
            <p>No appliance data available for this county</p>
        </div>
        """
    
    # Sort by consumption 
    total_kwh = sum(appliance_data.values())
    sorted_data = sorted(appliance_data.items(), key=lambda x: x[1], reverse=True)
    
    # Create HTML table
    table_rows = ""
    for category, kwh in sorted_data:
        percentage = (kwh / total_kwh) * 100 if total_kwh > 0 else 0
        table_rows += f"""
        <tr>
            <td style="text-align: left; padding: 8px; border-bottom: 1px solid #eee;">{category}</td>
            <td style="text-align: right; padding: 8px; border-bottom: 1px solid #eee;">{kwh:,.0f}</td>
            <td style="text-align: right; padding: 8px; border-bottom: 1px solid #eee;">{percentage:.1f}%</td>
        </tr>
        """
    
    return f"""
    <div style="border: 1px solid #ddd; border-radius: 8px; padding: 15px;">
        <h3 style="text-align: center; margin-bottom: 15px; color: #333;">
            {county_name} County - {scenario_name} Scenario
        </h3>
        <p style="text-align: center; margin-bottom: 15px; color: #666;">
            Electricity Consumption by End-Use (Electrified Only)<br>
            Total: {total_kwh:,.0f} kWh/year
        </p>
        <table style="width: 100%; border-collapse: collapse; font-family: Arial, sans-serif;">
            <thead>
                <tr style="background-color: #f5f5f5;">
                    <th style="text-align: left; padding: 12px; border-bottom: 2px solid #ddd;">End Use</th>
                    <th style="text-align: right; padding: 12px; border-bottom: 2px solid #ddd;">kWh/year</th>
                    <th style="text-align: right; padding: 12px; border-bottom: 2px solid #ddd;">%</th>
                </tr>
            </thead>
            <tbody>
                {table_rows}
            </tbody>
        </table>
    </div>
    """


def create_single_map(base_input_dir: str, scenario: str, housing_type: str, counties: list, 
                     metric_name: str, data_loader_config: dict) -> folium.Map:
    """
    Create a single diagnostic map for a specific metric.
    """
    # Initialize California county boundaries
    gdf = initialize_map()
    
    # Filter to requested counties
    county_names = [county.replace(" County", "") for county in counties]
    gdf = gdf[gdf["NAME"].isin(county_names)].copy()
    
    # Initialize metric columns
    gdf[metric_name] = 0.0
    gdf[f"{metric_name}_fmt"] = "N/A"
    
    # Load data for each county
    for _, row in gdf.iterrows():
        county_name = row["NAME"]
        county_slug = slugify_county_name(f"{county_name} County")
        county_dir = os.path.join(base_input_dir, scenario, housing_type, county_slug)
        
        try:
            # Special handling for different metrics
            if metric_name == "Solar Size (kW)":
                metric_value = load_solar_data(base_input_dir, scenario, housing_type, county_slug)
                
            elif metric_name == "Total Energy Consumption (kWh, therms)":
                elec_kwh, gas_thm = load_energy_consumption_data(
                    base_input_dir, scenario, housing_type, county_slug
                )
                # Use kWh equivalent for color mapping
                metric_value = elec_kwh + gas_thm * 29.3
                # Display both values in tooltip with better formatting
                elec_fmt = f"{elec_kwh:,.0f}" if elec_kwh >= 1000 else f"{elec_kwh:.0f}"
                gas_fmt = f"{gas_thm:,.0f}" if gas_thm >= 1000 else f"{gas_thm:.0f}"
                pretty = f"{elec_fmt} kWh<br>{gas_fmt} therms"
                gdf.loc[gdf["NAME"] == county_name, f"{metric_name}_fmt"] = pretty
                
            elif metric_name == "Solar+Storage Annual Savings ($)":
                metric_value = load_solar_savings_data(
                    base_input_dir, scenario, housing_type, county_slug
                )
                # Format with appropriate sign (+ for savings, - for extra costs)
                pretty = format_currency_with_sign(metric_value)
                gdf.loc[gdf["NAME"] == county_name, f"{metric_name}_fmt"] = pretty
                
            elif metric_name == "Capital Costs, Net After Incentives ($)":
                metric_value = load_capital_costs_data(
                    base_input_dir, scenario, housing_type, county_slug
                )

                # Format as currency
                pretty = f"${to_decimal_number(abs(metric_value))}"
                gdf.loc[gdf["NAME"] == county_name, f"{metric_name}_fmt"] = pretty
                
            elif metric_name == "Payback Period (years)":
                metric_value = load_payback_period_data(
                    scenario, housing_type, county_slug
                )
                # Format as years with 1 decimal place
                if metric_value >= 100:
                    pretty = ">100 years"
                else:
                    pretty = f"{metric_value:.1f} years"
                gdf.loc[gdf["NAME"] == county_name, f"{metric_name}_fmt"] = pretty
                
            elif metric_name == "Net Grid Consumption (kWh)":
                metric_value = load_net_grid_consumption_data(
                    base_input_dir, scenario, housing_type, county_slug
                )
                # Format as kWh with comma separators
                pretty = f"{to_decimal_number(metric_value)} kWh"
                gdf.loc[gdf["NAME"] == county_name, f"{metric_name}_fmt"] = pretty
                
            elif metric_name == "Total Energy Consumption (kWh)":
                metric_value = load_total_consumption_data(
                    base_input_dir, scenario, housing_type, county_slug
                )
                # Format as kWh with comma separators
                pretty = f"{to_decimal_number(metric_value)} kWh"
                gdf.loc[gdf["NAME"] == county_name, f"{metric_name}_fmt"] = pretty
                
            elif metric_name == "Battery Energy (kWh)":
                metric_value = load_battery_energy_data(
                    base_input_dir, scenario, housing_type, county_slug
                )
                # Format as kWh with comma separators
                pretty = f"{to_decimal_number(metric_value)} kWh"
                gdf.loc[gdf["NAME"] == county_name, f"{metric_name}_fmt"] = pretty
                
            elif metric_name == "Solar Energy (kWh)":
                metric_value = load_solar_energy_data(
                    base_input_dir, scenario, housing_type, county_slug
                )
                # Format as kWh with comma separators
                pretty = f"{to_decimal_number(metric_value)} kWh"
                gdf.loc[gdf["NAME"] == county_name, f"{metric_name}_fmt"] = pretty
                
            else:
                # Use load_cost_data to get metric data
                data = load_cost_data(
                    county_dir=county_dir,
                    subfolder=data_loader_config["subfolder"],
                    prefix=data_loader_config["prefix"],
                    scenario_row=data_loader_config["scenario_row"]
                )
                metric_value = float(data[data_loader_config["column"]])
            
            gdf.loc[gdf["NAME"] == county_name, metric_name] = metric_value
            
            # Only format if not already formatted (for energy consumption)
            if gdf.loc[gdf["NAME"] == county_name, f"{metric_name}_fmt"].iloc[0] == "N/A":
                gdf.loc[gdf["NAME"] == county_name, f"{metric_name}_fmt"] = to_decimal_number(metric_value)
            
        except Exception as e:
            print(f"Warning: Could not load {metric_name} data for {county_name}: {e}")
    
    m = folium.Map(
        location=[37.8, -120], 
        zoom_start=6, 
        zoom_control=False,
        width="450px", 
        height="350px"
    )
    
    # Add choropleth layer with error handling for bin issues
    try:
        add_choropleth_layer(
            m, gdf, metric_name,
            fill_color=data_loader_config["color_scheme"],
            bins=data_loader_config["bins"],
            legend_name=f"{metric_name} ({data_loader_config['unit']})"
        )
    except ValueError as e:
        if "All values are expected to fall into one of the provided bins" in str(e):
            # Debug: Print values outside bins
            values = gdf[metric_name].dropna()
            bins = data_loader_config["bins"]
            min_bin, max_bin = min(bins), max(bins)
            
            outside_values = values[(values < min_bin) | (values > max_bin)]
            
            print(f"\nERROR: Values outside bins for {metric_name}")
            print(f"Bins: {bins}")
            print(f"Bin range: {min_bin} to {max_bin}")
            print(f"Data range: {values.min():.2f} to {values.max():.2f}")
            print(f"Values outside bins ({len(outside_values)} total):")
            
            for idx, val in outside_values.items():
                county_name = gdf.loc[idx, "NAME"]
                print(f"  {county_name}: {val:.2f}")
            
            # Suggest new bins
            data_min, data_max = values.min(), values.max()
            suggested_min = min(min_bin, data_min * 0.9)  # 10% buffer below
            suggested_max = max(max_bin, data_max * 1.1)  # 10% buffer above
            print(f"\nSuggested bin range: {suggested_min:.0f} to {suggested_max:.0f}")
            
        raise e
    
    # Add county labels
    add_centroid_labels(m, gdf, metric_name)
    
    # Add tooltip layer
    tooltip = folium.GeoJsonTooltip(
        fields=["NAME", f"{metric_name}_fmt"],
        aliases=["County:", f"{metric_name}:"],
        localize=True
    )
    
    folium.GeoJson(
        gdf,
        style_function=lambda feature: {
            "fillColor": "transparent",
            "color": "black",
            "weight": 1,
            "fillOpacity": 0
        },
        tooltip=tooltip,
        name="County Info"
    ).add_to(m)
    
    return m


def create_appliance_breakdown_report(base_input_dir: str, scenario: str, housing_type: str, counties: list):
    """
    Create a standalone HTML report with appliance breakdown charts for all counties.
    """
    scenario_title = scenario.replace('_', ' ').title()
    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Appliance Breakdown Report - {scenario_title}</title>
        <meta charset="utf-8" />
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <style>
            body {{
                font-family: Arial, sans-serif;
                margin: 0;
                padding: 20px;
                background-color: #f5f5f5;
            }}
            .header {{
                text-align: center;
                margin-bottom: 30px;
                background-color: white;
                padding: 20px;
                border-radius: 8px;
                box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            }}
            .charts-grid {{
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(500px, 1fr));
                gap: 20px;
                max-width: 1400px;
                margin: 0 auto;
            }}
            .chart-container {{
                background-color: white;
                border-radius: 8px;
                padding: 15px;
                text-align: center;
                box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            }}
            .chart-title {{
                font-size: 16px;
                font-weight: bold;
                margin-bottom: 10px;
                color: #333;
            }}
        </style>
    </head>
    <body>
        <div class="header">
            <h1>Appliance Energy Consumption Breakdown</h1>
            <h2>{scenario_title} - {housing_type.replace('-', ' ').title()}</h2>
            <p>Annual energy consumption by end-use category for California counties</p>
        </div>
        
        <div class="charts-grid">
    """
    
    # Generate charts for all counties
    county_names = [county.replace(" County", "") for county in counties]
    for county_name in county_names:
        county_slug = slugify_county_name(f"{county_name} County")
        
        try:
            chart_data = create_appliance_breakdown_chart(base_input_dir, scenario, housing_type, county_slug)
            
            # Check if it's base64 image data or HTML table
            if chart_data.startswith('<div'):
                # It's an HTML table
                html_content += f"""
                    <div class="chart-container">
                        {chart_data}
                    </div>
                """
            else:
                # It's base64 image data
                html_content += f"""
                    <div class="chart-container">
                        <div class="chart-title">{county_name} County</div>
                        <img src="data:image/png;base64,{chart_data}" alt="Appliance breakdown for {county_name}" style="max-width: 100%; height: auto;">
                    </div>
                """
        except Exception as e:
            print(f"Error creating appliance chart for {county_name}: {e}")
    
    html_content += """
        </div>
    </body>
    </html>
    """
    
    # Save the report
    output_dir = os.path.join("visualizations", "appliance_breakdown", "html")
    os.makedirs(output_dir, exist_ok=True)
    
    filename = f"appliance_breakdown_{scenario}_{housing_type.replace(' ', '-').lower()}.html"
    output_path = os.path.join(output_dir, filename)
    
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(html_content)
    
    print(f"Appliance breakdown report saved to: {output_path}")


def create_combined_dashboard(base_input_dir: str, scenario: str, housing_type: str, counties: list):
    """
    Create a combined HTML dashboard with diagnostic maps for key electrification metrics.
    """
    
    # Define metrics configuration
    metrics_config = {
        "Solar Size (kW)": {
            "color_scheme": "YlOrBr",
            "bins": SOLAR_SIZE_BINS,
            "unit": "kW"
        },
        "Total Energy Consumption (kWh, therms)": {
            "color_scheme": "Greens",
            "bins": ENERGY_CONSUMPTION_BINS,
            "unit": "kWh equiv."
        },
        "Annual Electricity Bill ($)": {
            "subfolder": "electricity",
            "prefix": "RESULTS_electricity_annual_costs",
            "column": "electricity.PG&E.E-TOU-D",
            "scenario_row": 0,
            "color_scheme": "Reds",
            "bins": [0, 1000, 2000, 3000, 4000, 5000, 6000, 8000, 10000],
            "unit": "$"
        },
        "Annual Gas Bill ($)": {
            "subfolder": "gas",
            "prefix": "RESULTS_gas_annual_costs",
            "column": "gas.PG&E.G-1",
            "scenario_row": 0,
            "color_scheme": "Oranges",
            "bins": [0, 500, 1000, 1500, 2000, 2500, 3000, 4000],
            "unit": "$"
        },
        "Solar+Storage Annual Savings ($)": {
            "color_scheme": "RdYlGn",
            "bins": [-2000, -1000, -500, 0, 500, 1000, 1500, 2000, 3000],
            "unit": "$"
        },
        "Capital Costs, Net After Incentives ($)": {
            "color_scheme": "Blues",
            "bins": [-1000, 0, 5000, 10000, 15000, 20000, 25000, 30000, 40000, 50000, 100000],
            "unit": "$"
        },
        "Payback Period (years)": {
            "color_scheme": "RdYlGn_r",
            "bins": [0, 5, 10, 15, 20, 25, 30, 50, 100],
            "unit": "years"
        },
        "Net Grid Consumption (kWh)": {
            "color_scheme": "Reds",
            "bins": NET_GRID_CONSUMPTION_BINS,
            "unit": "kWh"
        },
        "Total Energy Consumption (kWh)": {
            "color_scheme": "Blues",
            "bins": TOTAL_ELECTRICITY_CONSUMPTION_BINS,
            "unit": "kWh"
        },
        "Battery Energy (kWh)": {
            "color_scheme": "Purples",
            "bins": BATTERY_ENERGY_BINS,
            "unit": "kWh"
        },
        "Solar Energy (kWh)": {
            "color_scheme": "Oranges",
            "bins": SOLAR_ENERGY_BINS,
            "unit": "kWh"
        },
    }
    
    # Create individual maps
    maps = {}
    for metric_name, config in metrics_config.items():
        print(f"Creating map for: {metric_name}")
        try:
            maps[metric_name] = create_single_map(
                base_input_dir, scenario, housing_type, counties, metric_name, config
            )
        except Exception as e:
            print(f"Error creating map for {metric_name}: {e}")
    
    # Create the combined HTML
    scenario_title = scenario.replace('_', ' ').title()
    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Diagnostic Maps - {scenario_title}</title>
        <meta charset="utf-8" />
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <style>
            body {{
                font-family: Arial, sans-serif;
                margin: 0;
                padding: 20px;
                background-color: #f5f5f5;
            }}
            .header {{
                text-align: center;
                margin-bottom: 30px;
                background-color: white;
                padding: 20px;
                border-radius: 8px;
                box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            }}
            .dashboard {{
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(450px, 1fr));
                gap: 20px;
                max-width: 1400px;
                margin: 0 auto;
            }}
            .map-container {{
                background-color: white;
                border-radius: 8px;
                padding: 15px;
                box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            }}
            .map-title {{
                font-size: 16px;
                font-weight: bold;
                margin-bottom: 10px;
                text-align: center;
                color: #333;
            }}
            .map-wrapper {{
                display: flex;
                justify-content: center;
            }}
            .charts-section {{
                margin-top: 40px;
                background-color: white;
                border-radius: 8px;
                padding: 20px;
                box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            }}
            .charts-grid {{
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(500px, 1fr));
                gap: 20px;
                margin-top: 20px;
            }}
            .chart-container {{
                background-color: #f8f9fa;
                border-radius: 8px;
                padding: 15px;
                text-align: center;
            }}
            .chart-title {{
                font-size: 14px;
                font-weight: bold;
                margin-bottom: 10px;
                color: #333;
            }}
        </style>
    </head>
    <body>
        <div class="header">
            <h1>Diagnostic Maps Dashboard</h1>
            <h2>{scenario_title} - {housing_type.replace('-', ' ').title()}</h2>
            <p>County-level analysis of key metrics for electrification scenario</p>
        </div>
        
        <div class="dashboard">
    """
    
    # Add each map to the HTML
    for i, (metric_name, map_obj) in enumerate(maps.items()):
        map_html = map_obj._repr_html_()
        html_content += f"""
            <div class="map-container">
                <div class="map-title">{metric_name}</div>
                <div class="map-wrapper">
                    {map_html}
                </div>
            </div>
        """
    
    html_content += """
        </div>
        
        <div class="charts-section">
            <h2>Appliance Energy Consumption Breakdown</h2>
            <p>Annual energy consumption by end-use category for selected counties</p>
            <div class="charts-grid">
    """
    
    # Generate appliance breakdown charts for a few representative counties
    sample_counties = ["Alameda", "Los Angeles", "San Diego", "Fresno"]
    for county_name in sample_counties:
        county_slug = slugify_county_name(f"{county_name} County")
        
        try:
            chart_data = create_appliance_breakdown_chart(base_input_dir, scenario, housing_type, county_slug)
            
            # Check if it's base64 image data or HTML table
            if chart_data.startswith('<div'):
                # It's an HTML table
                html_content += f"""
                    <div class="chart-container">
                        {chart_data}
                    </div>
                """
            else:
                # It's base64 image data
                html_content += f"""
                    <div class="chart-container">
                        <div class="chart-title">{county_name} County</div>
                        <img src="data:image/png;base64,{chart_data}" alt="Appliance breakdown for {county_name}" style="max-width: 100%; height: auto;">
                    </div>
                """
        except Exception as e:
            print(f"Error creating appliance chart for {county_name}: {e}")
            html_content += f"""
                <div class="chart-container">
                    <div class="chart-title">{county_name} County</div>
                    <p>Chart unavailable for this county</p>
                </div>
            """
    
    html_content += """
            </div>
        </div>
    </body>
    </html>
    """
    
    # Save the combined HTML file
    output_dir = os.path.join("visualizations", "diagnostic_maps", "html")
    os.makedirs(output_dir, exist_ok=True)
    
    filename = f"diagnostic_dashboard_{scenario}_{housing_type.replace(' ', '-').lower()}.html"
    output_path = os.path.join(output_dir, filename)
    
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(html_content)
    
    return output_path


def process(base_input_dir: str, base_output_dir: str, scenario: str, 
           housing_type: str, counties: list, desired_rate_plans: dict):
    """
    Display key metrics maps for the scenario in a combined dashboard.
    """
    
    log(
        at="step14_display_key_metrics_maps",
        info="starting_key_metrics_display",
        scenario=scenario,
        housing_type=housing_type,
        counties_requested=len(counties)
    )
    
    # Create combined dashboard
    try:
        dashboard_path = create_combined_dashboard(base_input_dir, scenario, housing_type, counties)
        
        # Also create standalone appliance breakdown report
        try:
            create_appliance_breakdown_report(base_input_dir, scenario, housing_type, counties)
            print(f"  - Created appliance breakdown report")
        except Exception as e:
            print(f"Warning: Could not create appliance breakdown report: {e}")
        
        # Auto-open in browser
        import webbrowser
        webbrowser.open(f'file://{os.path.abspath(dashboard_path)}')
        
        print(f"\nStep 16 complete! Created diagnostic dashboard:")
        print(f"  - File: {dashboard_path}")
        print(f"  - Opened in browser automatically")
        
        log(
            at="step14_display_key_metrics_maps",
            info="key_metrics_display_complete",
            scenario=scenario,
            housing_type=housing_type,
            counties_processed=len(counties),
            dashboard_path=dashboard_path
        )
        
        return [{"metric": "Combined Dashboard", "html_path": dashboard_path}]
        
    except Exception as e:
        print(f"Error creating dashboard: {e}")
        log(
            at="step14_display_key_metrics_maps",
            error=f"Failed to create dashboard: {e}",
            scenario=scenario
        )
        return []


def test_appliance_breakdown():
    """Test function to debug appliance breakdown functionality"""
    print("=" * 60)
    print("TESTING APPLIANCE BREAKDOWN FUNCTIONALITY")
    print("=" * 60)
    
    # Test scenarios and counties
    test_cases = [
        ("baseline", "alameda"),
        ("heat_pump_and_induction_stove", "alameda"),
        ("baseline", "los-angeles"),
        ("baseline", "san-diego")
    ]
    
    for scenario, county_slug in test_cases:
        print(f"\nTesting scenario: {scenario}, county: {county_slug}")
        print("-" * 40)
        
        data = load_appliance_breakdown_data(
            base_input_dir='data/loadprofiles',
            scenario=scenario,
            housing_type='single-family-detached',
            county_slug=county_slug
        )
        
        if data:
            print("SUCCESS: Found appliance data!")
            total_kwh = sum(data.values())
            print(f"Total consumption: {total_kwh:,.0f} kWh")
            for category, value in sorted(data.items(), key=lambda x: x[1], reverse=True):
                percentage = (value / total_kwh) * 100
                print(f"  {category}: {value:,.0f} kWh ({percentage:.1f}%)")
        else:
            print("FAILED: No appliance data found")
    
    print("\n" + "=" * 60)
    print("Creating test appliance breakdown report...")
    
    try:
        create_appliance_breakdown_report(
            base_input_dir='data/loadprofiles',
            scenario='baseline',
            housing_type='single-family-detached',
            counties=['Alameda County', 'Los Angeles County']
        )
        print("SUCCESS: Created appliance breakdown report")
    except Exception as e:
        print(f"FAILED: Could not create report: {e}")


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Display key metrics maps for electrification scenario")
    parser.add_argument("scenario", help="Electrification scenario to analyze (e.g., 'baseline', 'heat_pump', etc.)")
    parser.add_argument("--housing-type", default="single-family-detached", 
                       help="Housing type (default: single-family-detached)")
    parser.add_argument("--counties", nargs="+", default=norcal_counties + central_counties + socal_counties,
                       help="Counties to analyze (default: Alameda County)")
    parser.add_argument("--test-appliances", action="store_true",
                       help="Run appliance breakdown test instead of main process")
    
    args = parser.parse_args()
    
    if args.test_appliances:
        test_appliance_breakdown()
        exit()
    
    # Test configuration
    desired_rate_plans = {
        "PG&E": {"electricity": "E-TOU-D", "gas": "G-1"},
        "SCE": {"electricity": "TOU-D-4-9PM", "gas": "GR"},
        "SDG&E": {"electricity": "TOU-DR1", "gas": "GR"}
    }
    
    process(
        base_input_dir="data/loadprofiles",
        base_output_dir="data/loadprofiles",
        scenario=args.scenario,
        housing_type=args.housing_type,
        counties=args.counties,
        desired_rate_plans=desired_rate_plans
    )