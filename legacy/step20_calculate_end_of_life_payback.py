"""
Step 20: Calculate End-of-Life Payback

Then, do an "end-of-device life" electrification, when the component is being 
swapped when the previous gas component has reached its end of life.
Mostly, this affects the capital costs of electrification. Now, the "capital costs" 
get considered as electrified_capital_costs - gas_capital_costs, so incremental 
increase or decrease relative to the gas counterpart.
"""

import os
from main_helpers import log


def process(base_input_dir: str, base_output_dir: str, scenario: str,
           housing_type: str, counties: list, desired_rate_plans: dict):
    """
    Calculate end-of-life electrification payback periods.
    
    Args:
        base_input_dir: Input directory path
        base_output_dir: Output directory path
        scenario: Scenario name
        housing_type: Housing type
        counties: List of counties to process
        desired_rate_plans: Rate plans by utility
    """
    
    log(
        at="step20_calculate_end_of_life_payback",
        info="starting_end_of_life_payback",
        scenario=scenario,
        housing_type=housing_type
    )
    
    # TODO: Implement end-of-life payback calculation
    # This should:
    # - Calculate end-of-device-life electrification payback
    # - Use incremental costs (electric_cost - gas_cost)
    # - Account for remaining gas appliance life
    # - Compare with out-of-the-blue payback from step 19
    
    print("Step 20: End-of-life payback calculation not yet implemented")
    print("Will calculate incremental electrification payback when implemented")
    
    log(
        at="step20_calculate_end_of_life_payback",
        info="end_of_life_payback_skipped",
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