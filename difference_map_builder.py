"""
Unified Difference Map Builder

This module consolidates the difference map generation logic from step15 and step18 variants,
eliminating code duplication and providing a consistent interface for creating difference maps.
"""

import os
import pandas as pd
import geopandas as gpd
from dataclasses import dataclass
from typing import Dict, List, Optional, Union
from pathlib import Path

from helpers import get_counties, get_scenario_path, log, to_decimal_number, slugify_county_name
from helpers.maps_helpers import initialize_map, get_latest_csv_file, build_metric_map
from utility_helpers import get_utility_for_county


@dataclass
class DifferenceMapConfig:
    """Configuration for difference map generation"""
    scenario_a: str
    scenario_b: str
    comparison_type: str  # "scenario", "capital_cost_method", "custom"
    output_subdir: str
    map_title_template: str = "{scenario_b} vs {scenario_a}"
    diff_calculation: str = "absolute"  # "absolute", "percentage"
    subfolder_a: str = "totals"
    subfolder_b: str = "totals" 
    row_name_a: str = None  # If None, uses scenario_a
    row_name_b: str = None  # If None, uses scenario_b
    file_prefix: str = "RESULTS_total_annual_costs"


class DifferenceMapBuilder:
    """Unified builder for all difference map types"""
    
    def __init__(self, base_input_dir: str, base_output_dir: str, housing_type: str):
        self.base_input_dir = base_input_dir
        self.base_output_dir = base_output_dir  
        self.housing_type = housing_type
        
    def load_cost_data(self, scenario: str, county: str, subfolder: str = "totals", 
                      file_prefix: str = "RESULTS_total_annual_costs", row_name: str = None) -> pd.Series:
        """
        Load cost data for a specific scenario and county.
        
        Args:
            scenario: Scenario name
            county: County name
            subfolder: Subfolder under results/ (e.g., 'totals', 'solarstorage')
            file_prefix: Prefix of the CSV file to load
            row_name: Row to extract from the CSV. If None, uses scenario name.
            
        Returns:
            pandas Series with cost data for the specified row
        """
        county_slug = slugify_county_name(county)
        county_dir = os.path.join(
            self.base_input_dir, scenario, self.housing_type, county
        )
        
        results_dir = os.path.join(county_dir, "results", subfolder)
        full_prefix = f"{file_prefix}_{county_slug}_"
        
        try:
            latest_file = get_latest_csv_file(results_dir, full_prefix)
            df = pd.read_csv(latest_file, index_col="scenario")
            
            # Use provided row_name or fall back to scenario name
            target_row = row_name if row_name is not None else scenario
            
            if target_row not in df.index:
                available_rows = list(df.index)
                raise KeyError(f"Row '{target_row}' not found in {latest_file}. Available rows: {available_rows}")
                
            return df.loc[target_row]
            
        except FileNotFoundError as e:
            log(
                at="difference_map_builder",
                error="file_not_found",
                county=county,
                scenario=scenario,
                subfolder=subfolder,
                file_prefix=file_prefix
            )
            return pd.Series()
        except Exception as e:
            log(
                at="difference_map_builder", 
                error="data_loading_failed",
                county=county,
                scenario=scenario,
                exception=str(e)
            )
            return pd.Series()
            
    def calculate_differences(self, left_data: pd.Series, right_data: pd.Series, 
                            method: str = "absolute") -> pd.Series:
        """
        Calculate differences between two cost datasets.
        
        Args:
            left_data: First dataset (baseline/reference)
            right_data: Second dataset (comparison)
            method: "absolute" for (right - left) or "percentage" for ((right - left) / |left|) * 100
            
        Returns:
            pandas Series with calculated differences
        """
        if method == "absolute":
            return right_data - left_data
        elif method == "percentage":
            # Avoid division by zero
            mask = left_data != 0
            result = pd.Series(index=left_data.index, dtype=float)
            result[mask] = ((right_data[mask] - left_data[mask]) / abs(left_data[mask])) * 100
            result[~mask] = float('inf') if (right_data[~mask] != 0).any() else 0
            return result
        else:
            raise ValueError(f"Unknown difference calculation method: {method}")
            
    def compare_scenarios(self, config: DifferenceMapConfig, counties: List[str], 
                         desired_rate_plans: Dict[str, Dict[str, str]] = None) -> None:
        """
        Compare two scenarios and generate difference maps.
        
        Args:
            config: Configuration for the comparison
            counties: List of counties to process
            desired_rate_plans: Optional rate plans to filter columns
        """
        # Initialize California map
        california_gdf = initialize_map()
        
        # Get valid counties for both scenarios
        scenario_a_path = get_scenario_path(self.base_input_dir, config.scenario_a, self.housing_type)
        scenario_b_path = get_scenario_path(self.base_input_dir, config.scenario_b, self.housing_type)
        
        valid_counties_a = get_counties(scenario_a_path, counties)
        valid_counties_b = get_counties(scenario_b_path, counties) 
        valid_counties = list(set(valid_counties_a) & set(valid_counties_b))
        
        differences_data = []
        
        for county in valid_counties:
            try:
                # Load cost data for both scenarios
                costs_a = self.load_cost_data(
                    config.scenario_a, county, config.subfolder_a, 
                    config.file_prefix, config.row_name_a
                )
                costs_b = self.load_cost_data(
                    config.scenario_b, county, config.subfolder_b,
                    config.file_prefix, config.row_name_b  
                )
                
                if costs_a.empty or costs_b.empty:
                    log(
                        at="difference_map_builder",
                        warning="skipping_county_missing_data",
                        county=county
                    )
                    continue
                    
                # Calculate differences
                differences = self.calculate_differences(costs_a, costs_b, config.diff_calculation)
                
                # Prepare row data
                row_data = {"NAME": county}
                
                # Filter columns if rate plans are specified
                if desired_rate_plans:
                    utility = get_utility_for_county(county)
                    if utility in desired_rate_plans:
                        rate_elec = desired_rate_plans[utility]["electricity"] 
                        rate_gas = desired_rate_plans[utility]["gas"]
                        target_col = f"total.{utility}.{rate_elec}+{utility}.{rate_gas}"
                        
                        if target_col in differences:
                            row_data[target_col] = differences[target_col]
                else:
                    # Include all difference columns
                    for col, value in differences.items():
                        if pd.notnull(value):
                            row_data[col] = value
                            
                differences_data.append(row_data)
                
            except Exception as e:
                log(
                    at="difference_map_builder",
                    error="county_processing_failed", 
                    county=county,
                    exception=str(e)
                )
                continue
                
        if not differences_data:
            log(
                at="difference_map_builder",
                warning="no_valid_differences_computed",
                scenario_a=config.scenario_a,
                scenario_b=config.scenario_b
            )
            return
            
        # Create DataFrame and merge with map
        differences_df = pd.DataFrame(differences_data)
        merged_gdf = california_gdf.merge(differences_df, on="NAME", how="left")
        
        # Generate maps for each metric column
        self._generate_maps(merged_gdf, config)
        
        log(
            at="difference_map_builder",
            success="difference_maps_generated",
            scenario_a=config.scenario_a,
            scenario_b=config.scenario_b,
            counties_processed=len(differences_data)
        )
        
    def _generate_maps(self, merged_gdf: gpd.GeoDataFrame, config: DifferenceMapConfig) -> None:
        """Generate HTML and GeoJSON maps for difference data"""
        
        # Create output directories
        output_dir = os.path.join(self.base_output_dir, config.output_subdir)
        html_dir = os.path.join(output_dir, "html")
        geojson_dir = os.path.join(output_dir, "geojson")
        
        os.makedirs(html_dir, exist_ok=True)
        os.makedirs(geojson_dir, exist_ok=True)
        
        # Get metric columns (exclude NAME and geometry)
        metric_columns = [col for col in merged_gdf.columns if col not in ["NAME", "geometry"]]
        
        for col in metric_columns:
            if merged_gdf[col].isna().all():
                continue
                
            # Generate formatted column for display
            fmt_col = f"{col}_fmt"
            merged_gdf[fmt_col] = merged_gdf[col].apply(
                lambda x: to_decimal_number(x) if pd.notnull(x) else "N/A"
            )
            
            # Generate GeoJSON
            self._generate_geojson(merged_gdf, geojson_dir, col, fmt_col)
            
            # Generate HTML map
            self._generate_html_map(merged_gdf, html_dir, col, fmt_col, config)
            
    def _generate_geojson(self, gdf: gpd.GeoDataFrame, output_dir: str, 
                         col: str, fmt_col: str) -> None:
        """Generate GeoJSON file for a metric column"""
        subset = gdf[["NAME", "geometry", col, fmt_col]].copy()
        subset = subset[subset.geometry.notnull()]
        
        filename = os.path.join(output_dir, f"difference_{col.replace(' ', '_')}.geojson") 
        subset.to_file(filename, driver="GeoJSON")
        
    def _generate_html_map(self, gdf: gpd.GeoDataFrame, output_dir: str,
                          col: str, fmt_col: str, config: DifferenceMapConfig) -> None:
        """Generate HTML map for a metric column"""
        
        # Calculate symmetric diverging scale
        max_abs = gdf[col].abs().max()
        if pd.isna(max_abs) or max_abs == 0:
            return
            
        threshold_scale = [
            -max_abs,
            -max_abs * 0.5,
            0,
            max_abs * 0.5, 
            max_abs,
        ]
        
        title = config.map_title_template.format(
            scenario_a=config.scenario_a,
            scenario_b=config.scenario_b,
            metric=col
        )
        
        # Generate map using modern build_metric_map
        m = build_metric_map(
            gdf=gdf,
            column=col,
            title_text=title,
            tooltip_fields=["NAME", fmt_col],
            tooltip_aliases=["County:", "Difference:"],
            fill_color="PuOr_r",  # Purple-Orange diverging colormap
            legend_name=f"Difference ({col})",
            diverging=True,
            threshold_scale=threshold_scale
        )
        
        filename = os.path.join(output_dir, f"difference_map_{col.replace(' ', '_')}.html")
        m.save(filename)
        
        log(
            at="difference_map_builder",
            map_saved=filename,
            metric=col
        )


def compare_capital_cost_methods(base_input_dir: str, base_output_dir: str, 
                               scenario: str, housing_type: str, counties: List[str],
                               method_a: str, method_b: str) -> None:
    """
    Compare two capital cost calculation methods (e.g., "old" vs "new" or "new" vs "cris").
    
    Args:
        base_input_dir: Input directory path
        base_output_dir: Output directory path
        scenario: Scenario to analyze
        housing_type: Housing type (e.g., "single-family-detached")
        counties: List of counties to process
        method_a: First method identifier ("old", "new", "cris")
        method_b: Second method identifier ("old", "new", "cris")
    """
    
    builder = DifferenceMapBuilder(base_input_dir, base_output_dir, housing_type)
    
    config = DifferenceMapConfig(
        scenario_a=scenario,
        scenario_b=scenario,
        comparison_type="capital_cost_method",
        output_subdir=f"capital_cost_comparison/{method_a}_vs_{method_b}/{scenario}",
        map_title_template=f"Capital Cost Comparison: {method_b.upper()} vs {method_a.upper()} ({{metric}})",
        diff_calculation="absolute"
    )
    
    # Note: This is a simplified version. Full implementation would need to
    # handle the different capital cost calculation results from step17 variants
    log(
        at="difference_map_builder",
        info="capital_cost_method_comparison_placeholder",
        method_a=method_a,
        method_b=method_b,
        scenario=scenario
    )