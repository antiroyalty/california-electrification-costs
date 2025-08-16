"""
Gas water heating appliance class for residential electrification cost modeling.

This module defines the GasWaterHeatingAppliance class used to model the capital costs
and lifetime for gas water heating systems in residential electrification scenarios.
"""

from typing import Dict
from appliances.gas_base import GasAppliance

class GasWaterHeatingAppliance(GasAppliance):
    """
    Class representing gas water heating appliances for home electrification cost comparisons.
    
    This class models the capital costs and lifetime for gas water heating systems
    to compare against electric alternatives in residential electrification scenarios.
    """
    
    def __init__(self, 
                 heater_type: str = "tank",
                 base_cost: float = 1500.0,
                 lifetime_years: int = 12,
                 efficiency: float = 0.83,
                 capacity_gallons: int = 55):
        """
        Initialize gas water heating appliance.
        
        Args:
            heater_type: Type of gas water heating system (default: "tank")
            base_cost: Base equipment and installation cost in dollars
            lifetime_years: Expected equipment lifetime in years
            efficiency: Gas water heater efficiency (typically ~83% AFUE)
            capacity_gallons: Water heater tank capacity in gallons
        """
        super().__init__(f"gas_{heater_type}_water_heater", base_cost, lifetime_years, efficiency)
        self.heater_type = heater_type
        self.capacity_gallons = capacity_gallons
    
    def get_cost_breakdown(self) -> Dict:
        """Return detailed cost breakdown for gas water heating appliance."""
        return {
            "appliance_type": self.name,
            "heater_type": self.heater_type,
            "capacity_gallons": self.capacity_gallons,
            "base_cost": self.base_cost,
            "net_cost": self.get_net_cost(),
            "lifetime_years": self.lifetime_years,
            "efficiency": self.efficiency,
            "annual_cost": self.get_annual_cost(),
            "has_incentives": False,
            "total_incentives": 0.0
        }
    
    def compare_to_heat_pump_water_heater(self, 
                                        heat_pump_net_cost: float,
                                        annual_gas_cost: float,
                                        annual_electricity_cost: float) -> Dict:
        """
        Compare gas water heating to heat pump water heater alternative.
        
        Args:
            heat_pump_net_cost: Net cost of heat pump water heater after incentives
            annual_gas_cost: Annual gas cost for water heating
            annual_electricity_cost: Annual electricity cost for heat pump water heating
            
        Returns:
            Dictionary with comparison analysis
        """
        annual_fuel_savings = annual_gas_cost - annual_electricity_cost
        payback_period = self.get_replacement_payback_period(heat_pump_net_cost, annual_fuel_savings)
        
        total_fuel_savings_over_lifetime = annual_fuel_savings * min(self.lifetime_years, 15)  # Assume 15-year comparison period
        net_benefit = total_fuel_savings_over_lifetime - heat_pump_net_cost
        
        return {
            "gas_water_heater_cost": self.base_cost,
            "gas_annual_cost": self.get_annual_cost(),
            "heat_pump_net_cost": heat_pump_net_cost,
            "annual_fuel_savings": annual_fuel_savings,
            "payback_period_years": payback_period,
            "total_fuel_savings_over_lifetime": total_fuel_savings_over_lifetime,
            "net_lifetime_benefit": net_benefit,
            "recommendation": "Switch to heat pump water heater" if net_benefit > 0 else "Keep gas water heater",
            "efficiency_comparison": {
                "gas_efficiency": self.efficiency,
                "heat_pump_cop": 3.25,  # Typical heat pump water heater COP from CARB data
                "efficiency_improvement": 3.25 / self.efficiency
            }
        }
    
    def get_annual_operating_cost_estimate(self, 
                                         annual_hot_water_therms: float = 200,
                                         gas_price_per_therm: float = 2.50) -> float:
        """
        Estimate annual operating costs for gas water heating.
        
        Args:
            annual_hot_water_therms: Annual gas consumption for water heating (default: 200 therms)
            gas_price_per_therm: Price per therm of natural gas (default: $2.50)
            
        Returns:
            Estimated annual gas cost for water heating
        """
        return annual_hot_water_therms * gas_price_per_therm
    
    def get_total_cost_of_ownership(self, 
                                   annual_hot_water_therms: float = 200,
                                   gas_price_per_therm: float = 2.50) -> Dict:
        """
        Calculate total cost of ownership including fuel costs.
        
        Args:
            annual_hot_water_therms: Annual gas consumption for water heating
            gas_price_per_therm: Price per therm of natural gas
            
        Returns:
            Dictionary with total cost of ownership analysis
        """
        annual_operating_cost = self.get_annual_operating_cost_estimate(annual_hot_water_therms, gas_price_per_therm)
        total_operating_cost = annual_operating_cost * self.lifetime_years
        total_cost_of_ownership = self.base_cost + total_operating_cost
        
        return {
            "base_cost": self.base_cost,
            "annual_operating_cost": annual_operating_cost,
            "total_operating_cost_over_lifetime": total_operating_cost,
            "total_cost_of_ownership": total_cost_of_ownership,
            "annual_hot_water_therms": annual_hot_water_therms,
            "gas_price_per_therm": gas_price_per_therm,
            "lifetime_years": self.lifetime_years
        }
    
    def get_carbon_footprint_comparison(self, 
                                      annual_hot_water_therms: float = 200,
                                      electricity_carbon_intensity: float = 0.28) -> Dict:
        """
        Compare carbon footprint of gas water heating vs electric heat pump water heater.
        
        Args:
            annual_hot_water_therms: Annual gas consumption for water heating
            electricity_carbon_intensity: kg CO2/kWh for electricity (CA grid ~0.28)
            
        Returns:
            Dictionary with carbon footprint comparison
        """
        # Natural gas combustion: ~5.3 kg CO2 per therm
        gas_annual_co2 = annual_hot_water_therms * 5.3
        
        # Heat pump water heater electricity usage (assuming 3.25 COP)
        # 1 therm = 29.3 kWh thermal energy
        # Heat pump electrical energy = thermal energy / COP
        heat_pump_annual_kwh = (annual_hot_water_therms * 29.3) / 3.25
        heat_pump_annual_co2 = heat_pump_annual_kwh * electricity_carbon_intensity
        
        co2_reduction = gas_annual_co2 - heat_pump_annual_co2
        
        return {
            "gas_annual_co2_kg": gas_annual_co2,
            "heat_pump_annual_co2_kg": heat_pump_annual_co2,
            "annual_co2_reduction_kg": co2_reduction,
            "annual_co2_reduction_percent": (co2_reduction / gas_annual_co2) * 100,
            "lifetime_co2_reduction_kg": co2_reduction * self.lifetime_years
        }
    
    def get_hot_water_usage_estimate(self, 
                                   household_size: int = 3,
                                   daily_gallons_per_person: float = 20) -> Dict:
        """
        Estimate hot water usage based on household characteristics.
        
        Args:
            household_size: Number of people in household
            daily_gallons_per_person: Average daily hot water usage per person in gallons
            
        Returns:
            Dictionary with hot water usage estimates
        """
        daily_gallons = household_size * daily_gallons_per_person
        annual_gallons = daily_gallons * 365
        
        # Convert to therms: assume ~8.3 lbs/gallon water, ~50°F temperature rise, 
        # ~1 BTU per lb per degree F, 100,000 BTU per therm
        btus_per_gallon = 8.3 * 50  # ~415 BTU/gallon
        annual_btus = annual_gallons * btus_per_gallon
        annual_therms = annual_btus / 100000
        
        return {
            "household_size": household_size,
            "daily_gallons_per_person": daily_gallons_per_person,
            "daily_total_gallons": daily_gallons,
            "annual_gallons": annual_gallons,
            "annual_therms": annual_therms,
            "btus_per_gallon": btus_per_gallon
        }