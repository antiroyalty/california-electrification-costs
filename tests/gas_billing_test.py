"""Tests for gas billing functions.

Covers calculate_annual_costs_gas (step11_evaluate_gas_rates.py) and the
utility functions it depends on: categorize_season and sum_therms_by_season.

Prior to this file, calculate_annual_costs_gas had zero test coverage.

Fixed bug (2026-03-14): units mismatch in baseline comparison
=============================================================
BASELINE_ALLOWANCES stores therms/day. The original code compared seasonal
total therms directly to the daily value, so any load above ~0.49 therms for
the entire summer was billed at the excess rate — including fully-electrified
households with very low gas use. The fix (step11_evaluate_gas_rates.py):
multiply the daily baseline by _days_in_season() before comparing.
"""
import os
import sys

import pandas as pd
import pytest

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from pipeline.steps.step11_evaluate_gas_rates import (
    calculate_annual_costs_gas,
    categorize_season,
    sum_therms_by_season,
)
from helpers.gas_rate_helpers import GAS_RATE_PLANS, BASELINE_ALLOWANCES


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _gas_df(monthly_therms: dict, load_type: str = "default") -> pd.DataFrame:
    """Build a synthetic load profile DataFrame for gas billing tests.

    monthly_therms: {month_int: total_therms_for_that_month}
    Returns a DataFrame with 'month' and '{load_type}.gas.therms' columns,
    one row per month. calculate_annual_costs_gas expects this structure
    (the pipeline adds the 'month' column upstream via dt.month).
    """
    col = f"{load_type}.gas.therms"
    rows = [{"month": m, col: v} for m, v in monthly_therms.items()]
    return pd.DataFrame(rows)


# PGE G-1 territory X rates (covers Alameda and several Bay Area counties).
# Source: helpers/gas_rate_helpers.py
PGE_BASELINE_RATE = GAS_RATE_PLANS["PG&E"]["G-1"]["baseline"]["total_charge"]  # $2.30397/therm
PGE_EXCESS_RATE   = GAS_RATE_PLANS["PG&E"]["G-1"]["excess"]["total_charge"]    # $2.79773/therm
PGE_X_SUMMER_DAILY    = BASELINE_ALLOWANCES["PG&E"]["G-1"]["territories"]["X"]["summer"]          # 0.49 therms/day
PGE_X_WINTER_ON_DAILY = BASELINE_ALLOWANCES["PG&E"]["G-1"]["territories"]["X"]["winter_onpeak"]   # 2.00 therms/day
PGE_X_WINTER_OFF_DAILY = BASELINE_ALLOWANCES["PG&E"]["G-1"]["territories"]["X"]["winter_offpeak"] # 1.48 therms/day

# SCE (SoCal Gas) GR Zone1 rates (covers LA County)
SCE_BASELINE_RATE = GAS_RATE_PLANS["SCE"]["GR"]["baseline"]["total_charge"]  # $1.60189/therm
SCE_EXCESS_RATE   = GAS_RATE_PLANS["SCE"]["GR"]["excess"]["total_charge"]    # $2.08734/therm
SCE_Z1_SUMMER_DAILY = BASELINE_ALLOWANCES["SCE"]["GR"]["territories"]["Zone1"]["summer"]  # 1.69 therms/day


# ---------------------------------------------------------------------------
# Season categorization
# ---------------------------------------------------------------------------

class TestGasSeasonCategorization:
    """categorize_season maps each month to the correct gas billing season.

    Gas seasons differ from electricity seasons:
      Gas summer:         Apr–Oct (months 4–10) — 7 months
      Gas winter_offpeak: Nov, Feb, Mar (months 11, 2, 3) — 3 months
      Gas winter_onpeak:  Dec, Jan (months 12, 1) — 2 months

    Electricity summer is only Jun–Sep (months 6–9). Using the wrong
    season definition in gas billing would misclassify April, May, and
    October (potentially changing baseline tier for those months).
    """

    @pytest.mark.parametrize("month,expected", [
        (1,  "winter_onpeak"),
        (2,  "winter_offpeak"),
        (3,  "winter_offpeak"),
        (4,  "summer"),
        (5,  "summer"),
        (6,  "summer"),
        (7,  "summer"),
        (8,  "summer"),
        (9,  "summer"),
        (10, "summer"),
        (11, "winter_offpeak"),
        (12, "winter_onpeak"),
    ])
    def test_month_to_season(self, month, expected):
        """correctly maps all 12 months to their gas billing season."""
        assert categorize_season(month) == expected, (
            f"Month {month}: expected '{expected}', "
            f"got '{categorize_season(month)}'"
        )


# ---------------------------------------------------------------------------
# Season aggregation
# ---------------------------------------------------------------------------

class TestGasSeasonAggregation:
    """sum_therms_by_season correctly groups and sums monthly therms by season."""

    def test_summer_therms_aggregated_correctly(self):
        """Months 4–10 (7 months) contribute to 'summer' total."""
        df = _gas_df({m: 10.0 for m in range(1, 13)})  # 10 therms every month
        seasonal, total = sum_therms_by_season(df, "default")
        assert seasonal["summer"] == pytest.approx(70.0), (
            f"Summer (months 4–10): expected 70 therms, got {seasonal['summer']:.2f}"
        )
        assert total == pytest.approx(120.0)  # all 12 months

    def test_winter_onpeak_aggregated_correctly(self):
        """Months 12 and 1 contribute to 'winter_onpeak' total."""
        df = _gas_df({m: 5.0 for m in range(1, 13)})
        seasonal, _ = sum_therms_by_season(df, "default")
        assert seasonal["winter_onpeak"] == pytest.approx(10.0), (
            f"winter_onpeak (months 12, 1): expected 10 therms, "
            f"got {seasonal['winter_onpeak']:.2f}"
        )

    def test_winter_offpeak_aggregated_correctly(self):
        """Months 2, 3, 11 contribute to 'winter_offpeak' total."""
        df = _gas_df({m: 5.0 for m in range(1, 13)})
        seasonal, _ = sum_therms_by_season(df, "default")
        assert seasonal["winter_offpeak"] == pytest.approx(15.0), (
            f"winter_offpeak (months 2, 3, 11): expected 15 therms, "
            f"got {seasonal['winter_offpeak']:.2f}"
        )

    def test_zero_usage_months_do_not_contribute(self):
        """Months with zero therms don't inflate other seasons."""
        monthly = {m: 0.0 for m in range(1, 13)}
        monthly[7] = 50.0  # only July has usage
        df = _gas_df(monthly)
        seasonal, total = sum_therms_by_season(df, "default")
        assert seasonal["summer"] == pytest.approx(50.0)
        assert total == pytest.approx(50.0)


# ---------------------------------------------------------------------------
# Billing: above-baseline usage (both code paths agree)
# ---------------------------------------------------------------------------

class TestGasBillingAboveBaseline:
    """When seasonal usage clearly exceeds the baseline allowance, excess rate applies.

    For PGE G-1 territory X, summer daily baseline = 0.49 therms/day.
    Seasonal allowance (correct) ≈ 0.49 × 214 days ≈ 104.9 therms.

    A load of 200 therms in summer is above both the daily value (0.49) and
    the correct seasonal allowance (~105 therms), so the current code and the
    correct logic agree: excess rate applies. These tests pass with the bug.
    """

    def test_pge_summer_above_baseline_uses_excess_rate(self):
        """200 therms across summer months → excess rate for summer."""
        monthly = {m: 200.0 / 7 for m in range(4, 11)}
        monthly.update({m: 0.0 for m in [1, 2, 3, 11, 12]})
        df = _gas_df(monthly)
        cost = calculate_annual_costs_gas(df, "X", "default", "PG&E", "G-1")
        expected = 200.0 * PGE_EXCESS_RATE
        assert cost == pytest.approx(expected, abs=0.01), (
            f"PGE summer 200 therms: expected excess ${expected:.2f}, got ${cost:.2f}"
        )

    def test_pge_full_year_all_above_baseline_uses_excess_rate(self):
        """100 therms/month all year → every season billed at excess rate."""
        df = _gas_df({m: 100.0 for m in range(1, 13)})
        cost = calculate_annual_costs_gas(df, "X", "default", "PG&E", "G-1")
        # summer=700, winter_offpeak=300, winter_onpeak=200 → all well above daily baselines
        expected = 1200.0 * PGE_EXCESS_RATE
        assert cost == pytest.approx(expected, abs=0.01), (
            f"PGE 1200 therms/yr (all excess): expected ${expected:.2f}, got ${cost:.2f}"
        )

    def test_sce_summer_above_baseline_uses_excess_rate(self):
        """SCE (SoCal Gas) Zone1: 300 therms in summer → excess rate.

        SoCal Gas Zone1 daily summer baseline = 1.69 therms/day.
        Summer has ~214 days → seasonal allowance ≈ 361 therms.
        300 therms < 361 (correct: should be baseline) but 300 > 1.69 (buggy: excess).
        This test uses a load clearly above seasonal allowance (500 therms) so
        both code paths agree.
        """
        monthly = {m: 500.0 / 7 for m in range(4, 11)}
        monthly.update({m: 0.0 for m in [1, 2, 3, 11, 12]})
        df = _gas_df(monthly)
        cost = calculate_annual_costs_gas(df, "Zone1", "default", "SCE", "GR")
        expected = 500.0 * SCE_EXCESS_RATE
        assert cost == pytest.approx(expected, abs=0.01), (
            f"SCE Zone1 500 therms summer: expected excess ${expected:.2f}, "
            f"got ${cost:.2f}"
        )


# ---------------------------------------------------------------------------
# Billing: below-baseline usage — exposes units bug
# ---------------------------------------------------------------------------

class TestGasBillingBelowBaseline:
    """When seasonal usage is below the seasonal baseline allowance, the baseline rate applies.

    Baseline allowances are in therms/day. The correct comparison is:
        therms_used <= daily_baseline × days_in_season

    e.g., PGE territory X summer: 0.49 therms/day × 214 days ≈ 104.9 therms.
    A heat-pump household using 3.5 therms all summer is well below that
    allowance and should pay the baseline rate, not the excess rate.

    These tests lock in the corrected behavior after the 2026-03-14 fix.
    If they fail, the units bug has been reintroduced.
    """

    def test_pge_low_summer_usage_uses_baseline_rate(self):
        """3.5 total summer therms (well below ~105 therm allowance) → baseline rate."""
        # 0.5 therms/month × 7 summer months = 3.5 therms total
        monthly = {m: 0.5 for m in range(4, 11)}
        monthly.update({m: 0.0 for m in [1, 2, 3, 11, 12]})
        df = _gas_df(monthly)

        cost = calculate_annual_costs_gas(df, "X", "default", "PG&E", "G-1")
        expected_correct = 3.5 * PGE_BASELINE_RATE   # $8.06
        expected_buggy   = 3.5 * PGE_EXCESS_RATE     # $9.79

        assert cost == pytest.approx(expected_correct, abs=0.01), (
            f"PGE 3.5 therms summer (below seasonal allowance ~104.9 therms): "
            f"expected baseline rate ${PGE_BASELINE_RATE:.5f}/therm "
            f"→ ${expected_correct:.2f}, got ${cost:.2f}. "
            f"(If ${expected_buggy:.2f}: excess rate applied — units bug.)"
        )

    def test_pge_low_winter_onpeak_usage_uses_baseline_rate(self):
        """10 total winter_onpeak therms (well below ~124 therm allowance) → baseline rate."""
        monthly = {m: 0.0 for m in range(1, 13)}
        monthly[1]  = 5.0  # January
        monthly[12] = 5.0  # December
        df = _gas_df(monthly)

        cost = calculate_annual_costs_gas(df, "X", "default", "PG&E", "G-1")
        expected_correct = 10.0 * PGE_BASELINE_RATE
        expected_buggy   = 10.0 * PGE_EXCESS_RATE

        assert cost == pytest.approx(expected_correct, abs=0.01), (
            f"PGE 10 therms winter_onpeak (below seasonal allowance ~124 therms): "
            f"expected baseline ${expected_correct:.2f}, got ${cost:.2f}. "
            f"(If ${expected_buggy:.2f}: excess rate applied — units bug.)"
        )
