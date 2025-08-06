class ICEVehicleAppliance:
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