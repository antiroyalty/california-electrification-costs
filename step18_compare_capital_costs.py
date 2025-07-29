"""
Step 18: Compare Capital Costs

Show the differences between Mine and Cris's capital costs.
Just component by component, create bar graphs or something.
"""

import os
from main_helpers import log


def process(base_input_dir: str, base_output_dir: str, scenario: str,
           housing_type: str, counties: list):
    """
    Compare different capital cost methodologies.
    
    Args:
        base_input_dir: Input directory path
        base_output_dir: Output directory path
        scenario: Scenario name
        housing_type: Housing type
        counties: List of counties to process
    """
    
    log(
        at="step18_compare_capital_costs",
        info="starting_capital_cost_comparison",
        scenario=scenario,
        housing_type=housing_type
    )
    
    # TODO: Implement capital cost comparison
    # This should:
    # - Compare my capital costs vs Cris's capital costs
    # - Create component-by-component bar graphs
    # - Show differences in methodology and results
    
    print("Step 18: Capital cost comparison not yet implemented")
    print("Will create component-by-component comparisons when implemented")
    
    log(
        at="step18_compare_capital_costs",
        info="capital_cost_comparison_skipped",
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