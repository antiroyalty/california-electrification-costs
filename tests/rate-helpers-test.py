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
from pipeline.steps.step12_evaluate_electricity_rates import _hourly_import_rate as _step12_rate


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
        # 6 pm (hour 18) on a weekday in July: on-peak $0.60729
        ts = JULY_WEEKDAY.replace(hour=18)
        assert rate("E-TOU-C", ts) == pytest.approx(0.60729)

    def test_peak_hour_weekend_july(self):
        # E-TOU-C charges peak on weekends too — same rate structure as weekdays
        ts = JULY_WEEKEND.replace(hour=18)
        assert rate("E-TOU-C", ts) == pytest.approx(0.60729)

    def test_off_peak_hour_weekday_july(self):
        # 10 am (hour 10) on a weekday in July: off-peak $0.50429
        ts = JULY_WEEKDAY.replace(hour=10)
        assert rate("E-TOU-C", ts) == pytest.approx(0.50429)

    def test_boundary_hour_16_is_peak(self):
        # First peak hour (hour 16 = 4 pm): should be peak
        ts = JULY_WEEKDAY.replace(hour=16)
        assert rate("E-TOU-C", ts) == pytest.approx(0.60729)

    def test_boundary_hour_15_is_off_peak(self):
        # Last off-peak hour before peak (hour 15 = 3 pm): should be off-peak
        ts = JULY_WEEKDAY.replace(hour=15)
        assert rate("E-TOU-C", ts) == pytest.approx(0.50429)

    def test_winter_peak_rate(self):
        # Winter peak (hour 18 weekday): $0.49312
        ts = JAN_WEEKDAY.replace(hour=18)
        assert rate("E-TOU-C", ts) == pytest.approx(0.49312)

    def test_winter_off_peak_rate(self):
        # Winter off-peak (hour 10 weekday): $0.46312
        ts = JAN_WEEKDAY.replace(hour=10)
        assert rate("E-TOU-C", ts) == pytest.approx(0.46312)


# ---------------------------------------------------------------------------
# E-TOU-D: peak = 5–8 pm weekdays only (hours 17, 18, 19); weekends all off-peak
# ---------------------------------------------------------------------------

class TestETOUD:
    def test_peak_hour_weekday_july(self):
        # 6 pm (hour 18) weekday July: on-peak $0.56462
        ts = JULY_WEEKDAY.replace(hour=18)
        assert rate("E-TOU-D", ts) == pytest.approx(0.56462)

    def test_no_peak_on_weekend_july(self):
        # E-TOU-D has no weekend peak — 6 pm Saturday should be off-peak $0.42966
        ts = JULY_WEEKEND.replace(hour=18)
        assert rate("E-TOU-D", ts) == pytest.approx(0.42966)

    def test_off_peak_weekday_july(self):
        # 10 am weekday July: off-peak $0.42966
        ts = JULY_WEEKDAY.replace(hour=10)
        assert rate("E-TOU-D", ts) == pytest.approx(0.42966)

    def test_boundary_hour_17_is_peak(self):
        # First peak hour on E-TOU-D (hour 17 = 5 pm)
        ts = JULY_WEEKDAY.replace(hour=17)
        assert rate("E-TOU-D", ts) == pytest.approx(0.56462)

    def test_boundary_hour_16_is_off_peak(self):
        # Hour 16 is NOT peak on E-TOU-D (peak only 17–19)
        ts = JULY_WEEKDAY.replace(hour=16)
        assert rate("E-TOU-D", ts) == pytest.approx(0.42966)


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
