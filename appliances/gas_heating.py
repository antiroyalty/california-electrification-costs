"""
Gas heating appliance class for residential electrification cost modeling.

This module defines the GasHeatingAppliance class used to model the capital costs
and lifetime for gas heating systems in residential electrification scenarios.
"""

from typing import Dict
from appliances.gas_base import GasAppliance

class GasHeatingAppliance(GasAppliance):
    """
    Class representing gas heating appliances for home electrification cost comparisons.
    
    This class models the capital costs and lifetime for gas heating systems
    to compare against electric alternatives in residential electrification scenarios.
    """
    
    def __init__(self, 
                 heating_type: str = "furnace",
                 base_cost: float = 9771.3,
                 lifetime_years: int = 15,
                 efficiency: float = 0.83):
        """
        Initialize gas heating appliance.
        
        Args:
            heating_type: Type of gas heating system (default: "furnace")
            base_cost: Base equipment and installation cost in dollars
            lifetime_years: Expected equipment lifetime in years
            efficiency: Gas furnace efficiency (typically ~83% AFUE)
        """
        super().__init__(f"gas_{heating_type}", base_cost, lifetime_years, efficiency)
        self.heating_type = heating_type
    
    def get_cost_breakdown(self) -> Dict:
        """Return detailed cost breakdown for gas heating appliance."""
        return {
            "appliance_type": self.name,
            "heating_type": self.heating_type,
            "base_cost": self.base_cost,
            "net_cost": self.get_net_cost(),
            "lifetime_years": self.lifetime_years,
            "efficiency": self.efficiency,
            "annual_cost": self.get_annual_cost(),
            "has_incentives": False,
            "total_incentives": 0.0
        }
    
    def compare_to_heat_pump(self, 
                           heat_pump_net_cost: float,
                           annual_gas_cost: float,
                           annual_electricity_cost: float) -> Dict:
        """
        Compare gas heating to heat pump alternative.
        
        Args:
            heat_pump_net_cost: Net cost of heat pump after incentives
            annual_gas_cost: Annual gas cost for heating
            annual_electricity_cost: Annual electricity cost for heat pump heating
            
        Returns:
            Dictionary with comparison analysis
        """
        annual_fuel_savings = annual_gas_cost - annual_electricity_cost
        payback_period = self.get_replacement_payback_period(heat_pump_net_cost, annual_fuel_savings)
        
        total_fuel_savings_over_lifetime = annual_fuel_savings * min(self.lifetime_years, 15)  # Assume 15-year comparison period
        net_benefit = total_fuel_savings_over_lifetime - heat_pump_net_cost
        
        return {
            "gas_heating_cost": self.base_cost,
            "gas_annual_cost": self.get_annual_cost(),
            "heat_pump_net_cost": heat_pump_net_cost,
            "annual_fuel_savings": annual_fuel_savings,
            "payback_period_years": payback_period,
            "total_fuel_savings_over_lifetime": total_fuel_savings_over_lifetime,
            "net_lifetime_benefit": net_benefit,
            "recommendation": "Switch to heat pump" if net_benefit > 0 else "Keep gas heating",
            "efficiency_comparison": {
                "gas_efficiency": self.efficiency,
                "heat_pump_cop": 3.375,  # Typical heat pump COP from CARB data
                "efficiency_improvement": 3.375 / self.efficiency
            }
        }
    
    def get_annual_operating_cost_estimate(self, 
                                         annual_therms: float = 600,
                                         gas_price_per_therm: float = 2.50) -> float:
        """
        Estimate annual operating costs for gas heating.
        
        Args:
            annual_therms: Annual gas consumption for heating (default: 600 therms)
            gas_price_per_therm: Price per therm of natural gas (default: $2.50)
            
        Returns:
            Estimated annual gas cost for heating
        """
        return annual_therms * gas_price_per_therm
    
    def get_total_cost_of_ownership(self, 
                                   annual_therms: float = 600,
                                   gas_price_per_therm: float = 2.50) -> Dict:
        """
        Calculate total cost of ownership including fuel costs.
        
        Args:
            annual_therms: Annual gas consumption for heating
            gas_price_per_therm: Price per therm of natural gas
            
        Returns:
            Dictionary with total cost of ownership analysis
        """
        annual_operating_cost = self.get_annual_operating_cost_estimate(annual_therms, gas_price_per_therm)
        total_operating_cost = annual_operating_cost * self.lifetime_years
        total_cost_of_ownership = self.base_cost + total_operating_cost
        
        return {
            "base_cost": self.base_cost,
            "annual_operating_cost": annual_operating_cost,
            "total_operating_cost_over_lifetime": total_operating_cost,
            "total_cost_of_ownership": total_cost_of_ownership,
            "annual_therms": annual_therms,
            "gas_price_per_therm": gas_price_per_therm,
            "lifetime_years": self.lifetime_years
        }
    
    def get_carbon_footprint_comparison(self, 
                                      annual_therms: float = 600,
                                      electricity_carbon_intensity: float = 0.28) -> Dict:
        """
        Compare carbon footprint of gas heating vs electric heat pump.
        
        Args:
            annual_therms: Annual gas consumption for heating
            electricity_carbon_intensity: kg CO2/kWh for electricity (CA grid ~0.28)
            
        Returns:
            Dictionary with carbon footprint comparison
        """
        # Natural gas combustion: ~5.3 kg CO2 per therm
        gas_annual_co2 = annual_therms * 5.3
        
        # Heat pump electricity usage (assuming 3.375 COP)
        # 1 therm = 29.3 kWh thermal energy
        # Heat pump electrical energy = thermal energy / COP
        heat_pump_annual_kwh = (annual_therms * 29.3) / 3.375
        heat_pump_annual_co2 = heat_pump_annual_kwh * electricity_carbon_intensity
        
        co2_reduction = gas_annual_co2 - heat_pump_annual_co2
        
        return {
            "gas_annual_co2_kg": gas_annual_co2,
            "heat_pump_annual_co2_kg": heat_pump_annual_co2,
            "annual_co2_reduction_kg": co2_reduction,
            "annual_co2_reduction_percent": (co2_reduction / gas_annual_co2) * 100,
            "lifetime_co2_reduction_kg": co2_reduction * self.lifetime_years
        }