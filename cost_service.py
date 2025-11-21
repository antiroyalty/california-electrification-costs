
import sys
import argparse
import os

from scenarios import SCENARIOS

from helpers.main_helpers import (
    norcal_counties,
    socal_counties,
    central_counties,
)

import step1_identify_suitable_buildings as IdentifySuitableBuildings
import step2_pull_buildings as PullBuildings
import step3_build_electricity_load_profiles as BuildElectricityLoadProfiles
import step4_build_gas_load_profiles as BuildGasLoadProfiles
import step5_convert_gas_appliances_to_electrical_appliances as ConvertGasToElectric
import step6_build_electric_vehicle_load_profiles as BuildElectricVehicleLoadProfiles
import step7_combine_real_and_simulated_electricity_loads as CombineRealAndSimulatedProfiles
import step8_get_weather_files as WeatherFiles
import step9_my_own_solar_storage as Step9MyOwnSolarStorage
import step10_get_loads_for_rates as GetLoadsForRates
import step11_evaluate_gas_rates as EvaluateGasRates
import step12_evaluate_electricity_rates as EvaluateElectricityRates
import step13_combine_total_annual_costs as CombineTotalAnnualCosts
import step14_build_capital_costs_lifetimes_incentives as BuildCapitalCostsLifetimesIncentives
import step15_payback_periods as PaybackPeriods
import step16_display_key_metrics_maps as DisplayCaliforniaDiagnosticMaps
import step18_cross_scenario_comparisons as Step18CrossScenarioComparisons
import step19_compare_two_scenarios as Step19CompareTwoScenarios
import step20_no_solar_storage_electrification as Step20NoSolarStorageElectrification
import step21_compare_eac_with_vs_without as Step21CompareEACWithVsWithout
import step22_build_county_diagnostics as Step22BuildCountyDiagnostics

class CostService:
    def __init__(self, scenario, housing_type, counties, rate_plans, input_dir, output_dir):
        self.scenario = scenario
        self.housing_type = housing_type
        self.counties = counties
        self.input_dir = input_dir
        self.output_dir = output_dir
        self.desired_rate_plans = rate_plans

    def log_step(self, step: int):
        print("-" * 15, f" Step {step} ", "-" * 15)

    def _scenario_list_for_comparisons(self):
        preferred = [
            "baseline",
            "induction_stove",
            "water_heating",
            "heat_pump",
            "heat_pump_and_induction_stove",
            "heat_pump_and_induction_stove_and_water_heating",
            "baseline_ice_car",
            "baseline_ev_car",
            "full_electric_ev",
        ]
        return [s for s in preferred if s in SCENARIOS]

    def _summarize_dispatch_and_sizing(self):
        mode = "dynamic PV-only" if getattr(Step9MyOwnSolarStorage, "USE_DYNAMIC_DISPATCH", False) else "classic 4–9pm"
        sizing = (
            "EAC-optimal per county" if getattr(Step9MyOwnSolarStorage, "USE_EAC_OPTIMAL_SIZING", False)
            else f"fraction of annual-match (PV_SIZE_FRACTION={getattr(Step9MyOwnSolarStorage, 'PV_SIZE_FRACTION', 'n/a')})"
        )
        batt = getattr(Step9MyOwnSolarStorage, "BATTERY_CAPACITY_KWH", None)
        batt_str = f", default battery ≈{batt} kWh" if batt else ""
        plans = sorted({v.get('electricity') for v in self.desired_rate_plans.values() if isinstance(v, dict) and v.get('electricity')})
        plan_str = f"; Electricity plan preference: {', '.join(plans)}" if plans else ""
        return f"Dispatch: {mode}; Sizing: {sizing}{batt_str}{plan_str}; Billing variant: NEM3 for with-solar"

    def run(self):
        self.log_step(1)
        IdentifySuitableBuildings.process(self.scenario, self.housing_type, output_base_dir="data", target_counties=self.counties, force_recompute=False)

        self.log_step(2)
        PullBuildings.process(self.scenario, self.housing_type, self.counties, output_base_dir="data", download_new_files=False)

        self.log_step(3)
        BuildElectricityLoadProfiles.process(self.scenario, SCENARIOS[self.scenario], self.housing_type, self.counties, "data", "data/loadprofiles", force_recompute=False)

        self.log_step(4)
        BuildGasLoadProfiles.process("data", "data/loadprofiles", self.scenario, SCENARIOS, self.housing_type, self.counties, force_recompute=False)

        self.log_step(5)
        ConvertGasToElectric.process("data/loadprofiles", "data/loadprofiles", self.counties, self.scenario, [self.housing_type], force_recompute=False)

        self.log_step(6)
        BuildElectricVehicleLoadProfiles.process("data", "data/loadprofiles", self.scenario, SCENARIOS[self.scenario], [self.housing_type], self.counties, force_recompute=False)

        self.log_step(7)
        CombineRealAndSimulatedProfiles.process("data/loadprofiles", "data/loadprofiles", self.scenario, [self.housing_type], self.counties, force_recompute=False)

        self.log_step(8)
        WeatherFiles.process("data/loadprofiles", "data/loadprofiles", self.scenario, [self.housing_type], 2018, self.counties)

        self.log_step(9)
        Step9MyOwnSolarStorage.process("data/loadprofiles", "data/loadprofiles", self.scenario, self.housing_type, self.counties, force_recompute=True)

        self.log_step(10)
        GetLoadsForRates.process("data/loadprofiles", "data/loadprofiles", self.scenario, [self.housing_type], self.counties)

        self.log_step(11)
        EvaluateGasRates.process("data/loadprofiles", "data/loadprofiles", self.scenario, [self.housing_type], self.counties)

        self.log_step(12)
        EvaluateElectricityRates.process("data/loadprofiles", "data/loadprofiles", self.scenario, self.housing_type, self.counties)

        self.log_step(13)
        CombineTotalAnnualCosts.process("data/loadprofiles", "data/loadprofiles", self.scenario, [self.housing_type], self.counties)

        self.log_step(14)
        BuildCapitalCostsLifetimesIncentives.process("data/loadprofiles", "data/loadprofiles", self.scenario, self.housing_type, self.counties)

        self.log_step(15)
        PaybackPeriods.process("data/loadprofiles", self.scenario, self.housing_type, self.counties)

        self.log_step(16)
        # DisplayCaliforniaDiagnosticMaps.process("data/loadprofiles", "data/loadprofiles", self.scenario, self.housing_type, self.counties, self.desired_rate_plans)

        base_input_dir, output_dir = self._prepare_outputs()

        # Assumptions + plan preferences
        print("\nAssumptions — " + self._summarize_dispatch_and_sizing())
        plan_pref = list({v.get('electricity') for v in self.desired_rate_plans.values() if isinstance(v, dict) and v.get('electricity')})

        # Step 18 (cross-scenario EAC; NEM3 by default)
        self.log_step(18)
        Step18CrossScenarioComparisons.process(
            base_input_dir,
            output_dir,
            self.housing_type,
            self._scenario_list_for_comparisons(),
            self.counties,
            plan_preference=plan_pref,
            electricity_variant="nem3",
        )

        # Step 19 (EV vs ICE)
        self.log_step(19)
        Step19CompareTwoScenarios.process(
            base_input_dir,
            output_dir,
            self.housing_type,
            ["baseline_ice_car", "baseline_ev_car"],
            self.counties,
            plan_preference=plan_pref,
            electricity_variant="nem3",
        )

        # Step 20 (no-PV EAC)
        self.log_step(20)
        Step20NoSolarStorageElectrification.process(
            base_input_dir,
            output_dir,
            self.housing_type,
            [self.scenario],
            self.counties,
            incentive="full_incentives",
            discount_rate=0.07,
            agg="mean",
        )

        # Step 21 (with vs without PV)
        self.log_step(21)
        Step21CompareEACWithVsWithout.process(
            base_input_dir,
            output_dir,
            self.housing_type,
            self.scenario,
            self.counties,
            plan_preference=plan_pref,
            electricity_variant="nem3",
            incentive="full_incentives",
            discount_rate=0.07,
            agg="mean",
        )

        # Step 22 (per-county diagnostics)
        self.log_step(22)
        Step22BuildCountyDiagnostics.process(
            base_input_dir,
            output_dir,
            self.housing_type,
            self.scenario,
            self.counties,
        )

    def _prepare_outputs(self) -> tuple[str, str]:
        """Prepare and return (base_input_dir, output_dir). Keeps run() tidy."""
        base_input_dir = self.output_dir
        output_dir = os.path.join("analysis_results")
        os.makedirs(output_dir, exist_ok=True)
        return base_input_dir, output_dir


def parse_arguments():
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
  python3 cost_service.py baseline""",
    )
    parser.add_argument("scenario", help="Electrification scenario to analyze")
    return parser.parse_args()


if __name__ == "__main__":
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
        "PG&E": {"electricity": "E-TOU-D", "gas": "G-1"},
        "SCE": {"electricity": "TOU-D-4-9PM", "gas": "GR"},
        "SDG&E": {"electricity": "TOU-DR1", "gas": "GR"},
    }

    print(f"\nRunning cost analysis for scenario: {scenario}")
    print(f"Housing type: {housing_type}")
    all_counties = norcal_counties + central_counties + socal_counties
    print(f"Counties: {len(all_counties)} total counties")
    print("-" * 60)

    cost_service = CostService(
        scenario,
        housing_type,
        counties=["Alameda County"],
        rate_plans=rate_plans,
        input_dir=input_dir,
        output_dir=output_dir,
    )
    cost_service.run()

    print("\nCost analysis completed successfully!")
    print(f"Results saved to: {output_dir}")
