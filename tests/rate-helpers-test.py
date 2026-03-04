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

from helpers.electricity_rate_helpers import PGE_RATE_PLANS
from pipeline.steps.step9b_cooptimize_core import _hourly_import_rate


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
