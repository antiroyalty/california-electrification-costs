import os
from typing import Sequence
import geopandas as gpd
import pandas as pd
from helpers import get_scenario_path, to_decimal_number
from maps_helpers import build_metric_map  
import folium

def generate_diff_html_maps(
    diff_geojson_fp: str,
    scenario_a: str,
    scenario_b: str,
    out_dir: str,
    column_name: str
) -> None:
    diff = gpd.read_file(diff_geojson_fp)
    os.makedirs(out_dir, exist_ok=True)

    # (column, legend title, palette)
    metrics = [
        (f"{column_name} diff",           f"∆ {column_name}",  "PuOr_r"),
    ]

    for col, legend_name, palette in metrics:
        diff[col] = diff[col].round(0)

        fmt_col = f"{col}_fmt"
        diff[fmt_col] = diff[col].apply(lambda x: str(int(x)) if pd.notnull(x) else "N/A")

        # 2) Compute the max absolute value so our diverging scale is symmetric
        max_abs = diff[col].abs().max()

        threshold_scale = [
            -max_abs,
            -max_abs * 0.5,
             0,
             max_abs * 0.5,
             max_abs,
        ]

        title = f"{legend_name}: {scenario_b} vs. {scenario_a}"
        m = build_metric_map(
            gdf=diff,
            column=col,
            title_text=title,
            tooltip_fields=["NAME", fmt_col],
            tooltip_aliases=["County:", legend_name],
            fill_color=palette,
            legend_name=legend_name,
            diverging=True,
            threshold_scale=threshold_scale
        )

        # add_diff_legend_note(
        #     m,
        #     scenario_a=scenario_a,
        #     scenario_b=scenario_b,
        #     metric_label=legend_name,
        #     positive_label="Positive",
        #     negative_label="Negative"
        # )

        out_fp = os.path.join(out_dir, f"{col.replace(' ', '_')}.html")
        m.save(out_fp)
        print(f"Wrote diff map to {out_fp}")
        os.system(f"open \"{out_fp}\"")

def add_diff_legend_note(
    m: folium.Map,
    scenario_a: str,
    scenario_b: str,
    metric_label: str,
    positive_label: str = "Positive",
    negative_label: str = "Negative"
):
    """
    Tacks on a little HTML box in the lower‐left corner that explains
    what + vs – means in your diff maps.
    """
    html = f"""
    <div style="
        position: fixed;
        bottom: 50px; left: 50px;
        background-color: white;
        padding: 8px;
        border: 1px solid #ccc;
        font-size: 12px;
        z-index: 9999;
        box-shadow: 2px 2px 6px rgba(0,0,0,0.3);
    ">
      <b>How to read<br>{metric_label} diff</b><br>
      <ul style="margin:4px 0 0 16px; padding:0; list-style:disc;">
        <li><b>{positive_label}</b>: {scenario_b} > {scenario_a} </li>
        <li><b>{negative_label}</b>: {scenario_b} < {scenario_a} </li>
      </ul>
    </div>
    """
    m.get_root().html.add_child(folium.Element(html))

def diff_scenarios(
    scn_a_fp: str,
    scn_b_fp: str,
    out_dir: str,
    metrics: Sequence[str]
    ) -> gpd.GeoDataFrame:
    """
    Compute per‑county differences between two scenario GeoJSONs.

    Parameters:
        scn_a_fp (str): Filepath to scenario A GeoJSON.
        scn_b_fp (str): Filepath to scenario B GeoJSON.
        out_dir (str): Directory where the diff GeoJSON will be written.
        metrics (Sequence[str]): List of property names to diff.

    Returns:
        gpd.GeoDataFrame: A GeoDataFrame with geometry and "<metric> diff" columns.
    """

    # 1) Read both; they come in as GeoDataFrames with crs set
    gdf_a = gpd.read_file(scn_a_fp)
    gdf_b = gpd.read_file(scn_b_fp)

    # 2) Set the join index on NAME (keeps geometry & crs!)
    gdf_a = gdf_a.set_index("NAME")
    gdf_b = gdf_b.set_index("NAME")

    # 3) Join A’s metrics onto B, asking pandas to suffix overlaps
    diff = gdf_b.join(
      gdf_a[list(metrics)], # no tuple key issue :')
      how="left",
      lsuffix="_b",
      rsuffix="_a"
    )
    # diff is still a GeoDataFrame, with diff.crs == gdf_b.crs

    # 4) Compute your diffs
    for m in metrics:
        diff[f"{m} diff"] = diff[f"{m}_b"] - diff[f"{m}_a"]

    # 5) (Optional) drop the raw _a/_b columns...
    drop_cols = [f"{m}_a" for m in metrics] + [f"{m}_b" for m in metrics]
    diff = diff.drop(columns=drop_cols)

    # 6) Write out
    base_a = os.path.splitext(os.path.basename(scn_a_fp))[0]
    base_b = os.path.splitext(os.path.basename(scn_b_fp))[0]
    out_fp = os.path.join(out_dir, f"diff_{base_a}_{base_b}.geojson")
    diff.to_file(out_fp, driver="GeoJSON")

    return diff

if __name__ == '__main__':
    base_input_dir = "data/loadprofiles"
    base_output_dir = "data/loadprofiles"
    housing_type = "single-family-detached"

    scenario_a = "heat_pump"
    scenario_b = "heat_pump"

    file_a = "heat_pump_normal_subsidies" 
    # file_b = "heat_pump_50_percent_subsidies"
    file_b = "heat_pump_50_percent_subsidies"

    scenario_a = "induction_stove"
    scenario_b = "induction_stove"

    file_a = "induction_stove_normal_subsidies" 
    file_b = "induction_stove_0_subsidies"
    # file_b = "induction_stove_0_subsidies"

    column_name = "Payback Period (Electrification + Solar + Storage)"
    metric = ("Payback Period (Electrification + Solar + Storage)",)

    scenario_path_a = get_scenario_path(base_input_dir, scenario_a, housing_type)
    scenario_path_b = get_scenario_path(base_input_dir, scenario_b, housing_type)

    results_output_path = os.path.join(base_output_dir, scenario_a, housing_type, "RESULTS", "geojson")

    # 1) compute & write the diff GeoJSON
    diff = diff_scenarios(
      os.path.join(scenario_path_a, "RESULTS/geojson", f"{file_a}.geojson"),
      os.path.join(scenario_path_b, "RESULTS/geojson", f"{file_b}.geojson"),
      results_output_path,
      metric
    )
    # Positive “Annual Savings diff” -> county gets a “positive” color (e.g. blue in RdBu, green in RdYlGn) -> saved more in the heat‑pump case than in baseline.
    # Negative -> county gets a “negative” color (e.g. red) -> you actually saved less under heat pump than under baseline.

    # 2) point to the file diff_scenarios just created
    diff_geojson_fp = os.path.join(results_output_path, f"diff_{file_a}_{file_b}.geojson")

    # 3) generate the HTML maps for each diff‑metric
    generate_diff_html_maps(
        diff_geojson_fp=diff_geojson_fp,
        scenario_a=scenario_a,
        scenario_b=scenario_b,
        out_dir=os.path.join(results_output_path, "html_maps"),
        column_name=column_name
    )