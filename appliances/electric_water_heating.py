"""
Electric water heating appliance class for residential electrification cost modeling.

This module defines the ElectricWaterHeatingAppliance class used to model the capital costs,
lifetime, and incentives for electric water heating systems that replace gas water heaters
in residential electrification scenarios.
"""

from typing import Dict
from step15_build_capital_costs_lifetimes_incentives import ElectricAppliance, Incentive, IncentiveScenario

class ElectricWaterHeatingAppliance(ElectricAppliance):
    """
    Class representing electric water heating appliances for home electrification.
    
    This class models the capital costs, lifetime, and incentives for electric
    water heating systems that replace gas water heaters in residential electrification scenarios.
    """
    
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
        
        # Add default incentives based on current California programs
        self._add_default_incentives()
    
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
    
    def get_efficiency_comparison(self) -> Dict:
        """
        Compare efficiency of heat pump water heater vs gas water heater.
        
        Returns:
            Dictionary with efficiency comparison data
        """
        return {
            "heat_pump_cop": 3.25,  # From CARB data
            "gas_efficiency": 0.83,  # 83% efficiency for gas water heaters
            "efficiency_improvement": 3.25 / 0.83,  # ~3.9x improvement
            "energy_source": {
                "heat_pump": "electricity",
                "gas": "natural_gas"
            }
        }
    
    def get_operating_cost_estimate(self, 
                                   annual_hot_water_usage_therms: float = 200,
                                   gas_price_per_therm: float = 2.50,
                                   electricity_price_per_kwh: float = 0.25) -> Dict:
        """
        Estimate annual operating costs for heat pump water heater vs gas.
        
        Args:
            annual_hot_water_usage_therms: Annual thermal energy for hot water (default: 200 therms)
            gas_price_per_therm: Price per therm of natural gas (default: $2.50)
            electricity_price_per_kwh: Price per kWh of electricity (default: $0.25)
            
        Returns:
            Dictionary with operating cost comparison
        """
        # Gas water heater cost (at 83% efficiency)
        gas_annual_cost = annual_hot_water_usage_therms * gas_price_per_therm
        
        # Heat pump water heater cost (COP = 3.25)
        # 1 therm = 29.3 kWh thermal energy
        # Electric energy = thermal energy / COP
        thermal_energy_kwh = annual_hot_water_usage_therms * 29.3
        electric_energy_kwh = thermal_energy_kwh / 3.25
        heat_pump_annual_cost = electric_energy_kwh * electricity_price_per_kwh
        
        annual_savings = gas_annual_cost - heat_pump_annual_cost
        
        return {
            "gas_annual_cost": gas_annual_cost,
            "heat_pump_annual_cost": heat_pump_annual_cost,
            "annual_savings": annual_savings,
            "thermal_energy_kwh": thermal_energy_kwh,
            "electric_energy_kwh": electric_energy_kwh,
            "gas_price_per_therm": gas_price_per_therm,
            "electricity_price_per_kwh": electricity_price_per_kwh
        }