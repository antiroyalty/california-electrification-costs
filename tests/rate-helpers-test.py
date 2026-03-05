"""Unit tests for electricity rate helper data.

These tests encode rate values hand-verified against PG&E tariff PDFs.
They lock in the rate lookup logic so any accidental data change fails loudly.

References:
- E-TOU-C: https://www.pge.com/tariffs/assets/pdf/tariffbook/ELEC_SCHEDS_E-TOU-C.pdf
- E-TOU-D: https://www.pge.com/tariffs/assets/pdf/tariffbook/ELEC_SCHEDS_E-TOU-D.pdf
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

    Correct expected values from electricity_rate_helpers.py:
      superOffPeak $0.34  hours 8–16
      midPeak      $0.61  hours 17–19
      offPeak      $0.40  hours 0–7 and 20–23
    """

    def test_super_off_peak_hour_passes(self):
        # Hour 10 is in superOffPeakHours [8-16]; step12 already handles this.
        ts = SCE_JAN_WEEKDAY.replace(hour=10)
        assert _step12("TOU-D-5-8PM", ts) == pytest.approx(0.34)

    def test_overnight_off_peak_hour(self):
        # Hour 3 is in offPeakHours [0-7]; step12 misses it and crashes.
        ts = SCE_JAN_WEEKDAY.replace(hour=3)
        assert _step12("TOU-D-5-8PM", ts) == pytest.approx(0.40)

    def test_mid_peak_hour(self):
        # Hour 18 is in midPeakHours [17-19]; step12 misses it and crashes.
        ts = SCE_JAN_WEEKDAY.replace(hour=18)
        assert _step12("TOU-D-5-8PM", ts) == pytest.approx(0.61)

    def test_late_evening_off_peak_hour(self):
        # Hour 21 is in offPeakHours [17-23] outside midPeak; step12 crashes.
        ts = SCE_JAN_WEEKDAY.replace(hour=21)
        assert _step12("TOU-D-5-8PM", ts) == pytest.approx(0.40)

    def test_weekend_off_peak_hour(self):
        # Same plan, weekend, hour 3 — also has no 'peak' key, should be offPeak.
        ts = SCE_JAN_WEEKEND.replace(hour=3)
        assert _step12("TOU-D-5-8PM", ts) == pytest.approx(0.40)
