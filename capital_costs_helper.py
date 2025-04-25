import os
import pandas as pd
import geopandas as gpd
import folium
import numpy as np

from maps_helpers import get_latest_csv_file
from helpers import to_number
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

CAPITAL_COSTS = {
    "solar": {
        # Back-calculated from PG&E's cost estimator website: https://pge.wattplan.com/PV/Wizard/?sector=residential&
        "dollars_per_watt": 0.95,          # $/W for panels https://www.tesla.com/learn/solar-panel-cost-breakdown
        "installation_labor": 0.07,         # 7% extra cost for labor
        "design_eng_overhead_percent": 0.28 # 28% extra cost for design/engineering
    },
    "storage": {
        # Other papers suggest: 1200–$1600 per kilowatt-hour which would = $16320 - $21600 https://www.mdpi.com/2071-1050/16/23/10320#:~:text=residential%20solar%20and%20BESS%2C%20the,6%2FWh%20in%20Texas%20%28Figure%203d
        # https://energylibrary.tesla.com/docs/Public/EnergyStorage/Powerwall/3/Datasheet/en-us/Powerwall-3-Datasheet.pdf
        "powerwall_13.5kwh": 16853          # Cost for one Tesla Powerwall 3 before incentives. https://www.tesla.com/powerwall/design/overview
    },
    "heat_pump": {
        # Rewiring america: $19,000 https://www.rewiringamerica.org/research/home-electrification-cost-estimates
        # "average": 19000, # https://www.nrel.gov/docs/fy24osti/84775.pdf#:~:text=dwelling%20units,9%2C000%2C%20%2420%2C000%2C%20and%20%2424%2C000%20for
        # https://incentives.switchison.org/residents/incentives?state=CA&field_zipcode=90001&_gl=1*1ck7fcj*_gcl_au*OTAxNTQyNjA3LjE3NDQ1NjYxNzg.*_ga*MTEwMTk5ODQ0LjE3NDQ1NjYxNzg.*_ga_8NM1W0PLNN*MTc0NDU2NjE3OC4xLjEuMTc0NDU2NjIwNC4zNC4wLjA.
        # E3 cites single family residential heat pump cost to be $19,000 https://www.ethree.com/wp-content/uploads/2023/12/E3_Benefit-Cost-Analysis-of-Targeted-Electrification-and-Gas-Decommissioning-in-California.pdf#:~:text=%2419k%20%2415k%20%24154k%20The%20significant,commercial%20customers%20and%20therefore%20see
        "average": 19000,
    },
    "induction_stove": {
        # PG&E appliance guide also says $2000 https://guide.pge.com/browse/induction
        "average": 2000 # https://www.sce.com/factsheet/InductionCookingFactSheet
    }
}

# Consider low, medium, and high subsidy levels
# no one is installing standalone PV anymore with NEM 3.0
INCENTIVES = {
    "federal_tax_credit_2023_2032": 0.3, # 30% credit https://www.irs.gov/credits-deductions/residential-clean-energy-credit
    # Federal tax incentives will decline in later years
    "federal_tax_credit_2033": 0.26,
    "federal_tax_credit_2034": 0.22,
    "federal_tax_credit_2035": 0,
    "PGE_SCE_SDGE_General_SGIP_Rebate": 3375, #  General Market SGIP rebate of
        # approximately $250/kilowatt-hour https://www.cpuc.ca.gov/-/media/cpuc-website/files/uploadedfiles/cpucwebsite/content/news_room/newsupdates/2020/sgip-residential-web-120420.pdf
    "storage": {
        # "PG&E": {
            # "storage_rebate": 7500, # Only for homes in wildfire-prone areas, as deemed by PG&E https://www.tesla.com/support/incentives#california-local-incentives
        # },
        # "SCE": {

        # },
        # "SDG&E": {
        #     # https://www.sdge.com/solar/considering-solar
        # }
    },
    "heat_pump": {
        "other_rebates": 10000, # needed to make it worthwhile
        "max_federal_annual_tax_rebate": 2000,
        "california_TECH_incentive": 1500, # https://incentives.switchison.org/rebate-profile/tech-clean-california-single-family-hvac
    },
    "induction_stove": {
        "max_federal_annual_tax_rebate": 420, # https://www.geappliances.com/inflation-reduction-act
    },
    "water_heater": {
        "54-55gal": 700, # $700 rebate
        "55-75gal": 900 # $900 rebate https://incentives.switchison.org/residents/incentives?state=CA&field_zipcode=90001&_gl=1*1ck7fcj*_gcl_au*OTAxNTQyNjA3LjE3NDQ1NjYxNzg.*_ga*MTEwMTk5ODQ0LjE3NDQ1NjYxNzg.*_ga_8NM1W0PLNN*MTc0NDU2NjE3OC4xLjEuMTc0NDU2NjIwNC4zNC4wLjA.
    },
    "whole_building_electrification": 4250 # must include heat pump space heating, heat pump water heating, induction cooking, electric dryer https://caenergysmarthomes.com/alterations/#whole-building-eligibility
}

LIFETIMES = {
    "solar": 25, # https://www.energysage.com/solar/how-long-do-solar-panels-last/
    "storage": 15, # years
    "heat_pump": 15, # https://www.energysage.com/heat-pumps/how-long-do-heat-pumps-last/
    "induction_stove": 10, # https://www.greenbuildermedia.com/blog/dont-throw-out-that-old-electric-coil-stove-for-an-induction-top-yet
    "water_heater": 15, # https://www.oliverheatcool.com/about/blog/news-for-homeowners/the-average-lifespan-of-water-heaters/
}

FIXED_BINS = {
    "Payback Period": [-500, -100, -80, -60, -40, -20, 0, 20, 40, 60, 80, 100, 500], # ❌ Negative Payback = No Payback Ever
    "Annual Savings": [-2000, -1750, -1500, -1250, -1000, -750, -500, -250, 0, 0.1, 250, 500, 750, 1000, 1250, 1500, 1750, 2000],
    "Total Cost": [0, 10000, 20000, 30000, 40000, 50000, 60000, 80000, 100000],
    "Annual Savings % Change": [-200, -100, -50, -25, 0, 0.001, 25, 50, 100, 200, 2500],
}

COLOR_SCHEMES = {
    "Annual Savings": {"positive": "YlGn", "negative": "OrRd_r"},
    "Annual Savings % Change": { "positive": "YlGn",  "negative": "OrRd_r"},
    "Total Cost": {"default": "YlOrRd"}
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
        lambda x: to_number(x) if pd.notnull(x) else "N/A"
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

    folium.LayerControl().add_to(m)
    return m

