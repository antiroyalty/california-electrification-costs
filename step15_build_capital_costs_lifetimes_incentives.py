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
from main_helpers import log
from abc import ABC, abstractmethod
from typing import Dict, List, Optional
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


def get_appliances_for_scenario(scenario: str) -> Dict[str, type]:
    """
    Determine which electric appliances are needed based on the scenario.
    
    Args:
        scenario: Scenario name from CostService.SCENARIOS
        
    Returns:
        Dictionary mapping appliance type to appliance class
    """
    # Define scenario configurations based on CostService.SCENARIOS
    SCENARIOS = {
        "baseline": {"gas": {"heating", "hot_water", "cooking"}, "electric": {"appliances", "misc"}},
        "heat_pump": {"gas": {"hot_water", "cooking"}, "electric": {"appliances", "misc", "heating"}},
        "induction_stove": {"gas": {"hot_water", "heating"}, "electric": {"appliances", "misc", "cooking"}},
        "heat_pump_and_induction_stove": {"gas": {"hot_water"}, "electric": {"appliances", "misc", "cooking", "heating"}},
        "water_heating": {"gas": {"cooking", "heating"}, "electric": {"hot_water", "appliances", "misc"}},
        "heat_pump_and_induction_stove_and_water_heating": {"gas": set(), "electric": {"hot_water", "cooking", "heating", "appliances", "misc"}},
        # EV scenarios
        "baseline_ice_car": {"gas": {"heating", "hot_water", "cooking", "vehicle_fuel"}, "electric": {"appliances", "misc"}},
        "baseline_ev_car": {"gas": {"heating", "hot_water", "cooking"}, "electric": {"appliances", "misc", "vehicle_charging"}},
        "full_electric_ev": {"gas": set(), "electric": {"hot_water", "cooking", "heating", "appliances", "misc", "vehicle_charging"}},
    }
    
    if scenario not in SCENARIOS:
        raise ValueError(f"Unknown scenario: {scenario}. Available scenarios: {list(SCENARIOS.keys())}")
    
    scenario_config = SCENARIOS[scenario]
    electric_appliances = scenario_config.get("electric", set())
    
    # Map electric appliances to their corresponding classes
    appliance_classes = {}
    
    if "heating" in electric_appliances:
        from appliances.electric_heating import ElectricHeatingAppliance
        appliance_classes["heating"] = ElectricHeatingAppliance
    
    # TODO: Add other appliance types as they are implemented
    # if "cooking" in electric_appliances:
    #     from appliances.electric_cooking import ElectricCookingAppliance
    #     appliance_classes["cooking"] = ElectricCookingAppliance
    #
    # if "hot_water" in electric_appliances:
    #     from appliances.electric_water_heater import ElectricWaterHeaterAppliance
    #     appliance_classes["hot_water"] = ElectricWaterHeaterAppliance
    
    return appliance_classes


def process(base_input_dir: str, base_output_dir: str, scenario: str,
           housing_type: str, counties: list):
    """
    Build capital costs, lifetimes, and incentives definitions using scenario-based appliance selection.
    
    This function initializes the appropriate electric appliances based on the scenario
    and demonstrates cost calculations for different incentive scenarios.
    
    Args:
        base_input_dir: Input directory path
        base_output_dir: Output directory path
        scenario: Scenario name (from CostService.SCENARIOS)
        housing_type: Housing type
        counties: List of counties to process
    """
    
    log(
        at="step15_build_capital_costs_lifetimes_incentives",
        info="starting_capital_costs_build",
        scenario=scenario,
        housing_type=housing_type
    )
    
    print(f"Initializing appliances for scenario: {scenario}")
    
    # Get the appropriate appliances for this scenario
    try:
        appliance_classes = get_appliances_for_scenario(scenario)
    except ValueError as e:
        print(f"Error: {e}")
        log(
            at="step15_build_capital_costs_lifetimes_incentives",
            info="capital_costs_build_failed",
            error=str(e)
        )
        return {}
    
    # Initialize appliance instances
    appliances = {}
    
    if "heating" in appliance_classes:
        appliances["heating"] = appliance_classes["heating"](
            heating_type="heat_pump",
            base_cost=19000.0,
            lifetime_years=15
        )
    
    # Handle baseline scenario (no electric appliances, no capital costs)
    if scenario == "baseline":
        print("Baseline scenario: No electric appliances, no capital costs to model.")
        log(
            at="step15_build_capital_costs_lifetimes_incentives",
            info="capital_costs_build_completed",
            scenario_type="baseline",
            appliances_initialized=0
        )
        return {}
    
    if not appliances:
        print(f"No electric appliances configured for scenario: {scenario}")
        log(
            at="step15_build_capital_costs_lifetimes_incentives",
            info="capital_costs_build_completed",
            scenario_type="no_electric_appliances",
            appliances_initialized=0
        )
        return {}
    
    # Show cost breakdown for different incentive scenarios
    incentive_scenarios = [IncentiveScenario.FULL_INCENTIVES, IncentiveScenario.HALF_INCENTIVES, IncentiveScenario.NO_INCENTIVES]
    
    for appliance_name, appliance in appliances.items():
        print(f"\n=== {appliance_name.upper()} APPLIANCE ===")
        
        for incentive_scenario in incentive_scenarios:
            breakdown = appliance.get_cost_breakdown(incentive_scenario)
            
            print(f"\n--- {incentive_scenario.value.upper()} ---")
            print(f"Appliance: {breakdown['appliance_type']}")
            print(f"Base Cost: ${breakdown['base_cost']:,.2f}")
            print(f"Total Incentives: ${breakdown['total_incentives']:,.2f}")
            print(f"Net Cost: ${breakdown['net_cost']:,.2f}")
            print(f"Cost per Year: ${breakdown['cost_per_year']:,.2f}")
            print(f"Lifetime: {breakdown['lifetime_years']} years")
            
            # Show required annual savings for different payback periods
            for payback_years in [5, 10, 15]:
                required_savings = appliance.get_annual_cost_savings_needed_for_payback(
                    payback_years, incentive_scenario
                )
                print(f"Annual savings needed for {payback_years}-year payback: ${required_savings:,.2f}")
    
    log(
        at="step15_build_capital_costs_lifetimes_incentives",
        info="capital_costs_build_completed",
        appliances_initialized=len(appliances),
        scenarios_evaluated=len(incentive_scenarios)
    )
    
    return appliances


if __name__ == "__main__":
    # Test with baseline scenario (no electric appliances)
    print("=" * 50)
    print("TESTING BASELINE SCENARIO")
    print("=" * 50)
    process(
        base_input_dir="data/loadprofiles",
        base_output_dir="data/loadprofiles", 
        scenario="baseline",
        housing_type="single-family-detached",
        counties=["Alameda County"]
    )
    
    print("\n" + "=" * 50)
    print("TESTING HEAT_PUMP SCENARIO")
    print("=" * 50)
    process(
        base_input_dir="data/loadprofiles",
        base_output_dir="data/loadprofiles", 
        scenario="heat_pump",
        housing_type="single-family-detached",
        counties=["Alameda County"]
    )