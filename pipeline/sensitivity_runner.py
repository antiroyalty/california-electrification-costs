"""Sensitivity sweep orchestration.

Before this existed, "sensitivity analysis" meant manually overriding a
Config field, manually deciding which pipeline steps needed to re-run, and
manually assembling a comparison table — the exact ad hoc pattern that
produced the bugs fixed earlier tonight (LP silently duplicating a
primitive, discount_rate never reaching the LP or the reporting layer, NBC
having no override path at all).

`run_sensitivity` re-runs only the stages `evaluations.sensitivity`'s
registry says are necessary for a given parameter, using the same Config
threading fixed tonight, and writes one tidy schema (parameter, value,
scenario, county_slug, EAC components) through the shared
`merge_and_write_csv` helper — keyed on all four of those columns, so
sweeping one parameter can't collide with another parameter's sweep, another
scenario's rows, or the point-estimate ledger, and re-running one value only
refreshes that value's rows. The output file uses a stable name (no git-sha
suffix) since the merge semantics make "which file is current" unambiguous
by construction.
"""
from __future__ import annotations

import os
from dataclasses import replace
from typing import Dict, Iterable, List, Optional

import pandas as pd

from pipeline.config import Config
from pipeline.modules import solar_storage as mod_solar_storage
from pipeline.modules import rates_capital as mod_rates_capital
from helpers.main_helpers import merge_and_write_csv
from helpers.plot_scenario_comparison_helper import collect_eac_components_by_county
from evaluations.sensitivity import SENSITIVITY_PARAMETERS

DEFAULT_RATE_PLANS: Dict[str, Dict[str, str]] = {
    "PG&E": {"electricity": "E-TOU-D", "gas": "G-1"},
    "SCE": {"electricity": "TOU-D-4-9PM", "gas": "GR"},
    "SDG&E": {"electricity": "TOU-DR1", "gas": "GR"},
}


def _plan_preference_from(rate_plans: Optional[Dict[str, Dict[str, str]]]) -> Optional[List[str]]:
    if not rate_plans:
        return None
    return list({
        v.get("electricity") for v in rate_plans.values()
        if isinstance(v, dict) and v.get("electricity")
    })


def run_sensitivity(
    parameter_name: str,
    values: Iterable[float],
    *,
    scenario: str,
    sibling_scenarios: List[str],
    counties: List[str],
    housing_type: str = "single-family-detached",
    base_input_dir: str = "data/loadprofiles",
    output_dir: str = "analysis_results",
    rate_plans: Optional[Dict[str, Dict[str, str]]] = None,
    electricity_variant: str = "nem3",
    incentive: str = "full_incentives",
) -> pd.DataFrame:
    """Run a one-parameter sensitivity sweep; return the tidy result DataFrame.

    For each value: builds a Config with that value substituted for the swept
    parameter, re-runs only the pipeline stages SENSITIVITY_PARAMETERS says
    are necessary, and collects EAC-by-county results tagged with
    (parameter, value). `sibling_scenarios` should include `scenario` itself
    plus whatever comparison scenarios the resulting table needs (e.g. for
    the Claims 3&4 comparison: ["baseline_ice_car", "full_electric_ev",
    "full_electric_ev_coopt"]).
    """
    if parameter_name not in SENSITIVITY_PARAMETERS:
        raise ValueError(
            f"Unknown sensitivity parameter '{parameter_name}'. "
            f"Known: {sorted(SENSITIVITY_PARAMETERS)}. "
            "Add it to SENSITIVITY_PARAMETERS first (evaluations/sensitivity.py) "
            "— including which pipeline stages it actually requires re-running."
        )
    param = SENSITIVITY_PARAMETERS[parameter_name]
    rate_plans = rate_plans or DEFAULT_RATE_PLANS
    plan_preference = _plan_preference_from(rate_plans)

    all_rows = []
    for value in values:
        cfg = Config(
            scenario=scenario,
            housing_type=housing_type,
            counties=counties,
            base_input_dir=base_input_dir,
            output_dir=output_dir,
            rate_plans=rate_plans,
            electricity_variant=electricity_variant,
            incentive=incentive,
        )
        cfg = replace(cfg, **{param.config_field: value})

        if param.requires_lp_resolve:
            mod_solar_storage.run(cfg)
        mod_rates_capital.run(cfg)

        by_cty = collect_eac_components_by_county(
            cfg.base_input_dir,
            cfg.housing_type,
            sibling_scenarios,
            cfg.counties,
            incentive=cfg.incentive,
            discount_rate=cfg.discount_rate,
            electricity_plan_preference=plan_preference,
            electricity_variant=cfg.electricity_variant,
        )
        by_cty["parameter"] = parameter_name
        by_cty["value"] = value
        all_rows.append(by_cty)

    combined = pd.concat(all_rows, ignore_index=True)
    comp_cols = [c for c in ["capex_pv", "capex_storage", "capex_electric", "capex_gas", "vehicle_om"] if c in combined.columns]
    bill_cols = [c for c in ["annual_bill_electric", "annual_bill_gas"] if c in combined.columns]
    combined["total_eac"] = combined[comp_cols].sum(axis=1) + combined[bill_cols].sum(axis=1)

    out_path = os.path.join(output_dir, f"sensitivity_{parameter_name}.csv")
    merge_and_write_csv(combined, out_path, key_col=["parameter", "value", "scenario", "county_slug"])
    return combined
