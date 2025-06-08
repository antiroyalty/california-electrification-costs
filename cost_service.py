import step1_identify_suitable_buildings as IdentifySuitableBuildings
import step2_pull_buildings as PullBuildings
import step3_build_electricity_load_profiles as BuildElectricityLoadProfiles
import step4_build_gas_load_profiles as BuildGasLoadProfiles
import step5_convert_gas_appliances_to_electrical_appliances as ConvertGasToElectric
import step6_combine_real_and_simulated_electricity_loads as CombineRealAndSimulatedProfiles
import step7_get_weather_files as WeatherFiles
import step8_run_sam_model_for_solar_storage as RunSamModelForSolarStorage
import step9_get_loads_for_rates as GetLoadsForRates
import step10_evaluate_gas_rates as EvaluateGasRates
import step11_evaluate_electricity_rates as EvaluateElectricityRates
import step12_evaluate_capital_costs as EvaluateCapitalCosts
import step13_combine_total_annual_costs as CombineTotalAnnualCosts
import step14_build_maps as BuildMaps
import step15_build_difference_maps as BuildDifferenceMaps
import step17_build_payback_period_maps as MapPaybackVisualization

class CostService:
    SCENARIOS = {
        # "baseline": {"gas": {"heating", "hot_water", "cooking"}, "electric": {"appliances", "misc"}}, # Almost everything is gas, except normal electrical appliances
        # "heat_pump": {"gas": {"hot_water", "cooking"}, "electric": {"appliances", "misc", "heating"}},
        # "induction_stove": {"gas": {"hot_water", "heating"}, "electric": {"appliances", "misc", "cooking"}},
        # "heat_pump_and_induction_stove": {"gas": {"hot_water"}, "electric": {"appliances", "misc", "cooking", "heating"}},
        # "water_heating": {"gas": {"cooking", "heating"}, "electric": {"hot_water", "appliances", "misc"}},
        "heat_pump_and_induction_stove_and_water_heating": {"gas": {}, "electric": {"hot_water", "cooking", "heating", "appliances", "misc"}}
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
        IdentifySuitableBuildings.process(self.scenario, self.housing_type, output_base_dir="data", target_counties=self.counties, force_recompute=False)

        self.log_step(2)
        PullBuildings.process(self.scenario, self.housing_type, self.counties, output_base_dir="data", download_new_files=False) # output directory should just be 'data', not 'loadprofiles'
    
        self.log_step(3)
        # Make sure I don't pull load profiles on every run, only if they don't already exist
        BuildElectricityLoadProfiles.process(self.SCENARIOS, self.housing_type, self.counties, "data", "data/loadprofiles", force_recompute=False)

        self.log_step(4)
        BuildGasLoadProfiles.process(self.SCENARIOS, [self.housing_type], "data", "data/loadprofiles", self.counties, force_recompute=False)

        self.log_step(5)
        ConvertGasToElectric.process("data/loadprofiles", "data/loadprofiles", self.counties, list(self.SCENARIOS.keys()), [self.housing_type] )

        self.log_step(6)
        CombineRealAndSimulatedProfiles.process("data/loadprofiles", "data/loadprofiles", list(self.SCENARIOS.keys()), [self.housing_type], self.counties)
    
        self.log_step(7)
        WeatherFiles.process("data/loadprofiles", "data/loadprofiles", list(self.SCENARIOS.keys()), [self.housing_type], 2018, self.counties)

        self.log_step(8)
        RunSamModelForSolarStorage.process("data/loadprofiles", "data/loadprofiles", scenario, self.housing_type, self.counties)

        self.log_step(9)
        GetLoadsForRates.process("data/loadprofiles", "data/loadprofiles", list(self.SCENARIOS.keys()), [self.housing_type], self.counties)

        self.log_step(10)
        EvaluateGasRates.process("data/loadprofiles", "data/loadprofiles", scenario, [self.housing_type], self.counties)

        self.log_step(11)
        EvaluateElectricityRates.process("data/loadprofiles", "data/loadprofiles", scenario, self.housing_type, self.counties)

        CombineTotalAnnualCosts.process("data/loadprofiles", "data/loadprofiles", scenario, [self.housing_type], self.counties)

        # BuildMaps.process("data/loadprofiles", "data/loadprofiles", scenario, self.housing_type, self.counties, self.desired_rate_plans)
        
        # BuildDifferenceMaps.process("data/loadprofiles", "data/loadprofiles", housing_type, counties, "baseline", "baseline", "baseline", "baseline.solarstorage")
    
        MapPaybackVisualization.process("data/loadprofiles", "data/loadprofiles", scenario, self.housing_type, self.counties, self.desired_rate_plans)

# scenario = "heat_pump_and_induction_stove"
# scenario = "heat_pump"
# scenario = "induction_stove"
# scenario = "heat_pump"
# scenario = "heat_pump_and_induction_stove"
scenario = "heat_pump_and_induction_stove_and_water_heating"
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
cost_service = CostService(scenario, housing_type, counties=norcal_counties + central_counties + socal_counties, rate_plans=rate_plans, input_dir=input_dir, output_dir=output_dir)

final_csv = cost_service.run()