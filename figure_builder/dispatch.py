"""Per-county dispatch inputs: turn a county slug into the 8760-hour load, PV
yield, and import/export price arrays the co-optimization model consumes.

This block was copy-pasted three times across the old scratchpad scripts
(`regen_sweep_8760`, `regen_counties_8760`, `build_mechanism_figs`). It lives
here once.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List

import numpy as np

from tariffs import ExportCompensationRegime, NEM2OptimizationTerms

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
    p_exp: np.ndarray          # 8760 hourly export value, $/kWh
    export_compensation_regime: ExportCompensationRegime
    nem2_terms: NEM2OptimizationTerms | None

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

    def coopt_inputs(self):
        """Return the exact tariff-aware input object used by Step 9b."""

        from pipeline.steps.step9b_cooptimize_core import CooptInputs

        return CooptInputs(
            load_kwh=list(self.load),
            pv_gen_per_kw=list(self.pv_gen_per_kw),
            import_rates=list(self.p_imp),
            export_rates=list(self.p_exp),
            nem2_terms=self.nem2_terms,
            max_pv_to_annual_load_ratio=(
                self.export_compensation_regime.max_pv_to_annual_load_ratio
            ),
        )


def county_dispatch_inputs(
    slug: str,
    scenario: str = DEFAULT_SCENARIO,
    base: str = BASE_INPUT_DIR,
    export_compensation_regime: (
        str | ExportCompensationRegime
    ) = ExportCompensationRegime.NBT_2026,
) -> DispatchInputs:
    """Assemble the 8760-hour arrays for one county, mirroring the setup Step 9b
    performs before solving the model."""
    from tariffs import (
        NBTScenario,
        NEM2Scenario,
        TariffCatalog,
        resolve_county_service_assignment,
    )
    from tariffs.calendar import full_year_hourly_index
    from pipeline.steps.step9_solar_storage_dispatch_core import (
        prepare_weather_and_load, pv_timeseries_ac_kwh,
    )

    weather_path, load_path = county_dispatch_input_paths(slug, scenario, base)
    wdf, load = prepare_weather_and_load(
        str(weather_path),
        str(load_path),
        LOAD_COL,
    )
    pvgen = pv_timeseries_ac_kwh(wdf, 1.0)
    assignment = resolve_county_service_assignment(slug)
    regime = ExportCompensationRegime.parse(export_compensation_regime)
    catalog = TariffCatalog()
    ts = full_year_hourly_index(2026)
    nem2_terms = None
    if regime is ExportCompensationRegime.NBT_2026:
        tariff = catalog.bundle(assignment.utility, NBTScenario())
        p_imp = np.array(tariff.import_schedule.rates_for(ts))
        p_exp = (
            np.array(tariff.export_schedule.rates_for(ts))
            + tariff.acc_plus_rate
        )
    else:
        tariff = catalog.nem2_bundle(assignment.utility, NEM2Scenario())
        nem2_terms = tariff.optimization_terms_for(ts)
        p_imp = np.array(nem2_terms.offsettable_rates_usd_per_kwh)
        p_exp = np.array(nem2_terms.offsettable_rates_usd_per_kwh)
    return DispatchInputs(
        slug=slug,
        util=assignment.utility.value,
        load=load,
        pv_gen_per_kw=pvgen,
        p_imp=p_imp,
        p_exp=p_exp,
        export_compensation_regime=regime,
        nem2_terms=nem2_terms,
    )


def county_dispatch_input_paths(
    slug: str,
    scenario: str = DEFAULT_SCENARIO,
    base: str | Path = BASE_INPUT_DIR,
    housing_type: str = HOUSING_TYPE,
) -> tuple[Path, Path]:
    """Return the exact weather and load-profile files consumed by a sweep."""

    from helpers.main_helpers import get_scenario_path

    scenario_path = Path(get_scenario_path(str(base), scenario, housing_type))
    county_dir = scenario_path / slug
    return (
        county_dir / f"weather_TMY_{slug}.csv",
        county_dir / f"combined_profiles_{scenario}_{slug}.csv",
    )
