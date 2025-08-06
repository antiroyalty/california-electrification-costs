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
from scenarios import SCENARIOS
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
    
    if scenario not in SCENARIOS:
        raise ValueError(f"Unknown scenario: {scenario}. Available scenarios: {list(SCENARIOS.keys())}")
    
    scenario_config = SCENARIOS[scenario]
    electric_appliances = scenario_config.get("electric", set())
    
    # Map electric appliances to their corresponding classes
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
    
    scenario_config = SCENARIOS[scenario]
    gas_appliances = scenario_config.get("gas", set())
    
    # Map gas appliances to their corresponding classes
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
        electric_appliance_classes = get_appliances_for_scenario(scenario)
        gas_appliance_classes = get_gas_appliances_for_scenario(scenario)
    except ValueError as e:
        print(f"Error: {e}")
        log(
            at="step15_build_capital_costs_lifetimes_incentives",
            info="capital_costs_build_failed",
            error=str(e)
        )
        return {}
    
    electric_appliances = {}
    gas_appliances = {}
    
    # Initialize electric appliances
    if "heating" in electric_appliance_classes:
        electric_appliances["heating"] = electric_appliance_classes["heating"](
            heating_type="heat_pump",
            base_cost=19000.0,
            lifetime_years=15
        )
    
    if "cooking" in electric_appliance_classes:
        electric_appliances["cooking"] = electric_appliance_classes["cooking"](
            cooking_type="induction",
            base_cost=2000.0,
            lifetime_years=15
        )
    
    if "hot_water" in electric_appliance_classes:
        electric_appliances["hot_water"] = electric_appliance_classes["hot_water"](
            heater_type="heat_pump",
            base_cost=2637.0,
            lifetime_years=15
        )
    
    if "vehicle" in electric_appliance_classes:
        ev = electric_appliance_classes["vehicle"](
            vehicle_type="Tesla_Model_3",
            base_cost=45000.0,
            lifetime_years=12
        )

        # Add custom incentives in addition to what is defined in electric_vehicle.py
        # ev.add_incentive(Incentive(
        #     name="Federal Clean Vehicle Credit - Model 3",
        #     value=3750.0,  # Half credit for Tesla after phase-out
        #     unit="$"
        # ))

        electric_appliances["vehicle"] = ev

    
    # Initialize gas appliances
    if "heating" in gas_appliance_classes:
        gas_appliances["heating"] = gas_appliance_classes["heating"](
            heating_type="furnace",
            base_cost=4500.0,
            lifetime_years=15
        )
    
    if "cooking" in gas_appliance_classes:
        gas_appliances["cooking"] = gas_appliance_classes["cooking"](
            stove_type="gas",
            base_cost=1600.0,
            lifetime_years=15
        )
    
    if "vehicle" in gas_appliance_classes:
        gas_appliances["vehicle"] = gas_appliance_classes["vehicle"](
            vehicle_type="ICE",
            base_cost=35000.0,
            lifetime_years=12
        )
    
    if electric_appliances:
        print(f"Electric: {list(electric_appliances.keys())}")
    if gas_appliances:
        print(f"Gas: {list(gas_appliances.keys())}")
    
    # Show cost breakdown for electric appliances with different incentive scenarios
    incentive_scenarios = [IncentiveScenario.FULL_INCENTIVES, IncentiveScenario.HALF_INCENTIVES, IncentiveScenario.NO_INCENTIVES]
    
    if electric_appliances:
        print(f"\n{'='*60}")
        print("ELECTRIC APPLIANCES COST ANALYSIS")
        print(f"{'='*60}")
        
        for appliance_name, appliance in electric_appliances.items():
            print(f"\n=== ELECTRIC {appliance_name.upper()} ===")
            
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
                    print(f"  {payback_years}-year payback needs: ${required_savings:,.2f}/year")
    
    # Show cost breakdown for gas appliances (no incentives)
    if gas_appliances:
        print(f"\n{'='*60}")
        print("GAS APPLIANCES COST ANALYSIS")
        print(f"{'='*60}")
        
        for appliance_name, appliance in gas_appliances.items():
            print(f"\n=== GAS {appliance_name.upper()} ===")
            breakdown = appliance.get_cost_breakdown()
            
            print(f"Appliance: {breakdown['appliance_type']}")
            print(f"Base Cost: ${breakdown['base_cost']:,.2f}")
            print(f"Net Cost: ${breakdown['net_cost']:,.2f}")
            print(f"Annual Cost: ${breakdown['annual_cost']:,.2f}")
            print(f"Lifetime: {breakdown['lifetime_years']} years")
            print(f"Has Incentives: {breakdown['has_incentives']}")
            
            # Show total cost of ownership if available
            if hasattr(appliance, 'get_total_cost_of_ownership'):
                try:
                    tco = appliance.get_total_cost_of_ownership()
                    if 'total_cost_of_ownership' in tco:
                        print(f"Total Cost of Ownership: ${tco['total_cost_of_ownership']:,.2f}")
                except:
                    pass  # Skip if TCO calculation fails
    
    all_appliances = {**electric_appliances, **gas_appliances}
    
    log(
        at="step15_build_capital_costs_lifetimes_incentives",
        info="capital_costs_build_completed",
        electric_appliances_initialized=len(electric_appliances),
        gas_appliances_initialized=len(gas_appliances),
        total_appliances_initialized=len(all_appliances),
        scenarios_evaluated=len(incentive_scenarios) if electric_appliances else 0
    )
    
    return {"electric": electric_appliances, "gas": gas_appliances}


if __name__ == "__main__":
    import argparse
    from scenarios import SCENARIOS
    
    parser = argparse.ArgumentParser(description="Build capital costs, lifetimes, and incentives for electrification scenarios")
    parser.add_argument("--scenario", 
                       choices=list(SCENARIOS.keys()),
                       default="heat_pump_and_induction_stove_and_water_heating",
                       help="Electrification scenario to analyze")
    parser.add_argument("--housing-type",
                       default="single-family-detached",
                       help="Housing type to analyze")
    parser.add_argument("--county",
                       default="Alameda County", 
                       help="County to analyze")
    
    args = parser.parse_args()
    
    print("=" * 70)
    print(f"ANALYZING SCENARIO: {args.scenario.upper()}")
    print("=" * 70)
    
    result = process(
        base_input_dir="data/loadprofiles",
        base_output_dir="data/loadprofiles", 
        scenario=args.scenario,
        housing_type=args.housing_type,
        counties=[args.county]
    )
    
    print(f"\nResult summary for {args.scenario}:")
    if isinstance(result, dict):
        print(f"  Electric appliances: {len(result.get('electric', {}))}")
        print(f"  Gas appliances: {len(result.get('gas', {}))}")
    else:
        print(f"  Legacy result type: {type(result)}")