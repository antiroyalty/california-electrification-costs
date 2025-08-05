"""
Base gas appliance class for residential gas appliance cost modeling.

This module defines the base GasAppliance class used to model the capital costs
and lifetime for gas appliances in residential electrification scenario comparisons.
Unlike electric appliances, gas appliances typically don't have rebates or incentives.
"""

from typing import Dict
from abc import ABC, abstractmethod

class GasAppliance(ABC):
    """Abstract base class for gas appliances used in home electrification cost comparisons."""
    
    def __init__(self, name: str, base_cost: float, lifetime_years: int, efficiency: float = 1.0):
        self.name = name
        self.base_cost = base_cost
        self.lifetime_years = lifetime_years
        self.efficiency = efficiency  # Gas appliances typically have efficiency < 1.0
    
    def get_net_cost(self) -> float:
        """Return net cost (same as base cost since gas appliances typically have no incentives)."""
        return self.base_cost
    
    def get_annual_cost(self) -> float:
        """Return annualized cost over the appliance lifetime."""
        return self.base_cost / self.lifetime_years
    
    @abstractmethod
    def get_cost_breakdown(self) -> Dict:
        """Return detailed cost breakdown for gas appliance."""
        pass
    
    def get_annual_cost_premium_vs_electric(self, 
                                          electric_annual_cost: float) -> float:
        """
        Calculate annual cost difference compared to electric alternative.
        
        Args:
            electric_annual_cost: Annual cost of electric alternative
            
        Returns:
            Annual cost premium (positive means gas is more expensive annually)
        """
        return self.get_annual_cost() - electric_annual_cost
    
    def get_replacement_payback_period(self, 
                                     electric_net_cost: float,
                                     annual_fuel_savings: float) -> float:
        """
        Calculate payback period for replacing this gas appliance with electric alternative.
        
        Args:
            electric_net_cost: Net cost of electric replacement after incentives
            annual_fuel_savings: Annual savings from switching to electric
            
        Returns:
            Payback period in years for electric replacement
        """
        if annual_fuel_savings <= 0:
            return float('inf')
        
        return electric_net_cost / annual_fuel_savings