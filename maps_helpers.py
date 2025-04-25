import os
import requests
import geopandas as gpd
from zipfile import ZipFile
from datetime import datetime
import pandas as pd
import folium
from typing import List, Optional

def initialize_map():
    url = "https://www2.census.gov/geo/tiger/GENZ2018/shp/cb_2018_us_county_20m.zip"
    zip_name = "cb_2018_us_county_20m.zip"
    folder = "cb_2018_us_county_20m"

    if not os.path.exists(folder):
        r = requests.get(url, stream=True)

        with open(zip_name, "wb") as f:
            for chunk in r.iter_content(chunk_size=1024):
                f.write(chunk)
        with ZipFile(zip_name, "r") as zip_ref:
            zip_ref.extractall(folder)
    shp_file = [os.path.join(folder, f) for f in os.listdir(folder) if f.endswith(".shp")][0]

    gdf = gpd.read_file(shp_file)

    # Filter for California (STATEFP code "06")
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

def get_difference_color(diff, min_val, max_val):
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
    
def outline_style_function(feature):
    return {
        "fillColor":   "transparent",  # no fill, Choropleth covers it
        "color":       "black",        # or utility‐based if you like
        "weight":      1,
        "fillOpacity": 0
    }

def build_metric_map(
    gdf: gpd.GeoDataFrame,
    column: str,
    title_text: str,
    tooltip_fields: List[str],
    tooltip_aliases: List[str],
    fill_color: str,
    legend_name: str,
    diverging: bool = False,
    threshold_scale: Optional[List[float]] = None
) -> folium.Map:
    """
    Build a folium Map showing `column` from `gdf` as a choropleth plus county outlines.
    If diverging=True, expect diffs and use a diverging scale (e.g. 'RdBu').  
    threshold_scale overrides the auto‐bins.
    """
    m = folium.Map(location=[37.8, -120], zoom_start=6)

    # 1) Choropleth layer
    folium.Choropleth(
      geo_data=gdf,
      data=gdf,
      columns=["NAME", column],
      key_on="feature.properties.NAME",
      fill_color=fill_color,
      threshold_scale=threshold_scale,
      legend_name=legend_name,
      nan_fill_color="white",
      nan_fill_opacity=0.1,
      name=legend_name
    ).add_to(m)

    # 2) Outlines + tooltip
    tooltip = folium.GeoJsonTooltip(fields=tooltip_fields, aliases=tooltip_aliases, localize=True)
    folium.GeoJson(
      gdf,
      style_function=outline_style_function,
      tooltip=tooltip,
      name="County Info"
    ).add_to(m)

    # 3) Title
    m.get_root().html.add_child(folium.Element(f'<h3 align="center">{title_text}</h3>'))

    # 4) Centroid labels (optional)
    for _, r in gdf.iterrows():
        cent = r.geometry.centroid
        folium.map.Marker(
          [cent.y, cent.x],
          icon=folium.DivIcon(html=f"<div style='font-size:6pt'>{r[column]}</div>")
        ).add_to(m)

    folium.LayerControl().add_to(m)

    return m

