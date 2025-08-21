from typing import Dict
from appliances.electric_base import ElectricAppliance, Incentive, IncentiveScenario

class ElectricVehicleAppliance(ElectricAppliance):
    def __init__(self, 
                 vehicle_type: str = "BEV", # assuming midsize SUV (tesla model Y) for now, other values may be found in the excel 
                 base_cost: float = 47500.0 + 1400.0, 
                    # https://www.energy.gov/sites/default/files/2022-12/2022.12.23%202022%20Incremental%20Purchase%20Cost%20Methodology%20and%20Results%20for%20Clean%20Vehicles.pdf
                    # https://www.itskrs.its.dot.gov/2020-sc00472 - L2 charger cost
                # charger_cost: float = 1400.0, # https://www.itskrs.its.dot.gov/2020-sc00472 - L2 charger cost
                 lifetime_years: int = 12, #between 12 and 15 https://afdc.energy.gov/files/u/publication/electric-drive_vehicles.pdf?46ed6d7f2c=
                 annual_maintenance_cost: float = 121.56, 
                    # https://theicct.org/wp-content/uploads/2021/06/EV-equity-feb2021.pdf - $/mile
                    # https://www.fhwa.dot.gov/policyinformation/statistics/2022/mv1.cfm - # of vehicles in CA
                    # https://www.fhwa.dot.gov/policyinformation/statistics/2022/vm2.cfm - # of miles driven in CA for all cars
                 annual_insurance_cost: float = 2040.0): # https://theicct.org/wp-content/uploads/2021/06/EV-equity-feb2021.pdf - monthly insurance cost for EVs in CA
        """
        Initialize electric vehicle appliance.
        
        Args:
            vehicle_type: Type of electric vehicle (default: "BEV" - Battery Electric Vehicle)
            base_cost: Base vehicle purchase cost in dollars
            lifetime_years: Expected vehicle ownership period in years
            annual_maintenance_cost: Annual maintenance cost in dollars
            annual_insurance_cost: Annual insurance cost in dollars
        """
        super().__init__(f"electric_{vehicle_type.lower()}", base_cost, lifetime_years)
        self.vehicle_type = vehicle_type
        self.annual_maintenance_cost = annual_maintenance_cost
        self.annual_insurance_cost = annual_insurance_cost
        
        # Add federal EV tax credit
        self._add_federal_ev_credit()

    def _add_federal_ev_credit(self) -> None:
        """Add federal Clean Vehicle Credit for electric vehicles."""
        self._add_federal_incentive(
            name="Federal Clean Vehicle Credit",
            value=7500.0,
            unit="$",
            description="Federal tax credit for new electric vehicles",
            source_url="https://www.irs.gov/credits-deductions/clean-vehicle-credits"
        )
        
        # # Federal Alternative Fuel Infrastructure Tax Credit for charging equipment.
        # alt_fuel_infra_credit = Incentive(
        #     name="Alternative Fuel Infrastructure Tax Credit",
        #     value=min(0.30 * charger_cost, 1000.0), # 30% of charger cost, max $1,000.
        #     unit="$",
        #     description="Federal tax credit for installing qualified EV charging equipment. Covers 30 percent of the cost, up to a maximum of $1,000.",
        #     source_url="https://afdc.energy.gov/laws/10513"
        # )
        # self.add_incentive(alt_fuel_infra_credit)
        
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
        
        annual_operating_cost = self.annual_maintenance_cost + self.annual_insurance_cost
        total_operating_cost = annual_operating_cost * self.lifetime_years
        
        return {
            "appliance_type": self.name,
            "vehicle_type": self.vehicle_type,
            "base_cost": self.base_cost,
            "lifetime_years": self.lifetime_years,
            "scenario": scenario.value,
            "total_incentives": total_incentives,
            "net_cost": self.get_net_cost(scenario),
            "incentives_detail": incentives_detail,
            "cost_per_year": self.get_net_cost(scenario) / self.lifetime_years,
            "annual_maintenance_cost": self.annual_maintenance_cost,
            "annual_insurance_cost": self.annual_insurance_cost,
            "annual_operating_cost": annual_operating_cost,
            "total_operating_cost_over_lifetime": total_operating_cost,
            "total_cost_of_ownership": self.get_net_cost(scenario) + total_operating_cost
        }