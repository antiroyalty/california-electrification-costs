"""Unit tests for electricity rate helper data.

These tests encode rate values hand-verified against PG&E tariff PDFs.
They lock in the rate lookup logic so any accidental data change fails loudly.

References:
- E-TOU-C: https://www.pge.com/tariffs/assets/pdf/tariffbook/ELEC_SCHEDS_E-TOU-C.pdf
- E-TOU-D: https://www.pge.com/tariffs/assets/pdf/tariffbook/ELEC_SCHEDS_E-TOU-D.pdf
- SCE PNG screenshots: data/utility-rates/sce/*.png
"""
import os
import sys

import pandas as pd
import pytest

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from helpers.electricity_rate_helpers import PGE_RATE_PLANS, SCE_RATE_PLANS, SDGE_RATE_PLANS
from pipeline.steps.step9b_cooptimize_core import _hourly_import_rate
from pipeline.steps.step12_evaluate_electricity_rates import (
    _hourly_import_rate as _step12_rate,
    _estimate_monthly_fixed_from_plan,
    calculate_annual_costs_electricity,
)


def _ts(year: int, month: int, day: int, hour: int) -> pd.Timestamp:
    return pd.Timestamp(year=year, month=month, day=day, hour=hour)


# July 2018: month=7 (summer), weekday offset:
# 2018-07-03 = Tuesday (weekday), 2018-07-07 = Saturday (weekend)
JULY_WEEKDAY = _ts(2018, 7, 3, 0)   # Tuesday
JULY_WEEKEND = _ts(2018, 7, 7, 0)   # Saturday
JAN_WEEKDAY  = _ts(2018, 1, 2, 0)   # Tuesday (winter)


def rate(plan: str, ts: pd.Timestamp) -> float:
    return _hourly_import_rate(PGE_RATE_PLANS[plan], ts)


# ---------------------------------------------------------------------------
# E-TOU-C: peak = 4–9 pm (hours 16–20 inclusive), same rate weekdays/weekends
# ---------------------------------------------------------------------------

class TestETOUC:
    def test_peak_hour_weekday_july(self):
        # 6 pm (hour 18) on a weekday in July: on-peak 52¢ (March 2026 tariff)
        ts = JULY_WEEKDAY.replace(hour=18)
        assert rate("E-TOU-C", ts) == pytest.approx(0.52)

    def test_peak_hour_weekend_july(self):
        # E-TOU-C charges peak on weekends too — same rate structure as weekdays
        ts = JULY_WEEKEND.replace(hour=18)
        assert rate("E-TOU-C", ts) == pytest.approx(0.52)

    def test_off_peak_hour_weekday_july(self):
        # 10 am (hour 10) on a weekday in July: off-peak 40¢ (above-baseline)
        ts = JULY_WEEKDAY.replace(hour=10)
        assert rate("E-TOU-C", ts) == pytest.approx(0.40)

    def test_boundary_hour_16_is_peak(self):
        # First peak hour (hour 16 = 4 pm): should be peak
        ts = JULY_WEEKDAY.replace(hour=16)
        assert rate("E-TOU-C", ts) == pytest.approx(0.52)

    def test_boundary_hour_15_is_off_peak(self):
        # Last off-peak hour before peak (hour 15 = 3 pm): should be off-peak
        ts = JULY_WEEKDAY.replace(hour=15)
        assert rate("E-TOU-C", ts) == pytest.approx(0.40)

    def test_winter_peak_rate(self):
        # Winter peak (hour 18 weekday): 40¢ (March 2026 tariff, MEDIUM confidence)
        ts = JAN_WEEKDAY.replace(hour=18)
        assert rate("E-TOU-C", ts) == pytest.approx(0.40)

    def test_winter_off_peak_rate(self):
        # Winter off-peak (hour 10 weekday): 37¢ (March 2026 tariff, MEDIUM confidence)
        ts = JAN_WEEKDAY.replace(hour=10)
        assert rate("E-TOU-C", ts) == pytest.approx(0.37)


# ---------------------------------------------------------------------------
# E-TOU-D: peak = 5–8 pm weekdays only (hours 17, 18, 19); weekends all off-peak
# ---------------------------------------------------------------------------

class TestETOUD:
    def test_peak_hour_weekday_july(self):
        # 6 pm (hour 18) weekday July: on-peak 48¢ (March 2026 tariff)
        ts = JULY_WEEKDAY.replace(hour=18)
        assert rate("E-TOU-D", ts) == pytest.approx(0.48)

    def test_no_peak_on_weekend_july(self):
        # E-TOU-D has no weekend peak — 6 pm Saturday should be off-peak 34¢
        ts = JULY_WEEKEND.replace(hour=18)
        assert rate("E-TOU-D", ts) == pytest.approx(0.34)

    def test_off_peak_weekday_july(self):
        # 10 am weekday July: off-peak 34¢
        ts = JULY_WEEKDAY.replace(hour=10)
        assert rate("E-TOU-D", ts) == pytest.approx(0.34)

    def test_boundary_hour_17_is_peak(self):
        # First peak hour on E-TOU-D (hour 17 = 5 pm)
        ts = JULY_WEEKDAY.replace(hour=17)
        assert rate("E-TOU-D", ts) == pytest.approx(0.48)

    def test_boundary_hour_16_is_off_peak(self):
        # Hour 16 is NOT peak on E-TOU-D (peak only 17–19)
        ts = JULY_WEEKDAY.replace(hour=16)
        assert rate("E-TOU-D", ts) == pytest.approx(0.34)


# ---------------------------------------------------------------------------
# SCE TOU-D-5-8PM winter: midPeakHours plan without a 'peak' key
#
# Root cause: step12._hourly_import_rate doesn't check 'midPeakHours', so winter
# hours outside superOffPeakHours fall through to:
#   day_rates.get('offPeak', day_rates['peak'])
# Python evaluates day_rates['peak'] eagerly before calling .get(), even when
# 'offPeak' is present. Since the winter plan has no 'peak' key, this crashes
# with KeyError: 'peak'.
#
# Affected hours on a winter weekday: 0–7 (off-peak) and 17–23 (mid-peak + off-peak).
# Hours 8–16 (superOffPeakHours) already return correctly.
# ---------------------------------------------------------------------------

# Jan 2 2018 = Tuesday (weekday), Jan 6 2018 = Saturday (weekend)
SCE_JAN_WEEKDAY = pd.Timestamp(2018, 1, 2, 0)
SCE_JAN_WEEKEND = pd.Timestamp(2018, 1, 6, 0)


def _step12(plan_name: str, ts: pd.Timestamp) -> float:
    """Call step12's _hourly_import_rate with an SCE plan."""
    return _step12_rate(SCE_RATE_PLANS[plan_name], ts.to_pydatetime())


class TestStep12SCEWinterMidPeak:
    """SCE TOU-D-5-8PM winter uses midPeakHours/midPeak without a 'peak' key.

    step12._hourly_import_rate only checks peakHours, partPeakHours, and
    superOffPeakHours. Hours that fall outside those ranges crash at:
      return float(day_rates.get('offPeak', day_rates['peak']))
    because Python evaluates day_rates['peak'] eagerly even when 'offPeak' exists.

    Correct expected values from data/utility-rates/sce/tou-d-5-to-8-winter.png:
      superOffPeak $0.32  hours 8–16
      midPeak      $0.60  hours 17–19
      offPeak      $0.38  hours 0–7 and 20–23
    """

    def test_super_off_peak_hour_passes(self):
        # Hour 10 is in superOffPeakHours [8-16]; step12 already handles this.
        ts = SCE_JAN_WEEKDAY.replace(hour=10)
        assert _step12("TOU-D-5-8PM", ts) == pytest.approx(0.32)

    def test_overnight_off_peak_hour(self):
        # Hour 3 is in offPeakHours [0-7]; step12 misses it and crashes.
        ts = SCE_JAN_WEEKDAY.replace(hour=3)
        assert _step12("TOU-D-5-8PM", ts) == pytest.approx(0.38)

    def test_mid_peak_hour(self):
        # Hour 18 is in midPeakHours [17-19]; step12 misses it and crashes.
        ts = SCE_JAN_WEEKDAY.replace(hour=18)
        assert _step12("TOU-D-5-8PM", ts) == pytest.approx(0.60)

    def test_late_evening_off_peak_hour(self):
        # Hour 21 is in offPeakHours [20-23] outside midPeak; step12 crashes.
        ts = SCE_JAN_WEEKDAY.replace(hour=21)
        assert _step12("TOU-D-5-8PM", ts) == pytest.approx(0.38)

    def test_weekend_off_peak_hour(self):
        # Same plan, weekend, hour 3 — also has no 'peak' key, should be offPeak.
        ts = SCE_JAN_WEEKEND.replace(hour=3)
        assert _step12("TOU-D-5-8PM", ts) == pytest.approx(0.38)


# ---------------------------------------------------------------------------
# Back-of-envelope annual bill: code rates vs. PNG source-of-truth
#
# Strategy: reference rate functions using exact values from
#   data/utility-rates/sce/{tou-d-4-to-9,tou-d-5-to-8,tou-d-prime}-{summer,winter}.png
#
# Load profile: flat 1 kWh/hour for every hour of 2018 (8760 hours).
# Expected = sum of PNG rates over all hours.
# Actual   = sum of _hourly_import_rate over all hours.
#
# These tests FAIL when codebase rates diverge from the current tariff.
# The pytest message shows the dollar amount off and in which direction.
# Fix: update the stale values in helpers/electricity_rate_helpers.py.
#
# Both rate functions are tested:
#   step12._hourly_import_rate — used for billing (NEM3 annual cost calc)
#   step9b._hourly_import_rate — used by the LP optimizer for import cost
# ---------------------------------------------------------------------------

YEAR_2018 = pd.date_range("2018-01-01", periods=8760, freq="h")


def _sce_summer(ts: pd.Timestamp) -> bool:
    return 6 <= ts.month <= 9


def _png_rate_4_9pm(ts: pd.Timestamp) -> float:
    """PNG source-of-truth rates from tou-d-4-to-9-{summer,winter}.png.

    Summer (Jun–Sep):
      Weekdays:  On-Peak  58¢  hours 16–20 (4–9 pm)
                 Off-Peak 34¢  all other hours
      Weekends:  Mid-Peak 46¢  hours 16–20
                 Off-Peak 34¢  all other hours
    Winter (Oct–May, no weekday/weekend split):
      Mid-Peak       51¢  hours 16–20 (4–9 pm)
      Super-Off-Peak 33¢  hours 8–15  (8 am–4 pm)
      Off-Peak       37¢  all other hours
    """
    h = ts.hour
    if _sce_summer(ts):
        if h in range(16, 21):
            return 0.46 if ts.weekday() >= 5 else 0.58
        return 0.34
    else:
        if h in range(16, 21):
            return 0.51
        if h in range(8, 16):
            return 0.33
        return 0.37


def _png_rate_5_8pm(ts: pd.Timestamp) -> float:
    """PNG source-of-truth rates from tou-d-5-to-8-{summer,winter}.png.

    Summer (Jun–Sep):
      Weekdays:  On-Peak  74¢  hours 17–19 (5–8 pm)
                 Off-Peak 34¢  all other hours
      Weekends:  Mid-Peak 54¢  hours 17–19
                 Off-Peak 34¢  all other hours
    Winter (Oct–May, no weekday/weekend split):
      Mid-Peak       60¢  hours 17–19 (5–8 pm)
      Super-Off-Peak 32¢  hours 8–16  (8 am–5 pm)
      Off-Peak       38¢  all other hours
    """
    h = ts.hour
    if _sce_summer(ts):
        if h in range(17, 20):
            return 0.54 if ts.weekday() >= 5 else 0.74
        return 0.34
    else:
        if h in range(17, 20):
            return 0.60
        if h in range(8, 17):
            return 0.32
        return 0.38


def _png_rate_prime(ts: pd.Timestamp) -> float:
    """PNG source-of-truth rates from tou-d-prime-{summer,winter}.png.

    Summer (Jun–Sep):
      Weekdays:  On-Peak  59¢  hours 16–20 (4–9 pm)
                 Off-Peak 26¢  all other hours
      Weekends:  Mid-Peak 40¢  hours 16–20
                 Off-Peak 26¢  all other hours
    Winter (Oct–May, no weekday/weekend split):
      Mid-Peak       56¢  hours 16–20 (4–9 pm)
      Super-Off-Peak 24¢  hours 8–15  (same rate as Off-Peak)
      Off-Peak       24¢  all other hours
    """
    h = ts.hour
    if _sce_summer(ts):
        if h in range(16, 21):
            return 0.40 if ts.weekday() >= 5 else 0.59
        return 0.26
    else:
        if h in range(16, 21):
            return 0.56
        return 0.24


def _step9b(plan_name: str, ts: pd.Timestamp) -> float:
    """Call step9b's _hourly_import_rate with an SCE plan."""
    return _hourly_import_rate(SCE_RATE_PLANS[plan_name], ts)


class TestSCEAnnualBillVsPNG:
    """Annual electricity cost (flat 1 kWh/hr, 2018) via code vs. PNG tariff.

    Source of truth: data/utility-rates/sce/*.png

    Tests are run for both rate functions:
      step12._hourly_import_rate  used in billing (NEM3 annual cost)
      step9b._hourly_import_rate  used in LP optimizer (import cost signal)

    A FAILURE means the codebase rate values are stale. The diff shows the
    dollar amount and direction. Fix: update electricity_rate_helpers.py,
    then these tests lock in the corrected values.
    """

    # --- TOU-D-4-9PM ---

    def test_tou_d_4_9pm_step12(self):
        expected = sum(_png_rate_4_9pm(ts) for ts in YEAR_2018)
        plan = SCE_RATE_PLANS["TOU-D-4-9PM"]
        actual = sum(_step12_rate(plan, ts.to_pydatetime()) for ts in YEAR_2018)
        assert actual == pytest.approx(expected, abs=0.01), (
            f"TOU-D-4-9PM step12: code ${actual:.2f} vs PNG ${expected:.2f} "
            f"(diff ${actual - expected:+.2f})"
        )

    def test_tou_d_4_9pm_step9b(self):
        expected = sum(_png_rate_4_9pm(ts) for ts in YEAR_2018)
        plan = SCE_RATE_PLANS["TOU-D-4-9PM"]
        actual = sum(_step9b("TOU-D-4-9PM", ts) for ts in YEAR_2018)
        assert actual == pytest.approx(expected, abs=0.01), (
            f"TOU-D-4-9PM step9b: code ${actual:.2f} vs PNG ${expected:.2f} "
            f"(diff ${actual - expected:+.2f})"
        )

    # --- TOU-D-5-8PM ---

    def test_tou_d_5_8pm_step12(self):
        expected = sum(_png_rate_5_8pm(ts) for ts in YEAR_2018)
        plan = SCE_RATE_PLANS["TOU-D-5-8PM"]
        actual = sum(_step12_rate(plan, ts.to_pydatetime()) for ts in YEAR_2018)
        assert actual == pytest.approx(expected, abs=0.01), (
            f"TOU-D-5-8PM step12: code ${actual:.2f} vs PNG ${expected:.2f} "
            f"(diff ${actual - expected:+.2f})"
        )

    def test_tou_d_5_8pm_step9b(self):
        expected = sum(_png_rate_5_8pm(ts) for ts in YEAR_2018)
        plan = SCE_RATE_PLANS["TOU-D-5-8PM"]
        actual = sum(_step9b("TOU-D-5-8PM", ts) for ts in YEAR_2018)
        assert actual == pytest.approx(expected, abs=0.01), (
            f"TOU-D-5-8PM step9b: code ${actual:.2f} vs PNG ${expected:.2f} "
            f"(diff ${actual - expected:+.2f})"
        )

    # --- TOU-D-PRIME ---

    def test_tou_d_prime_step12(self):
        expected = sum(_png_rate_prime(ts) for ts in YEAR_2018)
        plan = SCE_RATE_PLANS["TOU-D-PRIME"]
        actual = sum(_step12_rate(plan, ts.to_pydatetime()) for ts in YEAR_2018)
        assert actual == pytest.approx(expected, abs=0.01), (
            f"TOU-D-PRIME step12: code ${actual:.2f} vs PNG ${expected:.2f} "
            f"(diff ${actual - expected:+.2f})"
        )

    def test_tou_d_prime_step9b(self):
        expected = sum(_png_rate_prime(ts) for ts in YEAR_2018)
        plan = SCE_RATE_PLANS["TOU-D-PRIME"]
        actual = sum(_step9b("TOU-D-PRIME", ts) for ts in YEAR_2018)
        assert actual == pytest.approx(expected, abs=0.01), (
            f"TOU-D-PRIME step9b: code ${actual:.2f} vs PNG ${expected:.2f} "
            f"(diff ${actual - expected:+.2f})"
        )


# ---------------------------------------------------------------------------
# Fixed charge tests
#
# Two billing paths each use fixedCharge differently:
#
#   _estimate_monthly_fixed_from_plan (NEM3 path in calculate_nem3_annual_costs):
#       returns fixedCharge_per_day × days_in_month
#
#   calculate_annual_costs_electricity (non-NEM3 path):
#       adds fixedCharge / 24 per hourly slot → fixedCharge × 365 per year
#
# Source: data/utility-rates/sce/*.png
#   TOU-D-4-9PM  $0.70/day
#   TOU-D-5-8PM  $0.79/day
#   TOU-D-PRIME  $0.79/day
#
# Zero-load fixture: passing all-zero consumption to calculate_annual_costs_electricity
# isolates fixed charges from energy charges. If the formula were /12 instead of
# /24, these tests would fail with values 2× too high ($576 instead of $288).
# ---------------------------------------------------------------------------

YEAR_2023 = pd.date_range("2023-01-01", periods=8760, freq="h")
FLAT_LOAD_8760 = [1.0] * 8760
ZERO_LOAD_8760 = [0.0] * 8760


class TestSCEFixedCharges:

    # --- NEM3 path: _estimate_monthly_fixed_from_plan ---

    def test_monthly_fixed_tou_d_4_9pm(self):
        plan = SCE_RATE_PLANS["TOU-D-4-9PM"]
        assert _estimate_monthly_fixed_from_plan(plan, 2018, 6) == pytest.approx(0.70 * 30)  # June (30 days)
        assert _estimate_monthly_fixed_from_plan(plan, 2018, 7) == pytest.approx(0.70 * 31)  # July (31 days)

    def test_monthly_fixed_tou_d_5_8pm(self):
        plan = SCE_RATE_PLANS["TOU-D-5-8PM"]
        assert _estimate_monthly_fixed_from_plan(plan, 2018, 6) == pytest.approx(0.79 * 30)
        assert _estimate_monthly_fixed_from_plan(plan, 2018, 7) == pytest.approx(0.79 * 31)

    def test_monthly_fixed_tou_d_prime(self):
        plan = SCE_RATE_PLANS["TOU-D-PRIME"]
        assert _estimate_monthly_fixed_from_plan(plan, 2018, 6) == pytest.approx(0.79 * 30)
        assert _estimate_monthly_fixed_from_plan(plan, 2018, 7) == pytest.approx(0.79 * 31)

    # --- Non-NEM3 path: calculate_annual_costs_electricity, zero load ---

    def test_annual_fixed_tou_d_4_9pm_zero_load(self):
        result = calculate_annual_costs_electricity(ZERO_LOAD_8760, "SCE", "TOU-D-4-9PM")
        assert result["TOU-D-4-9PM"] == pytest.approx(0.70 * 365, abs=0.01)

    def test_annual_fixed_tou_d_5_8pm_zero_load(self):
        result = calculate_annual_costs_electricity(ZERO_LOAD_8760, "SCE", "TOU-D-5-8PM")
        assert result["TOU-D-5-8PM"] == pytest.approx(0.79 * 365, abs=0.01)

    def test_annual_fixed_tou_d_prime_zero_load(self):
        result = calculate_annual_costs_electricity(ZERO_LOAD_8760, "SCE", "TOU-D-PRIME")
        assert result["TOU-D-PRIME"] == pytest.approx(0.79 * 365, abs=0.01)


# ---------------------------------------------------------------------------
# Combined annual bill: flat 1 kWh/hr load, energy + fixed charges
#
# calculate_annual_costs_electricity uses 2023 as the base year for weekday
# determination (line 84), so expected values are computed with YEAR_2023.
# Season is month-based (Jun–Sep = summer) and is year-independent.
#
# Expected = PNG energy total (2023 calendar) + fixedCharge × 365
#
# These are the integration-level tests: they exercise the full billing
# function (not just the rate lookup helper) with a realistic non-zero load.
# ---------------------------------------------------------------------------

class TestSCEFullAnnualBill:
    """Full annual bill (energy + fixed) via calculate_annual_costs_electricity.

    Load: flat 1 kWh/hr for all 8760 hours.
    Expected energy from PNG source-of-truth functions evaluated on the 2018 calendar.
    Expected fixed = fixedCharge_per_day × 365.

    calculate_annual_costs_electricity uses 2018 as the base year for weekday
    determination (step12 line 84: datetime(year=2018, month=1, day=1)), matching
    the NREL load profile year. Expected values must use YEAR_2018 to match.
    """

    def test_tou_d_4_9pm_full_bill(self):
        expected_energy = sum(_png_rate_4_9pm(ts) for ts in YEAR_2018)
        expected_total = expected_energy + 0.70 * 365
        result = calculate_annual_costs_electricity(FLAT_LOAD_8760, "SCE", "TOU-D-4-9PM")
        actual = result["TOU-D-4-9PM"]
        assert actual == pytest.approx(expected_total, abs=0.01), (
            f"TOU-D-4-9PM full bill: code ${actual:.2f} vs expected ${expected_total:.2f} "
            f"(energy ${expected_energy:.2f} + fixed ${0.70 * 365:.2f}, diff ${actual - expected_total:+.2f})"
        )

    def test_tou_d_5_8pm_full_bill(self):
        expected_energy = sum(_png_rate_5_8pm(ts) for ts in YEAR_2018)
        expected_total = expected_energy + 0.79 * 365
        result = calculate_annual_costs_electricity(FLAT_LOAD_8760, "SCE", "TOU-D-5-8PM")
        actual = result["TOU-D-5-8PM"]
        assert actual == pytest.approx(expected_total, abs=0.01), (
            f"TOU-D-5-8PM full bill: code ${actual:.2f} vs expected ${expected_total:.2f} "
            f"(energy ${expected_energy:.2f} + fixed ${0.79 * 365:.2f}, diff ${actual - expected_total:+.2f})"
        )

    def test_tou_d_prime_full_bill(self):
        expected_energy = sum(_png_rate_prime(ts) for ts in YEAR_2018)
        expected_total = expected_energy + 0.79 * 365
        result = calculate_annual_costs_electricity(FLAT_LOAD_8760, "SCE", "TOU-D-PRIME")
        actual = result["TOU-D-PRIME"]
        assert actual == pytest.approx(expected_total, abs=0.01), (
            f"TOU-D-PRIME full bill: code ${actual:.2f} vs expected ${expected_total:.2f} "
            f"(energy ${expected_energy:.2f} + fixed ${0.79 * 365:.2f}, diff ${actual - expected_total:+.2f})"
        )


# ---------------------------------------------------------------------------
# PGE BOE annual bill: code rates vs. PDF source-of-truth (March 1, 2026)
#
# Source: data/utility-rates/pge/pge-residential-electric-rate-plan-pricing.pdf
# Effective: March 1, 2026
#
# Strategy: identical to SCE BOE tests — flat 1 kWh/hr for every hour of 2018,
# sum code _hourly_import_rate vs. sum of PDF reference function.
#
# IMPORTANT: All PGE tests are EXPECTED TO FAIL because the codebase rates are
# from a significantly older tariff. These tests DOCUMENT the discrepancies;
# do not fix rates until the paper's rate vintage methodology is resolved.
#
# Rate parsing notes:
#   E-TOU-C: above-baseline rates used as primary (code charges all consumption
#             at the above-baseline rate; baseline_credit key is never applied).
#   E-TOU-D: single tier (no baseline distinction in PDF).
#   E-ELEC:  three tiers: peak / partial-peak / off-peak.
#   EV2-A:   three tiers: peak / partial-peak / off-peak.
#
# Winter rate confidence:
#   E-TOU-C winter: MEDIUM — PDF text extraction ambiguous; 40¢/37¢ is best read.
#   E-TOU-D winter: MEDIUM — 39¢/35¢ is best read; could be 48¢/34¢.
#   E-ELEC winter peak (4-9pm): MEDIUM — 32¢ is best read but not clearly labeled.
#   EV2-A winter off-peak: MEDIUM — 23¢ is best read; could be 24¢.
#
# Both rate functions tested:
#   step9b._hourly_import_rate — LP optimizer import cost
#   step12._hourly_import_rate — billing
# ---------------------------------------------------------------------------

def _pge_summer(ts: pd.Timestamp) -> bool:
    """PGE summer: June 1 – Sept 30 (months 6–9)."""
    return 6 <= ts.month <= 9


def _pdf_rate_e_tou_c(ts: pd.Timestamp) -> float:
    """PDF source-of-truth rates for E-TOU-C (March 1, 2026).

    Peak 4–9 pm every day (weekdays and weekends).
    Using above-baseline rates — code models all consumption at above-baseline
    rate (baseline_credit key is never applied in _hourly_import_rate).

    Summer (Jun–Sep):
      Peak (4–9pm, every day):   52¢  (above baseline; below baseline = 44¢)
      Off-Peak (all other hours): 40¢  (above baseline; below baseline = 32¢)
    Winter (Oct–May):
      Peak (4–9pm, every day):   40¢  (above baseline; below baseline = 32¢)
      Off-Peak (all other hours): 37¢  (above baseline; below baseline = 29¢)
    Baseline credit = 8¢ in all seasons and tiers.
    """
    h = ts.hour
    is_peak = h in range(16, 21)
    if _pge_summer(ts):
        return 0.52 if is_peak else 0.40
    return 0.40 if is_peak else 0.37


def _pdf_rate_e_tou_d(ts: pd.Timestamp) -> float:
    """PDF source-of-truth rates for E-TOU-D (March 1, 2026).

    Peak 5–8 pm weekdays only. Weekends: all off-peak.

    Summer (Jun–Sep):
      Weekday peak (5–8pm):       48¢
      All other hours:             34¢
    Winter (Oct–May):
      Weekday peak (5–8pm):       39¢
      All other hours:             35¢
    """
    h = ts.hour
    is_weekday_peak = (ts.weekday() < 5) and (h in [17, 18, 19])
    if _pge_summer(ts):
        return 0.48 if is_weekday_peak else 0.34
    return 0.39 if is_weekday_peak else 0.35


def _pdf_rate_e_elec(ts: pd.Timestamp) -> float:
    """PDF source-of-truth rates for E-ELEC (March 1, 2026).

    Three tiers: peak (4–9pm), partial-peak (3–4pm and 9pm–midnight),
    off-peak (all other hours). Every day (weekdays and weekends).
    Base Services Charge applies separately (not modeled here).

    Summer (Jun–Sep):
      Peak (4–9pm):                    55¢
      Partial-Peak (3–4pm, 9pm–midnight): 39¢
      Off-Peak (12am–3pm):              33¢
    Winter (Oct–May):  [winter peak MEDIUM confidence; partial/off-peak HIGH]
      Peak (4–9pm):                    32¢
      Partial-Peak (3–4pm, 9pm–midnight): 30¢
      Off-Peak (12am–3pm):              28¢
    """
    h = ts.hour
    if h in range(16, 21):          # peak 4–9pm
        return 0.55 if _pge_summer(ts) else 0.32
    if h in [15, 21, 22, 23]:       # partial-peak 3–4pm and 9pm–midnight
        return 0.39 if _pge_summer(ts) else 0.30
    return 0.33 if _pge_summer(ts) else 0.28  # off-peak


def _pdf_rate_ev_b(ts: pd.Timestamp) -> float:
    """PDF source-of-truth rates for EV-B (March 1, 2026).

    Weekday peak: 2–9 pm (hours 14–20).
    Weekday partial-peak: 7 am–2 pm and 9–11 pm (hours 7–13, 21–22).
    Weekday off-peak: midnight–7 am, 11 pm–midnight (hours 0–6, 23).

    Weekend peak: 3–7 pm (hours 15–18) only. NO partial-peak on weekends.
    Weekend off-peak: all other hours.

    Source: ELEC_SCHEDS_EV (Sch).pdf Special Condition 1.

    Summer (Jun–Sep):  Peak 62¢, Partial-Peak 38¢ (weekdays only), Off-Peak 26¢
    Winter (Oct–May):  Peak 44¢, Partial-Peak 31¢ (weekdays only), Off-Peak 24¢
    """
    h = ts.hour
    if ts.weekday() >= 5:  # weekend
        if h in range(15, 19):            # weekend peak 3–7 pm
            return 0.62 if _pge_summer(ts) else 0.44
        return 0.26 if _pge_summer(ts) else 0.24  # weekend off-peak (no partial-peak)
    else:  # weekday
        if h in range(14, 21):                    # weekday peak 2–9pm
            return 0.62 if _pge_summer(ts) else 0.44
        if h in list(range(7, 14)) + [21, 22]:    # weekday partial-peak 7am–2pm and 9–11pm
            return 0.38 if _pge_summer(ts) else 0.31
        return 0.26 if _pge_summer(ts) else 0.24  # weekday off-peak


def _pdf_rate_ev2a(ts: pd.Timestamp) -> float:
    """PDF source-of-truth rates for EV2-A (March 1, 2026).

    Three tiers: peak (4–9pm), partial-peak (3–4pm and 9pm–midnight),
    off-peak (all other hours). Every day (weekdays and weekends).

    Summer (Jun–Sep):
      Peak (4–9pm):                    54¢
      Partial-Peak (3–4pm, 9pm–midnight): 43¢
      Off-Peak (12am–3pm):              23¢
    Winter (Oct–May):
      Peak (4–9pm):                    41¢
      Partial-Peak (3–4pm, 9pm–midnight): 39¢
      Off-Peak (12am–3pm):              23¢  [MEDIUM confidence; could be 24¢]
    """
    h = ts.hour
    if h in range(16, 21):          # peak 4–9pm
        return 0.54 if _pge_summer(ts) else 0.41
    if h in [15, 21, 22, 23]:       # partial-peak 3–4pm and 9pm–midnight
        return 0.43 if _pge_summer(ts) else 0.39
    return 0.23                     # off-peak (same summer/winter)


class TestPGEAnnualBillVsPDF:
    """Annual electricity cost (flat 1 kWh/hr, 2018) via code vs. PDF tariff.

    Source of truth: data/utility-rates/pge/pge-residential-electric-rate-plan-pricing.pdf
    Effective: March 1, 2026.

    Rates were updated to match the March 2026 tariff (AB 205 restructuring) on 2026-03-11.
    Rate vintage decision: use most modern available rates for all utilities; load profiles
    from 2018 NREL data do not change the appropriate rate reference.
    """

    # --- E-TOU-C ---

    def test_e_tou_c_step9b(self):
        expected = sum(_pdf_rate_e_tou_c(ts) for ts in YEAR_2018)
        plan = PGE_RATE_PLANS["E-TOU-C"]
        actual = sum(_hourly_import_rate(plan, ts) for ts in YEAR_2018)
        assert actual == pytest.approx(expected, abs=0.01), (
            f"E-TOU-C step9b: code ${actual:.2f} vs PDF ${expected:.2f} "
            f"(diff ${actual - expected:+.2f})"
        )

    def test_e_tou_c_step12(self):
        expected = sum(_pdf_rate_e_tou_c(ts) for ts in YEAR_2018)
        plan = PGE_RATE_PLANS["E-TOU-C"]
        actual = sum(_step12_rate(plan, ts.to_pydatetime()) for ts in YEAR_2018)
        assert actual == pytest.approx(expected, abs=0.01), (
            f"E-TOU-C step12: code ${actual:.2f} vs PDF ${expected:.2f} "
            f"(diff ${actual - expected:+.2f})"
        )

    # --- E-TOU-D ---

    def test_e_tou_d_step9b(self):
        expected = sum(_pdf_rate_e_tou_d(ts) for ts in YEAR_2018)
        plan = PGE_RATE_PLANS["E-TOU-D"]
        actual = sum(_hourly_import_rate(plan, ts) for ts in YEAR_2018)
        assert actual == pytest.approx(expected, abs=0.01), (
            f"E-TOU-D step9b: code ${actual:.2f} vs PDF ${expected:.2f} "
            f"(diff ${actual - expected:+.2f})"
        )

    def test_e_tou_d_step12(self):
        expected = sum(_pdf_rate_e_tou_d(ts) for ts in YEAR_2018)
        plan = PGE_RATE_PLANS["E-TOU-D"]
        actual = sum(_step12_rate(plan, ts.to_pydatetime()) for ts in YEAR_2018)
        assert actual == pytest.approx(expected, abs=0.01), (
            f"E-TOU-D step12: code ${actual:.2f} vs PDF ${expected:.2f} "
            f"(diff ${actual - expected:+.2f})"
        )

    # --- E-ELEC ---

    def test_e_elec_step9b(self):
        expected = sum(_pdf_rate_e_elec(ts) for ts in YEAR_2018)
        plan = PGE_RATE_PLANS["E-ELEC"]
        actual = sum(_hourly_import_rate(plan, ts) for ts in YEAR_2018)
        assert actual == pytest.approx(expected, abs=0.01), (
            f"E-ELEC step9b: code ${actual:.2f} vs PDF ${expected:.2f} "
            f"(diff ${actual - expected:+.2f})"
        )

    def test_e_elec_step12(self):
        expected = sum(_pdf_rate_e_elec(ts) for ts in YEAR_2018)
        plan = PGE_RATE_PLANS["E-ELEC"]
        actual = sum(_step12_rate(plan, ts.to_pydatetime()) for ts in YEAR_2018)
        assert actual == pytest.approx(expected, abs=0.01), (
            f"E-ELEC step12: code ${actual:.2f} vs PDF ${expected:.2f} "
            f"(diff ${actual - expected:+.2f})"
        )

    # --- EV2-A ---

    def test_ev2a_step9b(self):
        expected = sum(_pdf_rate_ev2a(ts) for ts in YEAR_2018)
        plan = PGE_RATE_PLANS["EV2-A"]
        actual = sum(_hourly_import_rate(plan, ts) for ts in YEAR_2018)
        assert actual == pytest.approx(expected, abs=0.01), (
            f"EV2-A step9b: code ${actual:.2f} vs PDF ${expected:.2f} "
            f"(diff ${actual - expected:+.2f})"
        )

    def test_ev2a_step12(self):
        expected = sum(_pdf_rate_ev2a(ts) for ts in YEAR_2018)
        plan = PGE_RATE_PLANS["EV2-A"]
        actual = sum(_step12_rate(plan, ts.to_pydatetime()) for ts in YEAR_2018)
        assert actual == pytest.approx(expected, abs=0.01), (
            f"EV2-A step12: code ${actual:.2f} vs PDF ${expected:.2f} "
            f"(diff ${actual - expected:+.2f})"
        )

    # --- EV-B ---

    def test_ev_b_step9b(self):
        expected = sum(_pdf_rate_ev_b(ts) for ts in YEAR_2018)
        plan = PGE_RATE_PLANS["EV-B"]
        actual = sum(_hourly_import_rate(plan, ts) for ts in YEAR_2018)
        assert actual == pytest.approx(expected, abs=0.01), (
            f"EV-B step9b: code ${actual:.2f} vs PDF ${expected:.2f} "
            f"(diff ${actual - expected:+.2f})"
        )

    def test_ev_b_step12(self):
        expected = sum(_pdf_rate_ev_b(ts) for ts in YEAR_2018)
        plan = PGE_RATE_PLANS["EV-B"]
        actual = sum(_step12_rate(plan, ts.to_pydatetime()) for ts in YEAR_2018)
        assert actual == pytest.approx(expected, abs=0.01), (
            f"EV-B step12: code ${actual:.2f} vs PDF ${expected:.2f} "
            f"(diff ${actual - expected:+.2f})"
        )


# ---------------------------------------------------------------------------
# PGE full annual bill: calculate_annual_costs_electricity (energy + fixed)
#
# This tests the FULL billing function, not just the rate lookup helper.
# calculate_annual_costs_electricity has a separate rate-dispatch path
# (lines 99–108 in step12) that handles midPeakHours/partPeakHours/etc.
# via dayotw_rates dict lookups. The TestPGEAnnualBillVsPDF tests above only
# exercise _hourly_import_rate — if the billing function's dispatch path
# diverges from the helper, those tests would not catch it.
#
# Strategy: identical to TestSCEFullAnnualBill — flat 1 kWh/hr, 8760 hours.
# Expected = PDF energy total (YEAR_2018 calendar) + fixedCharge_per_day × 365.
#
# Fixed charges per day (March 2026 tariff, AB 205 restructuring):
#   E-TOU-C:  $0.00/day
#   E-TOU-D:  $0.00/day
#   EV2-A:    $0.79343/day (Base Services Charge, Tier 3)
#   EV-B:     $0.04928/day (Total Meter Charge)
#   E-ELEC:   $0.79343/day (Base Services Charge, Tier 3)
# ---------------------------------------------------------------------------


class TestPGEFullAnnualBill:
    """Full annual bill (energy + fixed) via calculate_annual_costs_electricity for PGE.

    Exercises the complete billing code path for each PGE plan, not just the
    rate lookup helper. Flat 1 kWh/hr load for all 8760 hours of 2018.
    Expected = PDF energy total + fixedCharge_per_day × 365.

    A FAILURE here means calculate_annual_costs_electricity disagrees with the
    tariff PDF on the energy total, OR the fixed charge is being accumulated
    incorrectly (e.g. /12 instead of /24 per hour).
    """

    def test_e_tou_c_full_bill(self):
        expected = sum(_pdf_rate_e_tou_c(ts) for ts in YEAR_2018) + 0.00 * 365
        result = calculate_annual_costs_electricity(FLAT_LOAD_8760, "PG&E", "E-TOU-C")
        actual = result["E-TOU-C"]
        assert actual == pytest.approx(expected, abs=0.01), (
            f"E-TOU-C full bill: code ${actual:.2f} vs expected ${expected:.2f} "
            f"(diff ${actual - expected:+.2f})"
        )

    def test_e_tou_d_full_bill(self):
        expected = sum(_pdf_rate_e_tou_d(ts) for ts in YEAR_2018) + 0.00 * 365
        result = calculate_annual_costs_electricity(FLAT_LOAD_8760, "PG&E", "E-TOU-D")
        actual = result["E-TOU-D"]
        assert actual == pytest.approx(expected, abs=0.01), (
            f"E-TOU-D full bill: code ${actual:.2f} vs expected ${expected:.2f} "
            f"(diff ${actual - expected:+.2f})"
        )

    def test_ev2a_full_bill(self):
        expected = sum(_pdf_rate_ev2a(ts) for ts in YEAR_2018) + 0.79343 * 365
        result = calculate_annual_costs_electricity(FLAT_LOAD_8760, "PG&E", "EV2-A")
        actual = result["EV2-A"]
        assert actual == pytest.approx(expected, abs=0.01), (
            f"EV2-A full bill: code ${actual:.2f} vs expected ${expected:.2f} "
            f"(energy + ${0.79343 * 365:.2f} fixed, diff ${actual - expected:+.2f})"
        )

    def test_ev_b_full_bill(self):
        expected = sum(_pdf_rate_ev_b(ts) for ts in YEAR_2018) + 0.04928 * 365
        result = calculate_annual_costs_electricity(FLAT_LOAD_8760, "PG&E", "EV-B")
        actual = result["EV-B"]
        assert actual == pytest.approx(expected, abs=0.01), (
            f"EV-B full bill: code ${actual:.2f} vs expected ${expected:.2f} "
            f"(energy + ${0.04928 * 365:.2f} fixed, diff ${actual - expected:+.2f})"
        )

    def test_e_elec_full_bill(self):
        expected = sum(_pdf_rate_e_elec(ts) for ts in YEAR_2018) + 0.79343 * 365
        result = calculate_annual_costs_electricity(FLAT_LOAD_8760, "PG&E", "E-ELEC")
        actual = result["E-ELEC"]
        assert actual == pytest.approx(expected, abs=0.01), (
            f"E-ELEC full bill: code ${actual:.2f} vs expected ${expected:.2f} "
            f"(energy + ${0.79343 * 365:.2f} fixed, diff ${actual - expected:+.2f})"
        )


# ---------------------------------------------------------------------------
# G4: PGE fixed charges — NEM3 path (_estimate_monthly_fixed_from_plan)
#     and retail path (calculate_annual_costs_electricity, zero load)
#
# Same structure as TestSCEFixedCharges. PGE fixed charges post-AB 205
# (March 1, 2026):
#   E-TOU-C: $0.00/day
#   E-TOU-D: $0.00/day
#   EV2-A:   $0.79343/day  (Base Services Charge, Tier 3)
#   EV-B:    $0.04928/day  (Total Meter Charge)
#   E-ELEC:  $0.79343/day  (Base Services Charge, Tier 3)
# ---------------------------------------------------------------------------


class TestPGEFixedCharges:
    """PGE fixed charge accuracy in both billing code paths.

    NEM3 path uses _estimate_monthly_fixed_from_plan (per-month × days).
    Retail path uses fixedCharge / 24 per hourly slot (× 8760 = × 365/day).
    Both should yield fixedCharge_per_day × 365 for a full year.
    """

    # --- NEM3 path: _estimate_monthly_fixed_from_plan ---

    def test_monthly_fixed_ev2a_june(self):
        plan = PGE_RATE_PLANS["EV2-A"]
        assert _estimate_monthly_fixed_from_plan(plan, 2018, 6) == pytest.approx(0.79343 * 30)

    def test_monthly_fixed_ev2a_july(self):
        plan = PGE_RATE_PLANS["EV2-A"]
        assert _estimate_monthly_fixed_from_plan(plan, 2018, 7) == pytest.approx(0.79343 * 31)

    def test_monthly_fixed_ev_b_june(self):
        plan = PGE_RATE_PLANS["EV-B"]
        assert _estimate_monthly_fixed_from_plan(plan, 2018, 6) == pytest.approx(0.04928 * 30)

    def test_monthly_fixed_ev_b_july(self):
        plan = PGE_RATE_PLANS["EV-B"]
        assert _estimate_monthly_fixed_from_plan(plan, 2018, 7) == pytest.approx(0.04928 * 31)

    def test_monthly_fixed_e_elec_july(self):
        plan = PGE_RATE_PLANS["E-ELEC"]
        assert _estimate_monthly_fixed_from_plan(plan, 2018, 7) == pytest.approx(0.79343 * 31)

    def test_monthly_fixed_e_tou_c_is_zero(self):
        plan = PGE_RATE_PLANS["E-TOU-C"]
        assert _estimate_monthly_fixed_from_plan(plan, 2018, 7) == pytest.approx(0.0)

    # --- Retail path: calculate_annual_costs_electricity, zero load ---

    def test_annual_fixed_ev2a_zero_load(self):
        result = calculate_annual_costs_electricity(ZERO_LOAD_8760, "PG&E", "EV2-A")
        assert result["EV2-A"] == pytest.approx(0.79343 * 365, abs=0.01)

    def test_annual_fixed_ev_b_zero_load(self):
        result = calculate_annual_costs_electricity(ZERO_LOAD_8760, "PG&E", "EV-B")
        assert result["EV-B"] == pytest.approx(0.04928 * 365, abs=0.01)

    def test_annual_fixed_e_elec_zero_load(self):
        result = calculate_annual_costs_electricity(ZERO_LOAD_8760, "PG&E", "E-ELEC")
        assert result["E-ELEC"] == pytest.approx(0.79343 * 365, abs=0.01)

    def test_annual_fixed_e_tou_c_zero_load_is_zero(self):
        result = calculate_annual_costs_electricity(ZERO_LOAD_8760, "PG&E", "E-TOU-C")
        assert result["E-TOU-C"] == pytest.approx(0.0, abs=0.01)


# ---------------------------------------------------------------------------
# G5: E-TOU-D weekday/weekend split in calculate_annual_costs_electricity
#
# E-TOU-D peak: 5–8 pm (hours 17, 18, 19) on WEEKDAYS only.
# Weekend hours 17–19 are off-peak (34¢ summer, 35¢ winter).
#
# A load placed only at weekend peak hours must be billed at the off-peak rate.
# A load placed only at weekday peak hours must be billed at the peak rate.
# If the weekday/weekend split is broken, both loads would get the same rate.
# ---------------------------------------------------------------------------


class TestETOUDWeekdayWeekendSplit:
    """E-TOU-D: peak rate applies only on weekdays; weekends are always off-peak.

    This confirms the dayotw_type branching in calculate_annual_costs_electricity
    (step12 lines 88–97) correctly distinguishes weekday from weekend.
    """

    # Build loads that fire at weekend 17-19 and weekday 17-19 respectively
    @staticmethod
    def _build_load(weekday_only: bool) -> list:
        load = []
        for ts in YEAR_2018:
            is_peak_hour = ts.hour in [17, 18, 19]
            is_weekday = ts.weekday() < 5
            if is_peak_hour and (is_weekday if weekday_only else not is_weekday):
                load.append(1.0)
            else:
                load.append(0.0)
        return load

    def test_weekend_peak_hours_billed_at_off_peak_rate(self):
        """Load only at weekend 5–8 pm: must be off-peak (34¢ summer, 35¢ winter)."""
        load = self._build_load(weekday_only=False)  # weekend hours 17-19 only
        result = calculate_annual_costs_electricity(load, "PG&E", "E-TOU-D")["E-TOU-D"]

        expected = sum(
            _pdf_rate_e_tou_d(ts)
            for ts in YEAR_2018
            if ts.weekday() >= 5 and ts.hour in [17, 18, 19]
        )
        assert result == pytest.approx(expected, abs=0.01), (
            f"Weekend 5–8 pm load: code ${result:.2f} vs off-peak expected ${expected:.2f}. "
            f"If result is higher, weekend hours are being charged the peak rate."
        )

    def test_weekday_peak_hours_billed_at_peak_rate(self):
        """Load only at weekday 5–8 pm: must be peak (48¢ summer, 39¢ winter)."""
        load = self._build_load(weekday_only=True)   # weekday hours 17-19 only
        result = calculate_annual_costs_electricity(load, "PG&E", "E-TOU-D")["E-TOU-D"]

        expected = sum(
            _pdf_rate_e_tou_d(ts)
            for ts in YEAR_2018
            if ts.weekday() < 5 and ts.hour in [17, 18, 19]
        )
        assert result == pytest.approx(expected, abs=0.01), (
            f"Weekday 5–8 pm load: code ${result:.2f} vs peak expected ${expected:.2f}. "
            f"If result is lower, weekday hours are not getting the peak rate."
        )

    def test_weekend_and_weekday_peak_rates_differ(self):
        """Direct check: weekend and weekday peak-hour rates are different."""
        # Same number of hours but on weekends vs weekdays
        weekend_load = self._build_load(weekday_only=False)
        weekday_load = self._build_load(weekday_only=True)

        weekend_cost = calculate_annual_costs_electricity(weekend_load, "PG&E", "E-TOU-D")["E-TOU-D"]
        weekday_cost = calculate_annual_costs_electricity(weekday_load, "PG&E", "E-TOU-D")["E-TOU-D"]

        assert weekday_cost > weekend_cost, (
            f"Weekday peak-hour load (${weekday_cost:.2f}) should cost more than "
            f"weekend peak-hour load (${weekend_cost:.2f}) because E-TOU-D has no "
            f"weekend peak. If equal, the weekday/weekend split is broken."
        )


# ---------------------------------------------------------------------------
# G6: step9b vs step12 rate parity for PGE
#
# The LP optimizer (step9b._hourly_import_rate) and the billing function
# (step12._hourly_import_rate) must agree on every rate for every hour.
# If they diverge, the optimizer is minimizing a different cost than what
# gets billed — the paper's dispatch profiles are not optimal for the actual
# billing rates.
# ---------------------------------------------------------------------------


class TestPGERateParity:
    """step9b and step12 rate functions must agree for every hour and every PGE plan.

    Both functions are already tested independently against tariff PDFs
    (TestPGEAnnualBillVsPDF). This test asserts they equal each other directly,
    hour by hour, so any divergence is caught regardless of the PDF reference.
    """

    @pytest.mark.parametrize("plan_name", ["E-TOU-C", "E-TOU-D", "EV2-A", "EV-B", "E-ELEC"])
    def test_step9b_matches_step12_all_hours(self, plan_name):
        plan = PGE_RATE_PLANS[plan_name]
        mismatches = []
        for ts in YEAR_2018:
            r9b = _hourly_import_rate(plan, ts)
            r12 = _step12_rate(plan, ts.to_pydatetime())
            if abs(r9b - r12) > 1e-9:
                mismatches.append((ts, r9b, r12))

        assert len(mismatches) == 0, (
            f"{plan_name}: {len(mismatches)} hour(s) where step9b ≠ step12. "
            f"First mismatch: {mismatches[0][0]} "
            f"step9b={mismatches[0][1]:.6f} step12={mismatches[0][2]:.6f}. "
            f"Optimizer and biller use different cost signals for these hours."
        )


# ---------------------------------------------------------------------------
# SDG&E: TOU-DR1
#
# Added 2026-07-07, the same day SDGE_RATE_PLANS['TOU-DR1'] was corrected
# against SDG&E's official tariff (previously sourced from a consumer
# marketing page, not the tariff itself). Before this file, SDG&E had zero
# rate-correctness test coverage, unlike PG&E and SCE, which both have
# dedicated parity tests against the utility's own published rate documents.
#
# Source of truth: SDG&E Schedule TOU-DR1 Total Rates Table, effective
# 1/1/2026: https://www.sdge.com/sites/default/files/regulatory/1-1-26%20Schedule%20TOU-DR1%20Total%20Rates%20Table.pdf
#
# TOU-DR1 is the plan actually used for San Diego throughout the pipeline
# (pipeline/sensitivity_runner.py DEFAULT_RATE_PLANS, and step9b/step12's
# default SDG&E plan preference).
# ---------------------------------------------------------------------------

def _sdge_summer(ts: pd.Timestamp) -> bool:
    return 6 <= ts.month <= 9


def _pdf_rate_tou_dr1(ts: pd.Timestamp) -> float:
    """Tariff source-of-truth for TOU-DR1's below-baseline rate.

    Summer: Peak 58.7c, Off-Peak 36.7c, Super-Off-Peak 27.9c
    Winter: Peak 51.3c, Off-Peak 43.1c, Super-Off-Peak 34.0c
    Peak hours: 4-9 pm (16-20), both weekdays and weekends.
    Super-off-peak: weekdays hours 0-5 and 10-13; weekends hours 0-13.
    All other hours are off-peak.

    Before 2026-07-07, SDGE_RATE_PLANS encoded the midnight boundary as hour
    24 instead of 0, which never matches a real datetime.hour (always
    0-23), so midnight was silently billed at the off-peak rate. Fixed the
    same day this test file was added. See TestSDGEMidnightHourBug for the
    regression guard.
    """
    h = ts.hour
    is_weekend = ts.weekday() >= 5
    super_off_peak_hours = set(range(0, 14)) if is_weekend else {0, 1, 2, 3, 4, 5, 10, 11, 12, 13}
    if _sdge_summer(ts):
        if 16 <= h <= 20:
            return 0.587
        if h in super_off_peak_hours:
            return 0.279
        return 0.367
    else:
        if 16 <= h <= 20:
            return 0.513
        if h in super_off_peak_hours:
            return 0.340
        return 0.431


def _sdge_step9b(ts: pd.Timestamp) -> float:
    return _hourly_import_rate(SDGE_RATE_PLANS["TOU-DR1"], ts)


def _sdge_step12(ts: pd.Timestamp) -> float:
    return _step12_rate(SDGE_RATE_PLANS["TOU-DR1"], ts.to_pydatetime())


class TestSDGETOUDR1Structure:
    def test_peak_hours_are_4_to_9pm(self):
        plan = SDGE_RATE_PLANS["TOU-DR1"]
        assert plan["summer"]["weekdays"]["peakHours"] == [16, 17, 18, 19, 20]

    def test_weekend_peak_hours_match_weekday(self):
        # TOU-DR1 charges peak on weekends too, same hours as weekdays.
        plan = SDGE_RATE_PLANS["TOU-DR1"]
        assert plan["summer"]["weekends"]["peakHours"] == plan["summer"]["weekdays"]["peakHours"]

    def test_winter_rates_differ_from_summer(self):
        # Regression guard: before the 2026-07-07 fix, winter and summer were
        # coded identically, which was wrong per the real tariff.
        plan = SDGE_RATE_PLANS["TOU-DR1"]
        assert plan["summer"]["weekdays"]["peak"] != plan["winter"]["weekdays"]["peak"]


class TestSDGEMidnightHourBug:
    """Regression guard for a real, pre-existing bug found while adding this
    test file: midnight (hour 0) fell through to the off-peak rate instead
    of super-off-peak, because
    SDGE_RATE_PLANS['TOU-DR1']['*']['*']['superOffPeakHours'] listed 24
    instead of 0. datetime.hour is always 0-23, so 24 never matched.

    Fixed the same day this test file was added, alongside the
    2026-07-07 rate-value correction. Not part of that correction itself.
    """

    def test_midnight_should_be_super_off_peak_summer(self):
        ts = pd.Timestamp(2018, 7, 3, 0)  # Tuesday, July, midnight
        plan = SDGE_RATE_PLANS["TOU-DR1"]
        actual = _hourly_import_rate(plan, ts)
        assert actual == pytest.approx(0.279), (
            f"Midnight should bill at the super-off-peak rate (27.9c), got {actual:.3f}. "
            f"If this fails, superOffPeakHours has regressed back to listing 24 instead of 0."
        )

    def test_midnight_should_be_super_off_peak_winter(self):
        ts = pd.Timestamp(2018, 1, 2, 0)  # Tuesday, January, midnight
        plan = SDGE_RATE_PLANS["TOU-DR1"]
        actual = _hourly_import_rate(plan, ts)
        assert actual == pytest.approx(0.340), (
            f"Midnight should bill at the super-off-peak rate (34.0c), got {actual:.3f}. "
            f"If this fails, superOffPeakHours has regressed back to listing 24 instead of 0."
        )


class TestSDGEAnnualBillVsPDF:
    """Annual electricity cost (flat 1 kWh/hr, 2018) via code vs. the tariff PDF.

    Mirrors TestSCEAnnualBillVsPNG / TestPGEAnnualBillVsPDF. A FAILURE means
    the codebase rate values no longer match the cited tariff.
    """

    def test_tou_dr1_step9b(self):
        expected = sum(_pdf_rate_tou_dr1(ts) for ts in YEAR_2018)
        actual = sum(_sdge_step9b(ts) for ts in YEAR_2018)
        assert actual == pytest.approx(expected, abs=0.01), (
            f"TOU-DR1 step9b: code ${actual:.2f} vs PDF ${expected:.2f} "
            f"(diff ${actual - expected:+.2f})"
        )

    def test_tou_dr1_step12(self):
        expected = sum(_pdf_rate_tou_dr1(ts) for ts in YEAR_2018)
        actual = sum(_sdge_step12(ts) for ts in YEAR_2018)
        assert actual == pytest.approx(expected, abs=0.01), (
            f"TOU-DR1 step12: code ${actual:.2f} vs PDF ${expected:.2f} "
            f"(diff ${actual - expected:+.2f})"
        )


class TestSDGERateParity:
    """step9b and step12 rate functions must agree for every hour, mirroring
    TestPGERateParity. If they diverge, the LP optimizer is dispatching
    against a different price than what gets billed.
    """

    def test_step9b_matches_step12_all_hours(self):
        plan = SDGE_RATE_PLANS["TOU-DR1"]
        mismatches = []
        for ts in YEAR_2018:
            r9b = _hourly_import_rate(plan, ts)
            r12 = _step12_rate(plan, ts.to_pydatetime())
            if abs(r9b - r12) > 1e-9:
                mismatches.append((ts, r9b, r12))

        assert len(mismatches) == 0, (
            f"TOU-DR1: {len(mismatches)} hour(s) where step9b != step12. "
            f"First mismatch: {mismatches[0][0]} "
            f"step9b={mismatches[0][1]:.6f} step12={mismatches[0][2]:.6f}."
        )


class TestSDGEFixedCharges:
    """Mirrors TestSCEFixedCharges. SDG&E's tariff has a Base Services
    Charge of $0.79343/day for TOU-DR1, the same figure PG&E charges under
    E-ELEC. SDGE_RATE_PLANS had no 'fixedCharge' key at all for TOU-DR1
    before this test file was added, so it silently defaulted to $0.00/day:
    a real, material undercount of roughly $290/year per household. Fixed
    the same day this test file was added, not part of the 2026-07-07
    rate-value correction itself.
    """

    def test_monthly_fixed_tou_dr1(self):
        plan = SDGE_RATE_PLANS["TOU-DR1"]
        assert _estimate_monthly_fixed_from_plan(plan, 2018, 7) == pytest.approx(0.79343 * 31), (
            "TOU-DR1's 'fixedCharge' key is missing or wrong (SDG&E's $0.79343/day "
            "Base Services Charge), so monthly fixed charges are silently off."
        )

    def test_annual_fixed_tou_dr1_zero_load(self):
        result = calculate_annual_costs_electricity(ZERO_LOAD_8760, "SDG&E", "TOU-DR1")
        assert result["TOU-DR1"] == pytest.approx(0.79343 * 365, abs=0.01), (
            "TOU-DR1's 'fixedCharge' key is missing or wrong: a zero-load annual "
            "bill should be $0.79343 x 365."
        )
