"""
Step 14: Display Key Metrics Maps

Display diagnostic maps for key metrics:
- Average solar panel size in county
- Total annual electricity load in county, in kWh
- Total electricity bill annually, in $
- Total gas bill annually, in $
"""

import os
import pandas as pd
import folium
from helpers.maps_helpers import (
    initialize_map, load_cost_data, add_choropleth_layer, 
    add_centroid_labels, add_map_title, export_geojson_and_html
)
from main_helpers import log, slugify_county_name, to_decimal_number


def create_metric_map(base_input_dir: str, scenario: str, housing_type: str, counties: list, 
                     metric_name: str, data_loader_config: dict) -> tuple[str, str]:
    """
    Create a diagnostic map for a specific metric.
    
    Args:
        base_input_dir: Input directory path
        scenario: Scenario name
        housing_type: Housing type
        counties: List of counties to process
        metric_name: Name of the metric to display
        data_loader_config: Configuration for loading the metric data
    
    Returns:
        tuple: (geojson_path, html_path)
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
            # Use load_cost_data to get metric data
            data = load_cost_data(
                county_dir=county_dir,
                subfolder=data_loader_config["subfolder"],
                prefix=data_loader_config["prefix"],
                scenario_row=data_loader_config["scenario_row"]
            )
            
            metric_value = float(data[data_loader_config["column"]])
            gdf.loc[gdf["NAME"] == county_name, metric_name] = metric_value
            gdf.loc[gdf["NAME"] == county_name, f"{metric_name}_fmt"] = to_decimal_number(metric_value)
            
        except Exception as e:
            print(f"Warning: Could not load {metric_name} data for {county_name}: {e}")
    
    # Create map
    m = folium.Map(
        location=[37.8, -120], 
        zoom_start=6, 
        zoom_control=False,
        width="900px", 
        height="700px"
    )
    
    # Add title
    scenario_title = scenario.replace('_', ' ').title()
    add_map_title(m, f"{metric_name} by County - {scenario_title}")
    
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
    
    # Hide layer control
    m.get_root().html.add_child(folium.Element(
        '<style>.leaflet-control-layers{display:none !important;}</style>'
    ))
    
    # Export map
    output_dir = os.path.join("visualizations", "diagnostic_maps")
    filename_prefix = f"{metric_name.lower().replace(' ', '_').replace('(', '').replace(')', '')}_{scenario}_{housing_type.replace(' ', '-').lower()}"
    
    return export_geojson_and_html(gdf, output_dir, filename_prefix, m, open_in_browser=False)


def process(base_input_dir: str, base_output_dir: str, scenario: str, 
           housing_type: str, counties: list, desired_rate_plans: dict):
    """
    Display key metrics maps for the scenario.
    
    Args:
        base_input_dir: Input directory path
        base_output_dir: Output directory path
        scenario: Scenario name
        housing_type: Housing type
        counties: List of counties to process
        desired_rate_plans: Rate plans by utility
    """
    
    log(
        at="step14_display_key_metrics_maps",
        info="starting_key_metrics_display",
        scenario=scenario,
        housing_type=housing_type,
        counties_requested=len(counties)
    )
    
    # Define metrics to display with their data loading configurations
    metrics_config = {
        "Solar Size (kW)": {
            "subfolder": "solarstorage",
            "prefix": "solar_results",
            "column": "Solar Size (kW)",
            "scenario_row": 1,  # Solar+storage scenario
            "color_scheme": "YlOrBr",
            "bins": [0, 2, 4, 6, 8, 10, 12, 15, 20],
            "unit": "kW"
        },
        "Annual Electricity Bill ($)": {
            "subfolder": "electricity",
            "prefix": "RESULTS_electricity_annual_costs",
            "column": "total_annual_bill",
            "scenario_row": 0,  # Baseline scenario
            "color_scheme": "Reds",
            "bins": [0, 1000, 2000, 3000, 4000, 5000, 6000, 8000, 10000],
            "unit": "$"
        },
        "Annual Gas Bill ($)": {
            "subfolder": "gas",
            "prefix": "RESULTS_gas_annual_costs",
            "column": "total_annual_bill",
            "scenario_row": 0,  # Baseline scenario
            "color_scheme": "Oranges",
            "bins": [0, 500, 1000, 1500, 2000, 2500, 3000, 4000],
            "unit": "$"
        }
    }
    
    # Create maps for each metric
    created_maps = []
    
    for metric_name, config in metrics_config.items():
        try:
            print(f"Creating map for: {metric_name}")
            
            geojson_path, html_path = create_metric_map(
                base_input_dir, scenario, housing_type, counties, metric_name, config
            )
            
            created_maps.append({
                "metric": metric_name,
                "html_path": html_path,
                "geojson_path": geojson_path
            })
            
            print(f"  Map saved: {html_path}")
            
        except Exception as e:
            print(f"  Error creating map for {metric_name}: {e}")
            log(
                at="step14_display_key_metrics_maps",
                error=f"Failed to create {metric_name} map: {e}",
                scenario=scenario,
                metric=metric_name
            )
    
    # Log completion
    log(
        at="step14_display_key_metrics_maps",
        info="key_metrics_display_complete",
        scenario=scenario,
        housing_type=housing_type,
        counties_processed=len(counties),
        maps_created=len(created_maps)
    )
    
    print(f"\nStep 14 complete! Created {len(created_maps)} diagnostic maps:")
    for map_info in created_maps:
        print(f"  - {map_info['metric']}: {map_info['html_path']}")
    
    return created_maps


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