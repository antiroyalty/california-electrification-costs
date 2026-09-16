"""
Battery Storage Appliance Class for Capital Cost Analysis
"""

from typing import Dict
from appliances.electric_base import ElectricAppliance, Incentive, IncentiveScenario
from appliances.incentive_policy import (
    PolicyRegime,
    DEFAULT_POLICY_REGIME,
    federal_itc_fraction,
    regime_summary,
)

class BatteryStorageAppliance(ElectricAppliance):
    """Battery storage system (Tesla Powerwall 3)."""

    BASE_UNIT_COST_USD = 18_258.0
    UNIT_CAPACITY_KWH = 12.5
    COST_BASIS_YEAR = 2023
    COST_SOURCE_ID = "nrel_atb_2024_via_cec_200_2024_011"
    COST_SOURCE_URLS = (
        "https://atb.nrel.gov/electricity/2024/data",
        "https://www.energy.ca.gov/sites/default/files/2024-07/"
        "CEC-200-2024-011.pdf",
    )

    def __init__(self, num_units: int = 1, lifetime_years: int = 15,
                 policy_regime: PolicyRegime = DEFAULT_POLICY_REGIME):
        base_unit_cost = self.BASE_UNIT_COST_USD
        capacity_per_unit = self.UNIT_CAPACITY_KWH

        total_cost = base_unit_cost * num_units
        total_capacity = capacity_per_unit * num_units

        super().__init__(f"battery_storage_{num_units}units", total_cost, lifetime_years)

        self.num_units = num_units
        self.unit_cost = base_unit_cost
        self.capacity_kwh = total_capacity
        self.policy_regime = policy_regime

        # Federal storage ITC (IRC 25D, systems >= 3 kWh). Whether it legally exists
        # is decided by the policy regime, not hardcoded: incentive_policy.py is the
        # single source of truth. Under the default POST_ITC_2026 regime the credit is
        # repealed (OBBBA, Pub. L. 119-21) and no incentive is created, so net == gross.
        itc_fraction = federal_itc_fraction(policy_regime)
        if total_capacity >= 3.0 and itc_fraction > 0:
            federal_tax_credit = Incentive(
                name="federal_storage_tax_credit",
                value=itc_fraction * 100.0,  # percent
                unit="%",
                description=f"Federal energy storage ITC (IRC 25D), systems >= 3 kWh, {regime_summary(policy_regime)}",
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

    @classmethod
    def per_kwh_cost_net(cls, scenario: IncentiveScenario,
                         regime: PolicyRegime = DEFAULT_POLICY_REGIME) -> float:
        """Net (after-incentive) $/kWh under the given incentive scenario and
        policy regime.

        Use this — not per_kwh_cost() — for a sizing decision meant to reflect
        what the modeled decision-maker actually pays, e.g. the LP's default
        sizing signal, which should match whichever incentive scenario is the
        one actually being reported (2026-07-07). The regime decides which
        incentives legally exist (2026-07-17); pass ITC_2025 to price the same
        system under the expired federal ITC for a before/after comparison."""
        unit = cls(num_units=1, policy_regime=regime)
        return unit.get_net_cost(scenario) / unit.capacity_kwh

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
