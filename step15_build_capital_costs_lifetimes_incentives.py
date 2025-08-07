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
    if scenario not in SCENARIOS:
        raise ValueError(f"Unknown scenario: {scenario}. Available scenarios: {list(SCENARIOS.keys())}")
    
    scenario_config = SCENARIOS[scenario]
    electric_appliances = scenario_config.get("electric", set())
    
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


def _save_capital_costs_to_csv(base_output_dir: str, scenario: str, housing_type: str, 
                              counties: List[str], electric_appliances: Dict, 
                              gas_appliances: Dict, incentive_scenarios: List[IncentiveScenario]) -> None:
    """
    Save capital cost data to CSV files for geojson/HTML transformation.
    
    Args:
        base_output_dir: Output directory path
        scenario: Scenario name
        housing_type: Housing type
        counties: List of counties
        electric_appliances: Dictionary of electric appliances
        gas_appliances: Dictionary of gas appliances
        incentive_scenarios: List of incentive scenarios
    """
    # Create output directory
    output_dir = os.path.join(base_output_dir, "capital_costs")
    os.makedirs(output_dir, exist_ok=True)
    
    # Prepare data for each appliance type
    data_rows = []
    
    for county in counties:
        county_slug = slugify_county_name(county)
        
        # Process electric appliances for each incentive scenario
        for appliance_name, appliance in electric_appliances.items():
            for incentive_scenario in incentive_scenarios:
                breakdown = appliance.get_cost_breakdown(incentive_scenario)
                
                row = {
                    'county': county,
                    'county_slug': county_slug,
                    'scenario': scenario,
                    'housing_type': housing_type,
                    'appliance_category': 'electric',
                    'appliance_type': appliance_name,
                    'appliance_name': breakdown['appliance_type'],
                    'incentive_scenario': incentive_scenario.value,
                    'base_cost': breakdown['base_cost'],
                    'total_incentives': breakdown['total_incentives'],
                    'net_cost': breakdown['net_cost'],
                    'lifetime_years': breakdown['lifetime_years'],
                    'cost_per_year': breakdown['cost_per_year'],
                    'annual_maintenance_cost': breakdown.get('annual_maintenance_cost', 0),
                    'annual_insurance_cost': breakdown.get('annual_insurance_cost', 0),
                    'annual_fuel_cost': breakdown.get('annual_fuel_cost', 0),
                    'annual_operating_cost': breakdown.get('annual_operating_cost', breakdown.get('annual_maintenance_cost', 0) + breakdown.get('annual_insurance_cost', 0)),
                    'total_operating_cost_over_lifetime': breakdown.get('total_operating_cost_over_lifetime', breakdown.get('annual_operating_cost', 0) * breakdown['lifetime_years']),
                    'total_cost_of_ownership': breakdown.get('total_cost_of_ownership', breakdown['net_cost'] + breakdown.get('total_operating_cost_over_lifetime', 0))
                }
                data_rows.append(row)
        
        # Process gas appliances (no incentive scenarios)
        # Skip gas appliances for baseline scenarios - they represent existing configuration with no capital costs
        if not (scenario == "baseline" or scenario == "baseline_ice_car"):
            for appliance_name, appliance in gas_appliances.items():
                if appliance_name == "vehicle":
                    breakdown = appliance.get_cost_breakdown(county)
                else:
                    breakdown = appliance.get_cost_breakdown()
                
                row = {
                    'county': county,
                    'county_slug': county_slug,
                    'scenario': scenario,
                    'housing_type': housing_type,
                    'appliance_category': 'gas',
                    'appliance_type': appliance_name,
                    'appliance_name': breakdown['appliance_type'],
                    'incentive_scenario': 'no_incentives',
                    'base_cost': breakdown['base_cost'],
                    'total_incentives': breakdown.get('total_incentives', 0),
                    'net_cost': breakdown['net_cost'],
                    'lifetime_years': breakdown['lifetime_years'],
                    'cost_per_year': breakdown['annual_cost'],
                    'annual_maintenance_cost': breakdown.get('annual_maintenance_cost', 0),
                    'annual_insurance_cost': breakdown.get('annual_insurance_cost', 0),
                    'annual_fuel_cost': breakdown.get('annual_fuel_cost', 0),
                    'annual_operating_cost': breakdown.get('annual_operating_cost', 0),
                    'total_operating_cost_over_lifetime': breakdown.get('total_operating_cost_over_lifetime', 0),
                    'total_cost_of_ownership': breakdown.get('total_cost_of_ownership', breakdown['base_cost'])
                }
                data_rows.append(row)
    
    # Create DataFrame and save to CSV
    df = pd.DataFrame(data_rows)
    
    if df.empty:
        return
    
    # Save comprehensive data file
    csv_filename = f"capital_costs_{scenario}_{housing_type.replace('-', '_')}.csv"
    csv_path = os.path.join(output_dir, csv_filename)
    df.to_csv(csv_path, index=False)
    
    print(f"Capital cost data saved: {csv_path}")
    
    # Also save summary files by appliance category
    if 'appliance_category' in df.columns:
        electric_df = df[df['appliance_category'] == 'electric']
        if not electric_df.empty:
            electric_csv_path = os.path.join(output_dir, f"electric_capital_costs_{scenario}_{housing_type.replace('-', '_')}.csv")
            electric_df.to_csv(electric_csv_path, index=False)
        
        gas_df = df[df['appliance_category'] == 'gas']  
        if not gas_df.empty:
            gas_csv_path = os.path.join(output_dir, f"gas_capital_costs_{scenario}_{housing_type.replace('-', '_')}.csv")
            gas_df.to_csv(gas_csv_path, index=False)
    


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
    
    
    # Get the appropriate appliances for this scenario
    try:
        electric_appliance_classes = get_appliances_for_scenario(scenario)
        gas_appliance_classes = get_gas_appliances_for_scenario(scenario)
    except ValueError as e:
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
            lifetime_years=12,
            annual_maintenance_cost=800.0,  # EVs typically have lower maintenance
            annual_insurance_cost=1800.0    # Slightly lower than ICE due to safety features
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
            lifetime_years=12,
            annual_maintenance_cost=1200.0,  # ICE vehicles have higher maintenance
            annual_insurance_cost=2000.0     # Slightly higher than EV
        )
    
    
    # Show cost breakdown for electric appliances with different incentive scenarios
    incentive_scenarios = [IncentiveScenario.FULL_INCENTIVES, IncentiveScenario.HALF_INCENTIVES, IncentiveScenario.NO_INCENTIVES]
    
    if electric_appliances:
        for appliance_name, appliance in electric_appliances.items():
            for incentive_scenario in incentive_scenarios:
                breakdown = appliance.get_cost_breakdown(incentive_scenario)
    
    
    all_appliances = {**electric_appliances, **gas_appliances}
    
    # Save capital costs to CSV files for each county
    _save_capital_costs_to_csv(base_output_dir, scenario, housing_type, counties, 
                              electric_appliances, gas_appliances, incentive_scenarios)
    
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
    
