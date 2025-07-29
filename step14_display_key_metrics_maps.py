"""
Step 14: Display Key Metrics Maps

Display maps for key metrics:
- Average solar panel size in county
- Total annual load in county, in kWh
- Total electricity bill annually, in $
- Total gas bill annually, in $

Display this as 4 maps all on one tab, if possible.
"""

import os
from main_helpers import log


def process(base_input_dir: str, base_output_dir: str, scenario: str, 
           housing_type: str, counties: list, desired_rate_plans: dict):
    """
    Display key metrics maps for the scenario.
    
    Args:
        base_input_dir: Input directory path
        base_output_dir: Output directory path
        scenario: Scenario name
        housing_type: Housing type
        counties: List of counties to process
        desired_rate_plans: Rate plans by utility
    """
    
    log(
        at="step14_display_key_metrics_maps",
        info="starting_key_metrics_display",
        scenario=scenario,
        housing_type=housing_type,
        counties_requested=len(counties)
    )
    
    # TODO: Implement key metrics map display
    # This should show:
    # 1. Average solar panel size in county
    # 2. Total annual load in county, in kWh
    # 3. Total electricity bill annually, in $
    # 4. Total gas bill annually, in $
    
    print("Step 14: Key metrics maps display not yet implemented")
    print("Will display 4 key maps on one tab when implemented")
    
    log(
        at="step14_display_key_metrics_maps",
        info="key_metrics_display_skipped", 
        reason="not_yet_implemented"
    )


if __name__ == "__main__":
    # Test configuration
    desired_rate_plans = {
        "PG&E": {"electricity": "E-TOU-D", "gas": "G-1"},
        "SCE": {"electricity": "TOU-D-4-9PM", "gas": "GR"},
        "SDG&E": {"electricity": "TOU-DR1", "gas": "GR"}
    }
    
    process(
        base_input_dir="data/loadprofiles",
        base_output_dir="data/loadprofiles",
        scenario="baseline",
        housing_type="single-family-detached",
        counties=["Alameda County"],
        desired_rate_plans=desired_rate_plans
    )