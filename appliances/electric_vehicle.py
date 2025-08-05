"""
Electric vehicle appliance class for residential electrification cost modeling.

This module defines the ElectricVehicleAppliance class used to model the capital costs,
lifetime, and incentives for electric vehicles that replace internal combustion engine
vehicles in residential electrification scenarios.
"""

from typing import Dict
from step15_build_capital_costs_lifetimes_incentives import ElectricAppliance, Incentive, IncentiveScenario

class ElectricVehicleAppliance(ElectricAppliance):
    """
    Class representing electric vehicles for home electrification.
    
    This class models the capital costs, lifetime, and incentives for electric
    vehicles that replace gasoline-powered vehicles in residential electrification scenarios.
    """
    
    def __init__(self, 
                 vehicle_type: str = "BEV",
                 base_cost: float = 42000.0,
                 lifetime_years: int = 12):
        """
        Initialize electric vehicle appliance.
        
        Args:
            vehicle_type: Type of electric vehicle (default: "BEV" - Battery Electric Vehicle)
            base_cost: Base vehicle purchase cost in dollars
            lifetime_years: Expected vehicle ownership period in years
        """
        super().__init__(f"electric_{vehicle_type.lower()}", base_cost, lifetime_years)
        self.vehicle_type = vehicle_type
        
        # Add default incentives based on current federal and California programs
        self._add_default_incentives()
    
    def _add_default_incentives(self) -> None:
        """Add default federal and state incentives for electric vehicles."""
        # Federal Clean Vehicle Credit (through September 2025)
        federal_credit = Incentive(
            name="Federal Clean Vehicle Credit",
            value=7500.0,
            unit="$",
            description="Federal tax credit for new electric vehicles (through Sept 2025)",
            source_url="https://www.irs.gov/credits-deductions/clean-vehicle-credits"
        )
        self.add_incentive(federal_credit)
        
        # California utility rebates (average across PG&E, SCE, SDG&E)
        ca_utility_rebate = Incentive(
            name="California Utility EV Rebate",
            value=3000.0,
            unit="$",
            description="California utility company electric vehicle rebates",
            source_url="https://www.cpuc.ca.gov/consumer-support/financial-assistance-savings-and-discounts/electric-vehicle-financial-assistance"
        )
        self.add_incentive(ca_utility_rebate)
    
    def get_cost_breakdown(self, scenario: IncentiveScenario = IncentiveScenario.FULL_INCENTIVES) -> Dict:
        """Return detailed cost breakdown for electric vehicle appliance."""
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
            "vehicle_type": self.vehicle_type,
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
    
    def get_total_cost_of_ownership(self, 
                                   annual_fuel_savings: float = 1500.0,
                                   annual_maintenance_savings: float = 400.0,
                                   scenario: IncentiveScenario = IncentiveScenario.FULL_INCENTIVES) -> Dict:
        """
        Calculate total cost of ownership including fuel and maintenance savings.
        
        Args:
            annual_fuel_savings: Annual savings from not buying gasoline (default: $1500)
            annual_maintenance_savings: Annual savings from reduced maintenance (default: $400)
            scenario: Incentive scenario to use
            
        Returns:
            Dictionary with total cost of ownership analysis
        """
        net_purchase_cost = self.get_net_cost(scenario)
        total_annual_savings = annual_fuel_savings + annual_maintenance_savings
        total_savings_over_lifetime = total_annual_savings * self.lifetime_years
        
        net_total_cost = net_purchase_cost - total_savings_over_lifetime
        
        return {
            "net_purchase_cost": net_purchase_cost,
            "annual_fuel_savings": annual_fuel_savings,
            "annual_maintenance_savings": annual_maintenance_savings,
            "total_annual_savings": total_annual_savings,
            "total_savings_over_lifetime": total_savings_over_lifetime,
            "net_total_cost_of_ownership": net_total_cost,
            "payback_period_years": net_purchase_cost / total_annual_savings if total_annual_savings > 0 else float('inf'),
            "lifetime_years": self.lifetime_years
        }