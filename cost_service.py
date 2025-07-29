import sys
import argparse
import step1_identify_suitable_buildings as IdentifySuitableBuildings
import step2_pull_buildings as PullBuildings
import step3_build_electricity_load_profiles as BuildElectricityLoadProfiles
import step4_build_gas_load_profiles as BuildGasLoadProfiles
import step5_convert_gas_appliances_to_electrical_appliances as ConvertGasToElectric
import step6_build_electric_vehicle_load_profiles as BuildElectricVehicleLoadProfiles
import step7_combine_real_and_simulated_electricity_loads as CombineRealAndSimulatedProfiles
import step8_get_weather_files as WeatherFiles
import step9_run_sam_model_for_solar_storage as RunSamModelForSolarStorage
import step10_get_loads_for_rates as GetLoadsForRates
import step11_evaluate_gas_rates as EvaluateGasRates
import step12_evaluate_electricity_rates as EvaluateElectricityRates
import step13_combine_total_annual_costs as CombineTotalAnnualCosts
import step14_display_key_metrics_maps as DisplayKeyMetricsMaps
import step15_build_capital_costs_lifetimes_incentives as BuildCapitalCostsLifetimesIncentives
import step16_build_cris_capital_costs as BuildCrisCapitalCosts
import step17_build_gas_capital_costs as BuildGasCapitalCosts
import step18_compare_capital_costs as CompareCapitalCosts
import step19_calculate_payback_periods as CalculatePaybackPeriods
import step20_calculate_end_of_life_payback as CalculateEndOfLifePayback
import step21_build_payback_difference_maps as BuildPaybackDifferenceMaps
import step22_calculate_npv as CalculateNPV

class CostService:
    SCENARIOS = {
        "baseline": {"gas": {"heating", "hot_water", "cooking"}, "electric": {"appliances", "misc"}}, # Almost everything is gas, except normal electrical appliances
        "heat_pump": {"gas": {"hot_water", "cooking"}, "electric": {"appliances", "misc", "heating"}},
        "induction_stove": {"gas": {"hot_water", "heating"}, "electric": {"appliances", "misc", "cooking"}},
        "heat_pump_and_induction_stove": {"gas": {"hot_water"}, "electric": {"appliances", "misc", "cooking", "heating"}},
        "water_heating": {"gas": {"cooking", "heating"}, "electric": {"hot_water", "appliances", "misc"}},
        "heat_pump_and_induction_stove_and_water_heating": {"gas": {}, "electric": {"hot_water", "cooking", "heating", "appliances", "misc"}}
        # TODO, EVs: Create a new scenario that looks *just* at EVs
        # TODO, EVs: Create a new scenario that looks at EVs plus all other electrified appliances
    }

    def __init__(self, scenario, housing_type, counties, rate_plans, input_dir, output_dir):
        self.scenario = scenario
        self.housing_type = housing_type
        self.counties = counties
        self.input_dir = input_dir
        self.output_dir = output_dir
        self.desired_rate_plans = rate_plans

    def log_step(self, step):
        print("-" * 15, f" Step {step} ", "-" * 15)

    def run(self):
        self.log_step(1)
        IdentifySuitableBuildings.process(scenario, self.housing_type, output_base_dir="data", target_counties=self.counties, force_recompute=False)

        self.log_step(2)
        PullBuildings.process(scenario, self.housing_type, self.counties, output_base_dir="data", download_new_files=False) # output directory should just be 'data', not 'loadprofiles'
    
        self.log_step(3)
        BuildElectricityLoadProfiles.process(scenario, self.SCENARIOS[scenario], self.housing_type, self.counties, "data", "data/loadprofiles", force_recompute=False)

        self.log_step(4)
        BuildGasLoadProfiles.process("data", "data/loadprofiles", scenario, self.SCENARIOS, self.housing_type, self.counties, force_recompute=False)

        self.log_step(5)
        ConvertGasToElectric.process("data/loadprofiles", "data/loadprofiles", self.counties, scenario, [self.housing_type], force_recompute=False)

        self.log_step(6)
        # TODO, EVs: Create a new class that processes EV load profiles for each specified county
        BuildElectricVehicleLoadProfiles.process("data/loadprofiles", "data/loadprofiles", scenario, [self.housing_type], self.counties, force_recompute=False)

        self.log_step(7)
        # Add EVs here so they get used in SAM model deployment
        CombineRealAndSimulatedProfiles.process("data/loadprofiles", "data/loadprofiles", scenario, [self.housing_type], self.counties, force_recompute=False)
    
        self.log_step(8)
        WeatherFiles.process("data/loadprofiles", "data/loadprofiles", scenario, [self.housing_type], 2018, self.counties)

        self.log_step(9)
        RunSamModelForSolarStorage.process("data/loadprofiles", "data/loadprofiles", scenario, self.housing_type, self.counties, force_recompute=True)

        self.log_step(10)
        # Ensure that EV loads are captured here too
        GetLoadsForRates.process("data/loadprofiles", "data/loadprofiles", scenario, [self.housing_type], self.counties)

        self.log_step(11)
        EvaluateGasRates.process("data/loadprofiles", "data/loadprofiles", scenario, [self.housing_type], self.counties)

        self.log_step(12)
        EvaluateElectricityRates.process("data/loadprofiles", "data/loadprofiles", scenario, self.housing_type, self.counties)

        self.log_step(13)
        # Combine total annual costs, without capital costs
        # Rename this to GetAnnualGasAndElectricCosts
        # Ensure that EV electricity costs are passed through to here too, applied with the right scenario.
        CombineTotalAnnualCosts.process("data/loadprofiles", "data/loadprofiles", scenario, [self.housing_type], self.counties)

        self.log_step(14)
        # Display Maps for key metrics: 
        # - Average solar panel size in county
        # - Total annual load in county, in kwh
        # - Total electricity bill annually, in $
        # - Total gas bill annually, in $
        # Display this as 4 maps all on one tab, if I can.
        DisplayKeyMetricsMaps.process("data/loadprofiles", "data/loadprofiles", scenario, self.housing_type, self.counties, self.desired_rate_plans)

        self.log_step(15)
        # Build Capital Costs, Lifetimes, Incentives for my numbers
        # Define each technology as a class that can be configured. It has a capital cost, a lifetime, and associated incentives at the state, federal, and utility level
        # I want the ability to configure different Component "scenarios", like No Incentives, Half Incentives, My Capital Costs, Cris's Capital Costs, EMP Capital Costs
        BuildCapitalCostsLifetimesIncentives.process("data/loadprofiles", "data/loadprofiles", scenario, self.housing_type, self.counties)
        
        self.log_step(16)
        # Build Capital Cost classes for Cris's numbers as well
        BuildCrisCapitalCosts.process("data/loadprofiles", "data/loadprofiles", scenario, self.housing_type, self.counties)

        self.log_step(17)
        # Build Capital Costs, Lifetimes, Incentives (? if they apply) for the gas counterparts of each of the components in question
        BuildGasCapitalCosts.process("data/loadprofiles", "data/loadprofiles", scenario, self.housing_type, self.counties)
        
        self.log_step(18)
        # Show the differences between Mine and Cris's capital costs
        # Just component by component, create bar graphs or something
        CompareCapitalCosts.process("data/loadprofiles", "data/loadprofiles", scenario, self.housing_type, self.counties)

        # Create a Payback Period helper
        self.log_step(19)
        # Calculate the Payback Period for the scenario, given the component parameters defined in the DefineElectrifiedComponents step
        # First, do an "out of the blue", electrification 
        CalculatePaybackPeriods.process("data/loadprofiles", "data/loadprofiles", scenario, self.housing_type, self.counties, self.desired_rate_plans)

        self.log_step(20)
        # Then, do an "end-of-device life" electrification, when the component is being swapped when the previous gas component has reached its end of life
        # Mostly, this affects the capital costs of electrification. Now, the "capital costs" get considered as electrified_capital_costs - gas_capital_costs, so incremental increase or decrease relative to the gas counterpart
        CalculateEndOfLifePayback.process("data/loadprofiles", "data/loadprofiles", scenario, self.housing_type, self.counties, self.desired_rate_plans)

        # Map how the payback periods differ across California. But before I decide which scenario to use, I will have to look at the difference maps

        # Create a DifferenceMaps helper
        self.log_step(21)
        # Show the differences in Payback Periods between Out of the Blue electrification, and End of Life electrification.
        # Do the same for my capital costs vs. Cris's capital costs
        BuildPaybackDifferenceMaps.process("data/loadprofiles", "data/loadprofiles", self.housing_type, self.counties, "baseline", "baseline", "baseline", "baseline.solarstorage")

        self.log_step(22)
        # Calculate the NPV for each scenario, in addition to the payback period
        # Define the NPV parameters here
        CalculateNPV.process("data/loadprofiles", "data/loadprofiles", scenario, self.housing_type, self.counties, self.desired_rate_plans)

def parse_arguments():
    """
    Parse command-line arguments for the cost service.
    """
    parser = argparse.ArgumentParser(
        description="Run cost analysis for residential electrification scenarios in California",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Available scenarios:
  - baseline
  - heat_pump
  - induction_stove
  - heat_pump_and_induction_stove
  - water_heating
  - heat_pump_and_induction_stove_and_water_heating

Example usage:
  python3 cost_service.py heat_pump_and_induction_stove
  python3 cost_service.py water_heating
  python3 cost_service.py baseline"""
    )
    
    parser.add_argument(
        "scenario",
        help="Electrification scenario to analyze"
    )
    
    return parser.parse_args()


if __name__ == '__main__':
    # Parse command-line arguments
    args = parse_arguments()
    scenario = args.scenario
    
    # Validate scenario
    if scenario not in CostService.SCENARIOS:
        print(f"Error: Unknown scenario '{scenario}'")
        print(f"Available scenarios: {', '.join(CostService.SCENARIOS.keys())}")
        sys.exit(1)
    
    housing_type = "single-family-detached"
    input_dir = "data"
    output_dir = "data/loadprofiles"

    norcal_counties = [
        "Alameda County", "Contra Costa County", "Marin County", "Napa County", 
        "San Francisco County", "San Mateo County", "Santa Clara County", "Solano County", "Sonoma County",  # Bay Area
        "Del Norte County", "Humboldt County", "Lake County", "Mendocino County", "Trinity County",  # North Coast
        "Butte County", "Colusa County", 
        "Nevada County", "Plumas County", "Shasta County", "Sierra County", "Tehama County",  # North Valley & Sierra
    ] # "Modoc County", "Glenn County", "Siskiyou County", "Lassen County"

    central_counties = [
        "Fresno County", "Kern County", "Kings County", "Madera County", "Merced County", 
        "Sacramento County", "San Joaquin County", "Stanislaus County", "Sutter County", 
        "Tulare County", "Yolo County",  # Central Valley
        "Monterey County", "San Benito County", "San Luis Obispo County", "Santa Barbara County", 
        "Santa Cruz County", "Ventura County",  # Central Coast
        "Alpine County", "Amador County", "Mono County",  # Eastern Sierra & Inland
    ]

    socal_counties = [
        "Los Angeles County", "Orange County", "San Bernardino County", 
        "Riverside County", "Ventura County",  # Greater Los Angeles
        "San Diego County", "Imperial County"  # San Diego & Imperial
    ]
    
    rate_plans = {
            "PG&E": {
                "electricity": "E-TOU-D",
                "gas": "G-1"
            },
            "SCE": {
                "electricity": "TOU-D-4-9PM",
                "gas": "GR"
            },
            "SDG&E": {
                "electricity": "TOU-DR1",
                "gas": "GR"
            }
        }
    
    print(f"\nRunning cost analysis for scenario: {scenario}")
    print(f"Housing type: {housing_type}")
    print(f"Counties: {len(norcal_counties + central_counties + socal_counties)} total counties")
    print("-" * 60)
    
    cost_service = CostService(scenario, housing_type, counties=norcal_counties + central_counties + socal_counties, rate_plans=rate_plans, input_dir=input_dir, output_dir=output_dir)
    cost_service.run()
    
    print("\nCost analysis completed successfully!")
    print(f"Results saved to: {output_dir}")
