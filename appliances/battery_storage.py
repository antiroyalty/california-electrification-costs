"""
Battery Storage Appliance Class for Capital Cost Analysis
"""

from typing import Dict
from appliances.electric_base import ElectricAppliance, Incentive, IncentiveScenario

class BatteryStorageAppliance(ElectricAppliance):
    """Battery storage system (Tesla Powerwall 3)."""
    
    def __init__(self, num_units: int = 1, lifetime_years: int = 15):
        # https://atb.nrel.gov/electricity/2024/data ATB data used by CEC report https://www.energy.ca.gov/sites/default/files/2024-07/CEC-200-2024-011.pdf
        base_unit_cost = 18258  # $18,258 per unit (2023 value)
        capacity_per_unit = 12.5  # 12.5 kWh per unit
        
        total_cost = base_unit_cost * num_units
        total_capacity = capacity_per_unit * num_units
        
        super().__init__(f"battery_storage_{num_units}units", total_cost, lifetime_years)
        
        self.num_units = num_units
        self.unit_cost = base_unit_cost
        self.capacity_kwh = total_capacity
        
        # Add federal storage tax credit (30% through 2032, for systems >= 3 kWh)
        if total_capacity >= 3.0:
            federal_tax_credit = Incentive(
                name="federal_storage_tax_credit",
                value=30.0,  # 30%
                unit="%",
                description="Federal energy storage investment tax credit (ITC) 30% for systems >= 3 kWh",
                source_url="https://www.energy.gov/eere/solar/homeowners-guide-federal-tax-credit-solar-photovoltaics"
            )
            self.add_incentive(federal_tax_credit)

    @classmethod
    def per_kwh_cost(cls) -> float:
        """Gross (pre-incentive) $/kWh, derived from the same unit economics as
        every other capex figure for this appliance — the single number any
        caller (the LP's sizing objective, step14's reporting) should use for
        battery cost per kWh, so sizing and reporting can't silently diverge."""
        unit = cls(num_units=1)
        return unit.base_cost / unit.capacity_kwh

    def get_cost_breakdown(self, scenario: IncentiveScenario = IncentiveScenario.FULL_INCENTIVES) -> Dict:
        """Return detailed cost breakdown for battery storage."""
        total_incentives = self.calculate_total_incentives(scenario)
        net_cost = self.get_net_cost(scenario)
        
        return {
            "appliance_name": self.name,
            "num_units": self.num_units,
            "capacity_kwh": self.capacity_kwh,
            "unit_cost": self.unit_cost,
            "base_cost": self.base_cost,
            "total_incentives": total_incentives,
            "net_cost": net_cost,
            "lifetime_years": self.lifetime_years,
            "cost_per_kwh": net_cost / self.capacity_kwh if self.capacity_kwh > 0 else 0,
            "incentive_scenario": scenario.value
        }