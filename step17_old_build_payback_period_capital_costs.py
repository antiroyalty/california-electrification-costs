import os
import pandas as pd
import geopandas as gpd
from main_helpers import get_counties, get_scenario_path, slugify_county_name, norcal_counties, socal_counties, central_counties, log
from helpers.utility_helpers import get_utility_for_county
from helpers.maps_helpers import initialize_map, get_latest_csv_file
from helpers.capital_costs_helper import process_payback_analysis
from helpers.payback_period_helper import CAPITAL_COSTS


def process(base_input_dir, base_output_dir, scenario, housing_type, counties, desired_rate_plans):
    """
    Constructs maps for payback period analysis using OLD capital costs structure.
    """
    return process_payback_analysis(
        base_input_dir, base_output_dir, scenario, housing_type, counties, desired_rate_plans,
        CAPITAL_COSTS, "OLD_CAPITAL_COSTS", "OLD"
    )

if __name__ == '__main__':
    base_input_dir = "data/loadprofiles"
    base_output_dir = "data/loadprofiles"
    scenario = "heat_pump_and_induction_stove_and_water_heating" 
    # scenario = "water_heating"
    housing_type = "single-family-detached"
    # List counties to process, these names must match the directory names in the scenario path.
    # counties = ["Los Angeles County", "Alameda County", "Contra Costa"]
    desired_rate_plans = {
        "PG&E": {"electricity": "E-TOU-D", "gas": "G-1"},
        "SCE": {"electricity": "TOU-D-4-9PM", "gas": "GR"},
        "SDG&E": {"electricity": "TOU-DR1", "gas": "GR"}
    }

    all_counties = norcal_counties + socal_counties + central_counties
    log(scenario = scenario)
    process(base_input_dir, base_output_dir, scenario, housing_type, all_counties, desired_rate_plans)