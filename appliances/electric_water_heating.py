from typing import Dict, Optional
import os
import pandas as pd
from appliances.electric_base import ElectricAppliance, IncentiveScenario
from main_helpers import slugify_county_name

class ElectricWaterHeatingAppliance(ElectricAppliance):
    """
    County-aware electric water heating appliance.
    """

    CONFIG_PATH = os.path.join(
        os.path.dirname(__file__), "..", "data", "County_Median_HPWH_Stats.csv"
    )
    _CONFIG_DF: Optional[pd.DataFrame] = None

    CAPITAL_COST_COLUMN_NAME = "Total Project Cost per Unit ($)"
    INCENTIVE_COLUMN_NAME    = "Total Incentive Received by Contractor ($)"

    def __init__(
        self,
        heater_type: str = "heat_pump",
        base_cost: float = 2637.0,
        lifetime_years: int = 15,
        capacity_gallons: int = 55,
    ):
        super().__init__(f"electric_{heater_type}_water_heater", base_cost, lifetime_years)
        self.heater_type = heater_type
        self.capacity_gallons = capacity_gallons
        self.county_slug: Optional[str] = None

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
    def for_county(cls, county_slug: str, heater_type: str = "heat_pump") -> "ElectricWaterHeatingAppliance":
        df = cls._load_config()

        if county_slug in df.index:
            row = df.loc[county_slug]
        elif "statewide" in df.index:
            row = df.loc["statewide"]
        else:
            row = pd.Series({
                cls.CAPITAL_COST_COLUMN_NAME: 2637.0,
                cls.INCENTIVE_COLUMN_NAME: 0.0,
            })

        base_cost = float(row[cls.CAPITAL_COST_COLUMN_NAME])
        inst = cls(heater_type=heater_type, base_cost=base_cost, lifetime_years=15)
        inst.county_slug = county_slug
        return inst

    def calculate_total_incentives(
        self,
        scenario: IncentiveScenario = IncentiveScenario.FULL_INCENTIVES,
    ) -> float:
        # Start with base class incentives (includes federal 15% ITC)
        base_incentives = super().calculate_total_incentives(scenario)
        
        # Add county-specific incentives from CSV data
        df = self._load_config()
        key = self.county_slug if (self.county_slug in df.index) else ("statewide" if "statewide" in df.index else df.index[0])
        csv_inc_full = float(df.loc[key, self.INCENTIVE_COLUMN_NAME])

        # Apply scenario multiplier to CSV incentives
        if scenario == IncentiveScenario.FULL_INCENTIVES:
            csv_incentives = csv_inc_full
        elif scenario == IncentiveScenario.HALF_INCENTIVES:
            csv_incentives = csv_inc_full * 0.5
        else:
            csv_incentives = 0.0
        
        # Return combined incentives
        return base_incentives + csv_incentives

    def get_cost_breakdown(
        self,
        scenario: IncentiveScenario = IncentiveScenario.FULL_INCENTIVES
    ) -> Dict:
        total_incentives = self.calculate_total_incentives(scenario)
        incentives_detail: list = []

        return {
            "appliance_type": self.name,
            "heater_type": self.heater_type,
            "capacity_gallons": self.capacity_gallons,
            "base_cost": self.base_cost,
            "lifetime_years": self.lifetime_years,
            "scenario": scenario.value,
            "total_incentives": total_incentives,
            "net_cost": self.get_net_cost(scenario),
            "incentives_detail": incentives_detail,
            "cost_per_year": self.get_net_cost(scenario) / self.lifetime_years,
        }