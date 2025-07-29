"""
Step 17: Build Gas Capital Costs

Build Capital Costs, Lifetimes, Incentives (if they apply) for the gas 
counterparts of each of the components in question.

This enables comparison between electric and gas appliance costs.
"""

import os
from main_helpers import log


def process(base_input_dir: str, base_output_dir: str, scenario: str,
           housing_type: str, counties: list):
    """
    Build gas capital costs, lifetimes, and incentives.
    
    Args:
        base_input_dir: Input directory path
        base_output_dir: Output directory path
        scenario: Scenario name
        housing_type: Housing type
        counties: List of counties to process
    """
    
    log(
        at="step17_build_gas_capital_costs",
        info="starting_gas_capital_costs",
        scenario=scenario,
        housing_type=housing_type
    )
    
    # TODO: Implement gas capital cost definitions
    # This should define:
    # - Gas appliance capital costs (furnaces, water heaters, stoves)
    # - Gas appliance lifetimes
    # - Any applicable incentives for gas appliances
    # - Enable comparison with electric alternatives
    
    print("Step 17: Gas capital costs not yet implemented")
    print("Will define gas appliance costs and lifetimes when implemented")
    
    log(
        at="step17_build_gas_capital_costs",
        info="gas_capital_costs_skipped",
        reason="not_yet_implemented"
    )


if __name__ == "__main__":
    process(
        base_input_dir="data/loadprofiles",
        base_output_dir="data/loadprofiles",
        scenario="baseline",
        housing_type="single-family-detached", 
        counties=["Alameda County"]
    )