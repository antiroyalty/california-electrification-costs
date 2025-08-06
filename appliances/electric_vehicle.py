from typing import Dict
from step15_build_capital_costs_lifetimes_incentives import ElectricAppliance, Incentive, IncentiveScenario

class ElectricVehicleAppliance(ElectricAppliance):
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