from typing import Dict

class ICEVehicleAppliance:
    def __init__(self, 
                 vehicle_type: str = "ICE",
                 base_cost: float = 35000.0,
                 lifetime_years: int = 12,
                 fuel_efficiency_mpg: float = 28.0,
                 annual_maintenance_cost: float = 1200.0,
                 annual_insurance_cost: float = 2000.0):
        """
        Initialize ICE vehicle appliance.
        
        Args:
            vehicle_type: Type of ICE vehicle (default: "ICE")
            base_cost: Base vehicle purchase cost in dollars
            lifetime_years: Expected vehicle ownership period in years
            fuel_efficiency_mpg: Vehicle fuel efficiency in miles per gallon
            annual_maintenance_cost: Annual maintenance cost in dollars
            annual_insurance_cost: Annual insurance cost in dollars
        """
        self.name = f"ice_{vehicle_type.lower()}"
        self.vehicle_type = vehicle_type
        self.base_cost = base_cost
        self.lifetime_years = lifetime_years
        self.fuel_efficiency_mpg = fuel_efficiency_mpg
        self.annual_maintenance_cost = annual_maintenance_cost
        self.annual_insurance_cost = annual_insurance_cost
    
    def get_net_cost(self) -> float:
        """Return net cost (same as base cost since ICE vehicles typically have no incentives)."""
        return self.base_cost
    
    def get_annual_cost(self) -> float:
        """Return annualized cost over the vehicle lifetime."""
        return self.base_cost / self.lifetime_years

    
    def get_annual_operating_cost_estimate(self, 
                                         county_name: str,
                                         annual_maintenance_cost: float = 1200.0) -> float:
        """
        Estimate annual operating costs for ICE vehicle using county-specific data.
        
        Args:
            county_name: County name for location-specific costs and VMT
            annual_maintenance_cost: Annual maintenance cost (default: $1,200)
            
        Returns:
            Estimated annual operating cost for ICE vehicle
        """
        from helpers.gasoline_cost_helper import calculate_annual_fuel_cost
        fuel_data = calculate_annual_fuel_cost(county_name, self.fuel_efficiency_mpg)
        annual_fuel_cost = fuel_data['annual_fuel_cost']
        
        return annual_fuel_cost + annual_maintenance_cost
    
    def get_cost_breakdown(self) -> Dict:
        """Return detailed cost breakdown for ICE vehicle."""
        annual_operating_cost = self.annual_maintenance_cost + self.annual_insurance_cost
        total_operating_cost = annual_operating_cost * self.lifetime_years
        
        return {
            "appliance_type": self.name,
            "vehicle_type": self.vehicle_type,
            "base_cost": self.base_cost,
            "net_cost": self.get_net_cost(),
            "lifetime_years": self.lifetime_years,
            "fuel_efficiency_mpg": self.fuel_efficiency_mpg,
            "annual_cost": self.get_annual_cost(),
            "has_incentives": False,
            "total_incentives": 0.0,
            "annual_maintenance_cost": self.annual_maintenance_cost,
            "annual_insurance_cost": self.annual_insurance_cost,
            "annual_operating_cost": annual_operating_cost,
            "total_operating_cost_over_lifetime": total_operating_cost,
            "total_cost_of_ownership": self.base_cost + total_operating_cost
        }