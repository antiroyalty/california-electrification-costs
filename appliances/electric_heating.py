git from typing import Dict, Optional
from appliances.electric_base import ElectricAppliance, Incentive, IncentiveScenario

class ElectricHeatingAppliance(ElectricAppliance):
    CAPITAL_COSTS = {
        "alameda": 18000.0,
        "san_mateo": 19500.0,
        "statewide": 19000.0,  # fallback
    }
    # Treat these as county **bonus/override amounts** added on top of your defaults.
    INCENTIVES = {
        "alameda": {"full": 8000.0, "half": 4000.0, "none": 0.0},
        "statewide": {"full": 0.0, "half": 0.0, "none": 0.0},  # fallback
    }

    def __init__(self, 
                 heating_type: str = "heat_pump",
                 base_cost: float = 19000.0,
                 lifetime_years: int = 15):
        """
        Initialize electric heating appliance.
        """
        super().__init__(f"electric_{heating_type}", base_cost, lifetime_years)
        self.heating_type = heating_type
        self.county_slug: Optional[str] = None   # set by for_county()
        self._add_default_incentives()

    @classmethod
    def for_county(cls, county_slug: str, heating_type: str = "heat_pump") -> "ElectricHeatingAppliance":
        """
        County-aware factory. Uses county-specific base_cost and tags the instance
        with the county so later calls (e.g., incentives) can use it.
        """
        key = county_slug if county_slug in cls.CAPITAL_COSTS else "statewide"
        base_cost = cls.CAPITAL_COSTS[key]

        # Use existing __init__ (no signature change)
        inst = cls(heating_type=heating_type, base_cost=base_cost, lifetime_years=15)
        inst.county_slug = county_slug
        return inst

    def _county_key(self) -> str:
        return self.county_slug if (self.county_slug in self.INCENTIVES) else "statewide"

    def _add_default_incentives(self) -> None:
        """Add default federal and state incentives for heat pumps."""
        federal_credit = Incentive(
            name="Federal Residential Clean Energy Credit",
            value=30.0,
            unit="%",
            max_value=2000.0,
            description="Federal tax credit for residential heat pumps (2023-2032)",
            source_url="https://www.irs.gov/credits-deductions/residential-clean-energy-credit",
        )
        self.add_incentive(federal_credit)

        ca_tech_incentive = Incentive(
            name="TECH Clean California HVAC Incentive",
            value=1500.0,
            unit="$",
            description="California incentive for single-family HVAC heat pump installation",
            source_url="https://incentives.switchison.org/rebate-profile/tech-clean-california-single-family-hvac",
        )
        self.add_incentive(ca_tech_incentive)

    def calculate_total_incentives(self, scenario: IncentiveScenario) -> float:
        """
        Total incentives = defaults (already added) + county-specific bonus (if any).
        Keeps your existing behavior and simply layers county logic on top.
        """
        # 1) Default incentives (sum the list added in __init__)
        #    If your base class already implements this logic, call super();
        #    otherwise replicate the same calculation used in get_cost_breakdown.
        base_total = super().calculate_total_incentives(scenario)

        # 2) County-specific bonus
        scen_key = {
            IncentiveScenario.FULL_INCENTIVES: "full",
            IncentiveScenario.HALF_INCENTIVES: "half",
            IncentiveScenario.NO_INCENTIVES:   "none",
        }[scenario]

        county_bonus = self.INCENTIVES.get(self._county_key(), {}).get(scen_key, 0.0)
        return base_total + county_bonus

    def get_cost_breakdown(self, scenario: IncentiveScenario = IncentiveScenario.FULL_INCENTIVES) -> Dict:
        """Return detailed cost breakdown for electric heating appliance."""
        # Use the unified total that includes county bonus
        total_incentives = self.calculate_total_incentives(scenario)

        # Optional: keep the per-program details (defaults only) for transparency
        incentives_detail = []
        if scenario != IncentiveScenario.NO_INCENTIVES:
            multiplier = 1.0 if scenario == IncentiveScenario.FULL_INCENTIVES else 0.5
            for incentive in self.incentives:
                if incentive.unit == "%":
                    val = self.base_cost * (incentive.value / 100)
                    if incentive.max_value:
                        val = min(val, incentive.max_value)
                else:
                    val = incentive.value
                applied = val * multiplier
                incentives_detail.append({
                    "name": incentive.name,
                    "base_value": val,
                    "applied_value": applied,
                    "scenario_multiplier": multiplier,
                })

        return {
            "appliance_type": self.name,
            "heating_type": self.heating_type,
            "base_cost": self.base_cost,
            "lifetime_years": self.lifetime_years,
            "scenario": scenario.value,
            "total_incentives": total_incentives,
            "net_cost": self.get_net_cost(scenario),
            "incentives_detail": incentives_detail,
            "cost_per_year": self.get_net_cost(scenario) / self.lifetime_years,
        }