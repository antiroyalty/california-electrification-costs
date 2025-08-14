"""
Step 15: Build Capital Costs, Lifetimes, Incentives

Build Capital Costs, Lifetimes, Incentives for my numbers.
Define each technology as a class that can be configured. It has a capital cost, 
a lifetime, and associated incentives at the state, federal, and utility level.

I want the ability to configure different Component "scenarios", like:
- No Incentives
- Half Incentives  
- My Capital Costs
- Cris's Capital Costs
- EMP Capital Costs
"""

import os
import pandas as pd
from main_helpers import log, slugify_county_name
from scenarios import SCENARIOS
from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from enum import Enum

class IncentiveScenario(Enum):
    """Defines different incentive scenarios for capital cost analysis."""
    FULL_INCENTIVES = "full_incentives"
    HALF_INCENTIVES = "half_incentives"
    NO_INCENTIVES = "no_incentives"

@dataclass
class Incentive:
    """Represents a single incentive (federal, state, or utility level)."""
    name: str
    value: float
    unit: str  # "$" for fixed amount, "%" for percentage
    max_value: Optional[float] = None
    description: str = ""
    source_url: str = ""


class ElectricAppliance(ABC):
    """Abstract base class for electric appliances used in home electrification."""
    
    def __init__(self, name: str, base_cost: float, lifetime_years: int):
        self.name = name
        self.base_cost = base_cost
        self.lifetime_years = lifetime_years
        self.incentives: List[Incentive] = []
    
    def add_incentive(self, incentive: Incentive) -> None:
        self.incentives.append(incentive)
    
    def calculate_total_incentives(self, scenario: IncentiveScenario = IncentiveScenario.FULL_INCENTIVES) -> float:
        if scenario == IncentiveScenario.NO_INCENTIVES:
            return 0.0
        
        total_incentives = 0.0
        multiplier = 1.0 if scenario == IncentiveScenario.FULL_INCENTIVES else 0.5
        
        for incentive in self.incentives:
            if incentive.unit == "%":
                incentive_value = self.base_cost * (incentive.value / 100)
                if incentive.max_value:
                    incentive_value = min(incentive_value, incentive.max_value)
            else:  # Fixed dollar amount
                incentive_value = incentive.value
            
            total_incentives += incentive_value * multiplier
        
        return total_incentives
    
    def get_net_cost(self, scenario: IncentiveScenario = IncentiveScenario.FULL_INCENTIVES) -> float:
        return max(0, self.base_cost - self.calculate_total_incentives(scenario))
    
    @abstractmethod
    def get_cost_breakdown(self, scenario: IncentiveScenario = IncentiveScenario.FULL_INCENTIVES) -> Dict:
        """Return detailed cost breakdown including incentives."""
        pass

from typing import Dict, Set

from typing import Dict, Set, Tuple

def diff_scenarios(
    scenario: str,
    base: str = "baseline",
)  -> dict[str, set[str]]:
    """
    Compare `scenario` with the `base` scenario (defaults to "baseline")
    and return two dictionaries:

        • electric_added  – end-uses that are electric in `scenario` but were
                            *not* electric in `base`  (includes gas→electric moves
                            *and* entirely new electric loads).

        • gas_removed     – end-uses that were gas in `base` and are *no longer*
                            gas in `scenario`  (i.e. converted to electric or
                            removed altogether).

    Example
    -------
    >>> e_added, g_removed = diff_scenarios("heat_pump")
    >>> e_added    # {'heating'}
    >>> g_removed  # {'heating'}
    """
    try:
        base_cfg   = SCENARIOS[base]
        target_cfg = SCENARIOS[scenario]
    except KeyError as err:
        raise ValueError(f"Unknown scenario '{err.args[0]}'") from None

    # --- convenience shortcuts -----------------------------------------
    base_elec   = base_cfg.get("electric", set())
    base_gas    = base_cfg.get("gas", set())
    target_elec = target_cfg.get("electric", set())
    target_gas  = target_cfg.get("gas", set())

    # --- what’s new on the electric side -------------------------------
    electric_added = target_elec - base_elec        # new or moved-from-gas

    # --- what’s vanished from the gas side -----------------------------
    gas_removed = base_gas - target_gas             # moved to electric or dropped

    return {"electric_added": electric_added, "gas_removed": gas_removed}

def net_outlay_by_scenario(
    electric: dict[str, "ElectricAppliance"],
    gas: dict[str, "ElectricAppliance"],
) -> dict[IncentiveScenario, float]:
    """
    Return a dict mapping each IncentiveScenario → summed net capital cost
    (electric - incentives) minus gas‐appliance capital cost.

    If the scenario does not replace a given gas appliance (e.g. induction stove
    when there was no gas stove), the gas cost is treated as 0.
    """
    gas_baseline = {name: app.base_cost for name, app in gas.items()}

    net_totals = defaultdict(float)         # {scenario: total $}

    for name, e_app in electric.items():
        gas_cost = gas_baseline.get(name, 0.0)

        for sc in (
            IncentiveScenario.FULL_INCENTIVES,
            IncentiveScenario.HALF_INCENTIVES,
            IncentiveScenario.NO_INCENTIVES,
        ):
            electric_net = e_app.get_net_cost(sc)
            net_totals[sc] += electric_net - gas_cost      # add difference

    return net_totals

def get_appliances_for_scenario(scenario: str) -> Dict[str, type]:
    if scenario not in SCENARIOS:
        raise ValueError(f"Unknown scenario: {scenario}. Available scenarios: {list(SCENARIOS.keys())}")
    
    diff = diff_scenarios(scenario)
    electric_appliances = diff["electric_added"]

    print(electric_appliances)
    
    appliance_classes = {}
    
    if "heating" in electric_appliances:
        from appliances.electric_heating import ElectricHeatingAppliance
        appliance_classes["heating"] = ElectricHeatingAppliance
    
    if "cooking" in electric_appliances:
        from appliances.electric_cooking import ElectricCookingAppliance
        appliance_classes["cooking"] = ElectricCookingAppliance
    
    if "hot_water" in electric_appliances:
        from appliances.electric_water_heating import ElectricWaterHeatingAppliance
        appliance_classes["hot_water"] = ElectricWaterHeatingAppliance
    
    if "vehicle_charging" in electric_appliances:
        from appliances.electric_vehicle import ElectricVehicleAppliance
        appliance_classes["vehicle"] = ElectricVehicleAppliance

    return appliance_classes


def get_gas_appliances_for_scenario(scenario: str) -> Dict[str, type]:
    """
    Determine which gas appliances are needed based on the scenario.
    
    Args:
        scenario: Scenario name from CostService.SCENARIOS
        
    Returns:
        Dictionary mapping appliance type to gas appliance class
    """
    
    if scenario not in SCENARIOS:
        raise ValueError(f"Unknown scenario: {scenario}. Available scenarios: {list(SCENARIOS.keys())}")
    
    diff = diff_scenarios(scenario)
    breakpoint()
    gas_appliances = diff["gas_removed"]

    print(gas_appliances)
    
    appliance_classes = {}
    
    if "heating" in gas_appliances:
        from appliances.gas_heating import GasHeatingAppliance
        appliance_classes["heating"] = GasHeatingAppliance
    
    if "cooking" in gas_appliances:
        from appliances.gas_stove import GasStoveAppliance
        appliance_classes["cooking"] = GasStoveAppliance
    
    if "vehicle_fuel" in gas_appliances:
        from appliances.ice_vehicle import ICEVehicleAppliance
        appliance_classes["vehicle"] = ICEVehicleAppliance

    return appliance_classes

def _save_capital_costs_to_csv(
    base_output_dir: str,
    scenario: str,
    housing_type: str,
    counties: list[str],
    electric_appliances: dict[str, "ElectricAppliance"],
    gas_appliances: dict[str, "ElectricAppliance"],
    incentive_scenarios: list[IncentiveScenario],
) -> None:
    """
    Write a single CSV with one row per county and the eight columns:

        county, capital_cost_full,
        incentives_full, incentives_half, incentives_none,
        net_outlay_full, net_outlay_half, net_outlay_none
    """
    rows: list[dict] = []

    for county in counties:
        # ----------------------------------------------------------
        # 1.  capital-cost buckets (no incentives applied yet)
        # ----------------------------------------------------------
        capital_cost_electric = sum(app.base_cost for app in electric_appliances.values())
        capital_cost_gas      = sum(app.base_cost for app in gas_appliances.values())

        # ----------------------------------------------------------
        # 2.  incentives on the electric side
        # ----------------------------------------------------------
        incentives_full = sum(
            app.calculate_total_incentives(IncentiveScenario.FULL_INCENTIVES)
            for app in electric_appliances.values()
        )
        incentives_half = incentives_full * 0.5
        incentives_none = 0.0

        # ----------------------------------------------------------
        # 3.  incremental (“net”) outlay  = electric – gas – incentives
        # ----------------------------------------------------------
        net_outlay_full = (capital_cost_electric - capital_cost_gas) - incentives_full
        net_outlay_half = (capital_cost_electric - capital_cost_gas) - incentives_half
        net_outlay_none = (capital_cost_electric - capital_cost_gas)                # no incentives

        rows.append(
            {
                "county": county,
                "capital_cost_electric": capital_cost_electric,
                "capital_cost_gas": capital_cost_gas,
                "incentives_full": incentives_full,
                "incentives_half": incentives_half,
                "incentives_none": incentives_none,
                "net_outlay_full": net_outlay_full,
                "net_outlay_half": net_outlay_half,
                "net_outlay_none": net_outlay_none,
            }
        )

    df = pd.DataFrame(rows).sort_values("county")

    out_dir = os.path.join(base_output_dir, "capital_costs")
    os.makedirs(out_dir, exist_ok=True)

    fname = f"capital_costs_summary_{scenario}_{housing_type.replace('-', '_')}.csv"
    csv_path = os.path.join(out_dir, fname)
    df.to_csv(csv_path, index=False)
    print(f"Capital-cost summary saved to: {csv_path}")

def initialize_capital_cost_appliances(
    scenario: str,
) -> Tuple[Dict[str, "ElectricAppliance"], Dict[str, "ElectricAppliance"]]:
    """
    Instantiate and return the electric_appliances and gas_appliances dicts
    required by `process`.

    Raises
    ------
    ValueError
        If `scenario` is not defined in SCENARIOS.
    """
    # look up which appliance classes the scenario requires
    electric_classes = get_appliances_for_scenario(scenario)
    gas_classes      = get_gas_appliances_for_scenario(scenario)

    electric: Dict[str, ElectricAppliance] = {}
    gas: Dict[str, ElectricAppliance]      = {}

    # ---------- electric ---------------------------------------------------
    if "heating" in electric_classes:
        electric["heating"] = electric_classes["heating"](
            heating_type="heat_pump",
            base_cost=19_000.0,
            lifetime_years=15,
        )

    if "cooking" in electric_classes:
        electric["cooking"] = electric_classes["cooking"](
            cooking_type="induction",
            base_cost=2_000.0,
            lifetime_years=15,
        )

    if "hot_water" in electric_classes:
        electric["hot_water"] = electric_classes["hot_water"](
            heater_type="heat_pump",
            base_cost=2_637.0,
            lifetime_years=15,
        )

    if "vehicle" in electric_classes:
        electric["vehicle"] = electric_classes["vehicle"](
            vehicle_type="Tesla_Model_3",
            base_cost=45_000.0,
            lifetime_years=12,
            annual_maintenance_cost=800.0,
            annual_insurance_cost=1_800.0,
        )

    # ---------- gas --------------------------------------------------------
    # TODO make sure the capital costs are net with gas, not absolute

    if "heating" in gas_classes:
        gas["heating"] = gas_classes["heating"](
            heating_type="furnace",
            base_cost=4_500.0,
            lifetime_years=15,
        )

    if "cooking" in gas_classes:
        gas["cooking"] = gas_classes["cooking"](
            stove_type="gas",
            base_cost=1_600.0,
            lifetime_years=15,
        )

    # TODO: Add a gas water heater too

    if "vehicle" in gas_classes:
        gas["vehicle"] = gas_classes["vehicle"](
            vehicle_type="ICE",
            base_cost=35_000.0,
            lifetime_years=12,
            annual_maintenance_cost=1_200.0,
            annual_insurance_cost=2_000.0,
        )

    return electric, gas

def process(
    base_input_dir: str,
    base_output_dir: str,
    scenario: str,
    housing_type: str,
    counties: list[str],
):
    """Build capital-cost, lifetime, and incentive tables for a scenario."""
    log(
        at="step15_build_capital_costs_lifetimes_incentives",
        info="starting_capital_costs_build",
        scenario=scenario,
        housing_type=housing_type,
    )

    try:
        electric_appliances, gas_appliances = initialize_capital_cost_appliances(
            scenario
        )
    except ValueError as err:
        log(
            at="step15_build_capital_costs_lifetimes_incentives",
            info="capital_costs_build_failed",
            error=str(err),
        )
        return {}

    incentive_scenarios = [
        IncentiveScenario.FULL_INCENTIVES,
        IncentiveScenario.HALF_INCENTIVES,
        IncentiveScenario.NO_INCENTIVES,
    ]

    # (Optional) quick sanity-check / warm-up
    for app in electric_appliances.values():
        _ = [app.get_cost_breakdown(sc) for sc in incentive_scenarios]

    _save_capital_costs_to_csv(
        base_output_dir,
        scenario,
        housing_type,
        counties,
        electric_appliances,
        gas_appliances,
        incentive_scenarios,
    )

    all_appliances = {**electric_appliances, **gas_appliances}
    log(
        at="step15_build_capital_costs_lifetimes_incentives",
        info="capital_costs_build_completed",
        electric_appliances_initialized=len(electric_appliances),
        gas_appliances_initialized=len(gas_appliances),
        total_appliances_initialized=len(all_appliances),
        scenarios_evaluated=len(incentive_scenarios),
    )

    return {"electric": electric_appliances, "gas": gas_appliances}

if __name__ == "__main__":
    import argparse
    from scenarios import SCENARIOS
    from main_helpers import norcal_counties, socal_counties, central_counties
    
    parser = argparse.ArgumentParser(description="Build capital costs, lifetimes, and incentives for electrification scenarios")
    parser.add_argument("scenario", 
                       choices=list(SCENARIOS.keys()),
                       help="Electrification scenario to analyze")
    
    args = parser.parse_args()
    
    housing_type = "single-family-detached"
    all_counties = norcal_counties + socal_counties + central_counties
    
    result = process(
        base_input_dir="data/loadprofiles",
        base_output_dir="data/loadprofiles", 
        scenario=args.scenario,
        housing_type=housing_type,
        counties=all_counties
    )
    
