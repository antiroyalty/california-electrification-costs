import os
import requests
import geopandas as gpd
from zipfile import ZipFile
from datetime import datetime
import pandas as pd
import folium
from typing import List, Optional, Dict, Any
from main_helpers import to_decimal_number, log

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
    m = create_folium_map(title=title_text)

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


    # 4) Centroid labels
    label_col = f"{column}_fmt" if f"{column}_fmt" in gdf.columns else column

    for _, r in gdf.iterrows():
        label = r[label_col]

        # --- skip empty / missing values so "nan" never shows up ---
        if pd.isnull(label) or str(label).upper() == "N/A":
            continue

        cent = r.geometry.centroid
        folium.map.Marker(
            [cent.y, cent.x],
            icon=folium.DivIcon(
                html=f"<div style='font-size:6pt'>{label}</div>"
            ),
        ).add_to(m)

    folium.LayerControl().add_to(m)

    m.get_root().html.add_child(folium.Element(
        '<style>.leaflet-control-layers{display:none !important;}</style>'
    ))

    return m

def create_folium_map(title: str = None) -> folium.Map:
    """
    Create a standardized folium map for California with consistent settings.
    
    Args:
        title: Optional title to add to map
        
    Returns:
        Configured folium Map object with standard California settings
    """
    m = folium.Map(
        location=[37.8, -120.0],
        zoom_start=6,
        width="550px",
        height="700px",
        zoom_control=False
    )
    
    css = f"""
        <style>
        #{m.get_name()} {{
            margin: 0 auto;
        }}
        </style>
    """
    m.get_root().html.add_child(folium.Element(css))
    
    if title:
        title_html = f'''
            <h3 align="center" style="font-size:20px">
                <b>{title}</b>
            </h3>
        '''
        m.get_root().html.add_child(folium.Element(title_html))
    
    return m

def export_geojson_and_html(
    merged_gdf: gpd.GeoDataFrame,
    output_base_dir: str,
    filename_prefix: str,
    map_object: folium.Map,
    open_in_browser: bool = True
) -> tuple[str, str]:
    """
    Export merged GeoDataFrame as GeoJSON and save folium map as HTML.
    Creates output directories as needed and optionally opens map in browser.
    
    Args:
        merged_gdf: GeoDataFrame with geometry and data columns
        output_base_dir: Base directory for outputs (will create 'geojson' and 'html' subdirs)
        filename_prefix: Prefix for output files (without extension)
        map_object: Folium map to save as HTML
        open_in_browser: Whether to open HTML file in default browser
        
    Returns:
        tuple: (geojson_path, html_path) - paths to saved files
    """
    import subprocess
    import sys
    
    # Create output directories
    geojson_dir = os.path.join(output_base_dir, "geojson")
    html_dir = os.path.join(output_base_dir, "html")
    os.makedirs(geojson_dir, exist_ok=True)
    os.makedirs(html_dir, exist_ok=True)
    
    # Generate file paths
    geojson_path = os.path.join(geojson_dir, f"{filename_prefix}.geojson")
    html_path = os.path.join(html_dir, f"{filename_prefix}.html")
    
    # Export GeoJSON
    try:
        merged_gdf.to_file(geojson_path, driver="GeoJSON")
        log(
            at="export_geojson_and_html",
            info="geojson_exported",
            path=geojson_path,
            rows=len(merged_gdf)
        )
    except Exception as e:
        log(
            at="export_geojson_and_html",
            error=f"Failed to export GeoJSON: {e}",
            path=geojson_path
        )
        raise
    
    # Save HTML map
    try:
        map_object.save(html_path)
        log(
            at="export_geojson_and_html", 
            info="html_map_exported",
            path=html_path
        )
    except Exception as e:
        log(
            at="export_geojson_and_html",
            error=f"Failed to save HTML map: {e}",
            path=html_path
        )
        raise
    
    # Open in browser if requested
    if open_in_browser:
        try:
            if sys.platform == "darwin":  # macOS
                subprocess.run(["open", html_path], check=False)
            elif sys.platform.startswith("linux"):  # Linux
                subprocess.run(["xdg-open", html_path], check=False)
            elif sys.platform == "win32":  # Windows
                subprocess.run(["start", html_path], shell=True, check=False)
            else:
                print(f"Cannot auto-open browser on platform {sys.platform}. Map saved to: {html_path}")
        except Exception as e:
            print(f"Could not open browser: {e}. Map saved to: {html_path}")
    
    return geojson_path, html_path


def add_choropleth_layer(
    map_obj: folium.Map,
    gdf: gpd.GeoDataFrame,
    data_column: str,
    fill_color: str,
    bins: List[float],
    legend_name: str,
    fill_opacity: float = 0.7,
    line_opacity: float = 0.2,
    legend_position: str = "bottomright"
) -> None:
    """
    Add a choropleth layer to a folium map with standardized styling.
    
    Args:
        map_obj: Folium map object to add choropleth to
        gdf: GeoDataFrame containing geometry and data
        data_column: Column name in gdf to use for choropleth values
        fill_color: Color scheme for choropleth (e.g., 'YlOrRd', 'Greens')
        bins: List of bin edges for choropleth classification
        legend_name: Name to display in map legend
        fill_opacity: Opacity of filled areas (0-1)
        line_opacity: Opacity of boundary lines (0-1)
        legend_position: Position of legend on map
    """
    choropleth = folium.Choropleth(
        geo_data=gdf,
        data=gdf,
        columns=["NAME", data_column],
        key_on="feature.properties.NAME",
        fill_color=fill_color,
        bins=bins,
        fill_opacity=fill_opacity,
        line_opacity=line_opacity,
        legend_name=legend_name,
        nan_fill_color="white",
        nan_fill_opacity=0.1,
        name=legend_name,
        legend_position=legend_position,
    )
    
    choropleth.add_to(map_obj)


def add_centroid_labels(
    map_obj: folium.Map,
    gdf: gpd.GeoDataFrame,
    label_column: str,
    font_size: str = "6pt",
    font_weight: str = "bold",
    font_color: str = "black"
) -> None:
    """
    Add text labels at county centroids on a folium map.
    
    Args:
        map_obj: Folium map object to add labels to
        gdf: GeoDataFrame containing geometry and label data
        label_column: Column name containing label values (should have matching _fmt column)
        font_size: CSS font size for labels
        font_weight: CSS font weight for labels  
        font_color: CSS color for labels
    """
    # Use formatted column if available, otherwise use raw column
    display_column = f"{label_column}_fmt" if f"{label_column}_fmt" in gdf.columns else label_column
    
    for _, row in gdf.iterrows():
        if pd.notnull(row[display_column]):
            centroid = row['geometry'].centroid
            label_value = row[display_column]
            
            # Skip empty/missing labels
            if pd.isnull(label_value) or str(label_value).upper() in ["N/A", "NAN"]:
                continue
                
            folium.map.Marker(
                location=[centroid.y, centroid.x],
                icon=folium.DivIcon(
                    html=f"""<div style="font-size:{font_size}; font-weight:{font_weight}; color:{font_color};">{label_value}</div>"""
                )
            ).add_to(map_obj)


def add_map_title(
    map_obj: folium.Map,
    title_text: str,
    font_size: str = "16px",
    font_weight: str = "bold",
    padding: str = "5px"
) -> None:
    """
    Add a centered title to a folium map.
    
    Args:
        map_obj: Folium map object to add title to
        title_text: Text to display as title
        font_size: CSS font size for title
        font_weight: CSS font weight for title
        padding: CSS padding around title
    """
    title_html = f'''
        <h3 align="center" style="font-size:{font_size}; font-weight:{font_weight}; padding: {padding};">{title_text}</h3>
    '''
    map_obj.get_root().html.add_child(folium.Element(title_html))


def add_labels_and_title(
    map_obj: folium.Map,
    gdf: gpd.GeoDataFrame,
    label_field: str,
    title_text: str
) -> None:
    """
    Add both centroid labels and title to a folium map (legacy wrapper function).
    
    Args:
        map_obj: Folium map object
        gdf: GeoDataFrame containing geometry and label data
        label_field: Column name for labels
        title_text: Title text for map
    """
    add_centroid_labels(map_obj, gdf, label_field)
    add_map_title(map_obj, title_text)


def load_cost_data(county_dir: str, subfolder: str, prefix: str, scenario_row: int = 0) -> pd.Series:
    """
    Load results data from timestamped CSV files in county results directories.
    
    Args:
        county_dir: County directory path (e.g., "data/loadprofiles/baseline/single-family-detached/alameda")
        subfolder: Results subfolder (e.g., "solarstorage", "costs", "payback")
        prefix: File prefix (e.g., "solar_results", "cost_results") 
        scenario_row: Which scenario row to return (0=baseline, 1=with solar+storage)
    
    Returns:
        pandas Series with all columns for the specified scenario
    """
    path = os.path.join(county_dir, "results", subfolder)
    county = os.path.basename(county_dir)
    full_prefix = f"{prefix}_{county}_"
    file_path = get_latest_csv_file(path, full_prefix)
    df = pd.read_csv(file_path, index_col="scenario")
    
    return df.iloc[scenario_row] # Baseline = row 0, Solar + storage = row 1

