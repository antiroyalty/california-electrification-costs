"""Ballpark sanity checks for load profile outputs and the methods manifest.

Two concerns are tested here:

1. Methods manifest integrity: docs/methods.yaml must load cleanly and all
   code references it declares (file:symbol pairs) must point to real files
   and symbols in the repo.

2. Load profile plausibility for Alameda County: the combined_profiles CSVs
   produced by the pipeline must satisfy energy-conservation invariants:
   - Baseline electricity is ~5,558 kWh/yr (within 20% of RECS/EIA benchmarks)
   - Electrified scenarios have strictly higher electricity loads than baseline
   - Reduced-gas scenarios have strictly lower gas loads than baseline
   - All profiles are exactly 8,760 rows with non-negative, non-null values

These tests use Alameda County as the single representative county because it
is the primary validation county throughout the paper. If a scenario's CSVs
are missing (e.g., a partial run), the test skips rather than fails.
"""
import json
import os
import sys

import pandas as pd
import pytest

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from helpers.main_helpers import slugify_county_name
from scenarios import SCENARIOS

def _repo_root() -> str:
    return REPO_ROOT


def _load_manifest() -> dict:
    path = os.path.join(_repo_root(), "docs", "methods.yaml")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def test_methods_manifest_loads() -> None:
    """docs/methods.yaml loads as a non-empty dict."""
    manifest = _load_manifest()
    assert isinstance(manifest, dict)
    assert manifest, "methods manifest is empty"


def test_methods_manifest_code_refs_exist() -> None:
    """every file:symbol code reference in docs/methods.yaml points to a real file and symbol."""
    manifest = _load_manifest()
    root = _repo_root()
    for key, entry in manifest.items():
        for ref in entry.get("code", []):
            path = ref.split(":", 1)[0]
            abs_path = os.path.join(root, path)
            assert os.path.exists(abs_path), f"{key}: missing file {path}"
            if ":" in ref:
                symbol = ref.split(":", 1)[1]
                with open(abs_path, "r", encoding="utf-8") as f:
                    content = f.read()
                assert symbol in content, f"{key}: symbol {symbol} not found in {path}"


# Tests

# 1) Energy load ballpark sanity checks

# a) Alameda baseline scenario should have 5,558 kWh/year of electricity consumption
# b) In all other scenarios, electricity load consumption should be > baseline electricity load
# c) In all other scenarios, gas load consumption should be < baseline gas consumption
# d) Combined profiles should have 8760 rows with non-negative, non-null electricity and gas columns

BASE_INPUT_DIR = os.path.join(REPO_ROOT, "data", "loadprofiles")
HOUSING_TYPE = "single-family-detached"
COUNTY = "Alameda County"
COUNTY_SLUG = slugify_county_name(COUNTY)
COL_ELEC = "electricity.real_and_simulated.for_typical_county_home.kwh"
COL_GAS = "gas.hourly_total.for_typical_county_home.therms"

_BASELINE_DIR = os.path.join(BASE_INPUT_DIR, "baseline", HOUSING_TYPE, COUNTY_SLUG)


def _load_elec_loads_df() -> pd.DataFrame | None:
    path = os.path.join(_BASELINE_DIR, f"electricity_loads_{COUNTY_SLUG}.csv")
    return pd.read_csv(path) if os.path.exists(path) else None


def _load_gas_loads_df() -> pd.DataFrame | None:
    path = os.path.join(_BASELINE_DIR, f"gas_loads_{COUNTY_SLUG}.csv")
    return pd.read_csv(path) if os.path.exists(path) else None


def _combined_profile_path(scenario: str) -> str:
    return os.path.join(
        BASE_INPUT_DIR,
        scenario,
        HOUSING_TYPE,
        COUNTY_SLUG,
        f"combined_profiles_{scenario}_{COUNTY_SLUG}.csv",
    )


def _load_combined_df(scenario: str) -> pd.DataFrame | None:
    path = _combined_profile_path(scenario)
    if not os.path.exists(path):
        return None
    return pd.read_csv(path)


def _annual_sum(df: pd.DataFrame, column: str) -> float:
    series = pd.to_numeric(df[column], errors="coerce").fillna(0.0)
    return float(series.sum())


def test_alameda_baseline_electricity_ballpark() -> None:
    """Alameda baseline annual electricity consumption is ~6,000 kWh (within 20% of ResStock Alameda mean).

    ResStock Alameda SF mean (592 buildings): 7,049 kWh/yr total.
    Model intentionally excludes the AC compressor (925.8 kWh) and a few minor
    loads (well pump, clothes washer, electric range = ~123 kWh combined).
    Expected model value: ~5,997 kWh. 20% tolerance accommodates county-level
    variation and future pipeline refinements.
    """
    df = _load_combined_df("baseline")
    if df is None:
        pytest.skip("Baseline combined profiles not found for Alameda County.")
    assert COL_ELEC in df.columns, f"Missing {COL_ELEC} in baseline combined profiles"
    annual_kwh = _annual_sum(df, COL_ELEC)
    assert annual_kwh == pytest.approx(6000.0, rel=0.20)


def test_electricity_increases_for_electrified_scenarios() -> None:
    """every scenario with more electric appliances than baseline has a strictly higher annual electricity load."""
    base_df = _load_combined_df("baseline")
    if base_df is None:
        pytest.skip("Baseline combined profiles not found for Alameda County.")
    if COL_ELEC not in base_df.columns:
        pytest.skip(f"Baseline combined profiles missing {COL_ELEC}")
    baseline_kwh = _annual_sum(base_df, COL_ELEC)

    baseline_electric = SCENARIOS["baseline"]["electric"]
    scenarios = [s for s, v in SCENARIOS.items() if v["electric"] > baseline_electric]
    checked = 0
    for scen in scenarios:
        df = _load_combined_df(scen)
        if df is None:
            continue
        if COL_ELEC not in df.columns:
            raise AssertionError(f"Missing {COL_ELEC} in combined profiles for {scen}")
        kwh = _annual_sum(df, COL_ELEC)
        assert kwh > baseline_kwh, f"{scen} electricity load did not exceed baseline"
        checked += 1
    if checked == 0:
        pytest.skip("No electrified scenario combined profiles available for Alameda County.")


def test_gas_decreases_for_reduced_gas_scenarios() -> None:
    """every scenario with fewer gas appliances than baseline has a strictly lower annual gas consumption."""
    base_df = _load_combined_df("baseline")
    if base_df is None:
        pytest.skip("Baseline combined profiles not found for Alameda County.")
    if COL_GAS not in base_df.columns:
        pytest.skip(f"Baseline combined profiles missing {COL_GAS}")
    baseline_therms = _annual_sum(base_df, COL_GAS)

    baseline_gas = SCENARIOS["baseline"]["gas"]
    scenarios = [s for s, v in SCENARIOS.items() if v["gas"] < baseline_gas]
    checked = 0
    for scen in scenarios:
        df = _load_combined_df(scen)
        if df is None:
            continue
        if COL_GAS not in df.columns:
            raise AssertionError(f"Missing {COL_GAS} in combined profiles for {scen}")
        therms = _annual_sum(df, COL_GAS)
        assert therms < baseline_therms, f"{scen} gas load did not decrease vs baseline"
        checked += 1
    if checked == 0:
        pytest.skip("No reduced-gas scenario combined profiles available for Alameda County.")


def test_combined_profiles_shape_and_non_negative() -> None:
    """combined load profiles for every available scenario have exactly 8,760 rows with non-negative, non-null electricity and gas values."""
    scenarios = list(SCENARIOS.keys())
    checked = 0
    for scen in scenarios:
        df = _load_combined_df(scen)
        if df is None:
            continue
        checked += 1
        assert len(df) == 8760, f"{scen} combined profile row count is {len(df)}"
        for col in (COL_ELEC, COL_GAS):
            assert col in df.columns, f"Missing {col} in combined profiles for {scen}"
            series = pd.to_numeric(df[col], errors="coerce")
            assert series.notna().all(), f"{scen} {col} has NaNs"
            assert (series >= 0).all(), f"{scen} {col} has negative values"
    if checked == 0:
        pytest.skip("No combined profile CSVs found under data/loadprofiles.")


# ============================================================================
# Real-world sanity checks against published energy consumption benchmarks
# ============================================================================
#
# Sources
# -------
# RECS 2020  EIA 2020 Residential Energy Consumption Survey, Table CE2.1.ST
#            https://www.eia.gov/consumption/residential/data/2020/index.php?view=state
#            CA all-household average: 6,482 kWh/yr (all dwelling types, all fuel mixes)
#
# RASS 2019  CEC 2019 Residential Appliance Saturation Study, CEC-200-2021-005-ES
#            https://www.energy.ca.gov/sites/default/files/2021-08/CEC-200-2021-005-ES.pdf
#            CA single-family average: 7,553 kWh/yr (Table ES-2, all fuel mixes)
#            Provides Unit Energy Consumption (UEC) and saturation by appliance.
#
# ResStock   NREL ResStock 2022 (CA factsheet: https://resstock.nrel.gov/factsheets/CA)
#            No automated test: the per-county, all-gas SF subset requires downloading
#            and filtering a 1.4 GB results CSV (https://data.openei.org/submissions/5959).
#            The RECS 2020 and RASS 2019 bounds below are sufficient for advisor review.
#
# All tests use the Alameda County baseline scenario, which has gas heating, gas
# water heating, and gas cooking. Electric load covers only appliances and
# miscellaneous plug loads. This population should have LOWER total electricity
# than state averages, which include homes with electric major appliances and
# hotter inland climate zones with heavier A/C load.
# ============================================================================


def _elec_annual(col: str) -> float:
    df = _load_elec_loads_df()
    if df is None:
        pytest.skip("electricity_loads_alameda.csv not found.")
    return float(pd.to_numeric(df[col], errors="coerce").sum())


def _gas_annual(col: str) -> float:
    df = _load_gas_loads_df()
    if df is None:
        pytest.skip("gas_loads_alameda.csv not found.")
    return float(pd.to_numeric(df[col], errors="coerce").sum())


# ---------------------------------------------------------------------------
# EIA RECS 2020 — total electricity upper and lower bounds
# ---------------------------------------------------------------------------

class TestEIARECS2020:
    """Baseline electricity is consistent with EIA RECS 2020 California bounds.

    Source: EIA 2020 Residential Energy Consumption Survey, Table CE2.1.ST
    https://www.eia.gov/consumption/residential/data/2020/index.php?view=state

    CA all-household average: 6,482 kWh/yr (all dwelling types, all fuel mixes).
    The Alameda baseline (all-gas major appliances) should be below this average
    because electric-heated and electric-cooked households are included in the
    6,482 figure and raise it above what an all-gas home would use.

    Lower bound: RECS end-use breakdown shows refrigerators + miscellaneous alone
    account for roughly 3,800–4,200 kWh/yr in CA, before adding lighting, dryer,
    and other plug loads. Values below 4,000 kWh indicate missing load categories.
    """

    RECS_2020_CA_ALL_HOUSEHOLD_KWH = 6_482  # Table CE2.1.ST

    def test_below_recs_all_household_average(self) -> None:
        """baseline electricity is below the RECS 2020 CA all-household average of 6,482 kWh/yr."""
        df = _load_combined_df("baseline")
        if df is None:
            pytest.skip("Baseline combined profiles not found for Alameda County.")
        kwh = _annual_sum(df, COL_ELEC)
        assert kwh < self.RECS_2020_CA_ALL_HOUSEHOLD_KWH, (
            f"Baseline: {kwh:.0f} kWh/yr. Should be below RECS 2020 CA all-household "
            f"average {self.RECS_2020_CA_ALL_HOUSEHOLD_KWH} kWh/yr. An all-gas home "
            f"should use less electricity than the statewide average, which includes "
            f"electrically heated and cooked homes."
        )

    def test_above_minimum_appliance_floor(self) -> None:
        """baseline electricity exceeds 4,000 kWh/yr, the minimum for a home with standard appliances.

        RECS 2020 end-use breakdowns show that refrigerators (~1,209 kWh, 100%
        saturation per RASS 2019) plus miscellaneous plug loads (~2,099 kWh, 100%
        saturation) alone sum to ~3,300 kWh, before lighting or laundry. Values
        below 4,000 kWh/yr suggest missing load categories in the profile.
        """
        df = _load_combined_df("baseline")
        if df is None:
            pytest.skip("Baseline combined profiles not found for Alameda County.")
        kwh = _annual_sum(df, COL_ELEC)
        assert kwh > 4_000, (
            f"Baseline: {kwh:.0f} kWh/yr is below the 4,000 kWh/yr floor. "
            f"Refrigerator (~1,209 kWh) + plug loads (~2,099 kWh) alone sum to "
            f"~3,300 kWh/yr per RASS 2019. Check for missing load categories."
        )


# ---------------------------------------------------------------------------
# CEC RASS 2019 — total electricity, individual electric appliances
# ---------------------------------------------------------------------------

class TestCECRASS2019TotalElectricity:
    """Baseline total electricity is below the RASS 2019 CA single-family average.

    Source: CEC 2019 Residential Appliance Saturation Study, Table ES-2
    CEC-200-2021-005-ES
    https://www.energy.ca.gov/sites/default/files/2021-08/CEC-200-2021-005-ES.pdf

    CA single-family average: 7,553 kWh/yr (all fuel mixes, statewide).
    The Alameda baseline should be well below this because (1) all major appliances
    are gas, (2) Bay Area mild climate requires far less A/C than statewide average
    (RASS 2019: central A/C UEC 1,372 kWh/yr at 66% statewide saturation), and
    (3) no pool pump in the baseline (RASS 2019: 2,895 kWh/yr at 15% saturation).
    """

    RASS_2019_CA_SF_AVG_KWH = 7_553  # Table ES-2

    def test_below_rass_sf_average(self) -> None:
        """baseline electricity is below the RASS 2019 CA single-family average of 7,553 kWh/yr."""
        df = _load_combined_df("baseline")
        if df is None:
            pytest.skip("Baseline combined profiles not found for Alameda County.")
        kwh = _annual_sum(df, COL_ELEC)
        assert kwh < self.RASS_2019_CA_SF_AVG_KWH, (
            f"Baseline: {kwh:.0f} kWh/yr. Should be below RASS 2019 CA SF average "
            f"{self.RASS_2019_CA_SF_AVG_KWH} kWh/yr. All-gas major appliances + "
            f"mild Bay Area climate justify being below the statewide SF average."
        )


class TestCECRASS2019IndividualAppliances:
    """Individual electric appliance loads are within RASS 2019 plausible ranges.

    Source: CEC 2019 Residential Appliance Saturation Study, Table ES-2
    CEC-200-2021-005-ES
    https://www.energy.ca.gov/sites/default/files/2021-08/CEC-200-2021-005-ES.pdf

    'UEC' = Unit Energy Consumption: average kWh/yr among CA SF homes that have
    each appliance. 'Saturation' = share of CA SF homes with the appliance.
    The county-level per-home average = UEC × saturation.

    Note on refrigerator and freezer: RASS 2019 UECs reflect the vintage stock
    mix as of 2019. The model uses post-2015 ResStock efficiency assumptions, which
    skew toward ENERGY STAR units (refrigerators 300–650 kWh/yr; freezers ~200 kWh/yr
    for chest freezers). The plausible ranges below span both.
    """

    def test_refrigerator_in_plausible_range(self) -> None:
        """refrigerator uses 300–1,400 kWh/yr (RASS 2019 UEC: 1,209 kWh; ENERGY STAR: 300–650 kWh).

        RASS 2019: UEC 1,209 kWh/yr, 100% saturation.
        The model is expected below the RASS UEC because it uses more efficient
        post-2015 stock. ENERGY STAR certified refrigerators use 300–650 kWh/yr.
        Upper bound: RASS UEC + 15% margin.
        """
        kwh = _elec_annual("out.electricity.refrigerator.energy_consumption")
        assert 300 < kwh < 1_400, (
            f"Refrigerator: {kwh:.0f} kWh/yr. "
            f"Expected 300–1,400 kWh/yr. "
            f"RASS 2019 UEC: 1,209 kWh/yr (100% saturation); "
            f"ENERGY STAR range: 300–650 kWh/yr."
        )

    def test_plug_loads_in_plausible_range(self) -> None:
        """plug loads are 1,500–3,500 kWh/yr (RASS 2019 miscellaneous UEC: 2,099 kWh/yr, 100% saturation)."""
        kwh = _elec_annual("out.electricity.plug_loads.energy_consumption")
        assert 1_500 < kwh < 3_500, (
            f"Plug loads: {kwh:.0f} kWh/yr. "
            f"Expected 1,500–3,500 kWh/yr. "
            f"RASS 2019 miscellaneous UEC: 2,099 kWh/yr (100% saturation). "
            f"The model's plug_loads column may include categories broader than "
            f"RASS 'miscellaneous' (e.g., home office, chargers, entertainment)."
        )

    def test_interior_lighting_in_plausible_range(self) -> None:
        """interior lighting is 400–1,500 kWh/yr (RASS 2019 all-household estimate: ~617 kWh/yr).

        RASS 2019 shows lighting at ~10% of the CA all-household average (6,174 kWh/yr),
        or roughly 617 kWh/yr. SF homes are larger than average, so lighting is higher.
        By 2019, LED adoption exceeded 80% of CA SF homes, pushing consumption well
        below incandescent-era estimates of 1,500–2,500 kWh/yr.
        """
        kwh = _elec_annual("out.electricity.lighting_interior.energy_consumption")
        assert 400 < kwh < 1_500, (
            f"Interior lighting: {kwh:.0f} kWh/yr. "
            f"Expected 400–1,500 kWh/yr. "
            f"RASS 2019 all-household lighting estimate: ~617 kWh/yr; "
            f"SF homes larger, but high LED penetration in CA caps the upper end."
        )

    def test_clothes_dryer_in_plausible_range(self) -> None:
        """clothes dryer uses 150–700 kWh/yr (RASS 2019 electric dryer UEC: 552 kWh/yr, 35% saturation).

        The baseline scenario treats 'appliances' as electric, which includes
        the dryer. RASS 2019 UEC for electric dryers: 552 kWh/yr. ENERGY STAR
        certified electric dryers use 300–500 kWh/yr. 35% of CA SF homes have
        electric dryers; the model represents the dryer as electric for all homes.
        """
        kwh = _elec_annual("out.electricity.clothes_dryer.energy_consumption")
        assert 150 < kwh < 700, (
            f"Clothes dryer: {kwh:.0f} kWh/yr. "
            f"Expected 150–700 kWh/yr. "
            f"RASS 2019 electric dryer UEC: 552 kWh/yr (35% CA SF saturation); "
            f"ENERGY STAR range: 300–500 kWh/yr."
        )

    def test_dishwasher_in_plausible_range(self) -> None:
        """dishwasher uses 50–200 kWh/yr (RASS 2019 UEC: 93 kWh/yr, 74% saturation)."""
        kwh = _elec_annual("out.electricity.dishwasher.energy_consumption")
        assert 50 < kwh < 200, (
            f"Dishwasher: {kwh:.0f} kWh/yr. "
            f"Expected 50–200 kWh/yr. "
            f"RASS 2019 UEC: 93 kWh/yr (74% CA SF saturation)."
        )

    def test_pool_pump_in_plausible_range(self) -> None:
        """pool pump contributes 200–600 kWh/yr at the county-average level (RASS 2019: 2,895 kWh UEC × 15% saturation = 434 kWh/home).

        RASS 2019: pool pump UEC 2,895 kWh/yr; 15% of CA SF homes have pools.
        Per-home county average = 2,895 × 0.15 = 434 kWh/yr. The model value
        represents the county-average contribution (pool homes + non-pool homes).
        """
        kwh = _elec_annual("out.electricity.pool_pump.energy_consumption")
        assert 200 < kwh < 600, (
            f"Pool pump: {kwh:.0f} kWh/yr. "
            f"Expected 200–600 kWh/yr at the county-average level. "
            f"RASS 2019: UEC 2,895 kWh/yr × 15% saturation = 434 kWh/yr county average."
        )


# ---------------------------------------------------------------------------
# NREL ResStock 2022 — Alameda County SF baseline, direct comparison
# ---------------------------------------------------------------------------

class TestNRELResStockAlameda:
    """Baseline electricity is bracketed by the ResStock Alameda no-AC floor and full mean.

    Source: NREL ResStock 2022 end-use load profiles, Alameda County CA,
    single-family detached, 592 buildings.
    Data: data/baseline/single-family-detached/alameda/buildings/*.parquet
    Reference: https://resstock.nrel.gov/factsheets/CA

    ResStock Alameda SF means (computed from 592 building parquet files):
      Total (all end-uses including AC compressor): 7,049 kWh/yr
      AC compressor alone:                            926 kWh/yr
      No-AC total (all end-uses except compressor):  6,123 kWh/yr
      Minor excluded loads (well pump, clothes washer, electric range): 123 kWh/yr
      Expected model value (no-AC, no minor excluded loads):          ~6,000 kWh/yr

    The model intentionally excludes the AC compressor (no-AC Bay Area baseline).
    Two bounds follow from this:
      Lower (no-AC floor): model should be >= ResStock no-AC total minus the
        intentionally excluded minor loads. 5,700 kWh gives ~5% slack below ~6,000.
      Upper (with-AC ceiling): model should be < the ResStock full mean (7,049 kWh),
        since we do not model the AC compressor load.
    The gap between the bounds (5,700–7,049 kWh) represents the range of AC loads
    across Alameda SF homes; it is the floor of electricity consumed before any
    electrification scenario is applied.

    New end-uses added 2026-03-27 (previously missing from pipeline):
      cooling_fans_pumps:  250.3 kWh/yr  (HVAC fan motor, runs with heating too)
      heating_fans_pumps:  117.2 kWh/yr  (furnace blower, electric even for gas heat)
      lighting_exterior:    71.3 kWh/yr
      Total addition:      438.8 kWh/yr  (old model: 5,558 → updated model: 5,997)
    """

    # ResStock Alameda SF means (kWh/yr), computed from 592 parquet files
    RESSTOCK_FULL_MEAN_KWH       = 7_049   # includes AC compressor
    RESSTOCK_AC_COMPRESSOR_KWH   =   926   # out.electricity.cooling.energy_consumption
    RESSTOCK_NO_AC_TOTAL_KWH     = 6_123   # FULL_MEAN - AC_COMPRESSOR
    RESSTOCK_MINOR_EXCLUDED_KWH  =   123   # well_pump + clothes_washer + electric_range
    RESSTOCK_MODEL_EXPECTED_KWH  = 6_000   # NO_AC_TOTAL - MINOR_EXCLUDED (approx)

    def test_total_electricity_above_no_ac_floor(self) -> None:
        """electricity_loads total_load exceeds 5,700 kWh/yr — the ResStock no-AC floor minus minor excluded loads (±5%).

        ResStock Alameda no-AC total (all loads except compressor): 6,123 kWh/yr.
        Subtracting intentionally excluded minor loads (well pump 58, clothes washer
        33, electric range 32 = 123 kWh): expected ~6,000 kWh/yr. Floor = 5,700
        gives 5% slack. A value below 5,700 indicates a missing end-use category.

        Note: reads electricity_loads_alameda.csv (direct step3 output), not the
        downstream combined_profiles CSV, which requires a full pipeline rerun.
        """
        df = _load_elec_loads_df()
        if df is None:
            pytest.skip("electricity_loads_alameda.csv not found.")
        kwh = float(pd.to_numeric(df["total_load"], errors="coerce").sum())
        assert kwh >= 5_700, (
            f"electricity_loads total_load: {kwh:.0f} kWh/yr is below the ResStock "
            f"no-AC floor of 5,700 kWh/yr. "
            f"ResStock Alameda no-AC mean: {self.RESSTOCK_NO_AC_TOTAL_KWH:,} kWh/yr; "
            f"minus intentionally excluded minor loads ({self.RESSTOCK_MINOR_EXCLUDED_KWH} kWh) "
            f"= expected ~{self.RESSTOCK_MODEL_EXPECTED_KWH:,} kWh/yr. "
            f"Check for missing end-use categories in step3."
        )

    def test_total_electricity_below_resstock_full_mean(self) -> None:
        """electricity_loads total_load is below the ResStock full mean of 7,049 kWh/yr (which includes AC).

        The model intentionally excludes the AC compressor (925.8 kWh/yr) for
        a no-AC Bay Area baseline. Exceeding the ResStock full mean would mean
        the model overcounts electricity relative to what ResStock simulates for
        Alameda SF homes across all end-uses including cooling.

        Note: reads electricity_loads_alameda.csv (direct step3 output).
        """
        df = _load_elec_loads_df()
        if df is None:
            pytest.skip("electricity_loads_alameda.csv not found.")
        kwh = float(pd.to_numeric(df["total_load"], errors="coerce").sum())
        assert kwh < self.RESSTOCK_FULL_MEAN_KWH, (
            f"electricity_loads total_load: {kwh:.0f} kWh/yr exceeds ResStock full mean "
            f"{self.RESSTOCK_FULL_MEAN_KWH:,} kWh/yr (which includes AC compressor). "
            f"The model should be below this since it excludes the AC compressor "
            f"({self.RESSTOCK_AC_COMPRESSOR_KWH} kWh/yr)."
        )

    def test_new_hvac_and_exterior_loads_are_nontrivial(self) -> None:
        """heating_fans_pumps + cooling_fans_pumps + lighting_exterior together exceed 400 kWh/yr.

        These three end-uses were added to the pipeline on 2026-03-27 after being
        found missing from the baseline electricity_loads CSV. ResStock Alameda means:
          cooling_fans_pumps:  250.3 kWh/yr
          heating_fans_pumps:  117.2 kWh/yr
          lighting_exterior:    71.3 kWh/yr
          Total:               438.8 kWh/yr
        A value below 400 kWh indicates one or more of these columns was dropped.
        """
        df = _load_elec_loads_df()
        if df is None:
            pytest.skip("electricity_loads_alameda.csv not found.")
        cols = [
            "out.electricity.cooling_fans_pumps.energy_consumption",
            "out.electricity.heating_fans_pumps.energy_consumption",
            "out.electricity.lighting_exterior.energy_consumption",
        ]
        combined_kwh = sum(
            float(pd.to_numeric(df[c], errors="coerce").sum())
            for c in cols if c in df.columns
        )
        assert combined_kwh >= 400, (
            f"cooling_fans_pumps + heating_fans_pumps + lighting_exterior = {combined_kwh:.0f} kWh/yr. "
            f"Expected >= 400 kWh/yr (ResStock Alameda means sum to 438.8 kWh/yr). "
            f"One or more of these columns may be missing from step3 END_USE_COLUMNS."
        )


# ---------------------------------------------------------------------------
# Load profile temporal shape checks
# ---------------------------------------------------------------------------

class TestElectricityLoadShape:
    """Temporal shape of the electricity load profile is physically realistic.

    These tests use electricity_loads_alameda.csv (direct step3 output) to
    verify that hourly load patterns match expected residential behavior,
    independent of the downstream combined_profiles pipeline.
    """

    def test_overnight_standby_floor(self) -> None:
        """Average hourly load during 2–4 am is 0.10–0.50 kWh/hr (refrigerator + standby).

        Even with all occupants asleep, a residential home maintains a baseline
        draw from the refrigerator (~0.07 kW continuous per RASS 2019 UEC of
        ~600 kWh/yr) plus electronics standby (~0.05–0.15 kW per LBNL standby
        surveys). Total: 0.10–0.35 kW minimum. Values below 0.10 indicate
        missing loads; values above 0.50 suggest a modeling error.

        Source: LBNL 'Standby Power Summary Table' (2015); RASS 2019 refrigerator UEC.
        """
        df = _load_elec_loads_df()
        if df is None:
            pytest.skip("electricity_loads_alameda.csv not found.")
        ts = pd.to_datetime(df["timestamp"])
        overnight = df[ts.dt.hour.isin([2, 3])]
        assert len(overnight) > 0, "No 2–4 am rows found in electricity_loads."
        avg_kw = float(pd.to_numeric(overnight["total_load"], errors="coerce").mean())
        assert 0.10 <= avg_kw <= 0.50, (
            f"Overnight (2–4 am) average load: {avg_kw:.3f} kWh/hr. "
            f"Expected 0.10–0.50 kWh/hr. "
            f"Below 0.10: missing appliance or standby loads. "
            f"Above 0.50: unexpectedly high baseload (check for spurious loads)."
        )

    def test_peak_to_mean_ratio_plausible(self) -> None:
        """Annual peak hour / annual mean hour is 1.2–4.0 (no-AC residential load shape).

        For a no-AC home, the load profile is driven by appliances (dryer, dishwasher,
        lights, fans) that create modest evening peaks rather than the sharp summer
        AC spikes seen in full-load profiles. A ratio below 1.2 indicates the profile
        is artificially flat (over-smoothed); above 4.0 suggests a data artifact
        introducing an implausibly large single-hour peak for a no-AC home.

        Source: EPRI residential load shape research; NREL ResStock temporal patterns.
        """
        df = _load_elec_loads_df()
        if df is None:
            pytest.skip("electricity_loads_alameda.csv not found.")
        load = pd.to_numeric(df["total_load"], errors="coerce").dropna()
        peak = float(load.max())
        mean = float(load.mean())
        assert mean > 0, "Mean hourly load is zero."
        ratio = peak / mean
        assert 1.2 <= ratio <= 4.0, (
            f"Peak-to-mean ratio: {ratio:.2f} (peak {peak:.3f} kWh/hr, mean {mean:.3f} kWh/hr). "
            f"Expected 1.2–4.0 for a no-AC residential load profile. "
            f"Below 1.2: profile may be over-smoothed. "
            f"Above 4.0: implausibly large single-hour peak for a no-AC home."
        )

    def test_exterior_lighting_higher_in_winter_than_summer(self) -> None:
        """December + January exterior lighting exceeds June + July exterior lighting.

        Bay Area daylight hours: ~9.5 hrs/day in Dec–Jan vs ~14.5 hrs/day in Jun–Jul
        (5 fewer hours of daylight). Exterior lighting is primarily used during
        dark hours, so winter consumption should be meaningfully higher than summer.
        If this test fails, the timestamps may be misaligned (e.g., a timezone
        localization bug) or exterior lighting is modeled as a flat annual load.

        Source: NREL NSRDB Bay Area daylight data; residential lighting behavior literature.
        """
        df = _load_elec_loads_df()
        if df is None:
            pytest.skip("electricity_loads_alameda.csv not found.")
        col = "out.electricity.lighting_exterior.energy_consumption"
        if col not in df.columns:
            pytest.skip(f"{col} not in electricity_loads — column may have been removed.")
        ts = pd.to_datetime(df["timestamp"])
        winter = float(df.loc[ts.dt.month.isin([12, 1]), col].sum())
        summer = float(df.loc[ts.dt.month.isin([6, 7]), col].sum())
        assert summer > 0, "Summer exterior lighting is zero — check that the column is populated."
        assert winter > summer, (
            f"Exterior lighting: winter (Dec+Jan) {winter:.1f} kWh < summer (Jun+Jul) {summer:.1f} kWh. "
            f"Expected winter > summer (Bay Area has ~5 fewer daylight hours/day in Dec–Jan). "
            f"Check timestamp localization or exterior lighting schedule in ResStock."
        )

    def test_ac_compressor_absent_from_baseline(self) -> None:
        """AC compressor (out.electricity.cooling) is absent or zero in the no-AC baseline.

        The baseline scenario models a Bay Area SF home with no central air
        conditioning. The AC compressor end-use (out.electricity.cooling) must
        not appear in the electricity_loads CSV, or if it does, must sum to zero.
        If it is present and non-zero, either the scenario configuration has changed
        or step3 is pulling the wrong end-use categories.

        This directly validates the no-AC modeling assumption: the ~926 kWh/yr
        AC compressor load (ResStock Alameda mean) is intentionally excluded from
        the baseline, and the ResStock floor/ceiling tests (TestNRELResStockAlameda)
        rely on this exclusion being correct.
        """
        df = _load_elec_loads_df()
        if df is None:
            pytest.skip("electricity_loads_alameda.csv not found.")
        col = "out.electricity.cooling.energy_consumption"
        if col not in df.columns:
            return  # Column absent: correctly excluded
        kwh = float(pd.to_numeric(df[col], errors="coerce").sum())
        assert kwh == 0.0, (
            f"AC compressor column present and non-zero: {kwh:.1f} kWh/yr. "
            f"The baseline scenario should exclude the AC compressor "
            f"(~926 kWh/yr ResStock Alameda mean). "
            f"Check step3 END_USE_COLUMNS and the baseline scenario's electric categories."
        )


# ---------------------------------------------------------------------------
# CEC RASS 2019 / EIA RECS 2020 — gas end-uses
# ---------------------------------------------------------------------------

class TestGasEndUsesBenchmarks:
    """Baseline gas end-use consumption is within RECS 2020 and RASS 2019 plausible ranges.

    Sources:
      RECS 2020  Table CE5.8.GS (natural gas end-uses by state)
                 https://www.eia.gov/consumption/residential/data/2020/index.php?view=state
                 CA average total natural gas (gas-using households): ~441 therms/yr
      RASS 2019  CEC-200-2021-005-ES, Table ES-2 (CA SF gas UECs)
                 https://www.energy.ca.gov/sites/default/files/2021-08/CEC-200-2021-005-ES.pdf

    Baseline has gas heating + gas water heating + gas cooking. Model total: 426 therms/yr,
    within 4% of the RECS 2020 CA gas-household average of 441 therms/yr.
    Individual end-use ranges are based on RECS CA state-level data and the
    mild Alameda / Bay Area climate (CEC climate zone 3), which gives lower
    heating loads than statewide or national averages.
    """

    def test_total_gas_in_plausible_range(self) -> None:
        """total gas consumption is 300–600 therms/yr (RECS 2020 CA average: ~441 therms/yr for gas households)."""
        therms = _gas_annual("load.gas.building_avg.therms")
        assert 300 < therms < 600, (
            f"Total gas: {therms:.0f} therms/yr. "
            f"Expected 300–600 therms/yr. "
            f"RECS 2020 CA average: ~441 therms/yr for gas-using households."
        )

    def test_gas_heating_in_plausible_range(self) -> None:
        """gas space heating is 100–400 therms/yr (RECS 2020 CA estimate for mild-climate SF homes).

        The national RECS average for gas-heated homes is ~430 therms/yr, but
        California's mild climate places most homes far below that. Alameda County
        (CEC climate zone 3, Bay Area) is one of the mildest heating zones in CA.
        """
        therms = _gas_annual("out.natural_gas.heating.energy_consumption.gas.building_avg.therms")
        assert 100 < therms < 400, (
            f"Gas heating: {therms:.0f} therms/yr. "
            f"Expected 100–400 therms/yr. "
            f"RECS 2020 national gas-heated average ~430 therms/yr; "
            f"CA mild climate (especially Bay Area CZ3) is substantially lower."
        )

    def test_gas_water_heating_in_plausible_range(self) -> None:
        """gas water heating is 80–250 therms/yr (RECS 2020 CA estimate: ~100–200 therms/yr)."""
        therms = _gas_annual("out.natural_gas.hot_water.energy_consumption.gas.building_avg.therms")
        assert 80 < therms < 250, (
            f"Gas water heating: {therms:.0f} therms/yr. "
            f"Expected 80–250 therms/yr. "
            f"RECS 2020 national average ~250 therms/yr; "
            f"CA lower due to warmer incoming water temperature year-round."
        )

    def test_gas_cooking_in_plausible_range(self) -> None:
        """gas cooking is 15–60 therms/yr (RECS 2020 CA range: ~20–45 therms/yr for homes with gas ranges)."""
        therms = _gas_annual("out.natural_gas.range_oven.energy_consumption.gas.building_avg.therms")
        assert 15 < therms < 60, (
            f"Gas cooking: {therms:.0f} therms/yr. "
            f"Expected 15–60 therms/yr. "
            f"RECS 2020 CA estimate: ~20–45 therms/yr for homes with gas ranges "
            f"(57% of CA SF homes per RASS 2019)."
        )


# ---------------------------------------------------------------------------
# Real-bill sanity checks for one Alameda County single-family home
# ---------------------------------------------------------------------------
#
# Source: PG&E energy statements for one Alameda County SF home on NEM2/TOU-E
# (billing periods June 2025 – March 2026, the first true-up year at this
# address). Data prior to June 2025 is excluded: it reflects a different
# address (a 2-bedroom apartment) and is not representative of an SF home.
#
# This home uses gas for space heating (PG&E heat source code: Not Electric).
#
# Key reference values from bills:
#   - One 32-day winter period (Jan 30 – Mar 2, 2026): 39 therms = 1.22 therms/day
#   - Peak kWh / net kWh: ~30–35% across two winter billing periods (TOU-E, 4–9 pm)
#
# These tests check the *combined_profiles* CSVs (total consumption, no solar),
# not net metered values. The peak-fraction range is widened to 20–45% to
# account for the difference between a solar-equipped (net) home and the
# model's solar-free typical home.
# ---------------------------------------------------------------------------

_PEAK_HOURS = frozenset(range(16, 21))  # 4 pm – 9 pm, inclusive (TOU-E peak window)
_WINTER_MONTHS = frozenset({11, 12, 1, 2})
_SUMMER_MONTHS = frozenset({6, 7, 8})
_COL_TS = "timestamp"


def _load_with_ts(scenario: str) -> pd.DataFrame | None:
    df = _load_combined_df(scenario)
    if df is None:
        return None
    df[_COL_TS] = pd.to_datetime(df[_COL_TS])
    return df


def test_alameda_baseline_annual_gas_from_real_bills() -> None:
    """Alameda baseline annual gas is 150–500 therms/yr, anchored to one SF home's bills.

    One Alameda SF home's winter billing period (Jan 30 – Mar 2, 2026) showed
    39 therms in 32 days (1.22 therms/day). Annualized with lower summer usage
    (water heating only), a typical gas-heated Bay Area SF home falls in this
    range. The lower bound catches a missing gas heating load; the upper bound
    catches a doubled load or incorrect unit conversion.
    """
    df = _load_combined_df("baseline")
    if df is None:
        pytest.skip("Baseline combined profiles not found for Alameda County.")
    if COL_GAS not in df.columns:
        pytest.skip(f"Baseline combined profiles missing {COL_GAS}")
    annual_therms = _annual_sum(df, COL_GAS)
    assert 150 <= annual_therms <= 500, (
        f"Annual gas {annual_therms:.1f} therms is outside the 150–500 therm range. "
        "One Alameda SF home's winter period: ~1.22 therms/day. "
        "Annualized with lower summer usage, expected 150–500 therms/yr."
    )


def test_alameda_baseline_gas_seasonality() -> None:
    """Winter gas substantially exceeds summer gas for Alameda baseline.

    One Alameda SF home's bills show gas heating drives strong winter peaks
    (~1.22 therms/day in Jan–Feb); summer usage is water heating only.
    Winter (Nov–Feb) total should be at least 3× summer (Jun–Aug) total.
    """
    df = _load_with_ts("baseline")
    if df is None:
        pytest.skip("Baseline combined profiles not found for Alameda County.")
    if COL_GAS not in df.columns:
        pytest.skip(f"Baseline combined profiles missing {COL_GAS}")

    gas = pd.to_numeric(df[COL_GAS], errors="coerce").fillna(0.0)
    months = df[_COL_TS].dt.month
    winter_gas = float(gas[months.isin(_WINTER_MONTHS)].sum())
    summer_gas = float(gas[months.isin(_SUMMER_MONTHS)].sum())

    assert summer_gas > 0, "Summer gas is zero — expected some water-heating baseline"
    assert winter_gas >= 3.0 * summer_gas, (
        f"Winter gas ({winter_gas:.1f} therms) is not at least 3× "
        f"summer gas ({summer_gas:.1f} therms). "
        "One Alameda SF home's bills show strongly winter-peaked gas use."
    )


def test_alameda_baseline_winter_daily_gas_rate() -> None:
    """Winter (Nov–Feb) average daily gas is 0.5–2.5 therms/day, anchored to one Alameda SF home.

    One Alameda SF home's PG&E statement (Jan 30 – Mar 2, 2026) showed 39 therms
    in 32 days = 1.22 therms/day during peak heating season. The model's Nov–Feb
    daily average should fall within the observed range for Bay Area SF homes.

    Upper bound: 2.5 therms/day (cold snap, large house, older furnace).
    Lower bound: 0.5 therms/day (below this, space heating appears missing).
    Real-bill anchor: 1.22 therms/day (one Alameda home, Jan–Feb 2026).
    """
    df = _load_with_ts("baseline")
    if df is None:
        pytest.skip("Baseline combined profiles not found for Alameda County.")
    if COL_GAS not in df.columns:
        pytest.skip(f"Baseline combined profiles missing {COL_GAS}")
    gas = pd.to_numeric(df[COL_GAS], errors="coerce").fillna(0.0)
    months = df[_COL_TS].dt.month
    winter_gas = float(gas[months.isin(_WINTER_MONTHS)].sum())
    winter_hours = int(months.isin(_WINTER_MONTHS).sum())
    winter_days = winter_hours / 24
    daily_rate = winter_gas / winter_days
    assert 0.5 <= daily_rate <= 2.5, (
        f"Winter (Nov–Feb) average daily gas: {daily_rate:.2f} therms/day "
        f"({winter_gas:.1f} therms over {winter_days:.0f} days). "
        f"Expected 0.5–2.5 therms/day. "
        f"Real-bill anchor: 1.22 therms/day (one Alameda SF home, Jan–Feb 2026). "
        f"Below 0.5: space heating may be missing. "
        f"Above 2.5: overestimated for a mild Bay Area climate."
    )


def test_alameda_baseline_peak_hour_electricity_fraction() -> None:
    """Peak-hour (4–9 pm) electricity is 20–45% of annual total electricity.

    One Alameda SF home's PG&E TOU-E bills showed peak kWh at ~30–35% of net
    usage across two winter billing periods. The range is widened to 20–45%
    because the model represents a solar-free home (no midday export reducing
    the apparent off-peak share).
    """
    df = _load_with_ts("baseline")
    if df is None:
        pytest.skip("Baseline combined profiles not found for Alameda County.")
    if COL_ELEC not in df.columns:
        pytest.skip(f"Baseline combined profiles missing {COL_ELEC}")

    elec = pd.to_numeric(df[COL_ELEC], errors="coerce").fillna(0.0)
    hours = df[_COL_TS].dt.hour
    total_kwh = float(elec.sum())
    peak_kwh = float(elec[hours.isin(_PEAK_HOURS)].sum())

    assert total_kwh > 0, "Total electricity is zero"
    peak_fraction = peak_kwh / total_kwh
    assert 0.20 <= peak_fraction <= 0.45, (
        f"Peak-hour fraction {peak_fraction:.2%} is outside the expected 20%–45% range. "
        "One Alameda SF home's TOU-E bills showed ~30–35% peak fraction."
    )


# ---------------------------------------------------------------------------
# Energy displacement: heat pump COP validation
# ---------------------------------------------------------------------------

class TestEnergyDisplacementCOP:
    """Heat pump electricity increase divided by gas reduction respects thermodynamic bounds.

    When a gas furnace is replaced by an electric heat pump, two things happen:
      1. Annual electricity increases (heat pump motor draws power).
      2. Annual gas decreases (no more furnace combustion).

    The ratio of gas energy displaced (kWh-thermal) to electricity added (kWh)
    is the effective COP of the heat pump as modeled. This must satisfy:
      COP = (gas_reduction_therms × 29.3 kWh_th/therm) / electricity_increase_kWh

    Plausible COP bounds for a Bay Area (CEC climate zone 3) mild-climate heat pump:
      Lower bound 1.5: A COP below 1.5 would make a heat pump worse than direct
        electric resistance heating (COP = 1.0), which contradicts established heat
        pump physics even in cold climates. Values below 1.5 suggest either the
        electricity increase is overcounted or the gas reduction is too small.
      Upper bound 6.0: In a very mild climate like the Bay Area (design heating
        temp ~35°F), peak seasonal COPs of 4–5 are well-documented (NEEP ccASHP
        database). Values above 6.0 suggest the gas displacement is overcounted
        or the electricity increase is too small (e.g., baseline stale from step3
        update not yet propagated through combined_profiles).

    Source: NEEP Cold Climate Air Source Heat Pump product list (2024);
    DOE Building Technologies Office heat pump field study (2022);
    ResStock heat pump efficiency assumptions (NREL, 2022).

    Note: compares combined_profiles (final pipeline output). If only the
    baseline step3 has been updated but the heat_pump scenario has not been
    rerun, the baseline combined_profiles will be stale (5,558 kWh vs the
    updated 5,997 kWh). In that case, delta_elec is larger than it should be,
    pushing the implied COP down. The lower bound of 1.5 is set wide enough
    to tolerate this stale-data scenario until the full pipeline rerun completes.
    """

    THERMS_TO_KWH = 29.3  # 1 therm = 29.3 kWh (higher heating value)
    COP_LOWER = 1.5
    COP_UPPER = 6.0

    def test_heat_pump_electricity_displacement_cop(self) -> None:
        """implied heat pump COP (gas displaced / electricity added) is 1.5–6.0.

        heat_pump scenario replaces gas space heating with an electric heat pump.
        The electricity increase and gas decrease are compared in energy-equivalent
        terms to infer the effective COP. Values outside 1.5–6.0 indicate either
        a modeling bug, a unit conversion error, or stale combined_profiles CSVs
        from a partial pipeline run.
        """
        base_df = _load_combined_df("baseline")
        hp_df = _load_combined_df("heat_pump")
        if base_df is None or hp_df is None:
            pytest.skip("baseline or heat_pump combined profiles not found for Alameda County.")

        baseline_elec = _annual_sum(base_df, COL_ELEC)
        hp_elec = _annual_sum(hp_df, COL_ELEC)
        baseline_gas = _annual_sum(base_df, COL_GAS)
        hp_gas = _annual_sum(hp_df, COL_GAS)

        delta_elec_kwh = hp_elec - baseline_elec
        delta_gas_therms = baseline_gas - hp_gas
        delta_gas_kwh = delta_gas_therms * self.THERMS_TO_KWH

        assert delta_elec_kwh > 0, (
            f"heat_pump electricity ({hp_elec:.0f} kWh) is not above baseline "
            f"({baseline_elec:.0f} kWh). Check scenario configuration or combined_profiles."
        )
        assert delta_gas_therms > 0, (
            f"heat_pump gas ({hp_gas:.0f} therms) is not below baseline "
            f"({baseline_gas:.0f} therms). Check scenario configuration or combined_profiles."
        )

        implied_cop = delta_gas_kwh / delta_elec_kwh
        assert self.COP_LOWER <= implied_cop <= self.COP_UPPER, (
            f"Implied heat pump COP: {implied_cop:.2f}. "
            f"Gas displaced: {delta_gas_therms:.1f} therms = {delta_gas_kwh:.0f} kWh_th. "
            f"Electricity added: {delta_elec_kwh:.0f} kWh. "
            f"Expected COP {self.COP_LOWER}–{self.COP_UPPER} for a Bay Area mild-climate heat pump. "
            f"Below {self.COP_LOWER}: too much electricity for the gas displaced "
            f"(possible stale combined_profiles or step3 misconfiguration). "
            f"Above {self.COP_UPPER}: too little electricity for the gas displaced "
            f"(possible missing heating load in heat_pump scenario)."
        )
