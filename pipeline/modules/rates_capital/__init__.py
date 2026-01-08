from __future__ import annotations

from typing import List

from ...config import Config
from helpers.main_helpers import log_step

import step10_get_loads_for_rates as GetLoadsForRates
import step11_evaluate_gas_rates as EvaluateGasRates
import step12_evaluate_electricity_rates as EvaluateElectricityRates
import step13_combine_total_annual_costs as CombineTotalAnnualCosts
import step14_build_capital_costs_lifetimes_incentives as BuildCapitalCostsLifetimesIncentives


def run(cfg: Config) -> None:
    """Run Module 3: compute rates and capital costs (Steps 10–14)."""
    base_dir = cfg.base_input_dir
    c_list: List[str] = list(cfg.counties)

    # 10) Loads for rates
    log_step(10)
    GetLoadsForRates.process(base_dir, base_dir, cfg.scenario, [cfg.housing_type], c_list)

    # 11) Gas rates
    log_step(11)
    EvaluateGasRates.process(base_dir, base_dir, cfg.scenario, [cfg.housing_type], c_list)

    # 12) Electricity rates
    log_step(12)
    EvaluateElectricityRates.process(base_dir, base_dir, cfg.scenario, cfg.housing_type, c_list)

    # 13) Combine totals
    log_step(13)
    CombineTotalAnnualCosts.process(base_dir, base_dir, cfg.scenario, [cfg.housing_type], c_list)

    # 14) Capital costs, lifetimes, incentives
    log_step(14)
    BuildCapitalCostsLifetimesIncentives.process(base_dir, base_dir, cfg.scenario, cfg.housing_type, c_list)


__all__ = ["run"]
