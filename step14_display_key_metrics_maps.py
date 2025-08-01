"""
Step 14: Display Key Metrics Maps

Display diagnostic maps for key metrics:
- Average solar panel size in county
- Total annual electricity bill in county, in $
- Total annual gas bill in county, in $
- Total annual energy consumption (electricity + gas equivalent), in kWh
"""

import os
import pandas as pd
import folium
from helpers.maps_helpers import (
    initialize_map, load_cost_data, add_choropleth_layer, 
    add_centroid_labels, add_map_title, export_geojson_and_html,
    get_latest_csv_file
)
from main_helpers import log, slugify_county_name, to_decimal_number


def load_solar_data(base_input_dir: str, scenario: str, housing_type: str, county_name: str) -> float:
    """
    Load solar capacity data from annual analysis files.
    """
    try:
        # Path to annual analysis directory
        annual_analysis_path = os.path.join(base_input_dir, scenario, housing_type, "ANNUAL_ANALYSIS")
        
        # Find the latest solar capacity file
        solar_file = get_latest_csv_file(annual_analysis_path, "annual_solar_capacity_")
        
        # Load and find the county data
        df = pd.read_csv(solar_file)
        county_row = df[df['county'] == county_name.lower()]
        
        if not county_row.empty:
            return float(county_row['solar_capacity_kw'].iloc[0])
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
    Load annual energy-consumption data for a county.

    Returns
    -------
    tuple
        (electricity_kwh, gas_therms)

        electricity_kwh – sum of all hourly electric loads (kWh)
        gas_therms      – sum of all hourly gas loads (therms)
    """
    try:
        county_slug = slugify_county_name(f"{county_name} County")
        county_dir = os.path.join(base_input_dir, scenario, housing_type, county_slug)

        electricity_kwh = 0.0
        try:
            electricity_file = get_latest_csv_file(county_dir, "electricity_loads_")
            elec_df = pd.read_csv(electricity_file)
            electricity_kwh = float(elec_df["total_load"].sum())
        except Exception as e:
            print(f"Warning: Could not load electricity consumption for {county_name}: {e}")

        gas_therms = 0.0
        try:
            gas_file = get_latest_csv_file(county_dir, "gas_loads_")
            gas_df = pd.read_csv(gas_file)
            gas_therms = float(gas_df["load.gas.building_avg.therms"].sum())
        except Exception as e:
            print(f"Warning: Could not load gas consumption for {county_name}: {e}")

        return electricity_kwh, gas_therms

    except Exception as e:
        print(f"Warning: Could not load energy consumption data for {county_name}: {e}")
        return 0.0, 0.0


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
            # Special handling for solar data
            if metric_name == "Solar Size (kW)":
                metric_value = load_solar_data(base_input_dir, scenario, housing_type, county_name)
            elif metric_name == "Total Energy Consumption (kWh, thermes)":
                elec_kwh, gas_thm = load_energy_consumption_data(
                    base_input_dir, scenario, housing_type, county_name
                )

                log(
                    elec_kwh=elec_kwh,
                    gas_thm=gas_thm
                )

                # Keep the map shading in kWh-equivalent so the existing bins work
                value = elec_kwh + gas_thm * 29.3

                # Tooltip string => “12 345 kWh / 678 therms”
                pretty = f"{to_decimal_number(elec_kwh)} kWh / {to_decimal_number(gas_thm)} therms"
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
    
    return export_geojson_and_html(gdf, output_dir, filename_prefix, m, open_in_browser=True)


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
            # Special case - loaded from annual analysis files
            "color_scheme": "YlOrBr",
            "bins": [0, 2, 4, 6, 8, 10, 12, 15, 20],
            "unit": "kW"
        },
        "Annual Electricity Bill ($)": {
            "subfolder": "electricity",
            "prefix": "RESULTS_electricity_annual_costs",
            "column": "electricity.PG&E.E-TOU-D",  # Use PG&E E-TOU-D rate as default
            "scenario_row": 0,  # Baseline scenario
            "color_scheme": "Reds",
            "bins": [0, 1000, 2000, 3000, 4000, 5000, 6000, 8000, 10000],
            "unit": "$"
        },
        "Annual Gas Bill ($)": {
            "subfolder": "gas",
            "prefix": "RESULTS_gas_annual_costs",
            "column": "gas.PG&E.G-1",  # Use PG&E G-1 rate as default
            "scenario_row": 0,  # Baseline scenario
            "color_scheme": "Oranges",
            "bins": [0, 500, 1000, 1500, 2000, 2500, 3000, 4000],
            "unit": "$"
        },
        # "Total Energy Consumption (kWh, thermes)": {
        #     # Special case - loaded from hourly load profile files
        #     "color_scheme": "Greens",
        #     "bins": [0, 10000, 20000, 30000, 40000, 50000, 60000, 80000, 100000],
        #     "unit": "kWh"
        # }
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