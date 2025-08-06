"""
Electric heating appliance class for residential electrification cost modeling.

This module defines the ElectricHeatingAppliance class used to model the capital costs,
lifetime, and incentives for electric heating systems (heat pumps) that replace gas
heating in residential electrification scenarios.
"""

from typing import Dict
from step15_build_capital_costs_lifetimes_incentives import ElectricAppliance, Incentive, IncentiveScenario

class ElectricHeatingAppliance(ElectricAppliance):
    """
    Class representing electric heating appliances (heat pumps) for home electrification.
    
    This class models the capital costs, lifetime, and incentives for electric heating
    systems that replace gas heating in residential electrification scenarios.
    """
    
    def __init__(self, 
                 heating_type: str = "heat_pump",
                 base_cost: float = 19000.0,
                 lifetime_years: int = 15):
        """
        Initialize electric heating appliance.
        
        Args:
            heating_type: Type of electric heating system (default: "heat_pump")
            base_cost: Base equipment and installation cost in dollars
            lifetime_years: Expected equipment lifetime in years
        """
        super().__init__(f"electric_{heating_type}", base_cost, lifetime_years)
        self.heating_type = heating_type
        
        # Add default incentives based on current California programs
        self._add_default_incentives()
    
    def _add_default_incentives(self) -> None:
        """Add default federal and state incentives for heat pumps."""
        # Federal tax credit (30% through 2032, then declining)
        federal_credit = Incentive(
            name="Federal Residential Clean Energy Credit",
            value=30.0,
            unit="%",
            max_value=2000.0,
            description="Federal tax credit for residential heat pumps (2023-2032)",
            source_url="https://www.irs.gov/credits-deductions/residential-clean-energy-credit"
        )
        self.add_incentive(federal_credit)
        
        # California TECH Clean California incentive
        ca_tech_incentive = Incentive(
            name="TECH Clean California HVAC Incentive",
            value=1500.0,
            unit="$",
            description="California incentive for single-family HVAC heat pump installation",
            source_url="https://incentives.switchison.org/rebate-profile/tech-clean-california-single-family-hvac"
        )
        self.add_incentive(ca_tech_incentive)
    
    def get_cost_breakdown(self, scenario: IncentiveScenario = IncentiveScenario.FULL_INCENTIVES) -> Dict:
        """Return detailed cost breakdown for electric heating appliance."""
        incentives_detail = []
        total_incentives = self.calculate_total_incentives(scenario)
        
        if scenario != IncentiveScenario.NO_INCENTIVES:
            multiplier = 1.0 if scenario == IncentiveScenario.FULL_INCENTIVES else 0.5
            
            for incentive in self.incentives:
                if incentive.unit == "%":
                    incentive_value = self.base_cost * (incentive.value / 100)
                    if incentive.max_value:
                        incentive_value = min(incentive_value, incentive.max_value)
                else:
                    incentive_value = incentive.value
                
                applied_value = incentive_value * multiplier
                
                incentives_detail.append({
                    "name": incentive.name,
                    "base_value": incentive_value,
                    "applied_value": applied_value,
                    "scenario_multiplier": multiplier
                })
        
        return {
            "appliance_type": self.name,
            "heating_type": self.heating_type,
            "base_cost": self.base_cost,
            "lifetime_years": self.lifetime_years,
            "scenario": scenario.value,
            "total_incentives": total_incentives,
            "net_cost": self.get_net_cost(scenario),
            "incentives_detail": incentives_detail,
            "cost_per_year": self.get_net_cost(scenario) / self.lifetime_years
        }
    
    def get_annual_cost_savings_needed_for_payback(self, 
                                                  target_payback_years: float,
                                                  scenario: IncentiveScenario = IncentiveScenario.FULL_INCENTIVES) -> float:
        """
        Calculate annual cost savings needed to achieve target payback period.
        
        Args:
            target_payback_years: Desired payback period in years
            scenario: Incentive scenario to use
            
        Returns:
            Required annual savings in dollars to achieve target payback
        """
        net_cost = self.get_net_cost(scenario)
        return net_cost / target_payback_years