"""
Base electric appliance classes for residential electrification cost modeling.

This module defines the base classes used to model the capital costs, lifetime,
and incentives for electric appliances in residential electrification scenarios.
"""

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
    
    def _add_federal_incentive(self, name: str, value: float, unit: str, 
                              max_value: Optional[float] = None, description: str = "", 
                              source_url: str = "") -> None:
        """
        Add a federal incentive specific to this appliance type.
        
        Args:
            name: Name of the federal incentive
            value: Incentive value (percentage or dollar amount)
            unit: "$" for fixed amount, "%" for percentage
            max_value: Maximum incentive amount (for percentage-based incentives)
            description: Description of the incentive
            source_url: Source URL for the incentive information
        """
        federal_incentive = Incentive(
            name=name,
            value=value,
            unit=unit,
            max_value=max_value,
            description=description,
            source_url=source_url
        )
        self.incentives.append(federal_incentive)
    
    def add_incentive(self, incentive: Incentive) -> None:
        self.incentives.append(incentive)
    
    def calculate_total_incentives(self, scenario: IncentiveScenario = IncentiveScenario.FULL_INCENTIVES) -> float:
        if scenario == IncentiveScenario.NO_INCENTIVES:
            return 0.0
        
        total_incentives = 0.0
        multiplier = 1.0 if scenario == IncentiveScenario.FULL_INCENTIVES else 0.5
        
        # Calculate incentives from all sources
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