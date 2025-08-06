"""
ICE (Internal Combustion Engine) vehicle appliance class for residential electrification cost modeling.

This module defines the ICEVehicleAppliance class used to model the capital costs
and lifetime for gasoline-powered vehicles in residential electrification scenarios.
"""

from typing import Dict
from abc import ABC

class ICEVehicleAppliance:
    """
    Class representing ICE vehicles for home electrification cost comparisons.
    
    This class models the capital costs and lifetime for internal combustion engine
    vehicles to compare against electric alternatives in residential electrification scenarios.
    """
    
    def __init__(self, 
                 vehicle_type: str = "ICE",
                 base_cost: float = 35000.0,
                 lifetime_years: int = 12,
                 fuel_efficiency_mpg: float = 28.0):
        """
        Initialize ICE vehicle appliance.
        
        Args:
            vehicle_type: Type of ICE vehicle (default: "ICE")
            base_cost: Base vehicle purchase cost in dollars
            lifetime_years: Expected vehicle ownership period in years
            fuel_efficiency_mpg: Vehicle fuel efficiency in miles per gallon
        """
        self.name = f"ice_{vehicle_type.lower()}"
        self.vehicle_type = vehicle_type
        self.base_cost = base_cost
        self.lifetime_years = lifetime_years
        self.fuel_efficiency_mpg = fuel_efficiency_mpg
    
    def get_net_cost(self) -> float:
        """Return net cost (same as base cost since ICE vehicles typically have no incentives)."""
        return self.base_cost
    
    def get_annual_cost(self) -> float:
        """Return annualized cost over the vehicle lifetime."""
        return self.base_cost / self.lifetime_years
    
    def get_cost_breakdown(self) -> Dict:
        """Return detailed cost breakdown for ICE vehicle."""
        return {
            "appliance_type": self.name,
            "vehicle_type": self.vehicle_type,
            "base_cost": self.base_cost,
            "net_cost": self.get_net_cost(),
            "lifetime_years": self.lifetime_years,
            "fuel_efficiency_mpg": self.fuel_efficiency_mpg,
            "annual_cost": self.get_annual_cost(),
            "has_incentives": False,
            "total_incentives": 0.0
        }
    
    def compare_to_electric_vehicle(self, 
                                  ev_net_cost: float,
                                  annual_fuel_cost: float,
                                  annual_electricity_cost: float,
                                  annual_maintenance_cost_ice: float = 1200.0,
                                  annual_maintenance_cost_ev: float = 800.0) -> Dict:
        """
        Compare ICE vehicle to electric vehicle alternative.
        
        Args:
            ev_net_cost: Net cost of electric vehicle after incentives
            annual_fuel_cost: Annual gasoline cost for ICE vehicle
            annual_electricity_cost: Annual electricity cost for EV charging
            annual_maintenance_cost_ice: Annual maintenance cost for ICE vehicle
            annual_maintenance_cost_ev: Annual maintenance cost for EV
            
        Returns:
            Dictionary with comparison analysis
        """
        annual_operating_savings = (annual_fuel_cost + annual_maintenance_cost_ice) - (annual_electricity_cost + annual_maintenance_cost_ev)
        purchase_price_difference = ev_net_cost - self.base_cost
        
        if annual_operating_savings > 0:
            payback_period = purchase_price_difference / annual_operating_savings
        else:
            payback_period = float('inf')
        
        total_operating_savings_over_lifetime = annual_operating_savings * self.lifetime_years
        net_benefit = total_operating_savings_over_lifetime - purchase_price_difference
        
        return {
            "ice_vehicle_cost": self.base_cost,
            "ice_annual_cost": self.get_annual_cost(),
            "ev_net_cost": ev_net_cost,
            "purchase_price_difference": purchase_price_difference,
            "annual_fuel_savings": annual_fuel_cost - annual_electricity_cost,
            "annual_maintenance_savings": annual_maintenance_cost_ice - annual_maintenance_cost_ev,
            "total_annual_operating_savings": annual_operating_savings,
            "payback_period_years": payback_period,
            "total_operating_savings_over_lifetime": total_operating_savings_over_lifetime,
            "net_lifetime_benefit": net_benefit,
            "recommendation": "Switch to electric vehicle" if net_benefit > 0 else "Keep ICE vehicle"
        }
    
    def get_annual_operating_cost_estimate(self, 
                                         annual_miles: float = 12000,
                                         gas_price_per_gallon: float = 4.50,
                                         annual_maintenance_cost: float = 1200.0) -> float:
        """
        Estimate annual operating costs for ICE vehicle.
        
        Args:
            annual_miles: Annual miles driven (default: 12,000)
            gas_price_per_gallon: Price per gallon of gasoline (default: $4.50)
            annual_maintenance_cost: Annual maintenance cost (default: $1,200)
            
        Returns:
            Estimated annual operating cost for ICE vehicle
        """
        annual_fuel_cost = (annual_miles / self.fuel_efficiency_mpg) * gas_price_per_gallon
        return annual_fuel_cost + annual_maintenance_cost
    
    def get_total_cost_of_ownership(self, 
                                   annual_miles: float = 12000,
                                   gas_price_per_gallon: float = 4.50,
                                   annual_maintenance_cost: float = 1200.0) -> Dict:
        """
        Calculate total cost of ownership including fuel and maintenance costs.
        
        Args:
            annual_miles: Annual miles driven
            gas_price_per_gallon: Price per gallon of gasoline
            annual_maintenance_cost: Annual maintenance cost
            
        Returns:
            Dictionary with total cost of ownership analysis
        """
        annual_fuel_cost = (annual_miles / self.fuel_efficiency_mpg) * gas_price_per_gallon
        annual_operating_cost = annual_fuel_cost + annual_maintenance_cost
        total_operating_cost = annual_operating_cost * self.lifetime_years
        total_cost_of_ownership = self.base_cost + total_operating_cost
        
        return {
            "base_cost": self.base_cost,
            "annual_fuel_cost": annual_fuel_cost,
            "annual_maintenance_cost": annual_maintenance_cost,
            "annual_operating_cost": annual_operating_cost,
            "total_operating_cost_over_lifetime": total_operating_cost,
            "total_cost_of_ownership": total_cost_of_ownership,
            "annual_miles": annual_miles,
            "gas_price_per_gallon": gas_price_per_gallon,
            "fuel_efficiency_mpg": self.fuel_efficiency_mpg,
            "lifetime_years": self.lifetime_years
        }
    
    def get_carbon_footprint_estimate(self, 
                                    annual_miles: float = 12000,
                                    co2_per_gallon: float = 19.6) -> Dict:
        """
        Estimate carbon footprint of ICE vehicle.
        
        Args:
            annual_miles: Annual miles driven
            co2_per_gallon: kg CO2 per gallon of gasoline (default: 19.6 kg)
            
        Returns:
            Dictionary with carbon footprint analysis
        """
        annual_gallons = annual_miles / self.fuel_efficiency_mpg
        annual_co2_kg = annual_gallons * co2_per_gallon
        lifetime_co2_kg = annual_co2_kg * self.lifetime_years
        
        return {
            "annual_miles": annual_miles,
            "annual_gallons": annual_gallons,
            "annual_co2_kg": annual_co2_kg,
            "lifetime_co2_kg": lifetime_co2_kg,
            "fuel_efficiency_mpg": self.fuel_efficiency_mpg,
            "co2_per_gallon": co2_per_gallon
        }