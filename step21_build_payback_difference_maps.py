"""
Step 21: Build Payback Difference Maps

Show the differences in Payback Periods between Out of the Blue electrification, 
and End of Life electrification.
Do the same for my capital costs vs. Cris's capital costs.

Map how the payback periods differ across California.
"""

import os
from main_helpers import log


def process(base_input_dir: str, base_output_dir: str, housing_type: str, 
           counties: list, scenario_a: str, scenario_b: str, 
           comparison_a: str, comparison_b: str):
    """
    Build difference maps for payback period comparisons.
    
    Args:
        base_input_dir: Input directory path
        base_output_dir: Output directory path
        housing_type: Housing type
        counties: List of counties to process
        scenario_a: First scenario for comparison
        scenario_b: Second scenario for comparison
        comparison_a: First comparison type
        comparison_b: Second comparison type
    """
    
    log(
        at="step21_build_payback_difference_maps",
        info="starting_payback_difference_maps",
        housing_type=housing_type,
        scenario_a=scenario_a,
        scenario_b=scenario_b
    )
    
    # TODO: Implement payback difference maps
    # This should:
    # - Compare Out of Blue vs End of Life payback periods
    # - Compare my capital costs vs Cris's capital costs
    # - Generate difference maps showing geographic variation
    # - Use DifferenceMapBuilder class
    
    print("Step 21: Payback difference maps not yet implemented")
    print("Will show payback period differences across California when implemented")
    
    log(
        at="step21_build_payback_difference_maps",
        info="payback_difference_maps_skipped",
        reason="not_yet_implemented"
    )


if __name__ == "__main__":
    process(
        base_input_dir="data/loadprofiles",
        base_output_dir="data/loadprofiles",
        housing_type="single-family-detached",
        counties=["Alameda County"],
        scenario_a="baseline",
        scenario_b="baseline",
        comparison_a="baseline",
        comparison_b="baseline.solarstorage"
    )