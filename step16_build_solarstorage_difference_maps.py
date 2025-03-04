import os
import pandas as pd
import geopandas as gpd
import folium
import requests
from zipfile import ZipFile
from datetime import datetime
from helpers import get_counties, get_scenario_path, log, to_decimal_number, norcal_counties, central_counties
from decimal import Decimal, ROUND_HALF_UP

def download_and_extract_shapefile():
    url = "https://www2.census.gov/geo/tiger/GENZ2018/shp/cb_2018_us_county_20m.zip"
    zip_name = "cb_2018_us_county_20m.zip"
    folder = "cb_2018_us_county_20m"
    if not os.path.exists(folder):
        response = requests.get(url, stream=True)
        with open(zip_name, "wb") as f:
            for chunk in response.iter_content(chunk_size=1024):
                f.write(chunk)
        with ZipFile(zip_name, "r") as zip_ref:
            zip_ref.extractall(folder)
    return folder

def format_2_sig(x):
    if x is None or pd.isnull(x):
        return "N/A"

    d = Decimal(str(x))
    exp = d.adjusted()  # exponent of the number (number of digits minus 1)
    # To get 2 significant figures, quantize to 10^(exp - 1)
    quantize_exp = Decimal("1e{}".format(exp - 1))
    rounded = d.quantize(quantize_exp, rounding=ROUND_HALF_UP)
    # Convert to fixed-point string (without scientific notation)
    return format(rounded, "f")

def initialize_map():
    folder = download_and_extract_shapefile()
    shp_file = [os.path.join(folder, f) for f in os.listdir(folder) if f.endswith(".shp")][0]
    gdf = gpd.read_file(shp_file)
    gdf = gdf[gdf["STATEFP"] == "06"][["NAME", "geometry"]].copy()
    return gdf

def extract_timestamp_from_filename(filename):
    parts = filename.rstrip(".csv").split("_")
    ts = parts[-2] + "_" + parts[-1]
    return datetime.strptime(ts, "%Y%m%d_%H")

def get_latest_csv_file(directory, prefix):
    files = [f for f in os.listdir(directory) if f.startswith(prefix) and f.endswith(".csv")]
    if not files:
        raise FileNotFoundError(f"No file found in {directory} with prefix {prefix}")
    latest_file = max(files, key=lambda f: extract_timestamp_from_filename(f))
    return os.path.join(directory, latest_file)

def load_cost_data(county_dir, subfolder, prefix):
    path = os.path.join(county_dir, "results", subfolder)
    county = os.path.basename(county_dir)
    full_prefix = f"{prefix}_{county}_"
    file_path = get_latest_csv_file(path, full_prefix)
    df = pd.read_csv(file_path, index_col="scenario")
    return df.iloc[0]

def get_total_costs(county_dir):
    return load_cost_data(county_dir, "totals", "RESULTS_total_annual_costs")

def get_color(diff, min_val, max_val):
    # If the difference is zero or missing, return white.
    if diff is None or pd.isnull(diff) or diff == 0:
        return "#ffffff"
    # For negative differences (heatpump cheaper), interpolate from white to green.
    if diff < 0:
        # Since min_val is negative, diff/min_val gives a proportion between 0 and 1.
        proportion = diff / min_val if min_val != 0 else 0
        # White: (255,255,255), Green: (0,128,0)
        r = int(255 + (0 - 255) * proportion)
        g = int(255 + (128 - 255) * proportion)
        b = int(255 + (0 - 255) * proportion)
        return f"#{r:02x}{g:02x}{b:02x}"
    else:
        # For positive differences (heatpump more expensive), interpolate from white to red.
        proportion = diff / max_val if max_val != 0 else 0
        # White: (255,255,255), Red: (255,0,0)
        r = 255
        g = int(255 + (0 - 255) * proportion)
        b = int(255 + (0 - 255) * proportion)
        return f"#{r:02x}{g:02x}{b:02x}"

def style_function(feature, rate, min_val, max_val):
    diff = feature["properties"].get(rate)
    return {
        "fillColor": get_color(diff, min_val, max_val),
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

    # Compute the overall min and max for the cost column
    min_val = merged_gdf[rate].min()
    max_val = merged_gdf[rate].max()

    folium.GeoJson(
        data=merged_gdf,
        style_function=lambda feature: style_function(feature, rate, min_val, max_val),
        tooltip=folium.GeoJsonTooltip(fields=["NAME", f"{rate}_fmt"], aliases=["County:", "Difference:"])
    ).add_to(m)

    filename = os.path.join(output_path, f"difference_map_solarstorage_{rate}.html")
    log(saved_to=filename)
    m.save(filename)

def generate_diff_maps(merged_gdf, base_output_dir):
    html_dir = os.path.join(base_output_dir, "html")
    geojson_dir = os.path.join(base_output_dir, "geojson")

    os.makedirs(html_dir, exist_ok=True)
    os.makedirs(geojson_dir, exist_ok=True)

    rates = [col for col in merged_gdf.columns if col not in ["NAME", "geometry"]]

    for rate in rates:
        generate_diff_geojson(merged_gdf, geojson_dir, rate)
        generate_diff_html(merged_gdf, html_dir, rate)

def process_difference_map(base_input_dir, base_output_dir, housing_type, counties, scenario_baseline, scenario_electrified):
    baseline_path = get_scenario_path(base_input_dir, scenario_baseline, housing_type)
    electrified_path = get_scenario_path(base_input_dir, scenario_electrified, housing_type)
    
    baseline_data, electrified_data = {}, {}
    valid_counties = get_counties(baseline_path, counties)

    for county in valid_counties:
        county_dir_baseline = os.path.join(baseline_path, county)
        county_dir_electrified = os.path.join(electrified_path, county)
        try:
            costs_baseline = get_total_costs(county_dir_baseline)
            costs_electrified = get_total_costs(county_dir_electrified)
            name = county.replace("-", " ").title()
            baseline_data[name] = costs_baseline.to_dict()
            electrified_data[name] = costs_electrified.to_dict()
        except Exception as e:
            log(county=county, message=f"Skipping county for diff map: {e}")
            continue

    if not baseline_data:
        return

    df_baseline = pd.DataFrame.from_dict(baseline_data, orient="index")
    df_electrified = pd.DataFrame.from_dict(electrified_data, orient="index")
    gdf = initialize_map()
    merged_baseline = gdf.merge(df_baseline, left_on="NAME", right_index=True, how="left")
    merged_electrified = gdf.merge(df_electrified, left_on="NAME", right_index=True, how="left")

    # Compute differences: electrified_scenario minus baseline.
    diff_gdf = merged_electrified.copy()
    cost_cols = [col for col in merged_electrified.columns if col not in ["NAME", "geometry"]]
    for col in cost_cols:
        diff_gdf[col] = merged_electrified[col] - merged_baseline[col]

    output_diff_dir = os.path.join(electrified_path, "RESULTS", "visualizations", "difference")
    os.makedirs(output_diff_dir, exist_ok=True)
    generate_diff_maps(diff_gdf, output_diff_dir)

# TODO: move this into its own file for solarstorage diff maps
def get_solarstorage_total_costs(county_dir):
    return load_cost_data(county_dir, "solarstorage", "RESULTS_total_annual_costs")

def load_cost_data(county_dir, subfolder, prefix):
    path = os.path.join(county_dir, "results", subfolder)
    county = os.path.basename(county_dir)
    full_prefix = f"{prefix}_{county}_"
    file_path = get_latest_csv_file(path, full_prefix)
    df = pd.read_csv(file_path, index_col="scenario")

    if subfolder == "solarstorage":
        # return df.at["baseline.solarstorage", "total.usd+gas.usd"] # solarstorage only makes sense for total cost comparison
        return df.iloc[1] # janky but we want to keep the column name so return the full row details
    else:
        # return df.iloc[df.index.get_loc("baseline"), 0] # column names may vary
        return df.iloc[0]
    
def process_difference_map_solar(base_input_dir, base_output_dir, housing_type, counties, scenario):
    scenario_path = get_scenario_path(base_input_dir, scenario, housing_type)
    data_normal, data_solar = {}, {}
    valid_counties = get_counties(scenario_path, counties)

    for county in valid_counties:
        county_dir = os.path.join(scenario_path, county)
        try:
            # Load the normal totals (first row) and solarstorage totals (second row)
            costs_normal = get_total_costs(county_dir)
            costs_solar = get_solarstorage_total_costs(county_dir)
            name = county.replace("-", " ").title()
            data_normal[name] = costs_normal.to_dict()
            data_solar[name] = costs_solar.to_dict()
        except Exception as e:
            log(county=county, message=f"Skipping county for diff solar map: {e}")
            continue

    if not data_normal:
        return

    # Build DataFrames from the dictionaries.
    df_normal = pd.DataFrame.from_dict(data_normal, orient="index")
    df_solar = pd.DataFrame.from_dict(data_solar, orient="index")

    # Merge with the counties GeoDataFrame.
    gdf = initialize_map()
    merged_normal = gdf.merge(df_normal, left_on="NAME", right_index=True, how="left")
    merged_solar = gdf.merge(df_solar, left_on="NAME", right_index=True, how="left")

    # Compute the differences: (solarstorage totals) - (normal totals)
    diff_gdf = merged_solar.copy()
    cost_cols = [col for col in merged_solar.columns if col not in ["NAME", "geometry"]]
    for col in cost_cols:
        diff_gdf[col] = merged_solar[col] - merged_normal[col]

    # Save the diff maps to a dedicated folder.
    output_diff_dir = os.path.join(scenario_path, "RESULTS", "visualizations", "difference_solar")
    os.makedirs(output_diff_dir, exist_ok=True)
    generate_diff_maps(diff_gdf, output_diff_dir)

base_input_dir = "data/loadprofiles"
base_output_dir = "data/loadprofiles"
counties = norcal_counties + central_counties
housing_type = "single-family-detached"

process_difference_map_solar(base_input_dir, base_output_dir, "single-family-detached", counties, "baseline") # baseline vs. baseline solarstorage