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

from helpers.electricity_rate_helpers import PGE_RATE_PLANS, SCE_RATE_PLANS
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

    Load: flat 1 kWh/hr for all 8760 hours of 2023.
    Expected energy from PNG source-of-truth functions evaluated on 2023 calendar.
    Expected fixed = fixedCharge_per_day × 365.
    """

    def test_tou_d_4_9pm_full_bill(self):
        expected_energy = sum(_png_rate_4_9pm(ts) for ts in YEAR_2023)
        expected_total = expected_energy + 0.70 * 365
        result = calculate_annual_costs_electricity(FLAT_LOAD_8760, "SCE", "TOU-D-4-9PM")
        actual = result["TOU-D-4-9PM"]
        assert actual == pytest.approx(expected_total, abs=0.01), (
            f"TOU-D-4-9PM full bill: code ${actual:.2f} vs expected ${expected_total:.2f} "
            f"(energy ${expected_energy:.2f} + fixed ${0.70 * 365:.2f}, diff ${actual - expected_total:+.2f})"
        )

    def test_tou_d_5_8pm_full_bill(self):
        expected_energy = sum(_png_rate_5_8pm(ts) for ts in YEAR_2023)
        expected_total = expected_energy + 0.79 * 365
        result = calculate_annual_costs_electricity(FLAT_LOAD_8760, "SCE", "TOU-D-5-8PM")
        actual = result["TOU-D-5-8PM"]
        assert actual == pytest.approx(expected_total, abs=0.01), (
            f"TOU-D-5-8PM full bill: code ${actual:.2f} vs expected ${expected_total:.2f} "
            f"(energy ${expected_energy:.2f} + fixed ${0.79 * 365:.2f}, diff ${actual - expected_total:+.2f})"
        )

    def test_tou_d_prime_full_bill(self):
        expected_energy = sum(_png_rate_prime(ts) for ts in YEAR_2023)
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
