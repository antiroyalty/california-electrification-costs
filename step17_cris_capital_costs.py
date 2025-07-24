import os
import pandas as pd
import geopandas as gpd
from helpers import get_counties, get_scenario_path, slugify_county_name, norcal_counties, socal_counties, central_counties, log
from utility_helpers import get_utility_for_county
from maps_helpers import initialize_map, get_latest_csv_file
from capital_costs_helper import process_payback_analysis

# CAPITAL_COSTS_CRIS - 2025 Capital Costs Data
# Based on CARB data, TECH California, and NREL sources
# Note: Using 2025 specific costs from Cris's research, no inflation adjustment needed

# Gas appliance costs (2025 base costs from Cris's research)
GAS_SPACE_HEATER = 4500  # Gas furnace cost
GAS_WATER_HEATER = 900   # Gas water heater cost  
GAS_COOKSTOVE = 1600     # Gas cookstove cost

# Electric appliance costs (2025 costs from Cris's research)
INDUCTION_COOKSTOVE = 2400  # Induction cookstove cost
CENTRALIZED_AC_COST = 5930  # Centralized AC unit cost

# Heat pump costs from TECH California and NREL data (2025)
HP_SPACE_HEATING_COST_PER_TON = 3753.78  # ASHP cost per ton of heating
HP_WATER_HEATING_COST_PER_GAL = 169.60   # HPWH cost per gallon capacity
WATER_HEATER_CAPACITY_GAL = 55 / 3.785   # 55 liters converted to gallons (~14.54 gal)

# Efficiency data
GAS_FURNACE_EFFICIENCY = 0.83      # 83% efficiency
GAS_WATER_HEATER_EFFICIENCY = 0.83 # 83% efficiency
GAS_TO_INDUCTION_EFFICIENCY_GAIN = 3  # 3x efficiency gain from gas to induction

# Heat pump coefficients of performance (COP)
ASHP_COP_SPACE_HEATING = 3.375  # Air source heat pump COP for space heating
HPWH_COP_WATER_HEATING = 3.250  # Heat pump water heater COP

# Calculate actual costs
HP_WATER_HEATER_COST = HP_WATER_HEATING_COST_PER_GAL * WATER_HEATER_CAPACITY_GAL  # ~$2466.78

CAPITAL_COSTS_CRIS = {
    "solar": {
        "panel": {
            "base": {
                "value": 2.8,  # TODO: Update with actual 2025 solar cost data
                "unit": "$/W"
            },
            "markup": {
                "installation_labor": {
                    "value": 0,  # TODO: Update with actual markup data
                    "unit": "%"
                },
                "design_engineering": {
                    "value": 0,  # TODO: Update with actual markup data
                    "unit": "%"
                }
            },
            "sources": [
                "TBD - User will provide solar sources"
            ],
            "last_verified": "2025-01-01"
        }
    },
    "storage": {
        "tesla_powerwall_3": {
            "capacity_kwh": 13.5,
            "base": {
                "value": 16853,  # TODO: Update with actual 2025 storage cost data
                "unit": "$"
            },
            "sources": [
                "TBD - User will provide storage sources"
            ],
            "notes": "2025 pricing",
            "last_verified": "2025-01-01"
        }
    },
    "heat_pump": {
        "space_heating": {
            "base": {
                "value": HP_SPACE_HEATING_COST_PER_TON,  # $3753.78/ton
                "unit": "$/ton"
            },
            "cop": ASHP_COP_SPACE_HEATING,  # 3.375
            "sources": [
                "https://techcleanca.com/heat-pump-data/download-data/",
                "P. Jadun, C. McMillan, L. Vimmerstedt, and T. Mai, Electrification Futures Study Technology Data. NREL Data Catalog. National Renewable Energy Laboratory., Golden, CO, 2017. doi: 10.7799/1414279",
                "https://data.bls.gov/cgi-bin/cpicalc.pl",
                "https://www.philadelphiafed.org/surveys-and-data/real-time-data-research/spf-q2-2024"
            ],
            "notes": "TECH California median installation costs, NREL cost decline rates, adjusted to 2025 dollars. Heating capacity based on max daily gas usage converted to heating tons, calibrated so median capacity is 3 tons.",
            "last_verified": "2025-01-01"
        },
        "average_residential": {
            "base": {
                "value": HP_SPACE_HEATING_COST_PER_TON * 3,  # Assume 3-ton system for average home
                "unit": "$"
            },
            "cop": ASHP_COP_SPACE_HEATING,
            "sources": [
                "https://techcleanca.com/heat-pump-data/download-data/",
                "P. Jadun, C. McMillan, L. Vimmerstedt, and T. Mai, Electrification Futures Study Technology Data. NREL Data Catalog. National Renewable Energy Laboratory., Golden, CO, 2017. doi: 10.7799/1414279"
            ],
            "notes": "Assuming 3-ton system for average residential home, based on median heating capacity in TECH incentive program data",
            "last_verified": "2025-01-01"
        }
    },
    "induction_stove": {
        "average_residential": {
            "base": {
                "value": INDUCTION_COOKSTOVE,  # $2400
                "unit": "$"
            },
            "efficiency_gain_vs_gas": GAS_TO_INDUCTION_EFFICIENCY_GAIN,  # 3x
            "sources": [
                "https://ww2.arb.ca.gov/our-work/programs/technology-clearinghouse/technology-clearinghouse-tools/residential-appliance-comparison"
            ],
            "notes": "CARB data, 3x efficiency gain over gas cookstove",
            "last_verified": "2025-01-01"
        }
    },
    "water_heater": {
        "heat_pump_55L": {
            "base": {
                "value": HP_WATER_HEATER_COST,  # $169.60/gal * 14.54 gal = ~$2466.78
                "unit": "$"
            },
            "capacity_liters": 55,
            "capacity_gallons": WATER_HEATER_CAPACITY_GAL,
            "cop": HPWH_COP_WATER_HEATING,  # 3.250
            "cost_per_gallon": HP_WATER_HEATING_COST_PER_GAL,
            "sources": [
                "https://techcleanca.com/heat-pump-data/download-data/",
                "P. Jadun, C. McMillan, L. Vimmerstedt, and T. Mai, Electrification Futures Study Technology Data. NREL Data Catalog. National Renewable Energy Laboratory., Golden, CO, 2017. doi: 10.7799/1414279"
            ],
            "notes": f"TECH California median installation costs, NREL cost decline rates, {WATER_HEATER_CAPACITY_GAL:.1f} gallon capacity",
            "last_verified": "2025-01-01"
        },
        "electric_55gal": {
            "base": {
                "value": HP_WATER_HEATER_COST,  # Use heat pump water heater cost
                "unit": "$"
            },
            "sources": [
                "https://techcleanca.com/heat-pump-data/download-data/"
            ],
            "notes": "Using heat pump water heater cost for electric water heater",
            "last_verified": "2025-01-01"
        }
    },
    # Reference data for efficiency comparisons
    "efficiency_data": {
        "gas_furnace_efficiency": GAS_FURNACE_EFFICIENCY,      # 0.83
        "gas_water_heater_efficiency": GAS_WATER_HEATER_EFFICIENCY,  # 0.83
        "ashp_cop_space_heating": ASHP_COP_SPACE_HEATING,     # 3.375
        "hpwh_cop_water_heating": HPWH_COP_WATER_HEATING,     # 3.250
        "gas_to_induction_efficiency_gain": GAS_TO_INDUCTION_EFFICIENCY_GAIN  # 3.0
    },
    # Reference gas appliance costs for comparison
    "gas_appliances_reference": {
        "space_heater": {
            "value": GAS_SPACE_HEATER,  # $4500
            "unit": "$",
            "efficiency": GAS_FURNACE_EFFICIENCY,
            "sources": [
                "https://ww2.arb.ca.gov/our-work/programs/technology-clearinghouse/technology-clearinghouse-tools/residential-appliance-comparison"
            ]
        },
        "water_heater": {
            "value": GAS_WATER_HEATER,  # $900
            "unit": "$",
            "efficiency": GAS_WATER_HEATER_EFFICIENCY,
            "sources": [
                "https://ww2.arb.ca.gov/our-work/programs/technology-clearinghouse/technology-clearinghouse-tools/residential-appliance-comparison"
            ]
        },
        "cookstove": {
            "value": GAS_COOKSTOVE,  # $1600
            "unit": "$",
            "sources": [
                "https://ww2.arb.ca.gov/our-work/programs/technology-clearinghouse/technology-clearinghouse-tools/residential-appliance-comparison"
            ]
        },
        "centralized_ac": {
            "value": CENTRALIZED_AC_COST,  # $5930
            "unit": "$",
            "sources": [
                "https://escholarship.org/content/qt0818n68p/qt0818n68p.pdf",
                "https://www.forbes.com/home-improvement/hvac/central-ac-unit-cost/"
            ]
        }
    }
}


def process(base_input_dir, base_output_dir, scenario, housing_type, counties, desired_rate_plans):
    """
    Constructs maps for payback period analysis using Cris's 2025 capital costs.
    """
    return process_payback_analysis(
        base_input_dir, base_output_dir, scenario, housing_type, counties, desired_rate_plans,
        CAPITAL_COSTS_CRIS, "CRIS_2025_CAPITAL_COSTS", "CRIS 2025"
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
    log(scenario = scenario)
    process(base_input_dir, base_output_dir, scenario, housing_type, all_counties, desired_rate_plans)