"""
DEPRECATED: Capital Cost Comparison - Old vs New Methods

This module has been consolidated into the unified difference_map_builder.py.
The original complex logic for comparing capital cost implementations has been 
simplified to use the standardized difference map generation framework.
"""

import os
import pandas as pd
from helpers import log, norcal_counties, socal_counties, central_counties
from difference_map_builder import compare_capital_cost_methods

def process(base_input_dir, base_output_dir, scenario, housing_type, counties, desired_rate_plans):
    """
    Creates difference maps comparing old vs new capital costs implementations.
    
    Parameters:
        base_input_dir (str): Base input directory.
        base_output_dir (str): Directory where output HTML files will be saved.
        scenario (str): Scenario name.
        housing_type (str): Housing type.
        counties (list): List of counties to process.
        desired_rate_plans (dict): Dictionary of rate plans for utilities.
    """
    
    log(
        at="step18_difference_maps_old_new_capital_costs",
        info="starting_capital_cost_comparison",
        scenario=scenario,
        housing_type=housing_type
    )
    
    # Use the unified capital cost comparison function
    compare_capital_cost_methods(
        base_input_dir=base_input_dir,
        base_output_dir=base_output_dir,
        scenario=scenario,
        housing_type=housing_type,
        counties=counties,
        method_a="old",
        method_b="new"
    )
    
    log(
        at="step18_difference_maps_old_new_capital_costs",
        success="capital_cost_comparison_completed"
    )

if __name__ == '__main__':
    base_input_dir = "data/loadprofiles"
    base_output_dir = "data/loadprofiles"
    scenario = "heat_pump_and_induction_stove_and_water_heating"
    housing_type = "single-family-detached"
    desired_rate_plans = {
        "PG&E": {"electricity": "E-TOU-D", "gas": "G-1"},
        "SCE": {"electricity": "TOU-D-4-9PM", "gas": "GR"},
        "SDG&E": {"electricity": "TOU-DR1", "gas": "GR"}
    }

    all_counties = norcal_counties + socal_counties + central_counties
    log(scenario=scenario)
    process(base_input_dir, base_output_dir, scenario, housing_type, all_counties, desired_rate_plans)