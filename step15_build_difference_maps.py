import os
import pandas as pd
from helpers import log, norcal_counties, central_counties, socal_counties
from difference_map_builder import DifferenceMapBuilder, DifferenceMapConfig

# Legacy functions removed - now handled by DifferenceMapBuilder
    
def process(base_input_dir, base_output_dir, housing_type, counties, left_scenario, left_row, right_scenario, right_row):
    """
    Generate difference maps between two scenarios using the unified DifferenceMapBuilder.
    
    Args:
        base_input_dir: Input directory path
        base_output_dir: Output directory path  
        housing_type: Housing type (e.g., "single-family-detached")
        counties: List of counties to process
        left_scenario: Reference scenario name
        left_row: Row name in reference scenario CSV
        right_scenario: Comparison scenario name
        right_row: Row name in comparison scenario CSV
    """
    
    builder = DifferenceMapBuilder(base_input_dir, base_output_dir, housing_type)
    
    config = DifferenceMapConfig(
        scenario_a=left_scenario,
        scenario_b=right_scenario,
        comparison_type="scenario",
        output_subdir=f"difference_maps/{left_scenario}.{left_row}_vs_{right_scenario}.{right_row}",
        map_title_template=f"{right_scenario}.{right_row} vs {left_scenario}.{left_row} ({{metric}})",
        diff_calculation="absolute",
        row_name_a=left_row,
        row_name_b=right_row
    )
    
    builder.compare_scenarios(config, counties)
    
    log(
        at="step15_build_difference_maps",
        success="difference_maps_completed",
        left_scenario=left_scenario,
        left_row=left_row,
        right_scenario=right_scenario, 
        right_row=right_row
    )

if __name__ == '__main__':
    base_input_dir = "data/loadprofiles"
    base_output_dir = "data/loadprofiles"
    counties = norcal_counties + central_counties + socal_counties
    housing_type = "single-family-detached"

    process(base_input_dir, base_output_dir, "single-family-detached", counties, "baseline", "baseline", "induction_stove", "induction_stove")
    # process(base_input_dir, base_output_dir, "single-family-detached", counties, "baseline", "baseline", "heat_pump", "heat_pump")
    # process(base_input_dir, base_output_dir, "single-family-detached", counties, "baseline", "baseline.solarstorage", "heat_pump", "heat_pump.solarstorage")
    # process(base_input_dir, base_output_dir, "single-family-detached", counties, "heat_pump", "heat_pump", "heat_pump", "heat_pump.solarstorage") # baseline vs. baseline solarstorage
    # process(base_input_dir, base_output_dir, "single-family-detached", counties, "baseline", "baseline", "heat_pump", "heat_pump.solarstorage")
