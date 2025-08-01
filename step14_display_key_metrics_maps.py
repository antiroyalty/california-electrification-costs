"""
Step 14: Display Key Metrics Maps

Display maps for key metrics:
- Average solar panel size in county
- Total annual load in county, in kWh
- Total electricity bill annually, in $
- Total gas bill annually, in $

Display this as 4 maps all on one tab, if possible.
"""

import os
from main_helpers import log


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
    
    # TODO: Implement key metrics map display
    # This should show:
    # 1. Average solar panel size in county
    # 2. Total annual load in county, in kWh
    # 3. Total electricity bill annually, in $
    # 4. Total gas bill annually, in $

#       Functions from maps_helpers.py that can be reused:

#   1. initialize_map() - Gets California county boundaries from Census data
#   2. add_choropleth_layer() - Adds the colored solar size choropleth with bins and color scheme
#   3. add_centroid_labels() - Adds solar size values as text labels on county centroids
#   4. add_map_title() - Adds title like "Solar Panel Size by County - Baseline EV Car"
#   5. export_geojson_and_html() - Saves the map as HTML and opens in browser
#   6. get_latest_csv_file() - Finds the most recent SAM results file by timestamp

#   Files that need to be read:

#   Based on the capital_cost_map_builder.py pattern, the solar size data comes from SAM (System Advisor Model) results:

#   data/loadprofiles/{scenario}/{housing_type}/{county_slug}/results/solarstorage/
#       └── solar_results_{county_slug}_{timestamp}.csv

#   Example file paths:
#   - data/loadprofiles/baseline_ev_car/single-family-detached/alameda/results/solarstorage/solar_results_alameda_20240315_14.csv
#   - data/loadprofiles/baseline_ev_car/single-family-detached/los-angeles/results/solarstorage/solar_results_los-angeles_20240315_
#   14.csv

#   Key column in SAM results: "Solar Size (kW)"

#   Implementation pattern:

#   # 1. Get county boundaries
#   gdf = initialize_map()

#   # 2. For each county, load SAM solar results
#   for county in counties:
#       county_slug = slugify_county_name(county)
#       sam_results_path = f"data/loadprofiles/{scenario}/{housing_type}/{county_slug}/results/solarstorage/"

#       # Find latest SAM file
#       solar_file = get_latest_csv_file(sam_results_path, f"solar_results_{county_slug}_")
#       df = pd.read_csv(solar_file, index_col="scenario")

#       # Get solar size (usually from solar+storage row)
#       solar_size_kw = df.iloc[1]["Solar Size (kW)"]  # Second row = with solar+storage
#       gdf.loc[gdf["NAME"] == county_name, "Solar Size (kW)"] = solar_size_kw

#   # 3. Create map using maps helpers
#   m = create_folium_map(title=f"Solar Size - {scenario}")
#   add_choropleth_layer(m, gdf, "Solar Size (kW)", "YlOrBr", [0,2,4,6,8,10,12,15], "Solar Size (kW)")
#   add_centroid_labels(m, gdf, "Solar Size (kW)")
#   export_geojson_and_html(gdf, output_dir, "solar_size_map", m)
    
    print("Step 14: Key metrics maps display not yet implemented")
    print("Will display 4 key maps on one tab when implemented")
    
    log(
        at="step14_display_key_metrics_maps",
        info="key_metrics_display_skipped", 
        reason="not_yet_implemented"
    )


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