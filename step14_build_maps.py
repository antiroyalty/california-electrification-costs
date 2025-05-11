import os
import pandas as pd
import numpy as np
import geopandas as gpd
import folium
import requests
from zipfile import ZipFile
from datetime import datetime
from helpers import get_counties, get_scenario_path, log, to_decimal_number, norcal_counties, central_counties, socal_counties

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

def get_gas_costs(county_dir):
    return load_cost_data(county_dir, "gas", "RESULTS_gas_annual_costs")

def get_total_costs(county_dir):
    return load_cost_data(county_dir, "totals", "RESULTS_total_annual_costs")

def get_solarstorage_total_costs(county_dir):
    return load_cost_data(county_dir, "solarstorage", "RESULTS_total_annual_costs")

def generate_geojson(merged_gdf, output_path, file_prefix, rate):
    subset = merged_gdf[["NAME", "geometry", rate]]
    filename = os.path.join(output_path, f"{file_prefix}.{rate}.geojson")
    subset.to_file(filename, driver="GeoJSON")

def get_selected_rate_info(row, rate_columns):
    for rate in rate_columns:
        if pd.notnull(row[rate]):
            return row[rate], rate
    return None, None

def generate_html(merged_gdf, output_path, scenario, file_prefix, all_rates_for_map) -> str:
    selected_info = merged_gdf.apply(lambda row: get_selected_rate_info(row, all_rates_for_map), axis=1)
    merged_gdf["selected_rate"] = [info[0] for info in selected_info]
    merged_gdf["selected_rate_label"] = [info[1] for info in selected_info]
    merged_gdf["selected_rate_fmt"] = merged_gdf["selected_rate"].apply(
        lambda x: to_decimal_number(x) if pd.notnull(x) else ""
    )

    num_bins = 10  
    min_val = merged_gdf["selected_rate"].min()
    max_val = merged_gdf["selected_rate"].max()
    threshold_scale = list(np.linspace(min_val, max_val, num_bins)) # np.linspace ensures max value is included
    
    m = folium.Map(location=[37.8, -120], zoom_start=6)
    title_html = f'''
             <h3 align="center" style="font-size:16px"><b>Total annual costs: {file_prefix}</b></h3>
             '''
    m.get_root().html.add_child(folium.Element(title_html))
    
    # Add the choropleth layer using the new 'selected_rate' column.
    folium.Choropleth(
        geo_data=merged_gdf,
        data=merged_gdf,
        columns=["NAME", "selected_rate"],
        key_on="feature.properties.NAME",
        fill_color="YlOrRd",
        fill_opacity=0.7,
        line_opacity=0.2,
        legend_name="Total Costs",
        threshold_scale=threshold_scale,
        nan_fill_color="white",      
        nan_fill_opacity=0.2         
    ).add_to(m)
    
    # Add GeoJson layer with an extended tooltip including the rate label.
    folium.GeoJson(
        data=merged_gdf,
        style_function=lambda x: {'fillOpacity': 0, 'color': 'transparent', 'weight': 0},
        tooltip=folium.GeoJsonTooltip(
            fields=["NAME", "selected_rate_label", "selected_rate_fmt"],
            aliases=["County:", "Rate Applied:", "Annual Cost:"]
        )
    ).add_to(m)
    
    # Add markers at the centroid for each county.
    for idx, row in merged_gdf.iterrows():
        centroid = row['geometry'].centroid
        folium.map.Marker(
            location=[centroid.y, centroid.x],
            icon=folium.DivIcon(
                html=f"""<div style="font-size:5pt; font-weight:bold; color:black;">{row["selected_rate_fmt"]}</div>"""
            )
        ).add_to(m)

    legend_html = f'''
    <div style="
         position: fixed; 
         bottom: 50px; left: 50px; width: 250px; 
         background-color: white;
         border:2px solid grey; z-index:9999; font-size:14px;
         padding: 10px;
         ">
         <h3>Scenario:</h3>
         <div style="padding-left: 16px">{file_prefix}</div>
         <hr style="margin:2px 0;">
    '''
    # Add each rate on its own line.
    
    for rate in all_rates_for_map:
        utility, electricity_plan, gas_plan = get_rate_plans_from_label(rate)
        html = f"<b>{utility}</b><div style='padding-left: 16px'>{electricity_plan}, {gas_plan}</div>"

        legend_html += f'<div style="margin:2px 0;">{html}</div>'
    legend_html += '</div>'
    
    # Add the custom legend to the map.
    m.get_root().html.add_child(folium.Element(legend_html))
    
    filename = os.path.join(output_path, f"{file_prefix}.html")
    # Assuming log is defined elsewhere; if not, you can print or remove it.
    print(f"Saved to: {filename}")
    m.save(filename)
    return filename

def get_rate_plans_from_label(label: str):
    costs, utility, plans  = label.split('.', maxsplit=2)

    if costs == "total":
        electricity_plan, gas_plan = plans.split('+')
        gas_utility, gas_plan = gas_plan.split('.')
    elif costs == "electricity":
        electricity_plan = plans
        gas_plan = None
    elif costs == "gas":
        electricity_plan = None
        gas_plan = plans
    else:
        raise ValueError(f"Unknown Cost Category: {costs}")

    return utility, electricity_plan, gas_plan

def generate_service_maps(merged_gdf, base_output_dir, scenario, file_prefix, desired_rate_plans) -> list[str]:
    html_dir = os.path.join(base_output_dir, "html")
    geojson_dir = os.path.join(base_output_dir, "geojson")
    os.makedirs(html_dir, exist_ok=True)
    os.makedirs(geojson_dir, exist_ok=True)

    rates = [col for col in merged_gdf.columns if col not in ["NAME", "geometry"]]

    eligible_rates = []
    for rate in rates:
        utility, electricity_plan, gas_plan = get_rate_plans_from_label(rate)

        if (electricity_plan is None or electricity_plan == desired_rate_plans[utility]["electricity"]) and (gas_plan is None or gas_plan == desired_rate_plans[utility]["gas"]):
            eligible_rates.append(rate)


    print("step14_build_maps rates:")
    print(eligible_rates)

    html_files = []
    for rate in eligible_rates:
        generate_geojson(merged_gdf, geojson_dir, file_prefix, rate)

    filename = generate_html(merged_gdf, html_dir, scenario, file_prefix, eligible_rates)
    html_files.append(filename)

    return html_files

def process(base_input_dir, base_output_dir, scenario, housing_type, counties, desired_rate_plans):
    scenario_path = get_scenario_path(base_input_dir, scenario, housing_type)
    valid_counties = get_counties(scenario_path, counties)
    data_combined, data_solar, data_elec, data_gas, data_elec_solarstorage = {}, {}, {}, {}, {}

    for county in valid_counties:
        county_dir = os.path.join(scenario_path, county)
        try:
            combined = get_total_costs(county_dir)
            solar_totals = get_solarstorage_total_costs(county_dir)
            elec = get_electricity_costs(county_dir)
            gas = get_gas_costs(county_dir)

            name = county.replace("-", " ").title()
            data_combined[name] = combined.to_dict()
            data_solar[name] = solar_totals.to_dict()
            data_elec[name] = elec.to_dict()
            data_gas[name] = gas.to_dict()
        except Exception as e:
            log(county=county, message=f"Skipping county", error=e)
            continue

    df_combined = pd.DataFrame.from_dict(data_combined, orient="index")
    df_solar = pd.DataFrame.from_dict(data_solar, orient="index")
    df_elec = pd.DataFrame.from_dict(data_elec, orient="index")
    df_gas = pd.DataFrame.from_dict(data_gas, orient="index")

    gdf = initialize_map()

    merged_combined = gdf.merge(df_combined, left_on="NAME", right_index=True, how="left")
    merged_solar = gdf.merge(df_solar, left_on="NAME", right_index=True, how="left")
    merged_elec = gdf.merge(df_elec, left_on="NAME", right_index=True, how="left")
    merged_gas = gdf.merge(df_gas, left_on="NAME", right_index=True, how="left")

    output_maps_path = os.path.join(scenario_path, "RESULTS", "visualizations")

    html_files = []

    html_files.extend(generate_service_maps(merged_combined, output_maps_path, scenario, f"{scenario}", desired_rate_plans=desired_rate_plans))
    html_files.extend(generate_service_maps(merged_elec, output_maps_path, scenario, "electricity", desired_rate_plans=desired_rate_plans))
    html_files.extend(generate_service_maps(merged_gas, output_maps_path, scenario, "gas", desired_rate_plans=desired_rate_plans))
    html_files.extend(generate_service_maps(merged_solar, output_maps_path, scenario, f"{scenario}.solarstorage", desired_rate_plans=desired_rate_plans))

    # open the generated maps in default browser
    for file in html_files:
        os.system(f"open \"{file}\"")

if __name__ == '__main__': 
    base_input_dir = "data/loadprofiles"
    base_output_dir = "data/loadprofiles"
    counties = ["Los Angeles County"]
    scenarios = "heat_pump_and_induction_stove"
    housing_types = "single-family-detached"
    pge_rate_plan = "E-TOU-D"
    sce_rate_plan = "TOU-D-4-9PM"
    sdge_rate_plan = "TOU-DR1"

    desired_rate_plans = {
        "PG&E": {
            "electricity": "E-TOU-D",
            "gas": "G-1"
        },
        "SCE": {
            "electricity": "TOU-D-4-9PM",
            "gas": "GR"
        },
        "SDG&E": {
            "electricity": "TOU-DR1",
            "gas": "GR"
        }
    }

    process(base_input_dir, base_output_dir, scenarios, housing_types, norcal_counties+socal_counties+central_counties, desired_rate_plans=desired_rate_plans)