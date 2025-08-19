import os
import pandas as pd
from typing import Dict, Optional
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

    # Load settings from CSV file
    CONFIG_PATH = os.path.join(
        os.path.dirname(__file__), "..", "data", "electric_heating_costs.csv"
    )

    CAPITAL_COST_COLUMN_NAME = ""

    _CONFIG_DF: Optional[pd.DataFrame] = None

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

    @classmethod
    def _load_config(cls) -> pd.DataFrame:
        """Load CSV once and cache as DataFrame indexed by county_slug."""
        if cls._CONFIG_DF is None:
            df = pd.read_csv(cls.CONFIG_PATH)
            df = df.set_index("county_slug")
            cls._CONFIG_DF = df
        return cls._CONFIG_DF

    @classmethod
    def for_county(cls, county_slug: str, heating_type: str = "heat_pump") -> "ElectricHeatingAppliance":
        """Factory: create a county-specific appliance instance using CSV config."""
        df = cls._load_config()
        if county_slug in df.index:
            row = df.loc[county_slug]
        else:
            row = df.loc["statewide"]  # fallback

        base_cost = float(row[CAPITAL_COST_COLUMN_NAME]) 

        inst = cls(heating_type=heating_type, base_cost=base_cost, lifetime_years=15)
        inst.county_slug = county_slug
        return inst

    def _county_key(self) -> str:
        return self.county_slug if (self.county_slug in self.INCENTIVES) else "statewide"
    
    def calculate_total_incentives(
        self,
        scenario: IncentiveScenario = IncentiveScenario.FULL_INCENTIVES,
    ) -> float:
        # Read the column from your cached CSV (e.g., incentive_full/half/none)
        scen_col = {
            IncentiveScenario.FULL_INCENTIVES: "incentive_full",
            IncentiveScenario.HALF_INCENTIVES: "incentive_half",
            IncentiveScenario.NO_INCENTIVES:   "incentive_none",
        }[scenario]

        df = self._load_config()
        key = self.county_slug if (self.county_slug in df.index) else "statewide"
        return float(df.loc[key, scen_col])

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

    def get_cost_breakdown(self, scenario: IncentiveScenario = IncentiveScenario.FULL_INCENTIVES) -> Dict:
        """Return detailed cost breakdown for electric heating appliance."""
        total_incentives = self.calculate_total_incentives(scenario)

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