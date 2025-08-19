"""
Zero cost appliance class for residential electrification cost modeling.

This module defines the ZeroCostAppliance class used to model appliances with
no capital costs in residential electrification scenarios. This can be useful
for modeling scenarios where appliances are provided at no cost through
incentive programs or for theoretical analysis.
"""

from typing import Dict
from appliances.electric_base import ElectricAppliance, IncentiveScenario


class ZeroCostAppliance(ElectricAppliance):
    """
    Class representing zero-cost appliances for home electrification scenarios.
    
    This class models appliances that have no capital costs, which can be useful
    for modeling scenarios where appliances are provided through incentive programs
    or for theoretical analysis of operating costs only.
    """
    
    def __init__(self, 
                 name: str = "zero_cost",
                 lifetime_years: int = 15):
        """
        Initialize zero cost appliance.
        
        Args:
            name: Name of the appliance (used in step14)
            lifetime_years: Expected equipment lifetime in years
        """
        super().__init__(f"zero_cost_{name}", 0.0, lifetime_years)
        self.appliance_type = name
    
    def get_cost_breakdown(self, scenario: IncentiveScenario = IncentiveScenario.FULL_INCENTIVES) -> Dict:
        """Return detailed cost breakdown for zero cost appliance."""
        return {
            "appliance_type": self.name,
            "appliance_category": self.appliance_type,
            "base_cost": self.base_cost,
            "lifetime_years": self.lifetime_years,
            "scenario": scenario.value,
            "total_incentives": 0.0,
            "net_cost": 0.0,
            "incentives_detail": [],
            "cost_per_year": 0.0
        }