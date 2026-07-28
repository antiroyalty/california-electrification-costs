"""Per-county dispatch inputs: turn a county slug into the 8760-hour load, PV
yield, and import/export price arrays the co-optimization LP consumes.

This block was copy-pasted three times across the old scratchpad scripts
(`regen_sweep_8760`, `regen_counties_8760`, `build_mechanism_figs`). It lives
here once.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Dict, List

import numpy as np

# --- domain constants -------------------------------------------------------
DEFAULT_SCENARIO = "full_electric_ev_coopt"
HOUSING_TYPE = "single-family-detached"
BASE_INPUT_DIR = "data/loadprofiles"
LOAD_COL = "electricity.real_and_simulated.for_typical_county_home.kwh"

# The four Claim-1 case-study counties and their IOU territory.
CLAIM1_COUNTIES = [
    ("alameda", "Alameda County", "PG&E"),
    ("fresno", "Fresno County", "PG&E"),
    ("los-angeles", "Los Angeles County", "SCE"),
    ("san-diego", "San Diego County", "SDG&E"),
]

# Battery capex sweep points, $/kWh. $1 is a near-free degenerate probe used
# only by the "ceiling" figure; market figures filter to >= $25. The list runs
# past $1,200 so today's net price stays on-chart under any current regime.
SWEEP_POINTS: List[int] = [1, 5, 10, 25, 50, 100, 150, 200, 300, 400,
                           500, 600, 700, 800, 1000, 1200, 1400, 1500]


@dataclass
class DispatchInputs:
    slug: str
    util: str
    load: np.ndarray           # 8760 hourly load, kWh
    pv_gen_per_kw: np.ndarray  # 8760 hourly AC yield per installed kW
    p_imp: np.ndarray          # 8760 hourly import price, $/kWh
    p_exp: np.ndarray          # 8760 hourly NEM 3.0 export price, $/kWh

    @property
    def annual_load(self) -> float:
        return float(np.sum(self.load))

    @property
    def yield_per_kw(self) -> float:
        return float(np.sum(self.pv_gen_per_kw))

    def pv_kw_for_full_load(self, round_trip_eff: float = 0.90):
        """PV size (kW) that covers 100% of annual load, and the same grossed up
        for round-trip storage losses. Optimal solar flattens against this band.
        """
        cover = self.annual_load / self.yield_per_kw
        return cover, cover / round_trip_eff


def _rate_plans() -> Dict[str, dict]:
    from helpers.electricity_rate_helpers import (
        PGE_RATE_PLANS, SCE_RATE_PLANS, SDGE_RATE_PLANS,
    )
    return {"PG&E": PGE_RATE_PLANS, "SCE": SCE_RATE_PLANS, "SDG&E": SDGE_RATE_PLANS}


def county_dispatch_inputs(
    slug: str,
    scenario: str = DEFAULT_SCENARIO,
    base: str = BASE_INPUT_DIR,
) -> DispatchInputs:
    """Assemble the 8760-hour arrays for one county, mirroring the setup Step 9b
    performs before solving the LP."""
    from helpers.main_helpers import get_scenario_path
    from helpers.utility_helpers import get_utility_for_county
    from helpers.nem3_export_rates import get_export_rate_table_for_county
    from pipeline.steps.step9_solar_storage_dispatch_core import (
        prepare_weather_and_load, pv_timeseries_ac_kwh,
    )
    from pipeline.steps.step9b_cooptimize_core import (
        _hourly_import_rate, _timestamp_index_8760,
    )

    cdir = os.path.join(get_scenario_path(base, scenario, HOUSING_TYPE), slug)
    wdf, load = prepare_weather_and_load(
        os.path.join(cdir, f"weather_TMY_{slug}.csv"),
        os.path.join(cdir, f"combined_profiles_{scenario}_{slug}.csv"),
        LOAD_COL,
    )
    pvgen = pv_timeseries_ac_kwh(wdf, 1.0)
    util = get_utility_for_county(slug)
    plans = _rate_plans()[util]
    plan = plans[next(iter(plans))]
    ts = _timestamp_index_8760(2018)
    p_imp = np.array([_hourly_import_rate(plan, t) for t in ts])
    xt = get_export_rate_table_for_county(
        base_dir=os.path.join("data", "NEM3"),
        utility=util, county_name_or_slug=slug,
    )
    p_exp = np.array([float(xt[t.month][t.hour]) for t in ts])
    return DispatchInputs(slug, util, load, pvgen, p_imp, p_exp)
