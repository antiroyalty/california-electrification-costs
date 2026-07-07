"""Capital cost sanity checks against published market prices and research estimates.

These tests validate the values production code actually uses — the appliance
classes in appliances/ — not the data/loadprofiles/CAPITAL_COST_DEFINITIONS/
CSV, which despite looking like documentation is never read by any
production code path (confirmed 2026-07-06: no import references it anywhere).
Testing that file gave false confidence — solar, battery, heat pump, and
induction stove numbers it validated were not the numbers used to build the
paper's results.

Sources:
  LBNL Tracking the Sun 2023 (cited in CPUC's solar cost report, see below):
    CA residential solar installed cost: ~$3.80/W-DC (2019 estimate, judged
    too high by CPUC's own analysis).

  CPUC, "adopted 2023 cost of solar in California"
    (docs.cpuc.ca.gov/PublishedDocs/Published/G000/M499/K921/499921246.PDF):
    $3.30/W-DC, reconciling NREL ATB ($2.34/W, judged too low) against LBNL
    Tracking the Sun ($3.80/W, judged too high); accounts for panel upgrades,
    delays, and inflation. This is the rate appliances/solar_system.py uses.

  NREL Annual Technology Baseline (ATB) 2024, moderate scenario, via CEC
    report CEC-200-2024-011 (energy.ca.gov/sites/default/files/2024-07/CEC-200-2024-011.pdf):
    Residential 5kW/12.5kWh battery system: $18,258 installed (2023 value).
    This is the rate appliances/battery_storage.py uses.

  TECH Clean California program data (CEC), per Simon La Vieille, "EV
  Integration to Ana's Project" (Aug 2025):
    Heat pump space heating (ducted systems only, AHRI types without "-O"
    suffix) and heat pump water heater (Single Family HPWH installs) county
    median contractor/turnkey costs. Source of data/County_Median_HPSH_Stats.csv
    and data/County_Median_HPWH_Stats.csv.

  CARB appliance comparison data ("Cristina's approach"), same report,
  section "Rest of the Values": induction stove, gas stove, gas water
  heater, gas heating — each is capital + installation + other (2022),
  inflated 3.4% CPI-U (BLS) to 2023.

Because HPSH/HPWH costs are contractor/turnkey (not equipment-only) and
HPSH is filtered to ducted systems specifically, these run at or above
generic national ranges (e.g. DOE/NEEP's $4,000-$20,000 ASHP figure, which
likely includes cheaper ductless mini-splits) — that's an expected
consequence of the methodology, not a red flag, so bounds here are wider
than a naive DOE-range check would suggest.
"""
import os
import sys

import pytest

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from appliances.solar_system import SolarSystemAppliance
from appliances.battery_storage import BatteryStorageAppliance
from appliances.electric_heating import ElectricHeatingAppliance
from appliances.electric_water_heating import ElectricWaterHeatingAppliance
from appliances.electric_cooking import ElectricCookingAppliance
from appliances.gas_stove import GasStoveAppliance
from appliances.gas_water_heating import GasWaterHeatingAppliance
from appliances.gas_heating import GasHeatingAppliance
from helpers.main_helpers import norcal_counties, central_counties, socal_counties, slugify_county_name


PIPELINE_COUNTY_SLUGS = sorted({
    slugify_county_name(c) for c in norcal_counties + central_counties + socal_counties
})


class TestSolarPanelCost:
    """Solar panel cost per watt matches the CPUC-adopted 2023 CA rate."""

    def test_solar_cost_per_kw_matches_cpuc_rate(self) -> None:
        cost_per_kw = SolarSystemAppliance.per_kw_cost()
        assert cost_per_kw == pytest.approx(3300.0), (
            f"Solar installed cost: ${cost_per_kw:,.2f}/kW. Expected $3,300/kW "
            f"(CPUC-adopted 2023 CA rate, $3.30/W). If this changed intentionally, "
            f"update this test and docs/methods.yaml together."
        )


class TestBatteryStorageCost:
    """Battery storage cost per kWh matches the NREL ATB 2024 / CEC report rate."""

    def test_battery_cost_per_kwh_matches_atb_rate(self) -> None:
        cost_per_kwh = BatteryStorageAppliance.per_kwh_cost()
        assert cost_per_kwh == pytest.approx(1460.64, rel=1e-3), (
            f"Battery installed cost: ${cost_per_kwh:,.2f}/kWh "
            f"(expected $18,258 / 12.5 kWh = $1,460.64/kWh, NREL ATB 2024 moderate "
            f"scenario via CEC-200-2024-011). If this changed intentionally, "
            f"update this test and docs/methods.yaml together."
        )

    def test_lp_sizing_price_matches_this_reporting_price(self) -> None:
        """Regression for the 2026-07-06/07 bugs: the LP must size against the
        same rate this appliance class reports for the actual scenario being
        modeled — net of full_incentives (Config's default), not a stale
        independent default and not the unincentivized gross price."""
        from appliances.electric_base import IncentiveScenario
        from pipeline.steps.step9b_cooptimize_core import _DEFAULT_BATT_CAPEX_PER_KWH
        expected = BatteryStorageAppliance.per_kwh_cost_net(IncentiveScenario.FULL_INCENTIVES)
        assert _DEFAULT_BATT_CAPEX_PER_KWH == pytest.approx(expected)


class TestHeatPumpSpaceCost:
    """Heat pump space heating cost per county (TECH Clean California, ducted-only).

    Source: DOE Building Technologies Office & NEEP cold climate ASHP report (2022):
      Whole-home air source heat pump installed cost: $4,000-$20,000.
      https://neep.org/initiatives/high-efficiency-products/ashp
    CEC TECH California CRIS 2025 data point: $11,261 for a 3-ton system
      (see data/loadprofiles/CAPITAL_COST_DEFINITIONS/*.csv, heat_pump_space_cris row —
      that file isn't read by production code, but this specific figure is a
      useful independent cross-check).

    This pipeline's actual data is filtered to ducted systems only and reports
    contractor/turnkey cost (equipment + install) — both push county medians
    above DOE's range and above the CRIS 3-ton reference point. That's an
    expected consequence of the documented methodology (see
    docs/methods.yaml: appliances.electric_heating), not a red flag. The
    upper bound below is therefore anchored to DOE's ceiling with explicit,
    documented headroom (2x) rather than either a naive DOE-range check
    (would false-fail on legitimate data) or an unanchored round number.
    """

    DOE_LOWER = 4_000
    DOE_UPPER = 20_000
    CRIS_3_TON_REFERENCE = 11_261
    LOWER = 3_000              # $ — below DOE's own floor, clearly implausible
    UPPER = DOE_UPPER * 2      # $ — 2x DOE's ceiling: generous for ducted+turnkey, still catches real corruption

    def test_all_pipeline_counties_in_plausible_range(self) -> None:
        for county_slug in PIPELINE_COUNTY_SLUGS:
            hp = ElectricHeatingAppliance.for_county(county_slug)
            assert self.LOWER <= hp.base_cost <= self.UPPER, (
                f"{county_slug}: heat pump space heating cost ${hp.base_cost:,.0f} "
                f"outside plausible range ${self.LOWER:,}-${self.UPPER:,} "
                f"(DOE/NEEP 2022 range: ${self.DOE_LOWER:,}-${self.DOE_UPPER:,}; "
                f"CRIS 2025 3-ton reference: ${self.CRIS_3_TON_REFERENCE:,}). "
                f"Source: data/County_Median_HPSH_Stats.csv (TECH Clean California, ducted only, turnkey cost)."
            )

    def test_missing_county_falls_back_to_computed_median_not_a_guess(self) -> None:
        """Regression: for_county() used to fall back to a hardcoded $19,000 (or
        an arbitrary first row) for counties absent from the source data. It
        must compute the actual median of counties present instead."""
        df = ElectricHeatingAppliance._load_config()
        expected_median = df[ElectricHeatingAppliance.CAPITAL_COST_COLUMN_NAME].median()
        missing_county = "not-a-real-county-xyz"
        assert missing_county not in df.index
        hp = ElectricHeatingAppliance.for_county(missing_county)
        assert hp.base_cost == pytest.approx(expected_median)


class TestHeatPumpWaterHeaterCost:
    """Heat pump water heater cost per county (TECH Clean California).

    Source: DOE Office of Energy Efficiency & Renewable Energy (2023):
      Heat pump water heater (55-gallon equivalent) installed cost: $1,000-$5,000.
      https://www.energy.gov/eere/buildings/water-heating
    CEC TECH California CRIS 2025 data point: $2,467
      (data/loadprofiles/CAPITAL_COST_DEFINITIONS/*.csv, water_heater_electric_cris row).

    Same reasoning as TestHeatPumpSpaceCost: this pipeline's data is
    contractor/turnkey cost, which runs above DOE's range for a large share
    of counties (87% exceed $5,000 — verified 2026-07-06). Upper bound is
    anchored to DOE's ceiling with documented headroom, not unanchored.
    """

    DOE_LOWER = 1_000
    DOE_UPPER = 5_000
    CRIS_REFERENCE = 2_467
    LOWER = 800                # $ — below plausible even for a bare unit
    UPPER = DOE_UPPER * 3      # $ — 3x DOE's ceiling: HPWH turnkey costs run further above DOE than HPSH does (worst observed: Lake County ~$14.1k, ~2.8x)

    def test_all_pipeline_counties_in_plausible_range(self) -> None:
        for county_slug in PIPELINE_COUNTY_SLUGS:
            wh = ElectricWaterHeatingAppliance.for_county(county_slug)
            assert self.LOWER <= wh.base_cost <= self.UPPER, (
                f"{county_slug}: HPWH cost ${wh.base_cost:,.0f} outside plausible "
                f"range ${self.LOWER:,}-${self.UPPER:,} "
                f"(DOE 2023 range: ${self.DOE_LOWER:,}-${self.DOE_UPPER:,}; "
                f"CRIS 2025 reference: ${self.CRIS_REFERENCE:,}). "
                f"Source: data/County_Median_HPWH_Stats.csv (TECH Clean California, turnkey cost)."
            )

    def test_missing_county_falls_back_to_computed_median_not_a_guess(self) -> None:
        df = ElectricWaterHeatingAppliance._load_config()
        expected_median = df[ElectricWaterHeatingAppliance.CAPITAL_COST_COLUMN_NAME].median()
        missing_county = "not-a-real-county-xyz"
        assert missing_county not in df.index
        wh = ElectricWaterHeatingAppliance.for_county(missing_county)
        assert wh.base_cost == pytest.approx(expected_median)


class TestCARBAppliancesCost:
    """Induction stove / gas appliance costs: CARB data + 3.4% CPI-U to 2023.

    Each value is capital + installation + other (2022) * 1.034. See
    docs/methods.yaml: appliances.carb_appliance_costs for the breakdown.

    Rewiring America Electrification Handbook (2022) cites induction range
    installed cost as $800-$3,500 (hardware + basic install). CARB's
    $4,260.08 exceeds that ceiling by ~22% — expected, since it separately
    itemizes an "other" cost component ($340, e.g. permits/misc) on top of
    capital + installation, and applies 2023 inflation, both of which
    Rewiring America's figure may not include.
    """

    REWIRING_AMERICA_LOWER = 800
    REWIRING_AMERICA_UPPER = 3_500

    def test_induction_stove_cost(self) -> None:
        cost = ElectricCookingAppliance().base_cost
        assert cost == pytest.approx(4260.08), (
            f"Induction stove: ${cost:,.2f}, expected $4,260.08. "
            f"(Rewiring America 2022 range: ${self.REWIRING_AMERICA_LOWER:,}-"
            f"${self.REWIRING_AMERICA_UPPER:,} — CARB's figure exceeds this by "
            f"~22%, expected due to its added 'other' cost line + 2023 inflation.)"
        )

    def test_gas_stove_cost(self) -> None:
        cost = GasStoveAppliance().base_cost
        assert cost == pytest.approx(2802.14), f"Gas stove: ${cost:,.2f}, expected $2,802.14"

    def test_gas_water_heater_cost(self) -> None:
        cost = GasWaterHeatingAppliance().base_cost
        assert cost == pytest.approx(2264.46), f"Gas water heater: ${cost:,.2f}, expected $2,264.46"

    def test_gas_heating_cost(self) -> None:
        cost = GasHeatingAppliance().base_cost
        assert cost == pytest.approx(9771.30), f"Gas heating: ${cost:,.2f}, expected $9,771.30"


class TestGasVsElectricCostOrdering:
    """Gas appliances have lower installed cost than their electric replacements.

    This is a key economic assumption in the paper: electrification requires
    upfront capital for more expensive equipment, and the paper analyzes
    whether lower operating costs justify the premium. If electric appliances
    were modeled as cheaper than gas, the economic conclusions would be
    systematically biased.
    """

    def test_heat_pump_space_costs_more_than_gas_furnace_everywhere(self) -> None:
        gas_cost = GasHeatingAppliance().base_cost
        for county_slug in PIPELINE_COUNTY_SLUGS:
            hp_cost = ElectricHeatingAppliance.for_county(county_slug).base_cost
            assert hp_cost > gas_cost, (
                f"{county_slug}: heat pump (${hp_cost:,.0f}) is not more expensive "
                f"than gas furnace (${gas_cost:,.0f})."
            )

    def test_heat_pump_water_heater_costs_more_than_gas_water_heater_everywhere(self) -> None:
        gas_cost = GasWaterHeatingAppliance().base_cost
        for county_slug in PIPELINE_COUNTY_SLUGS:
            hpwh_cost = ElectricWaterHeatingAppliance.for_county(county_slug).base_cost
            assert hpwh_cost > gas_cost, (
                f"{county_slug}: HPWH (${hpwh_cost:,.0f}) is not more expensive "
                f"than gas water heater (${gas_cost:,.0f})."
            )

    def test_induction_stove_costs_more_than_gas_stove(self) -> None:
        induction_cost = ElectricCookingAppliance().base_cost
        gas_cost = GasStoveAppliance().base_cost
        assert induction_cost > gas_cost, (
            f"Induction (${induction_cost:,.0f}) is not more expensive than gas (${gas_cost:,.0f})."
        )
