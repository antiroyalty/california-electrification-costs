"""
Electric water heating appliance class for residential electrification cost modeling.

This module defines the ElectricWaterHeatingAppliance class used to model the capital costs,
lifetime, and incentives for electric water heating systems that replace gas water heaters
in residential electrification scenarios.
"""

from typing import Dict, Optional
import os
import pandas as pd
from appliances.electric_base import ElectricAppliance, Incentive, IncentiveScenario

class ElectricWaterHeatingAppliance(ElectricAppliance):
    """
    Class representing electric water heating appliances for home electrification.
    
    This class models the capital costs, lifetime, and incentives for electric
    water heating systems that replace gas water heaters in residential electrification scenarios.
    """

    CONFIG_PATH = os.path.join(
        os.path.dirname(__file__), "..", "data", "electric_water_heating_costs.csv"
    )

    # Class-level cache of the DataFrame
    _CONFIG_DF: Optional[pd.DataFrame] = None
    
    def __init__(self, 
                 heater_type: str = "heat_pump",
                 base_cost: float = 2637.0,
                 lifetime_years: int = 15,
                 capacity_gallons: int = 55):
        """
        Initialize electric water heating appliance.
        
        Args:
            heater_type: Type of electric water heating system (default: "heat_pump")
            base_cost: Base equipment and installation cost in dollars
            lifetime_years: Expected equipment lifetime in years
            capacity_gallons: Water heater tank capacity in gallons
        """
        super().__init__(f"electric_{heater_type}_water_heater", base_cost, lifetime_years)
        self.heater_type = heater_type
        self.capacity_gallons = capacity_gallons
        self.county_slug: Optional[str] = None
        
        self._add_default_incentives()

    @classmethod
    def for_county(cls, county_slug: str, heater_type: str = "heat_pump") -> "ElectricWaterHeatingAppliance":
        """Factory: create a county-specific appliance instance using CSV config."""
        df = cls._load_config()
        if county_slug in df.index:
            row = df.loc[county_slug]
        else:
            row = df.loc["statewide"]  # fallback

        base_cost = float(row[CAPITAL_COST_COLUMN_NAME])

        inst = cls(heating_type=heating_type, base_cost=base_cost, lifetime_years=15)
        inst.county_slug = county_slug
        return inst

    def _load_config(cls) -> pd.DataFrame:
        """Load CSV once and cache as DataFrame indexed by county_slug."""
        if cls._CONFIG_DF is None:
            df = pd.read_csv(cls.CONFIG_PATH)
            df = df.set_index("county_slug")
            cls._CONFIG_DF = df
        return cls._CONFIG_DF
    
    def _add_default_incentives(self) -> None:
        """Add default federal and state incentives for electric water heaters."""
        # Federal tax credit for heat pump water heaters (30% through 2032)
        federal_credit = Incentive(
            name="Federal Residential Clean Energy Credit",
            value=30.0,
            unit="%",
            max_value=2000.0,
            description="Federal tax credit for residential heat pump water heaters (2023-2032)",
            source_url="https://www.irs.gov/credits-deductions/residential-clean-energy-credit"
        )
        self.add_incentive(federal_credit)
        
        # California rebate for heat pump water heaters
        ca_rebate = Incentive(
            name="California Heat Pump Water Heater Rebate",
            value=700.0,
            unit="$",
            description="California rebate for heat pump water heaters (45-55 gallon capacity)",
            source_url="https://incentives.switchison.org/residents/incentives"
        )
        self.add_incentive(ca_rebate)
    
    def get_cost_breakdown(self, scenario: IncentiveScenario = IncentiveScenario.FULL_INCENTIVES) -> Dict:
        """Return detailed cost breakdown for electric water heating appliance."""
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
            "heater_type": self.heater_type,
            "capacity_gallons": self.capacity_gallons,
            "base_cost": self.base_cost,
            "lifetime_years": self.lifetime_years,
            "scenario": scenario.value,
            "total_incentives": total_incentives,
            "net_cost": self.get_net_cost(scenario),
            "incentives_detail": incentives_detail,
            "cost_per_year": self.get_net_cost(scenario) / self.lifetime_years
        }