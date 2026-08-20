"""
Solar System Appliance Class for Capital Cost Analysis
"""

from typing import Dict, Optional
from appliances.electric_base import ElectricAppliance, Incentive, IncentiveScenario
from appliances.incentive_policy import (
    PolicyRegime,
    DEFAULT_POLICY_REGIME,
    federal_itc_fraction,
    regime_summary,
)

class SolarSystemAppliance(ElectricAppliance):
    """Solar panel system with sizing based on capacity in kW."""

    GROSS_COST_USD_PER_WATT = 3.3
    COST_BASIS_YEAR = 2023
    COST_SOURCE_ID = "cpuc_2023_residential_pv_cost"
    COST_SOURCE_URL = (
        "https://docs.cpuc.ca.gov/PublishedDocs/Published/"
        "G000/M499/K921/499921246.PDF"
    )

    def __init__(self, capacity_kw: float, lifetime_years: int = 25,
                 policy_regime: PolicyRegime = DEFAULT_POLICY_REGIME):
        # Sourced residential PV unit economics.
        dollars_per_watt = self.GROSS_COST_USD_PER_WATT
        installation_markup = 0.0  # 0% installation markup
        design_markup = 0.0  # 0% design/engineering markup

        # Calculate total solar cost
        panel_cost = capacity_kw * 1000 * dollars_per_watt  # Convert kW to W
        total_cost = panel_cost * (1 + installation_markup + design_markup)

        super().__init__(f"solar_system_{capacity_kw}kW", total_cost, lifetime_years)

        self.capacity_kw = capacity_kw
        self.panel_cost = panel_cost
        self.policy_regime = policy_regime

        # Federal solar ITC (IRC 25D). Whether it legally exists is decided by the
        # policy regime, not hardcoded here: incentive_policy.py is the single source
        # of truth. Under the default POST_ITC_2026 regime the credit is repealed
        # (OBBBA, Pub. L. 119-21) and no incentive is created, so net cost == gross.
        itc_fraction = federal_itc_fraction(policy_regime)
        if itc_fraction > 0:
            federal_tax_credit = Incentive(
                name="federal_solar_tax_credit",
                value=itc_fraction * 100.0,  # percent
                unit="%",
                description=f"Federal solar investment tax credit (IRC 25D), {regime_summary(policy_regime)}",
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

    @classmethod
    def per_kw_cost_net(cls, scenario: IncentiveScenario,
                        regime: PolicyRegime = DEFAULT_POLICY_REGIME) -> float:
        """Net (after-incentive) $/kW under the given incentive scenario and
        policy regime.

        Use this — not per_kw_cost() — for a sizing decision meant to reflect
        what the modeled decision-maker actually pays, e.g. the LP's default
        sizing signal, which should match whichever incentive scenario is the
        one actually being reported (2026-07-07). The regime decides which
        incentives legally exist (2026-07-17); pass ITC_2025 to price the same
        system under the expired federal ITC for a before/after comparison."""
        unit = cls(capacity_kw=1.0, policy_regime=regime)
        return unit.get_net_cost(scenario)

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
