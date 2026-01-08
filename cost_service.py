
import sys
import argparse
import os

from scenarios import SCENARIOS

from helpers.main_helpers import (
    norcal_counties,
    socal_counties,
    central_counties,
)

import runpy

class CostService:
    def __init__(self, scenario, housing_type, counties, rate_plans, input_dir, output_dir):
        self.scenario = scenario
        self.housing_type = housing_type
        self.counties = counties
        self.input_dir = input_dir
        self.output_dir = output_dir
        self.desired_rate_plans = rate_plans

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

    def run(self):
        def _run_module(script_rel_path: str, **kwargs):
            script_path = os.path.join(os.path.dirname(__file__), script_rel_path)
            ns = runpy.run_path(script_path, run_name="__not_main__")
            run_fn = ns.get("run")
            if callable(run_fn):
                return run_fn(**kwargs)
            raise RuntimeError(f"run() not found in {script_rel_path}")

        # Module 1: Steps 1–7
        _run_module(
            os.path.join("1_retrieve-buildings-and-construct-load-profiles", "run.py"),
            scenario=self.scenario,
            housing_type=self.housing_type,
            counties=self.counties,
            input_dir="data",
            output_dir="data/loadprofiles",
        )

        # Module 2: Steps 8–9
        _run_module(
            os.path.join("2_compute-and-cooptimize-solar-storage", "run.py"),
            scenario=self.scenario,
            housing_type=self.housing_type,
            counties=self.counties,
            base_dir="data/loadprofiles",
            weather_year=2018,
        )

        # Module 3: Steps 10–14
        _run_module(
            os.path.join("3_compute_rates_and_capital_costs", "run.py"),
            scenario=self.scenario,
            housing_type=self.housing_type,
            counties=self.counties,
            base_dir="data/loadprofiles",
        )

        # Module 4: Steps 15, 18–22
        _run_module(
            os.path.join("4_visualize-and-compare-results", "run.py"),
            scenario=self.scenario,
            housing_type=self.housing_type,
            counties=self.counties,
            base_input_dir=self.output_dir,
            output_dir=os.path.join("analysis_results"),
            electricity_variant="nem3",
            plan_preference=None,
            desired_rate_plans=self.desired_rate_plans,
            incentive="full_incentives",
            discount_rate=0.07,
            agg="mean",
        )


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
    alameda_county = ["Alameda County"]
    print(f"Counties: {len(all_counties)} total counties")
    print("-" * 60)

    cost_service = CostService(
        scenario,
        housing_type,
        counties=alameda_county,
        rate_plans=rate_plans,
        input_dir=input_dir,
        output_dir=output_dir,
    )
    cost_service.run()

    print("\nCost analysis completed successfully!")
    print(f"Results saved to: {output_dir}")
