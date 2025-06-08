import os
import pandas as pd
import geopandas as gpd
import folium
import numpy as np

from maps_helpers import get_latest_csv_file
from helpers import to_number, to_decimal_number
from utility_helpers import get_utility_for_county

# Personal notes for CAB meeting
# workforce is a big part of electfiication adoption
# contractor availability is a big factor, especially in rural areas
# subsidies scenarios to look at the EBB subsidies
# electrical pricing: a really big painpoint is the V&M charge, the $5 charge
# AB 306 is a direct threat to the deployment of heat pumps, PV, EV, energy efficiency and any other energy code requirements.
# Education, education, education! Safety of battery storage, climate change, incentives, faster charging access for EV’s, rural access to DC fast charging, etc
# Doing indoor air quality testing, so that people give up the value of giving up their gas stove
# https://www.law.berkeley.edu/research/clee/research/climate/projectclimate/projects/los-angeles-fire-recovery
# Incentives for developers who are building affordable housing to incorporate these items. To that end, education for developers.
# Disconnection fees by PG&E are problematic.
# Rebuilding for speed: faster with just electric
# Supply chain: evenly split between gas and electric
# Utility reform to support electrification rather than expanding their natural gas infrastructure
# Workforce training

LIFETIMES = {
    "solar": 25, # https://www.energysage.com/solar/how-long-do-solar-panels-last/
    "storage": 15, # years
    "heat_pump": 15, # https://www.energysage.com/heat-pumps/how-long-do-heat-pumps-last/
    "induction_stove": 15, # https://www.greenbuildermedia.com/blog/dont-throw-out-that-old-electric-coil-stove-for-an-induction-top-yet
    "water_heater": 15, # https://www.oliverheatcool.com/about/blog/news-for-homeowners/the-average-lifespan-of-water-heaters/
}

FIXED_BINS = {
    "Payback Period": [-500, -100, -80, -60, -40, -20, 0, 20, 40, 60, 80, 100, 500],
    "Annual Savings": [-600, -450, -300, -150, 0, 0.1, 250, 500, 750, 1000, 1250, 1500, 1750, 2000, 2500, 3000, 3500],
    "Total Cost": [0, 5000, 10000, 15000, 20000, 25000, 30000, 35000, 40000, 45000, 50000],
    "Annual Savings % Change": [-200, -100, -50, -25, 0, 0.001, 25, 50, 100, 200],
    "Solar Size (kW)": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15]   # kW buckets
}

COLOR_SCHEMES = {
    "Annual Savings": {"positive": "YlGn", "negative": "OrRd_r"},
    "Annual Savings % Change": { "positive": "YlGn",  "negative": "OrRd_r"},
    "Total Cost": {"default": "YlOrRd"},
    "Solar Size (kW)": {"default": "YlOrBr"}
}

def load_cost_data(county_dir, subfolder, prefix):
    path = os.path.join(county_dir, "results", subfolder)
    county = os.path.basename(county_dir)
    full_prefix = f"{prefix}_{county}_"
    file_path = get_latest_csv_file(path, full_prefix)
    df = pd.read_csv(file_path, index_col="scenario")

    if subfolder == "solarstorage":
        # Use the second row (assumed to be the solar+storage scenario)
        return df.iloc[1]
    else:
        # Baseline scenario row
        return df.iloc[0]
    
def style_function(feature):
    utility = feature["properties"].get("Utility", "")
    if utility == "PG&E":
        outline_color = "blue"
    elif utility == "SCE":
        outline_color = "orange"
    elif utility == "SDG&E":
        outline_color = "purple"
    else:
        outline_color = "black"
    return {
        "fillColor": "transparent",
        "color": outline_color,
        "weight": 1,
        "fillOpacity": 0,
    }

def split_payback_groups(gdf, col, lifetime):
    neg = gdf[gdf[col] < 0]                       # loses money
    inw = gdf[(gdf[col] >= 0) & (gdf[col] <= lifetime)]
    out = gdf[gdf[col] > lifetime]                # > life

    # choose equal-width bins within each sub-range
    neg_bins = np.linspace(neg[col].min(), 0, 6).tolist() if not neg.empty else []
    in_bins  = np.linspace(0, lifetime, 6).tolist()        if not inw.empty else []
    out_bins = np.linspace(lifetime, out[col].max(), 6).tolist() if not out.empty else []

    return [
        (neg, "OrRd_r", neg_bins, "(Loss)"),
        (inw, "Greens_r", in_bins,  f"(≤ {lifetime} yrs)"),
        (out, "OrRd",   out_bins, f"(> {lifetime} yrs)")
    ]

def prepare_data_columns(merged_gdf, desired_rate_plans, metric, variant, title_prefix=""):
    if variant.endswith("_only"):
        suffix = "(Electrification Only)"
    elif variant.endswith("_solar"):
        suffix = "(Electrification + Solar + Storage)"
    else:
        suffix = f"({variant.replace('_', ' ').title()})"

    col_map = {
        "Payback Period": f"Payback Period {suffix}",
        "Annual Savings": f"Annual Savings {suffix}",
        "Total Cost": f"Total Cost {suffix}",
        "Solar Size (kW)": "Solar Size (kW)",
        # "Annual Savings % Change": "Annual Savings % Change",
    }

    data_column = col_map[metric]
    legend_name = f"{metric} {suffix}"
    label_field = data_column
    title_text = f"{title_prefix}{metric} {suffix}"

    # Ensure values are numeric
    merged_gdf[data_column] = pd.to_numeric(merged_gdf[data_column], errors="coerce")
    merged_gdf["Utility"] = merged_gdf["county_slug"].apply(get_utility_for_county)
    merged_gdf["Rate Plan"] = merged_gdf["Utility"].apply(
        lambda u: f"Electricity: {desired_rate_plans[u]['electricity']}, Gas: {desired_rate_plans[u]['gas']}"
        if u and u in desired_rate_plans else "N/A"
    )
    merged_gdf[f"{data_column}_fmt"] = merged_gdf[data_column].apply(
        lambda x: to_decimal_number(x) if pd.notnull(x) else "N/A"
    )

    return data_column, label_field, legend_name, title_text, suffix

def add_choropleth_layer(map_obj, gdf, data_column, fill_color, bins, legend_name):
    choropleth = folium.Choropleth(
        geo_data=gdf,
        data=gdf,
        columns=["NAME", data_column],
        key_on="feature.properties.NAME",
        fill_color=fill_color,
        bins=bins,
        fill_opacity=0.7,
        line_opacity=0.2,
        legend_name=legend_name,
        nan_fill_color="white",
        nan_fill_opacity=0.1,
        name=legend_name,
        legend_position="bottomright",
    )

    choropleth.add_to(map_obj)

def add_labels_and_title(map_obj, gdf, label_field, title_text):
    for _, row in gdf.iterrows():
        if pd.notnull(row[label_field]):
            centroid = row['geometry'].centroid
            label_value = row[f"{label_field}_fmt"]
            folium.map.Marker(
                location=[centroid.y, centroid.x],
                icon=folium.DivIcon(
                    html=f"""<div style="font-size:6pt; font-weight:bold; color:black;">{label_value}</div>"""
                )
            ).add_to(map_obj)

    title_html = f'''
        <h3 align="center" style="font-size:16px; font-weight:bold; padding: 5px;">{title_text}</h3>
    '''
    map_obj.get_root().html.add_child(folium.Element(title_html))

def build_metric_map(merged_gdf, desired_rate_plans, metric, variant, title_prefix=""):
    print("*******")
    print(metric)
    data_column, label_field, legend_name, title_text, suffix = prepare_data_columns(merged_gdf, desired_rate_plans, metric, variant, title_prefix)

    m = folium.Map(
        location=[37.8, -120],
        zoom_start=6,
        zoom_control=False, # hide +/- buttons
        width="550px",      # or 900
        height="700px",     # or "60vh"
    )

    css = f"""
        <style>
        /* #{m.get_name()} is the map’s <div> */
        #{m.get_name()} {{
            margin: 0 auto;         /* left & right auto = centred */
        }}
        </style>
        """
    m.get_root().html.add_child(folium.Element(css))

    m.get_root().html.add_child(folium.Element(
        '<style>.leaflet-control-layers{display:none !important;}</style>'
    ))

    # Split into positive/negative if metric allows
    values = merged_gdf[data_column]

    if metric == "Payback Period":
        lifetime = merged_gdf[f"Lifetime Limit {suffix}"].min()

        for sub_gdf, cmap, bins, label in split_payback_groups(merged_gdf, data_column, lifetime):
            if sub_gdf.empty or len(bins) < 2:             # GDF is empty (for instance no electrified appliances are within the payback period - lifetime window)
                continue
            add_choropleth_layer(
                m, sub_gdf, data_column,
                cmap, bins,
                f"{legend_name} {label}"
            )

    elif metric in {"Annual Savings", "Annual Savings % Change"}:
        gdf_pos = merged_gdf[values > 0]
        gdf_neg = merged_gdf[values <= 0]

        bins_pos = [b for b in FIXED_BINS[metric] if b > 0]
        bins_neg = [b for b in FIXED_BINS[metric] if b <= 0] + [0]

        if not gdf_pos.empty:
            add_choropleth_layer(m, gdf_pos, data_column, COLOR_SCHEMES[metric]["positive"], bins_pos, f"{legend_name} (Savings)")
        if not gdf_neg.empty:
            add_choropleth_layer(m, gdf_neg, data_column, COLOR_SCHEMES[metric]["negative"], bins_neg, f"{legend_name} (Loss)")
    else:
        # Total cost, solar capacity
        add_choropleth_layer(m, merged_gdf, data_column, COLOR_SCHEMES[metric]["default"], FIXED_BINS[metric], legend_name)

    # Tooltip layer
    tooltip = folium.GeoJsonTooltip(
        fields=["NAME", "Utility", "Rate Plan", "Solar Size (kW)", f"{data_column}_fmt"],
        aliases=["County:", "Utility:", "Rate Plan:", "Solar Size (kW)", f"{metric}:"],
        localize=True
    )

    geojson_layer = folium.GeoJson(
        merged_gdf,
        style_function=style_function,
        tooltip=tooltip,
        name="County Info"
    )
    geojson_layer.add_to(m)

    add_labels_and_title(m, merged_gdf, label_field, title_text)
    m.get_root().html.add_child(folium.Element(
        "<style>.leaflet-control-color-scale{display:none!important;}</style>"
    ))

    # ------------- Statistics panel
    stats_series = merged_gdf[data_column].dropna()

    if not stats_series.empty:
        stats = {
            "Min":    to_decimal_number(stats_series.min()),
            "Median": to_decimal_number(stats_series.median()),
            "Mean":   to_decimal_number(stats_series.mean()),
            "Max":    to_decimal_number(stats_series.max())
        }

        stats_html = (
            '<div style="width:550px; margin:20px auto 20px;'
            'padding:4px 6px;font-size:10pt;'
            'background:#f7f7f7;border:1px solid #bbb;'
            'border-radius:4px;text-align:center;" display="inline">'
            f'<b>{metric} summary:</b> '
            + ' &nbsp;|&nbsp; '.join(f'{k}: {v}' for k, v in stats.items())
            + '</div>'
        )

        m.get_root().html.add_child(folium.Element(stats_html))

    folium.LayerControl().add_to(m)
    return m

