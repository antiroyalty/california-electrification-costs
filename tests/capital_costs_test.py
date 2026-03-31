"""Capital cost sanity checks against published market prices and research estimates.

Tests verify that the equipment cost assumptions in the pipeline are within
real-world installed cost ranges. These are not regression tests — they compare
against independently published price data from LBNL, NREL, and DOE so that
model assumptions remain grounded in market reality.

Sources:
  LBNL Tracking the Sun 2023:
    CA residential solar installed cost: median $3.9/W-DC; range $2.5–$5.5/W-DC.
    https://emp.lbl.gov/tracking-the-sun

  NREL Annual Technology Baseline (ATB) 2024:
    Residential battery storage: $800–$1,500/kWh installed (includes inverter, BOS).
    https://atb.nrel.gov/electricity/2024/residential_battery_storage

  DOE Building Technologies Office / NEEP Cold Climate Heat Pump report (2022):
    Whole-home air source heat pump (ASHP): $4,000–$20,000 installed.
    Heat pump water heater (HPWH): $1,000–$5,000 installed.
    https://neep.org/initiatives/high-efficiency-products/ashp

  DOE / Rewiring America (2022):
    Induction range/cooktop: $800–$3,500 installed.
    Gas furnace (baseline replacement): $2,000–$8,000 installed.
    Gas water heater: $500–$2,500 installed.
    https://www.rewiringamerica.org/electrification-handbook

  CEC TECH Clean California Initiative (CRIS 2025):
    Provides California-specific cost data used in the CRIS_2025 methodology rows.
    https://www.tech-clean-california.com/

The capital costs CSV contains rows for two methodologies:
  NEW       — costs from consumer/installer quotes (Tesla, EnergySage, Rewiring America)
  CRIS_2025 — costs from CARB/CEC TECH California program data
  BASELINE  — costs for gas appliances retained in baseline scenario

All appliance_id values and their market price bounds are documented per test.
"""
import glob
import os
import sys

import pandas as pd
import pytest

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

CAPITAL_COST_DIR = os.path.join(REPO_ROOT, "data", "loadprofiles", "CAPITAL_COST_DEFINITIONS")


def _load_capital_costs() -> pd.DataFrame | None:
    files = sorted(glob.glob(os.path.join(CAPITAL_COST_DIR, "capital_costs_definitions_*.csv")))
    if not files:
        return None
    df = pd.read_csv(files[-1])
    df = df.set_index("appliance_id")
    return df


def _get_cost(df: pd.DataFrame, appliance_id: str) -> float | None:
    if appliance_id not in df.index:
        return None
    return float(df.loc[appliance_id, "cost_per_unit"])


# ---------------------------------------------------------------------------
# Solar panels
# ---------------------------------------------------------------------------

class TestSolarPanelCost:
    """Solar panel cost per watt is within the LBNL Tracking the Sun 2023 range.

    Source: LBNL Tracking the Sun 2023, California residential systems:
      Median installed cost: $3.9/W-DC (all-in: hardware + labor + permitting + design).
      5th–95th percentile range: ~$2.5–$5.5/W-DC.
      Costs have declined ~50% since 2012, with modest decline continuing.
      https://emp.lbl.gov/tracking-the-sun

    The model uses $2.80/W-DC (below median, consistent with a competitive quote
    from a national installer like Tesla or EnergySage marketplace). This is on
    the lower end of LBNL's range but within the observed market distribution.
    Values below $2.00/W are no longer realistic for all-in installed cost
    (even wholesale hardware alone exceeds $0.30/W-DC in 2024).
    """

    SOLAR_COST_LOWER_PER_W = 2.00   # $/W-DC — below market for all-in installed cost
    SOLAR_COST_UPPER_PER_W = 6.00   # $/W-DC — above 95th percentile, LBNL 2023

    def test_solar_cost_per_watt_in_market_range(self) -> None:
        """solar panel installed cost is $2.00–$6.00/W-DC (LBNL Tracking the Sun 2023 range)."""
        df = _load_capital_costs()
        if df is None:
            pytest.skip("Capital costs CSV not found — run step14 or check CAPITAL_COST_DEFINITIONS/.")
        cost_per_w = _get_cost(df, "solar_panels")
        if cost_per_w is None:
            pytest.skip("'solar_panels' not in capital costs — appliance_id may have changed.")
        assert self.SOLAR_COST_LOWER_PER_W <= cost_per_w <= self.SOLAR_COST_UPPER_PER_W, (
            f"Solar installed cost: ${cost_per_w:.2f}/W-DC. "
            f"Expected ${self.SOLAR_COST_LOWER_PER_W}–${self.SOLAR_COST_UPPER_PER_W}/W-DC. "
            f"LBNL Tracking the Sun 2023: CA median $3.9/W-DC, range $2.5–$5.5/W-DC. "
            f"Below ${self.SOLAR_COST_LOWER_PER_W}/W: unrealistically cheap for all-in cost. "
            f"Above ${self.SOLAR_COST_UPPER_PER_W}/W: above 95th percentile — check source."
        )


# ---------------------------------------------------------------------------
# Battery storage
# ---------------------------------------------------------------------------

class TestBatteryStorageCost:
    """Battery storage cost per kWh is within NREL ATB 2024 residential range.

    Source: NREL Annual Technology Baseline 2024, residential battery storage:
      Installed cost range: $800–$1,500/kWh (includes inverter, BOS, labor).
      https://atb.nrel.gov/electricity/2024/residential_battery_storage

    Tesla Powerwall 3 (13.5 kWh usable, 11.5 kW continuous): $11,500 hardware
    + installation brings all-in cost to ~$13,000–$18,000 → ~$960–$1,330/kWh.
    The model uses $16,853 total / 13.5 kWh = $1,248/kWh, consistent with
    premium installation in a high-cost-of-living market.
    """

    BATTERY_COST_LOWER_PER_KWH = 700    # $/kWh — below NREL lower bound
    BATTERY_COST_UPPER_PER_KWH = 1_700  # $/kWh — above premium all-in installed cost

    def test_battery_cost_per_kwh_in_market_range(self) -> None:
        """battery storage installed cost is $700–$1,700/kWh (NREL ATB 2024 residential range)."""
        df = _load_capital_costs()
        if df is None:
            pytest.skip("Capital costs CSV not found.")
        if "battery_storage" not in df.index:
            pytest.skip("'battery_storage' not in capital costs.")
        row = df.loc["battery_storage"]
        total_cost = float(row["cost_per_unit"])
        capacity_kwh = float(row["capacity"]) if pd.notna(row["capacity"]) else None
        if capacity_kwh is None or capacity_kwh <= 0:
            pytest.skip("Battery capacity (kWh) not specified in capital costs.")
        cost_per_kwh = total_cost / capacity_kwh
        assert self.BATTERY_COST_LOWER_PER_KWH <= cost_per_kwh <= self.BATTERY_COST_UPPER_PER_KWH, (
            f"Battery installed cost: ${cost_per_kwh:.0f}/kWh "
            f"(${total_cost:,.0f} total / {capacity_kwh:.1f} kWh usable). "
            f"Expected ${self.BATTERY_COST_LOWER_PER_KWH:,}–${self.BATTERY_COST_UPPER_PER_KWH:,}/kWh. "
            f"NREL ATB 2024 residential: $800–$1,500/kWh installed. "
            f"Tesla Powerwall 3 all-in: ~$960–$1,330/kWh depending on installation."
        )


# ---------------------------------------------------------------------------
# Heat pump: space heating
# ---------------------------------------------------------------------------

class TestHeatPumpSpaceCost:
    """Heat pump space heating installed cost is within DOE/NEEP field-study range.

    Source: DOE Building Technologies Office & NEEP cold climate ASHP report (2022):
      Whole-home air source heat pump installed cost: $4,000–$20,000.
      Median for a 3-ton system (appropriate for a typical SF home): ~$12,000–$15,000.
      CEC TECH California CRIS 2025 data: $11,261 for a 3-ton system.
      https://neep.org/initiatives/high-efficiency-products/ashp

    The model has two rows for heat pump space heating:
      heat_pump_space      (NEW methodology): $19,000 — high end but within range
      heat_pump_space_cris (CRIS_2025):      $11,261 — close to median
    Both should fall within the documented installed-cost range.
    """

    HP_SPACE_LOWER = 3_000    # $ — below minimum realistic installed cost
    HP_SPACE_UPPER = 25_000   # $ — above documented high end for residential

    @pytest.mark.parametrize("appliance_id", ["heat_pump_space", "heat_pump_space_cris"])
    def test_heat_pump_space_cost_in_range(self, appliance_id: str) -> None:
        """heat pump space heating installed cost is $3,000–$25,000 (DOE/NEEP 2022 range)."""
        df = _load_capital_costs()
        if df is None:
            pytest.skip("Capital costs CSV not found.")
        cost = _get_cost(df, appliance_id)
        if cost is None:
            pytest.skip(f"'{appliance_id}' not in capital costs.")
        assert self.HP_SPACE_LOWER <= cost <= self.HP_SPACE_UPPER, (
            f"{appliance_id} installed cost: ${cost:,.0f}. "
            f"Expected ${self.HP_SPACE_LOWER:,}–${self.HP_SPACE_UPPER:,}. "
            f"DOE/NEEP 2022: whole-home ASHP $4,000–$20,000 installed; "
            f"CEC TECH CA CRIS 2025: $11,261 (3-ton system)."
        )


# ---------------------------------------------------------------------------
# Heat pump water heater
# ---------------------------------------------------------------------------

class TestHeatPumpWaterHeaterCost:
    """Heat pump water heater installed cost is within DOE range.

    Source: DOE Office of Energy Efficiency & Renewable Energy (2023):
      Heat pump water heater (55-gallon equivalent) installed cost: $1,000–$5,000.
      Federal tax credit (25C) covers 30% up to $2,000 after 2022.
      CEC TECH California CRIS 2025: $2,467.
      https://www.energy.gov/eere/buildings/water-heating

    Both NEW and CRIS_2025 methodology rows are checked.
    """

    HPWH_LOWER = 1_000   # $
    HPWH_UPPER = 5_000   # $

    @pytest.mark.parametrize("appliance_id", ["water_heater_electric", "water_heater_electric_cris"])
    def test_heat_pump_water_heater_cost_in_range(self, appliance_id: str) -> None:
        """heat pump water heater installed cost is $1,000–$5,000 (DOE 2023 range)."""
        df = _load_capital_costs()
        if df is None:
            pytest.skip("Capital costs CSV not found.")
        cost = _get_cost(df, appliance_id)
        if cost is None:
            pytest.skip(f"'{appliance_id}' not in capital costs.")
        assert self.HPWH_LOWER <= cost <= self.HPWH_UPPER, (
            f"{appliance_id} installed cost: ${cost:,.0f}. "
            f"Expected ${self.HPWH_LOWER:,}–${self.HPWH_UPPER:,}. "
            f"DOE EERE 2023: HPWH installed cost $1,000–$5,000. "
            f"CEC TECH CA CRIS 2025: $2,467."
        )


# ---------------------------------------------------------------------------
# Induction stove
# ---------------------------------------------------------------------------

class TestInductionStoveCost:
    """Induction stove/range installed cost is within Rewiring America range.

    Source: Rewiring America Electrification Handbook (2022):
      Induction range (freestanding) installed cost: $800–$3,500.
      Mid-range residential models: $1,200–$2,000 (hardware); installation adds $200–$500.
      https://www.rewiringamerica.org/electrification-handbook

    The model has $2,000 (NEW) and $2,400 (CRIS_2025). Both are in the
    plausible range for a mid-to-high-quality induction range with installation.
    """

    INDUCTION_LOWER = 500    # $
    INDUCTION_UPPER = 4_000  # $

    @pytest.mark.parametrize("appliance_id", ["induction_stove", "induction_stove_cris"])
    def test_induction_stove_cost_in_range(self, appliance_id: str) -> None:
        """induction stove installed cost is $500–$4,000 (Rewiring America 2022 range)."""
        df = _load_capital_costs()
        if df is None:
            pytest.skip("Capital costs CSV not found.")
        cost = _get_cost(df, appliance_id)
        if cost is None:
            pytest.skip(f"'{appliance_id}' not in capital costs.")
        assert self.INDUCTION_LOWER <= cost <= self.INDUCTION_UPPER, (
            f"{appliance_id} installed cost: ${cost:,.0f}. "
            f"Expected ${self.INDUCTION_LOWER:,}–${self.INDUCTION_UPPER:,}. "
            f"Rewiring America 2022: induction range $800–$3,500 installed."
        )


# ---------------------------------------------------------------------------
# Gas appliances are cheaper than their electric equivalents
# ---------------------------------------------------------------------------

class TestGasVsElectricCostOrdering:
    """Gas appliances have lower installed cost than their electric replacements.

    This is a key economic assumption in the paper: electrification requires
    upfront capital for more expensive equipment, and the paper analyzes whether
    lower operating costs justify the premium.

    If electric appliances are modeled as cheaper than gas, the economic
    conclusions (payback periods, NPV) will be systematically biased.

    Source: All comparative cost data from DOE EERE, Rewiring America (2022),
    and CEC TECH California CRIS 2025.
    """

    def test_heat_pump_space_costs_more_than_gas_furnace(self) -> None:
        """heat pump space heating costs more to install than a gas furnace.

        DOE: gas furnace $2,000–$8,000; ASHP $4,000–$20,000. The electric
        alternative should be more expensive upfront, creating a payback story.
        """
        df = _load_capital_costs()
        if df is None:
            pytest.skip("Capital costs CSV not found.")
        hp_cost = _get_cost(df, "heat_pump_space") or _get_cost(df, "heat_pump_space_cris")
        gas_cost = _get_cost(df, "gas_space_heater")
        if hp_cost is None or gas_cost is None:
            pytest.skip("heat pump or gas furnace cost not found in capital costs.")
        assert hp_cost > gas_cost, (
            f"Heat pump space (${hp_cost:,.0f}) is not more expensive than "
            f"gas furnace (${gas_cost:,.0f}). "
            f"The paper's economic analysis assumes electrification has higher upfront cost. "
            f"DOE: gas furnace $2,000–$8,000; ASHP $4,000–$20,000."
        )

    def test_heat_pump_water_heater_costs_more_than_gas_water_heater(self) -> None:
        """heat pump water heater costs more to install than a gas water heater.

        DOE: gas water heater $500–$2,500; HPWH $1,000–$5,000. Electric
        should be more expensive, consistent with the electrification premium story.
        """
        df = _load_capital_costs()
        if df is None:
            pytest.skip("Capital costs CSV not found.")
        hpwh_cost = _get_cost(df, "water_heater_electric") or _get_cost(df, "water_heater_electric_cris")
        gas_wh_cost = _get_cost(df, "gas_water_heater")
        if hpwh_cost is None or gas_wh_cost is None:
            pytest.skip("HPWH or gas water heater cost not found in capital costs.")
        assert hpwh_cost > gas_wh_cost, (
            f"HPWH (${hpwh_cost:,.0f}) is not more expensive than "
            f"gas water heater (${gas_wh_cost:,.0f}). "
            f"DOE: gas water heater $500–$2,500; HPWH $1,000–$5,000."
        )
