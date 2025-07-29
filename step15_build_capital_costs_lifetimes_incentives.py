"""
Step 15: Build Capital Costs, Lifetimes, Incentives

Build Capital Costs, Lifetimes, Incentives for my numbers.
Define each technology as a class that can be configured. It has a capital cost, 
a lifetime, and associated incentives at the state, federal, and utility level.

I want the ability to configure different Component "scenarios", like:
- No Incentives
- Half Incentives  
- My Capital Costs
- Cris's Capital Costs
- EMP Capital Costs
"""

import os
from main_helpers import log


def process(base_input_dir: str, base_output_dir: str, scenario: str,
           housing_type: str, counties: list):
    """
    Build capital costs, lifetimes, and incentives definitions.
    
    Args:
        base_input_dir: Input directory path
        base_output_dir: Output directory path
        scenario: Scenario name
        housing_type: Housing type
        counties: List of counties to process
    """
    
    log(
        at="step15_build_capital_costs_lifetimes_incentives",
        info="starting_capital_costs_build",
        scenario=scenario,
        housing_type=housing_type
    )
    
    # TODO: Implement capital costs, lifetimes, incentives builder
    # This should define configurable technology classes with:
    # - Capital costs
    # - Equipment lifetimes
    # - Federal, state, utility incentives
    # - Different cost scenarios (No/Half/Full incentives, different cost methods)
    
    print("Step 15: Capital costs, lifetimes, incentives builder not yet implemented")
    print("Will define configurable technology classes when implemented")
    
    log(
        at="step15_build_capital_costs_lifetimes_incentives",
        info="capital_costs_build_skipped",
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