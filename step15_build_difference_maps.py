import os
import pandas as pd
import folium
from helpers import get_counties, get_scenario_path, log, to_decimal_number, norcal_counties, central_counties, socal_counties
from maps_helpers import initialize_map, get_latest_csv_file, get_difference_color
# import itertools # TODO: Ana, use to get permutations of each scenario, etc.

def style_function(feature, rate, min_val, max_val):
    diff = feature["properties"].get(rate)
    return {
        "fillColor": get_difference_color(diff, min_val, max_val),
        "color": "black",
        "weight": 1,
        "fillOpacity": 0.7,
    }

def generate_diff_geojson(merged_gdf, output_path, rate):
    subset = merged_gdf[["NAME", "geometry", rate]]
    filename = os.path.join(output_path, f"difference_{rate}.geojson")
    subset.to_file(filename, driver="GeoJSON")

def generate_diff_html(merged_gdf, output_path, rate):
    merged_gdf[f"{rate}_fmt"] = merged_gdf[rate].apply(lambda x: to_decimal_number(x) if pd.notnull(x) else "N/A")
    m = folium.Map(location=[37.8, -120], zoom_start=6)
    title_html = f'''
             <h3 align="center" style="font-size:20px"><b>{output_path}.{rate}</b></h3>
             '''
    m.get_root().html.add_child(folium.Element(title_html))

    # Compute the overall min and max for the cost column
    min_val = merged_gdf[rate].min()
    max_val = merged_gdf[rate].max()

    # folium.Choropleth(
    #     geo_data=merged_gdf,
    #     data=merged_gdf,
    #     columns=["NAME", rate],              # 'NAME' is your key, 'rate' is the numeric column
    #     key_on="feature.properties.NAME",    # Match on county name in GeoJSON
    #     # fill_color="YlOrRd",                 # Color scheme from light yellow to dark red
    #     fill_opacity=0.7,
    #     line_opacity=0.2,
    #     legend_name=f"Total Costs ({rate})",
    #     threshold_scale=[-1200, -1000, -800, -600, -400, -200, 0, 200, 400, 600, 800, 1000]
    # ).add_to(m)

    folium.GeoJson(
        data=merged_gdf,
        style_function=lambda feature: style_function(feature, rate, min_val, max_val),
        tooltip=folium.GeoJsonTooltip(fields=["NAME", f"{rate}_fmt"], aliases=["County:", "Difference:"]),
        legend_name=f"Cost savings ({rate})",
        threshold_scale=[-1200, -1000, -800, -600, -400, -200, 0, 200, 400, 600, 800, 1000]
    ).add_to(m)

    filename = os.path.join(output_path, f"difference_map_solarstorage_{rate}.html")
    log(saved_to=filename)
    
    m.save(filename)
    os.system(f"open {filename}")

def generate_diff_maps(merged_gdf, base_output_dir):
    html_dir = os.path.join(base_output_dir, "html")
    geojson_dir = os.path.join(base_output_dir, "geojson")

    os.makedirs(html_dir, exist_ok=True)
    os.makedirs(geojson_dir, exist_ok=True)

    rates = [col for col in merged_gdf.columns if col not in ["NAME", "geometry"]]

    for rate in rates:
        generate_diff_geojson(merged_gdf, geojson_dir, rate)
        generate_diff_html(merged_gdf, html_dir, rate)

def get_costs(county_dir, row_name):
    return load_cost_data(county_dir, "totals", "RESULTS_total_annual_costs", row_name)

def load_cost_data(county_dir, subfolder, prefix, row_name):
    path = os.path.join(county_dir, "results", subfolder)
    county = os.path.basename(county_dir)

    full_prefix = f"{prefix}_{county}_"
    file_path = get_latest_csv_file(path, full_prefix)
    df = pd.read_csv(file_path, index_col="scenario")

    row_idx = df.index.get_loc(row_name)
    return df.iloc[row_idx]
    
def process(base_input_dir, base_output_dir, housing_type, counties, left_scenario, left_row, right_scenario, right_row):
    left_scenario_path = get_scenario_path(base_input_dir, left_scenario, housing_type)
    data_left, data_right = {}, {}
    valid_counties = get_counties(left_scenario_path, counties)

    right_scenario_path = get_scenario_path(base_input_dir, right_scenario, housing_type)

    for county in valid_counties:
        left_county_dir = os.path.join(left_scenario_path, county)
        right_county_dir = os.path.join(right_scenario_path, county)
        
        try:
            # Load the normal totals (first row) and solarstorage totals (second row)
            costs_left = get_costs(left_county_dir, left_row) # this may be baseline
            costs_right = get_costs(right_county_dir, right_row) # this may happen to be solarstorage

            name = county.replace("-", " ").title()

            data_left[name] = costs_left.to_dict()
            data_right[name] = costs_right.to_dict()
        except Exception as e:
            log(county=county, message=f"Skipping county for diff solar map: {e}")
            continue

    # Build DataFrames from the dictionaries.
    df_left = pd.DataFrame.from_dict(data_left, orient="index")
    df_right = pd.DataFrame.from_dict(data_right, orient="index")

    # Merge with the counties GeoDataFrame.
    gdf = initialize_map()
    merged_left = gdf.merge(df_left, left_on="NAME", right_index=True, how="left")
    merged_right = gdf.merge(df_right, left_on="NAME", right_index=True, how="left")

    # Compute the differences: (solarstorage totals) - (normal totals)
    # Right - left
    # so left is the base, right is the thing we're comparing
    diff_gdf = merged_right.copy()
    cost_cols = [col for col in merged_right.columns if col not in ["NAME", "geometry"]]

    for col in cost_cols:
        diff_gdf[col] = merged_right[col] - merged_left[col]

    output_diff_dir = os.path.join(right_scenario_path, "RESULTS", "visualizations", "difference", f"{left_scenario}.{left_row}_{right_scenario}.{right_row}")
    os.makedirs(output_diff_dir, exist_ok=True)
    generate_diff_maps(diff_gdf, output_diff_dir)

if __name__ == '__main__':
    base_input_dir = "data/loadprofiles"
    base_output_dir = "data/loadprofiles"
    counties = norcal_counties + central_counties + socal_counties
    housing_type = "single-family-detached"

    process(base_input_dir, base_output_dir, "single-family-detached", counties, "baseline", "baseline", "baseline", "baseline.solarstorage")
    # process(base_input_dir, base_output_dir, "single-family-detached", counties, "baseline", "baseline", "heat_pump", "heat_pump")
    # process(base_input_dir, base_output_dir, "single-family-detached", counties, "baseline", "baseline.solarstorage", "heat_pump", "heat_pump.solarstorage")
    # process(base_input_dir, base_output_dir, "single-family-detached", counties, "heat_pump", "heat_pump", "heat_pump", "heat_pump.solarstorage") # baseline vs. baseline solarstorage
    # process(base_input_dir, base_output_dir, "single-family-detached", counties, "baseline", "baseline", "heat_pump", "heat_pump.solarstorage")
