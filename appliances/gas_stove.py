from typing import Dict
from appliances.gas_base import GasAppliance

class GasStoveAppliance(GasAppliance):
    def __init__(self,
                 stove_type: str = "gas",
                 base_cost: float = 2802.14,
                 lifetime_years: int = 15,
                 efficiency: float = 0.45):
        """
        Initialize gas stove appliance.

        Args:
            stove_type: Type of gas cooking system (default: "gas")
            base_cost: Base equipment and installation cost in dollars.
                CARB appliance comparison data ("Cristina's approach" — see Simon
                La Vieille, "EV Integration to Ana's Project," Aug 2025): capital
                $1,600 + installation $890 + other $220 = $2,710 (2022), inflated
                3.4% CPI-U to 2023 = $2,802.14.
            lifetime_years: Expected equipment lifetime in years
            efficiency: Gas stove efficiency (typically ~45% for cooking)
        """
        super().__init__(f"gas_{stove_type}_stove", base_cost, lifetime_years, efficiency)
        self.stove_type = stove_type
    
    def get_cost_breakdown(self) -> Dict:
        return {
            "appliance_type": self.name,
            "stove_type": self.stove_type,
            "base_cost": self.base_cost,
            "net_cost": self.get_net_cost(),
            "lifetime_years": self.lifetime_years,
            "efficiency": self.efficiency,
            "annual_cost": self.get_annual_cost(),
            "has_incentives": False,
            "total_incentives": 0.0
        }
    
    def compare_to_induction(self, 
                           induction_net_cost: float,
                           annual_gas_cost: float,
                           annual_electricity_cost: float) -> Dict:
        """
        Compare gas stove to induction stove alternative.
        
        Args:
            induction_net_cost: Net cost of induction stove after incentives
            annual_gas_cost: Annual gas cost for cooking
            annual_electricity_cost: Annual electricity cost for induction cooking
            
        Returns:
            Dictionary with comparison analysis
        """
        annual_fuel_savings = annual_gas_cost - annual_electricity_cost
        payback_period = self.get_replacement_payback_period(induction_net_cost, annual_fuel_savings)
        
        total_fuel_savings_over_lifetime = annual_fuel_savings * min(self.lifetime_years, 15)  # Assume 15-year comparison period
        net_benefit = total_fuel_savings_over_lifetime - induction_net_cost
        
        return {
            "gas_stove_cost": self.base_cost,
            "gas_annual_cost": self.get_annual_cost(),
            "induction_net_cost": induction_net_cost,
            "annual_fuel_savings": annual_fuel_savings,
            "payback_period_years": payback_period,
            "total_fuel_savings_over_lifetime": total_fuel_savings_over_lifetime,
            "net_lifetime_benefit": net_benefit,
            "recommendation": "Switch to induction" if net_benefit > 0 else "Keep gas stove",
            "efficiency_comparison": {
                "gas_efficiency": self.efficiency,
                "induction_efficiency": 0.85,  # Typical induction efficiency
                "efficiency_improvement": 0.85 / self.efficiency
            }
        }
    
    def get_annual_operating_cost_estimate(self, 
                                         annual_therms: float = 25,
                                         gas_price_per_therm: float = 2.50) -> float:
        return annual_therms * gas_price_per_therm
    
    def get_total_cost_of_ownership(self, 
                                   annual_therms: float = 25,
                                   gas_price_per_therm: float = 2.50) -> Dict:
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