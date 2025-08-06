"""
Step 14: Display Key Metrics Maps

Display diagnostic maps for key metrics in a single HTML file:
- Average solar panel size in county
- Total annual electricity bill in county, in $
- Total annual gas bill in county, in $
- Total annual energy consumption (electricity kWh, gas therms)
"""

import os
import pandas as pd
import folium
from folium import plugins
from helpers.maps_helpers import (
    initialize_map, load_cost_data, add_choropleth_layer, 
    add_centroid_labels, add_map_title, export_geojson_and_html,
    get_latest_csv_file
)
from main_helpers import log, slugify_county_name, to_decimal_number


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
    county_name: str
) -> tuple[float, float]:
    """
    Load annual energy consumption data for county.
    Returns (electricity_kwh, gas_therms)
    """
    county_slug = slugify_county_name(f"{county_name} County")
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
                    base_input_dir, scenario, housing_type, county_name
                )
                # Use kWh equivalent for color mapping
                metric_value = elec_kwh + gas_thm * 29.3
                # Display both values in tooltip
                pretty = f"{to_decimal_number(elec_kwh)} kWh, {to_decimal_number(gas_thm)} therms"
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
    
    # Create map
    m = folium.Map(
        location=[37.8, -120], 
        zoom_start=6, 
        zoom_control=False,
        width="450px", 
        height="350px"
    )
    
    # Add choropleth layer
    add_choropleth_layer(
        m, gdf, metric_name,
        fill_color=data_loader_config["color_scheme"],
        bins=data_loader_config["bins"],
        legend_name=f"{metric_name} ({data_loader_config['unit']})"
    )
    
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


def create_combined_dashboard(base_input_dir: str, scenario: str, housing_type: str, counties: list):
    """
    Create a combined HTML dashboard with all 4 diagnostic maps.
    """
    
    # Define metrics configuration
    metrics_config = {
        "Solar Size (kW)": {
            "color_scheme": "YlOrBr",
            "bins": [0, 2, 4, 6, 8, 10, 12, 15, 20],
            "unit": "kW"
        },
        "Total Energy Consumption (kWh, therms)": {
            "color_scheme": "Greens",
            "bins": [0, 10000, 20000, 30000, 40000, 50000, 60000, 80000, 100000],
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
                grid-template-columns: 1fr 1fr;
                gap: 20px;
                max-width: 1200px;
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
        
        # Auto-open in browser
        import webbrowser
        webbrowser.open(f'file://{os.path.abspath(dashboard_path)}')
        
        print(f"\nStep 14 complete! Created diagnostic dashboard:")
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


if __name__ == "__main__":
    # Test configuration
    desired_rate_plans = {
        "PG&E": {"electricity": "E-TOU-D", "gas": "G-1"},
        "SCE": {"electricity": "TOU-D-4-9PM", "gas": "GR"},
        "SDG&E": {"electricity": "TOU-DR1", "gas": "GR"}
    }
    
    process(
        base_input_dir="data/loadprofiles",
        base_output_dir="data/loadprofiles",
        scenario="baseline",
        housing_type="single-family-detached",
        counties=["Alameda County"],
        desired_rate_plans=desired_rate_plans
    )