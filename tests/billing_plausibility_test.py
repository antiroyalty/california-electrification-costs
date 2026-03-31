"""Billing dollar-amount sanity checks against EIA data and real PG&E bills.

Tests validate that the pipeline's computed annual energy costs are within
real-world plausible ranges, using published EIA data and one Alameda SF
household's actual PG&E bills as anchors.

Sources:
  EIA Electric Power Monthly Table 5.6a (2023):
    CA residential average electricity expenditure: ~$1,800/yr (all dwelling types).
    Single-family homes are larger and use more — typical range $1,500–$3,500/yr.
    https://www.eia.gov/electricity/monthly/

  EIA 2020 Residential Energy Consumption Survey (RECS), Table CE4.1.ST:
    CA residential total energy expenditure (electricity + gas): ~$1,900–$2,600/yr
    (all dwelling types). Single-family gas-heated homes in a high-rate utility
    territory (PG&E) are toward the high end: $2,500–$5,000/yr is plausible.
    https://www.eia.gov/consumption/residential/data/2020/index.php?view=state

  LBNL "Tracking the Sun 2024":
    Typical CA solar+storage households see 60–85% reduction in electricity bill.
    https://emp.lbl.gov/tracking-the-sun

  Real-bill anchor: One Alameda SF home on NEM2/TOU-E (June 2025–March 2026):
    Net electricity cost before true-up: estimated $100–$250/yr with solar+storage.

Results are read from the most recent versioned output CSV in:
  data/loadprofiles/baseline/single-family-detached/alameda/results/

All tests skip gracefully if the results files are absent.
"""
import glob
import os
import sys

import pandas as pd
import pytest

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from helpers.main_helpers import slugify_county_name

COUNTY = "Alameda County"
COUNTY_SLUG = slugify_county_name(COUNTY)
HOUSING_TYPE = "single-family-detached"
RESULTS_DIR = os.path.join(
    REPO_ROOT, "data", "loadprofiles", "baseline",
    HOUSING_TYPE, COUNTY_SLUG, "results",
)

_BASELINE_ROW = "baseline"
_SOLAR_ROW = "baseline.solarstorage"

# Representative rate plans used for cross-checks (E-TOU-C is the paper's primary plan).
_ELEC_COL_BASELINE    = "electricity.PG&E.E-TOU-C"
_ELEC_COL_SOLAR       = "electricity.PG&E.E-TOU-C"
_ELEC_COL_SOLAR_NEM3  = "electricity.PG&E.E-TOU-C_NEM3"
_TOTAL_COL_BASELINE   = "total.PG&E.E-TOU-C+PG&E.G-1"
_TOTAL_COL_SOLAR      = "total.PG&E.E-TOU-C+PG&E.G-1"
_TOTAL_COL_SOLAR_NEM3 = "total.PG&E.E-TOU-C_NEM3+PG&E.G-1"


def _latest_csv(subdir: str, pattern: str) -> str | None:
    files = sorted(glob.glob(os.path.join(RESULTS_DIR, subdir, pattern)))
    return files[-1] if files else None


def _load_electricity_results() -> pd.DataFrame | None:
    path = _latest_csv("electricity", f"RESULTS_electricity_annual_costs_{COUNTY_SLUG}_*.csv")
    if path is None:
        return None
    df = pd.read_csv(path)
    df = df.set_index("scenario")
    return df


def _load_total_results() -> pd.DataFrame | None:
    path = _latest_csv("totals", f"RESULTS_total_annual_costs_{COUNTY_SLUG}_*.csv")
    if path is None:
        return None
    df = pd.read_csv(path)
    df = df.set_index("scenario")
    return df


# ---------------------------------------------------------------------------
# Baseline electricity bill plausibility
# ---------------------------------------------------------------------------

class TestBaselineElectricityBill:
    """Baseline annual electricity bill is within the plausible CA SF range.

    Source: EIA Electric Power Monthly Table 5.6a (2023):
      CA residential average: ~$1,800/yr (all dwelling types, ~6,500 kWh × $0.28/kWh avg).
      SF homes are larger and on TOU rates — a range of $1,000–$4,000/yr is appropriate.

    The Alameda baseline has gas heating, gas water heating, and gas cooking.
    Electricity covers only appliances and misc loads (~5,558–6,000 kWh/yr).
    On PG&E E-TOU-C (~$0.35–0.45/kWh blended), this implies ~$1,900–$2,700/yr.
    """

    ELEC_BILL_LOWER = 1_000   # $ — below this, the rate or load is clearly wrong
    ELEC_BILL_UPPER = 4_000   # $ — above this for an all-gas home, something is off

    def test_baseline_electricity_bill_in_plausible_range(self) -> None:
        """baseline annual electricity bill (E-TOU-C) is $1,000–$4,000 for an Alameda SF home."""
        df = _load_electricity_results()
        if df is None:
            pytest.skip("Electricity results CSV not found — run step12 first.")
        if _BASELINE_ROW not in df.index:
            pytest.skip(f"'{_BASELINE_ROW}' row not in electricity results.")
        if _ELEC_COL_BASELINE not in df.columns:
            pytest.skip(f"Column '{_ELEC_COL_BASELINE}' not in electricity results.")
        bill = float(df.loc[_BASELINE_ROW, _ELEC_COL_BASELINE])
        assert self.ELEC_BILL_LOWER <= bill <= self.ELEC_BILL_UPPER, (
            f"Baseline electricity bill (E-TOU-C): ${bill:.0f}/yr. "
            f"Expected ${self.ELEC_BILL_LOWER:,}–${self.ELEC_BILL_UPPER:,}/yr. "
            f"EIA 2023: CA residential average ~$1,800/yr (all types); "
            f"SF home on TOU typically $1,900–$2,700/yr. "
            f"Below ${self.ELEC_BILL_LOWER:,}: check rate calculation or load profile. "
            f"Above ${self.ELEC_BILL_UPPER:,}: check for double-counted load or wrong rate."
        )

    def test_baseline_implied_average_electricity_rate(self) -> None:
        """baseline implied average electricity rate is $0.20–$0.55/kWh (PG&E TOU blended).

        Computed as annual bill / annual kWh. PG&E E-TOU-C blended rate for
        a home without solar is approximately $0.30–$0.45/kWh depending on
        peak-hour fraction. Values outside $0.20–$0.55 indicate a rate
        misconfiguration or a load/bill unit mismatch.

        Source: PG&E E-TOU-C tariff sheet (March 2026):
          Peak rate: $0.4789/kWh; off-peak: $0.2863/kWh.
          https://www.pge.com/tariffs/assets/pdf/tariffbook/ELEC_SCHEDS_E-TOU-C.pdf
        """
        df_elec = _load_electricity_results()
        if df_elec is None:
            pytest.skip("Electricity results CSV not found — run step12 first.")
        if _BASELINE_ROW not in df_elec.index:
            pytest.skip(f"'{_BASELINE_ROW}' row not in electricity results.")

        # Load the combined profiles to get annual kWh
        combined_path = os.path.join(
            REPO_ROOT, "data", "loadprofiles", "baseline",
            HOUSING_TYPE, COUNTY_SLUG,
            f"combined_profiles_baseline_{COUNTY_SLUG}.csv",
        )
        if not os.path.exists(combined_path):
            pytest.skip("combined_profiles_baseline_alameda.csv not found.")

        combined = pd.read_csv(combined_path)
        elec_col = "electricity.real_and_simulated.for_typical_county_home.kwh"
        if elec_col not in combined.columns:
            pytest.skip(f"Column '{elec_col}' not in combined profiles.")

        annual_kwh = float(pd.to_numeric(combined[elec_col], errors="coerce").sum())
        if annual_kwh <= 0:
            pytest.skip("Annual electricity load is zero — combined profiles may be empty.")

        bill = float(df_elec.loc[_BASELINE_ROW, _ELEC_COL_BASELINE])
        implied_rate = bill / annual_kwh

        assert 0.20 <= implied_rate <= 0.55, (
            f"Implied average electricity rate: ${implied_rate:.4f}/kWh "
            f"(${bill:.0f} / {annual_kwh:.0f} kWh). "
            f"Expected $0.20–$0.55/kWh for PG&E TOU. "
            f"PG&E E-TOU-C: peak $0.4789/kWh, off-peak $0.2863/kWh (March 2026). "
            f"Outside this range: check rate plan definition or load units (kWh vs MWh)."
        )


# ---------------------------------------------------------------------------
# Total household energy cost (electricity + gas)
# ---------------------------------------------------------------------------

class TestTotalHouseholdEnergyCost:
    """Baseline total annual energy cost (electricity + gas) is within CA SF norms.

    Source: EIA 2020 RECS, Table CE4.1.ST:
      CA residential total energy expenditure: ~$1,900–$2,600/yr (all types).
      Single-family gas-heated homes in PG&E territory are above average due to
      higher rates and larger square footage: $2,500–$5,500/yr is plausible.

    The model's baseline: gas ~$1,190/yr (426 therms × $2.80/therm avg) +
      electricity ~$2,185/yr = ~$3,375/yr total. This is above the statewide
      average but reasonable for a larger SF home in a high-rate utility territory.
    """

    TOTAL_LOWER = 2_000   # $ — below this: missing gas or electricity component
    TOTAL_UPPER = 5_500   # $ — above this: overcounting or wrong rate territory

    def test_baseline_total_cost_in_plausible_range(self) -> None:
        """baseline annual gas + electricity cost (E-TOU-C + G-1) is $2,000–$5,500."""
        df = _load_total_results()
        if df is None:
            pytest.skip("Total costs CSV not found — run step13 first.")
        if _BASELINE_ROW not in df.index:
            pytest.skip(f"'{_BASELINE_ROW}' row not in total costs.")
        if _TOTAL_COL_BASELINE not in df.columns:
            pytest.skip(f"Column '{_TOTAL_COL_BASELINE}' not in total costs.")
        total = float(df.loc[_BASELINE_ROW, _TOTAL_COL_BASELINE])
        assert self.TOTAL_LOWER <= total <= self.TOTAL_UPPER, (
            f"Baseline total annual cost (E-TOU-C + G-1): ${total:.0f}/yr. "
            f"Expected ${self.TOTAL_LOWER:,}–${self.TOTAL_UPPER:,}/yr. "
            f"EIA RECS 2020: CA SF gas-heated homes in high-rate territory ~$2,500–$5,000/yr. "
            f"Below ${self.TOTAL_LOWER:,}: check that gas billing is included. "
            f"Above ${self.TOTAL_UPPER:,}: check for rate territory mismatch or double-counting."
        )

    def test_solar_storage_total_cost_below_baseline(self) -> None:
        """solar+storage total annual cost is below the baseline total cost.

        Adding solar and battery storage should reduce total costs, not increase them,
        when capital costs are excluded. This test uses energy cost only (step13
        annual costs, not annualized capital costs from step15).
        """
        df = _load_total_results()
        if df is None:
            pytest.skip("Total costs CSV not found — run step13 first.")
        for row in (_BASELINE_ROW, _SOLAR_ROW):
            if row not in df.index:
                pytest.skip(f"'{row}' row not in total costs.")
        if _TOTAL_COL_BASELINE not in df.columns or _TOTAL_COL_SOLAR not in df.columns:
            pytest.skip(f"Required columns not in total costs.")
        baseline_total = float(df.loc[_BASELINE_ROW, _TOTAL_COL_BASELINE])
        solar_total = float(df.loc[_SOLAR_ROW, _TOTAL_COL_SOLAR])
        assert solar_total < baseline_total, (
            f"Solar+storage total (${solar_total:.0f}/yr) is not below "
            f"baseline total (${baseline_total:.0f}/yr). "
            f"Solar+storage should reduce annual energy costs (excluding capital). "
            f"Check dispatch optimization or rate calculation."
        )


# ---------------------------------------------------------------------------
# Bill savings from solar+storage
# ---------------------------------------------------------------------------

class TestSolarStorageBillSavings:
    """Solar+storage reduces the electricity bill by a magnitude consistent with published studies.

    Source: LBNL 'Tracking the Sun 2024':
      Typical CA residential solar+storage household achieves 60–85% electricity
      bill reduction vs a comparable home without solar.
      https://emp.lbl.gov/tracking-the-sun

    Real-bill anchor: one Alameda SF home on NEM2/TOU-E with solar+storage
      (June 2025 – March 2026) shows near-zero net electricity cost before true-up.
      The model's ~75% reduction on E-TOU-C is consistent with this.

    Note: these tests compare annual energy costs only (no capital costs).
    A system that shows only 5–10% savings is clearly undersized or misconfigured.
    A system that shows 99%+ savings likely has a billing error.
    """

    SAVINGS_LOWER_PCT = 0.50   # 50% minimum
    SAVINGS_UPPER_PCT = 0.95   # 95% maximum (near-zero bill is possible but 99%+ is suspicious)

    def test_solar_reduces_electricity_bill_by_50_to_95_pct(self) -> None:
        """solar+storage reduces annual electricity bill by 50–95% vs baseline (E-TOU-C).

        LBNL Tracking the Sun 2024: CA solar+storage households see 60–85% bill reduction.
        The wider 50–95% range here accommodates the model's load-matched system sizing
        and the Alameda home's relatively low baseline load (~5,558–6,000 kWh/yr).
        Below 50%: solar system appears undersized or dispatch is suboptimal.
        Above 95%: billing calculation may be producing negative or near-zero results
          that indicate an error rather than true zero-bill operation.
        """
        df = _load_electricity_results()
        if df is None:
            pytest.skip("Electricity results CSV not found — run step12 first.")
        for row in (_BASELINE_ROW, _SOLAR_ROW):
            if row not in df.index:
                pytest.skip(f"'{row}' row not in electricity results.")
        if _ELEC_COL_BASELINE not in df.columns:
            pytest.skip(f"Column '{_ELEC_COL_BASELINE}' not in electricity results.")

        baseline_bill = float(df.loc[_BASELINE_ROW, _ELEC_COL_BASELINE])
        solar_bill = float(df.loc[_SOLAR_ROW, _ELEC_COL_BASELINE])
        assert baseline_bill > 0, "Baseline electricity bill is zero — check rate calculation."
        savings_pct = (baseline_bill - solar_bill) / baseline_bill

        assert self.SAVINGS_LOWER_PCT <= savings_pct <= self.SAVINGS_UPPER_PCT, (
            f"Solar+storage electricity bill reduction: {savings_pct:.1%} "
            f"(${baseline_bill:.0f} → ${solar_bill:.0f}/yr on E-TOU-C). "
            f"Expected {self.SAVINGS_LOWER_PCT:.0%}–{self.SAVINGS_UPPER_PCT:.0%}. "
            f"LBNL Tracking the Sun 2024: typical CA solar+storage savings 60–85%. "
            f"Below {self.SAVINGS_LOWER_PCT:.0%}: check solar sizing or dispatch optimization. "
            f"Above {self.SAVINGS_UPPER_PCT:.0%}: check for billing calculation errors."
        )

    def test_nem3_solar_bill_is_within_10_pct_of_retail_solar_bill(self) -> None:
        """NEM3 solar+storage electricity bill is within 10% of the non-NEM3 solar bill.

        Under NEM3, exports are compensated at avoided cost (~$0.05–0.08/kWh) rather
        than retail rate (~$0.35–0.45/kWh). However, with a well-optimized battery,
        self-consumption is maximized and export value matters less. The LP optimizer
        under NEM3 constraints may find comparable or slightly better import costs
        through aggressive peak-hour avoidance.

        A difference greater than 10% in either direction would indicate that the
        NEM3 vs retail billing distinction is not being modeled correctly, or that
        the dispatch optimizer is not adapting to the NEM3 export rate structure.

        Source: CPUC NEM3 Decision (D.22-12-056); PG&E E-NEM3 avoided cost schedule.
        """
        df = _load_electricity_results()
        if df is None:
            pytest.skip("Electricity results CSV not found — run step12 first.")
        if _SOLAR_ROW not in df.index:
            pytest.skip(f"'{_SOLAR_ROW}' row not in electricity results.")
        if _ELEC_COL_SOLAR not in df.columns or _ELEC_COL_SOLAR_NEM3 not in df.columns:
            pytest.skip("NEM3 or retail solar columns not in electricity results.")

        retail_bill = float(df.loc[_SOLAR_ROW, _ELEC_COL_SOLAR])
        nem3_bill = float(df.loc[_SOLAR_ROW, _ELEC_COL_SOLAR_NEM3])

        # Use the larger as denominator to compute relative difference
        larger = max(abs(retail_bill), abs(nem3_bill))
        if larger == 0:
            pytest.skip("Both NEM3 and retail solar bills are zero.")
        rel_diff = abs(nem3_bill - retail_bill) / larger

        assert rel_diff <= 0.10, (
            f"NEM3 vs retail solar bill relative difference: {rel_diff:.1%} "
            f"(NEM3 ${nem3_bill:.0f}/yr vs retail ${retail_bill:.0f}/yr on E-TOU-C). "
            f"Expected within 10%. With a battery optimized for self-consumption, "
            f"NEM3 and retail billing should produce similar annual costs. "
            f"A large gap suggests the dispatch optimizer is not adapting to export rates."
        )
