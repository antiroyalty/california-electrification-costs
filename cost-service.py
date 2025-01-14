import step1_identify_suitable_buildings as IdentifySuitableBuildings
import step2_pull_buildings as PullBuildings
import step3_build_electricity_load_profiles as BuildElectricityLoadProfiles
# import step4_build_gas_load_profiles as BuildGasLoadProfiles
# import step5_convert_gas_appliances_to_electrical_appliances as ConvertGasToElectric
# import step6_get_household_electricity_loads_for_solar_storage as 
# import step7_get_weather_files as WeatherFiles
# import step8_run_sam_model_for_solar_storage as RunSamModelForSolarStorage
# import step9_get_loads_for_rates
# import step10_evaluate_gas_rates
# import step11_evaluate_electricity_rates
# import step12_evaluate_capital_costs

class CostService:
    SCENARIOS = {
        "baseline": {"appliances", "misc"},
        # "heat_pump_and_water_heater": ["heating", "hot_water", "appliances", "misc"],
        # "heat_pump_water_heater_and_induction_stove": ["heating", "cooling", "hot_water", "appliances", "cooking", "misc"],
        # "heat_pump_heating_cooling_water_heater_and_induction_stove": ["heating", "cooling", "hot_water", "appliances", "cooking", "misc"]
    }

    def __init__(self, initial_csv, scenario, housing_type, county, output_dir):
        self.csv_file = initial_csv
        self.scenario = scenario
        self.housing_type = housing_type
        self.county = county
        self.output_dir = output_dir

    def run(self):
        # Should give an array of CSV file paths
        result = IdentifySuitableBuildings.process(self.scenario, self.housing_type, output_base_dir=self.output_dir, target_county=county)

        print("Step 1")
        print(result)

        # # Step 2: Pull Buildings
        result = PullBuildings.process(output_base_dir=self.output_dir, download_new_files=False)

        print("Step 2")
        print(result)
    
        # # Step 3: Build County Load Profiles
        print("county, ", county)
        result = BuildElectricityLoadProfiles.process(self.SCENARIOS, [self.housing_type], [self.county])

        print("Step 3")
        print(result)

        # # Step 4: Evaluate Electricity Rates
        # self.csv_file = EvaluateElectricityRates.process(self.csv_file)


        # # Step 5: Run SAM Model for Solar & Storage
        # self.csv_file = RunSamModelForSolarStorage.process(self.csv_file)

        # # Step 6: Analyze Gas Usage
        # self.csv_file = GasUsage.process(self.csv_file)

        # # Step 7: Evaluate Gas Rates
        # self.csv_file = GasRates.process(self.csv_file)

        return self.csv_file
    

initial_csv = "initial_data.csv" # TODO: update

scenario = "baseline"
housing_type = "single-family-detached"
county = "Riverside County"

cost_service = CostService(initial_csv, scenario, housing_type, county="Riverside County", output_dir="data")

final_csv = cost_service.run()

print("Final processed CSV file:", final_csv)