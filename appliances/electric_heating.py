import os
import pandas as pd
from typing import Dict, Optional
from appliances.electric_base import ElectricAppliance, IncentiveScenario
from main_helpers import slugify_county_name

class ElectricHeatingAppliance(ElectricAppliance):
    CONFIG_PATH = os.path.join(
        os.path.dirname(__file__), "..", "data", "County_Median_HPSH_Stats.csv"
    )
    _CONFIG_DF: Optional[pd.DataFrame] = None

    # Column names we care about
    CAPITAL_COST_COLUMN_NAME = "Total Project Cost per Unit ($)"
    INCENTIVE_COLUMN_NAME    = "Total Incentive Received by Contractor ($)"

    def __init__(
        self,
        heating_type: str = "heat_pump",
        base_cost: float = 19000.0,
        lifetime_years: int = 15,
    ):
        super().__init__(f"electric_{heating_type}", base_cost, lifetime_years)
        self.heating_type = heating_type
        self.county_slug: Optional[str] = None  # set by for_county()

    @classmethod
    def _load_config(cls) -> pd.DataFrame:
        """Load CSV once and cache as DataFrame indexed by county_slug."""
        if cls._CONFIG_DF is None:
            df = pd.read_csv(cls.CONFIG_PATH)

            if "County" not in df.columns:
                raise ValueError(f"{cls.CONFIG_PATH} missing required 'County' column")

            # Slugify the County column and set as index
            df["county_slug"] = df["County"].apply(slugify_county_name)
            df = df.set_index("county_slug")

            cls._CONFIG_DF = df
        return cls._CONFIG_DF

    @classmethod
    def for_county(cls, county_slug: str, heating_type: str = "heat_pump") -> "ElectricHeatingAppliance":
        """
        Factory that reads county-specific base_cost from CSV.
        Expects county_slug to match the CSV index.
        """
        df = cls._load_config()

        if county_slug in df.index:
            row = df.loc[county_slug]
        elif "statewide" in df.index:
            row = df.loc["statewide"]
        else:
            # final fallback
            row = pd.Series({
                cls.CAPITAL_COST_COLUMN_NAME: 19000.0,
                cls.INCENTIVE_COLUMN_NAME: 0.0,
            })

        base_cost = float(row[cls.CAPITAL_COST_COLUMN_NAME])
        inst = cls(heating_type=heating_type, base_cost=base_cost, lifetime_years=15)
        inst.county_slug = county_slug
        return inst

    def calculate_total_incentives(
        self,
        scenario: IncentiveScenario = IncentiveScenario.FULL_INCENTIVES,
    ) -> float:
        """
        Interpret CSV incentive as the 'FULL' amount; HALF is 50%, NONE is 0%.
        """
        df = self._load_config()
        key = self.county_slug if (self.county_slug in df.index) else ("statewide" if "statewide" in df.index else df.index[0])
        inc_full = float(df.loc[key, self.INCENTIVE_COLUMN_NAME])

        if scenario == IncentiveScenario.FULL_INCENTIVES:
            return inc_full
        elif scenario == IncentiveScenario.HALF_INCENTIVES:
            return inc_full * 0.5
        else:
            return 0.0

    def get_cost_breakdown(
        self,
        scenario: IncentiveScenario = IncentiveScenario.FULL_INCENTIVES
    ) -> Dict:
        total_incentives = self.calculate_total_incentives(scenario)
        incentives_detail: list = []  # totals come from CSV; no per-program breakdown here

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