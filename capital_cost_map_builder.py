import os
import pandas as pd
import geopandas as gpd
import folium
import numpy as np

from helpers.maps_helpers import get_latest_csv_file, add_choropleth_layer, add_labels_and_title, load_cost_data
from helpers.main_helpers import to_number, to_decimal_number
from helpers.utility_helpers import get_utility_for_county

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
    "Solar Size (kW)": [-1, 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15]   # kW buckets
}

COLOR_SCHEMES = {
    "Annual Savings": {"positive": "YlGn", "negative": "OrRd_r"},
    "Annual Savings % Change": { "positive": "YlGn",  "negative": "OrRd_r"},
    "Total Cost": {"default": "YlOrRd"},
    "Solar Size (kW)": {"default": "YlOrBr"}
}

# load_cost_data function moved to helpers/maps_helpers.py for reusability
    
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

def build_capital_cost_map(merged_gdf, desired_rate_plans, metric, variant, title_prefix=""):
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

