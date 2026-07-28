from typing import Dict, Optional
import os
import pandas as pd
from appliances.electric_base import ElectricAppliance, IncentiveScenario
from appliances.incentive_policy import (
    PolicyRegime, DEFAULT_POLICY_REGIME, federal_25c_credit, regime_summary,
)
from helpers.main_helpers import slugify_county_name

class ElectricWaterHeatingAppliance(ElectricAppliance):
    """County-aware heat pump water heater appliance.

    Cost data source: TECH Clean California program data (CEC), filtered to
    Single Family installs of Heat Pump Water Heater / Split System HPWH /
    120V and 240V integrated HPWH (see Simon La Vieille, "EV Integration to
    Ana's Project," Aug 2025). Values are contractor/turnkey costs
    (equipment + installation), not equipment-only. 9 of the pipeline's 47
    counties are absent from the source data; those use the median of the
    counties present, per the same report's documented approach ("take the
    state median to fill in the gaps") — computed here, not hardcoded, so it
    stays correct if the source data is refreshed.
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
        policy_regime: PolicyRegime = DEFAULT_POLICY_REGIME,
    ):
        super().__init__(f"electric_{heater_type}_water_heater", base_cost, lifetime_years)
        self.heater_type = heater_type
        self.capacity_gallons = capacity_gallons
        self.county_slug: Optional[str] = None
        self.policy_regime = policy_regime

        # Federal heat pump water heater tax credit (IRC 25C), gated on the regime.
        self._add_federal_heat_pump_water_heater_incentive()

    def _add_federal_heat_pump_water_heater_incentive(self) -> None:
        """Add the federal IRC 25C credit for heat pump water heaters, only if it
        legally applies under this appliance's policy regime. incentive_policy.py
        is the single source of truth for whether the credit exists (repealed by
        OBBBA section 70505 for property placed in service after 2025-12-31) and
        for its value. Under the default POST_ITC_2026 regime no incentive is
        created, so net cost == gross."""
        credit = federal_25c_credit(self.policy_regime)
        if credit is None:
            return
        fraction, cap = credit
        self._add_federal_incentive(
            name="Federal Heat Pump Water Heater Tax Credit (IRC 25C)",
            value=fraction * 100.0,
            unit="%",
            max_value=cap,
            description=(
                f"Federal energy efficient home improvement credit (IRC 25C), "
                f"{fraction * 100:.0f}% of installed cost capped at ${cap:,.0f}/yr for "
                f"heat pump water heaters; {regime_summary(self.policy_regime)}"
            ),
            source_url="https://www.irs.gov/newsroom/faqs-for-modification-of-sections-25c-25d-25e-30c-30d-45l-45w-and-179d-under-public-law-119-21-139-stat-72-july-4-2025-commonly-known-as-the-one-big-beautiful-bill-obbb",
        )

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
    def _state_median_row(cls, df: pd.DataFrame) -> pd.Series:
        """Median of all counties present, for counties missing from the source data."""
        return pd.Series({
            cls.CAPITAL_COST_COLUMN_NAME: df[cls.CAPITAL_COST_COLUMN_NAME].median(),
            cls.INCENTIVE_COLUMN_NAME: df[cls.INCENTIVE_COLUMN_NAME].median(),
        })

    @classmethod
    def for_county(cls, county_slug: str, heater_type: str = "heat_pump",
                   policy_regime: PolicyRegime = DEFAULT_POLICY_REGIME) -> "ElectricWaterHeatingAppliance":
        df = cls._load_config()

        if county_slug in df.index:
            row = df.loc[county_slug]
        else:
            row = cls._state_median_row(df)

        base_cost = float(row[cls.CAPITAL_COST_COLUMN_NAME])
        inst = cls(heater_type=heater_type, base_cost=base_cost, lifetime_years=15,
                   policy_regime=policy_regime)
        inst.county_slug = county_slug
        return inst

    def calculate_total_incentives(
        self,
        scenario: IncentiveScenario = IncentiveScenario.FULL_INCENTIVES,
    ) -> float:
        # Start with base class incentives (includes federal heat pump water heater tax credit)
        base_incentives = super().calculate_total_incentives(scenario)
        
        # Add county-specific incentives from CSV data
        df = self._load_config()
        if self.county_slug in df.index:
            csv_inc_full = float(df.loc[self.county_slug, self.INCENTIVE_COLUMN_NAME])
        else:
            csv_inc_full = float(self._state_median_row(df)[self.INCENTIVE_COLUMN_NAME])

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