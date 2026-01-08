from __future__ import annotations

import os
import sys
from typing import Iterable, List


# Ensure module folder and repo root are importable
MODDIR = os.path.dirname(os.path.abspath(__file__))
if MODDIR not in sys.path:
    sys.path.insert(0, MODDIR)
ROOT = os.path.dirname(os.path.dirname(MODDIR))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import step10_get_loads_for_rates as GetLoadsForRates  # noqa: E402
import step11_evaluate_gas_rates as EvaluateGasRates  # noqa: E402
import step12_evaluate_electricity_rates as EvaluateElectricityRates  # noqa: E402
import step13_combine_total_annual_costs as CombineTotalAnnualCosts  # noqa: E402
import step14_build_capital_costs_lifetimes_incentives as BuildCapitalCostsLifetimesIncentives  # noqa: E402


def run(
    scenario: str,
    housing_type: str,
    counties: Iterable[str],
    *,
    base_dir: str = "data/loadprofiles",
) -> None:
    """Run module 3: rates and capital costs (Steps 10–14)."""
    c_list: List[str] = list(counties)

    # 10) Loads for rates
    GetLoadsForRates.process(base_dir, base_dir, scenario, [housing_type], c_list)

    # 11) Gas rates
    EvaluateGasRates.process(base_dir, base_dir, scenario, [housing_type], c_list)

    # 12) Electricity rates
    EvaluateElectricityRates.process(base_dir, base_dir, scenario, housing_type, c_list)

    # 13) Combine totals
    CombineTotalAnnualCosts.process(base_dir, base_dir, scenario, [housing_type], c_list)

    # 14) Capital costs, lifetimes, incentives
    BuildCapitalCostsLifetimesIncentives.process(base_dir, base_dir, scenario, housing_type, c_list)


if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser(description="Module 3: rates and capital costs")
    p.add_argument("scenario")
    p.add_argument("--housing-type", default="single-family-detached")
    p.add_argument("--counties", nargs="*", default=["Alameda County"])
    p.add_argument("--base-dir", default="data/loadprofiles")
    args = p.parse_args()

    run(args.scenario, args.housing_type, args.counties, base_dir=args.base_dir)
