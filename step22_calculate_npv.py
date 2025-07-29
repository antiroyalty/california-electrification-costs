"""
Step 22: Calculate NPV

Calculate the NPV for each scenario, in addition to the payback period.
Define the NPV parameters here.
"""

import os
from main_helpers import log


def process(base_input_dir: str, base_output_dir: str, scenario: str,
           housing_type: str, counties: list, desired_rate_plans: dict):
    """
    Calculate Net Present Value (NPV) for each scenario.
    
    Args:
        base_input_dir: Input directory path
        base_output_dir: Output directory path
        scenario: Scenario name
        housing_type: Housing type
        counties: List of counties to process
        desired_rate_plans: Rate plans by utility
    """
    
    log(
        at="step22_calculate_npv",
        info="starting_npv_calculation",
        scenario=scenario,
        housing_type=housing_type
    )
    
    # TODO: Implement NPV calculation
    # This should:
    # - Define NPV parameters (discount rate, analysis period)
    # - Calculate NPV for each electrification scenario
    # - Factor in capital costs, annual savings, equipment lifetimes
    # - Generate NPV maps and comparisons
    
    print("Step 22: NPV calculation not yet implemented")
    print("Will calculate Net Present Value for scenarios when implemented")
    
    log(
        at="step22_calculate_npv",
        info="npv_calculation_skipped",
        reason="not_yet_implemented"
    )


if __name__ == "__main__":
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