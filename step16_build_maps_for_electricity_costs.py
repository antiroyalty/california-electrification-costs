import os
import pandas as pd
import geopandas as gpd
import folium
import requests
from zipfile import ZipFile
from datetime import datetime
from helpers import get_counties, get_scenario_path, log, to_decimal_number, norcal_counties, central_counties, socal_counties

electricity_costs_file_prefix = "RESULTS_electricity_annual_costs"

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

    if subfolder == "solarstorage":
        return df.iloc[1] # janky but we want to keep the column name so return the full row details
    else:
        # return df.iloc[df.index.get_loc("baseline"), 0] # column names may vary
        return df.iloc[0]

def get_electricity_costs(county_dir):
    return load_cost_data(county_dir, "electricity", "RESULTS_electricity_annual_costs")

def get_solarstorage_total_costs(county_dir):
    return load_cost_data(county_dir, "solarstorage", "RESULTS_total_annual_costs")

def generate_geojson(merged_gdf, output_path, file_prefix, rate):
    subset = merged_gdf[["NAME", "geometry", rate]]
    filename = os.path.join(output_path, f"{file_prefix}.{rate}.geojson")
    subset.to_file(filename, driver="GeoJSON")

def generate_html(merged_gdf, output_path, file_prefix, rate):
    merged_gdf[f"{rate}_fmt"] = merged_gdf[rate].apply(lambda x: to_decimal_number(x) if pd.notnull(x) else "N/A")
    m = folium.Map(location=[37.8, -120], zoom_start=6)
    title_html = f'''
             <h3 align="center" style="font-size:20px"><b>{output_path}/{file_prefix}.{rate}</b></h3>
             '''
    m.get_root().html.add_child(folium.Element(title_html))

    folium.Choropleth(
        geo_data=merged_gdf,
        data=merged_gdf,
        columns=["NAME", rate],
        key_on="feature.properties.NAME",
        fill_color="YlOrRd",
        fill_opacity=0.7,
        line_opacity=0.2,
        legend_name=f"Total Costs ({rate})",
        threshold_scale=[0, 500, 1000, 1500, 2000, 2500, 3000, 3500, 4000, 4500, 5000, 5500, 6000, 6500, 7000]
    ).add_to(m)

    folium.GeoJson(
        data=merged_gdf,
        style_function=lambda x: {'fillOpacity': 0, 'color': 'transparent', 'weight': 0},
        tooltip=folium.GeoJsonTooltip(fields=["NAME", f"{rate}_fmt"], aliases=["County:", "Cost:"])
    ).add_to(m)

    for idx, row in merged_gdf.iterrows():
        # Calculate the centroid of the county polygon...
        centroid = row['geometry'].centroid
        folium.map.Marker(
            location=[centroid.y, centroid.x],
            icon=folium.DivIcon(
                html=f"""<div style="font-size:10pt; font-weight:bold; color:black;">{row[f"{rate}_fmt"]}</div>"""
            )
        ).add_to(m)

    filename = os.path.join(output_path, f"{file_prefix}.{rate}.html")
    log(saved_to=filename)

    m.save(filename)

def generate_service_maps(merged_gdf, base_output_dir, file_prefix):
    html_dir = os.path.join(base_output_dir, "html")
    geojson_dir = os.path.join(base_output_dir, "geojson")
    os.makedirs(html_dir, exist_ok=True)
    os.makedirs(geojson_dir, exist_ok=True)

    rates = [col for col in merged_gdf.columns if col not in ["NAME", "geometry"]]

    for rate in rates:
        generate_geojson(merged_gdf, geojson_dir, file_prefix, rate)
        generate_html(merged_gdf, html_dir, file_prefix, rate)

def process(base_input_dir, base_output_dir, scenario, housing_types, counties):
    for housing_type in housing_types:
        scenario_path = get_scenario_path(base_input_dir, scenario, housing_type)
        valid_counties = get_counties(scenario_path, counties)
        data_combined, data_solar, data_elec, data_gas, data_elec_solarstorage = {}, {}, {}, {}, {}

        for county in valid_counties:
            county_dir = os.path.join(scenario_path, county)
            try:
                solar_totals = get_solarstorage_total_costs(county_dir)
                elec = get_electricity_costs(county_dir)

                name = county.replace("-", " ").title()
                data_combined[name] = combined.to_dict()
                data_solar[name] = solar_totals.to_dict()
                data_elec[name] = elec.to_dict()
                data_gas[name] = gas.to_dict()
            except Exception as e:
                log(county=county, message=f"Skipping county", error=e)
                continue
        if not data_combined:
            continue

        df_solar = pd.DataFrame.from_dict(data_solar, orient="index")
        df_elec = pd.DataFrame.from_dict(data_elec, orient="index")

        gdf = initialize_map()

        merged_solar = gdf.merge(df_solar, left_on="NAME", right_index=True, how="left")
        merged_elec = gdf.merge(df_elec, left_on="NAME", right_index=True, how="left")

        output_maps_path = os.path.join(scenario_path, "RESULTS", "visualizations")

        generate_service_maps(merged_elec, output_maps_path, "annual_costs_map.electricity")
        generate_service_maps(merged_solar, output_maps_path, "annual_costs_map.solarstorage")

        # we actually want difference maps
        # How much lower are annual costs if we just compare the costs of electricity without solar and storage, with the costs of electricity WITH solarstorage
        # can't make the costs with solar and storage go to 0

        # open the generated maps in default browser
        # os.system(f"open {output_maps_path}/html/annual_costs_map.total.total.usd+gas.usd.html")
        # os.system(f"open {output_maps_path}/html/annual_costs_map.solarstorage.total.usd+gas.usd.html")
        # os.system(f"open {output_maps_path}/html/annual_costs_map.electricity_w_solarstorage.total.usd+gas.usd.html")

base_input_dir = "data/loadprofiles"
base_output_dir = "data/loadprofiles"
# counties = norcal_counties + central_counties + socal_counties
scenarios = "heat_pump"
housing_types = ["single-family-detached"]

process(base_input_dir, base_output_dir, scenarios, housing_types, norcal_counties + central_counties + socal_counties)