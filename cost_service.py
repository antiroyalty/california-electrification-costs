import sys
import argparse
from scenarios import SCENARIOS
import step1_identify_suitable_buildings as IdentifySuitableBuildings
import step2_pull_buildings as PullBuildings
import step3_build_electricity_load_profiles as BuildElectricityLoadProfiles
import step4_build_gas_load_profiles as BuildGasLoadProfiles
import step5_convert_gas_appliances_to_electrical_appliances as ConvertGasToElectric
import step6_build_electric_vehicle_load_profiles as BuildElectricVehicleLoadProfiles
import step7_combine_real_and_simulated_electricity_loads as CombineRealAndSimulatedProfiles
import step8_get_weather_files as WeatherFiles
# Historical step 9 implementations (toggle as needed):
# import step9_run_sam_model_for_solar_storage as RunSamModelForSolarStorage  # Pvwatts + Battwatts
# import step9_pvsamv1_battery as RunSamModelForSolarStorage                 # Pvsamv1 integrated battery
# import step9_solar_storage_custom_dispatch as RunSamModelForSolarStorage     # Pvsamv1 PV + custom dispatch
import step9_my_own_solar_storage as RunSamModelForSolarStorage             # DIY PV + custom dispatch
import step10_get_loads_for_rates as GetLoadsForRates
import step11_evaluate_gas_rates as EvaluateGasRates
import step12_evaluate_electricity_rates as EvaluateElectricityRates
import step13_combine_total_annual_costs as CombineTotalAnnualCosts
import step14_build_capital_costs_lifetimes_incentives as BuildCapitalCostsLifetimesIncentives
import step15_payback_periods as PaybackPeriods
import step16_display_key_metrics_maps as DisplayKeyMetricsMaps
from main_helpers import norcal_counties, socal_counties, central_counties

class CostService:

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
        BuildElectricityLoadProfiles.process(scenario, SCENARIOS[scenario], self.housing_type, self.counties, "data", "data/loadprofiles", force_recompute=False)

        self.log_step(4)
        BuildGasLoadProfiles.process("data", "data/loadprofiles", scenario, SCENARIOS, self.housing_type, self.counties, force_recompute=False)

        self.log_step(5)
        ConvertGasToElectric.process("data/loadprofiles", "data/loadprofiles", self.counties, scenario, [self.housing_type], force_recompute=False)

        self.log_step(6)
        # Build vehicle load profiles (EV charging and/or ICE fuel consumption) based on scenario
        BuildElectricVehicleLoadProfiles.process("data", "data/loadprofiles", scenario, SCENARIOS[scenario], [self.housing_type], self.counties, force_recompute=False)

        self.log_step(7)
        # Add EVs here so they get used in SAM model deployment
        CombineRealAndSimulatedProfiles.process("data/loadprofiles", "data/loadprofiles", scenario, [self.housing_type], self.counties, force_recompute=False)
    
        self.log_step(8)
        WeatherFiles.process("data/loadprofiles", "data/loadprofiles", scenario, [self.housing_type], 2018, self.counties)

        self.log_step(9)
        RunSamModelForSolarStorage.process("data/loadprofiles", "data/loadprofiles", scenario, self.housing_type, self.counties, force_recompute=True)

        self.log_step(10)
        GetLoadsForRates.process("data/loadprofiles", "data/loadprofiles", scenario, [self.housing_type], self.counties)

        self.log_step(11)
        EvaluateGasRates.process("data/loadprofiles", "data/loadprofiles", scenario, [self.housing_type], self.counties)

        self.log_step(12)
        EvaluateElectricityRates.process("data/loadprofiles", "data/loadprofiles", scenario, self.housing_type, self.counties)

        self.log_step(13)
        CombineTotalAnnualCosts.process("data/loadprofiles", "data/loadprofiles", scenario, [self.housing_type], self.counties)

        self.log_step(14)
        BuildCapitalCostsLifetimesIncentives.process("data/loadprofiles", "data/loadprofiles", scenario, self.housing_type, self.counties)
        
        self.log_step(15)
        PaybackPeriods.process("data/loadprofiles", scenario, self.housing_type, self.counties)
        
        self.log_step(16)
        DisplayKeyMetricsMaps.process("data/loadprofiles", "data/loadprofiles", scenario, self.housing_type, self.counties, self.desired_rate_plans)

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
    args = parse_arguments()
    scenario = args.scenario
    
    if scenario not in SCENARIOS:
        print(f"Error: Unknown scenario '{scenario}'")
        print(f"Available scenarios: {', '.join(SCENARIOS.keys())}")
        sys.exit(1)
    
    housing_type = "single-family-detached"
    input_dir = "data"
    output_dir = "data/loadprofiles"
    
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
    
    cost_service = CostService(scenario, housing_type, counties=norcal_counties + socal_counties + central_counties, rate_plans=rate_plans, input_dir=input_dir, output_dir=output_dir)
    cost_service.run()
    
    print("\nCost analysis completed successfully!")
    print(f"Results saved to: {output_dir}")
