
import sys
import argparse
import os

from scenarios import SCENARIOS

from helpers.main_helpers import (
    norcal_counties,
    socal_counties,
    central_counties,
)

from pipeline.config import Config
from pipeline.modules import (
    load_profiles as mod_load_profiles,
    solar_storage as mod_solar_storage,
    rates_capital as mod_rates_capital,
    visualization as mod_visualization,
)

class CostService:
    def __init__(self, scenario, housing_type, counties, rate_plans, input_dir, output_dir):
        self.scenario = scenario
        self.housing_type = housing_type
        self.counties = counties
        self.input_dir = input_dir
        self.output_dir = output_dir
        self.desired_rate_plans = rate_plans

    def run(self):
        cfg = Config(
            scenario=self.scenario,
            housing_type=self.housing_type,
            counties=list(self.counties),
            base_input_dir=self.output_dir,
            output_dir=os.path.join("analysis_results"),
            rate_plans=self.desired_rate_plans,
            electricity_variant="nem3",
            incentive="full_incentives",
            discount_rate=0.07,
            agg="mean",
        )

        # Module 1: Steps 1–7
        mod_load_profiles.run(cfg)

        # Module 2: Steps 8–9
        mod_solar_storage.run(cfg)

        # Module 3: Steps 10–14
        mod_rates_capital.run(cfg)

        # Module 4: Steps 15, 18–22
        mod_visualization.run(cfg)


def parse_arguments():
    parser = argparse.ArgumentParser(
        description="Run cost analysis for residential electrification scenarios in California",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Example usage:
  python3 cost_service.py baseline
  python3 cost_service.py baseline_coopt --full_sweep""",
    )
    parser.add_argument("scenario", help="Electrification scenario to analyze")
    parser.add_argument(
        "--full_sweep",
        action="store_true",
        help="Run the complete co-optimization pipeline end-to-end. Requires a _coopt scenario.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_arguments()
    scenario = args.scenario

    if scenario not in SCENARIOS:
        print(f"Error: Unknown scenario '{scenario}'")
        print(f"Available scenarios: {', '.join(SCENARIOS.keys())}")
        sys.exit(1)

    if args.full_sweep and not scenario.endswith("_coopt"):
        print(f"Error: --full_sweep requires a _coopt scenario (e.g. '{scenario}_coopt')")
        sys.exit(1)

    housing_type = "single-family-detached"
    input_dir = "data"
    output_dir = "data/loadprofiles"

    rate_plans = {
        "PG&E": {"electricity": "E-TOU-D", "gas": "G-1"},
        "SCE": {"electricity": "TOU-D-4-9PM", "gas": "GR"},
        "SDG&E": {"electricity": "TOU-DR1", "gas": "GR"},
    }

    all_counties = norcal_counties + central_counties + socal_counties

    print(f"\nRunning cost analysis for scenario: {scenario}")
    print(f"Housing type: {housing_type}")
    print(f"Counties: {len(all_counties)} total")
    print("-" * 60)

    cost_service = CostService(
        scenario,
        housing_type,
        counties=all_counties,
        rate_plans=rate_plans,
        input_dir=input_dir,
        output_dir=output_dir,
    )
    cost_service.run()

    print("\nCost analysis completed successfully!")
