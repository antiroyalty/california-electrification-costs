"""
Electric cooking appliance class for residential electrification cost modeling.

This module defines the ElectricCookingAppliance class used to model the capital costs,
lifetime, and incentives for electric cooking systems that replace gas stoves
in residential electrification scenarios.
"""

from typing import Dict
from appliances.electric_base import ElectricAppliance, Incentive, IncentiveScenario

class ElectricCookingAppliance(ElectricAppliance):
    """
    Class representing electric cooking appliances for home electrification.
    
    This class models the capital costs, lifetime, and incentives for electric
    cooking systems that replace gas stoves in residential electrification scenarios.
    """
    
    def __init__(self, 
                 cooking_type: str = "induction",
                 base_cost: float = 2000.0,
                 lifetime_years: int = 15):
        """
        Initialize electric cooking appliance.
        
        Args:
            cooking_type: Type of electric cooking system (default: "induction")
            base_cost: Base equipment and installation cost in dollars
            lifetime_years: Expected equipment lifetime in years
        """
        super().__init__(f"electric_{cooking_type}_cooking", base_cost, lifetime_years)
        self.cooking_type = cooking_type
        
        # Add default incentives based on current California programs
        self._add_default_incentives()
    
    def _add_default_incentives(self) -> None:
        # Federal tax credit for electric cooking appliances (Inflation Reduction Act)
        federal_credit = Incentive(
            name="Federal Residential Electrification Rebate",
            value=420.0,
            unit="$",
            description="Federal rebate for residential electric cooking appliances under Inflation Reduction Act",
            source_url="https://www.geappliances.com/inflation-reduction-act"
        )
        self.add_incentive(federal_credit)
    
    def get_cost_breakdown(self, scenario: IncentiveScenario = IncentiveScenario.FULL_INCENTIVES) -> Dict:
        """Return detailed cost breakdown for electric cooking appliance."""
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
            "cooking_type": self.cooking_type,
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