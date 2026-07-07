"""
Solar System Appliance Class for Capital Cost Analysis
"""

from typing import Dict, Optional
from appliances.electric_base import ElectricAppliance, Incentive, IncentiveScenario

class SolarSystemAppliance(ElectricAppliance):
    """Solar panel system with sizing based on capacity in kW."""
    
    def __init__(self, capacity_kw: float, lifetime_years: int = 25):
        # Solar panel specifications (2025 pricing)
        dollars_per_watt = 3.3  # $3.3/W https://docs.cpuc.ca.gov/PublishedDocs/Published/G000/M499/K921/499921246.PDF 2023
        installation_markup = 0.0  # 0% installation markup
        design_markup = 0.0  # 0% design/engineering markup
        
        # Calculate total solar cost
        panel_cost = capacity_kw * 1000 * dollars_per_watt  # Convert kW to W
        total_cost = panel_cost * (1 + installation_markup + design_markup)
        
        super().__init__(f"solar_system_{capacity_kw}kW", total_cost, lifetime_years)
        
        self.capacity_kw = capacity_kw
        self.panel_cost = panel_cost
        
        # Add federal solar tax credit (30% through 2032)
        federal_tax_credit = Incentive(
            name="federal_solar_tax_credit",
            value=30.0,  # 30%
            unit="%",
            description="Federal solar investment tax credit (ITC) 30% through 2032",
            source_url="https://www.energy.gov/eere/solar/homeowners-guide-federal-tax-credit-solar-photovoltaics"
        )
        self.add_incentive(federal_tax_credit)

    @classmethod
    def per_kw_cost(cls) -> float:
        """Gross (pre-incentive) $/kW, derived from the same unit economics as
        every other capex figure for this appliance — the single number any
        caller (the LP's sizing objective, step14's reporting) should use for
        PV cost per kW, so sizing and reporting can't silently diverge."""
        unit = cls(capacity_kw=1.0)
        return unit.base_cost

    def get_cost_breakdown(self, scenario: IncentiveScenario = IncentiveScenario.FULL_INCENTIVES) -> Dict:
        """Return detailed cost breakdown for solar system."""
        total_incentives = self.calculate_total_incentives(scenario)
        net_cost = self.get_net_cost(scenario)
        
        return {
            "appliance_name": self.name,
            "capacity_kw": self.capacity_kw,
            "panel_cost": self.panel_cost,
            "base_cost": self.base_cost,
            "total_incentives": total_incentives,
            "net_cost": net_cost,
            "lifetime_years": self.lifetime_years,
            "cost_per_kw": net_cost / self.capacity_kw if self.capacity_kw > 0 else 0,
            "incentive_scenario": scenario.value
        }