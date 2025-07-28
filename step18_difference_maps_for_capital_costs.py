"""
DEPRECATED: Generic Capital Cost Difference Maps

This module has been consolidated into the unified difference_map_builder.py.
The generate_diff_html_maps function is now handled by the DifferenceMapBuilder
class with consistent styling and output formats.
"""

import os
from typing import Sequence
import geopandas as gpd
import pandas as pd
from helpers import get_scenario_path, to_decimal_number, log
from difference_map_builder import DifferenceMapBuilder, DifferenceMapConfig

def generate_diff_html_maps(
    diff_geojson_fp: str,
    scenario_a: str,
    scenario_b: str,
    out_dir: str,
    column_name: str
) -> None:
    """
    DEPRECATED: Use DifferenceMapBuilder instead.
    
    This function has been replaced by the unified difference map builder.
    For new implementations, create a DifferenceMapConfig and use
    DifferenceMapBuilder.compare_scenarios() method.
    """
    
    log(
        at="step18_difference_maps_for_capital_costs",
        warning="deprecated_function_used",
        function="generate_diff_html_maps",
        recommendation="Use DifferenceMapBuilder instead"
    )
    
    # Load the existing GeoJSON difference data
    diff_gdf = gpd.read_file(diff_geojson_fp)
    
    # Create output directory
    os.makedirs(out_dir, exist_ok=True)
    
    # Use the unified map builder for consistent output
    builder = DifferenceMapBuilder("", "", "")  # Minimal initialization for legacy support
    
    # Generate the HTML map using the modern approach
    fmt_col = f"{column_name}_fmt"
    diff_gdf[fmt_col] = diff_gdf[column_name].apply(
        lambda x: to_decimal_number(x) if pd.notnull(x) else "N/A"
    )
    
    # Create a basic config for legacy compatibility
    config = DifferenceMapConfig(
        scenario_a=scenario_a,
        scenario_b=scenario_b,
        comparison_type="legacy",
        output_subdir="",
        map_title_template=f"{scenario_b} vs {scenario_a} ({column_name})"
    )
    
    # Generate the map directly
    builder._generate_html_map(diff_gdf, out_dir, column_name, fmt_col, config)
    
    log(
        at="step18_difference_maps_for_capital_costs",
        info="legacy_map_generated",
        output_dir=out_dir,
        column=column_name
    )