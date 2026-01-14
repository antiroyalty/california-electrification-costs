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

from helpers.main_helpers import get_counties, get_scenario_path, log, to_decimal_number, slugify_county_name
from helpers.maps_helpers import initialize_map, get_latest_csv_file, build_metric_map
from helpers.utility_helpers import get_utility_for_county


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
        Compare two scenarios and produce difference maps saved under a subdirectory of the output directory.
        
        Args:
            config: DifferenceMapConfig specifying the comparison details
            counties: List of counties to include in the map
            desired_rate_plans: Optional dictionary specifying desired rate plans for each utility
        """
        output_dir = os.path.join(self.base_output_dir, config.output_subdir)
        os.makedirs(output_dir, exist_ok=True)
        
        rows = []
        for county in counties:
            try:
                left_series = self.load_cost_data(config.scenario_a, county, config.subfolder_a, config.file_prefix, config.row_name_a)
                right_series = self.load_cost_data(config.scenario_b, county, config.subfolder_b, config.file_prefix, config.row_name_b)
                if left_series.empty or right_series.empty:
                    continue
                diffs = self.calculate_differences(left_series, right_series, config.diff_calculation)
                diffs.name = county
                rows.append(diffs)
            except Exception as e:
                log(at="difference_map_builder", error="row_compute_failed", county=county, exception=str(e))
                continue
        if not rows:
            print("No data to compare; nothing to build.")
            return
        df = pd.DataFrame(rows)
        df.index.name = "county"
        out_csv = os.path.join(output_dir, f"differences_{config.scenario_b}_vs_{config.scenario_a}.csv")
        df.to_csv(out_csv)
        print(f"Saved differences CSV: {out_csv}")

        # Build a basic heatmap for a default column (first column), or utility-filtered columns
        default_col = df.columns[0]
        for col in [default_col]:
            try:
                # Fake a map builder using helpers.maps_helpers.build_metric_map
                # Create a simple DataFrame aligned with expected build_metric_map API
                mdf = pd.DataFrame({
                    'county_slug': [slugify_county_name(c) for c in df.index],
                    col: [df.loc[c, col] for c in df.index],
                })
                title = config.map_title_template.format(scenario_a=config.scenario_a, scenario_b=config.scenario_b)
                fmap = build_metric_map(mdf, metric=col, title=title)
                out_html = os.path.join(output_dir, f"map_{col.replace('.', '_')}.html")
                fmap.save(out_html)
                print(f"Saved map: {out_html}")
            except Exception as e:
                log(at="difference_map_builder", error="map_build_failed", metric=col, exception=str(e))

