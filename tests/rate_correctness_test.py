"""
Rate correctness tests for electricity_rate_helpers.py and the LP import rate function.

These tests encode rate values that were hand-verified against official PG&E tariff PDFs
(March 2026 tariff sheets, effective March 1, 2026). They serve as a permanent regression
guard: if any rate value or peak-hour definition changes without an explicit tariff update,
these tests will fail.

Each test documents the specific tariff rule it is checking and the source.

Run with: pytest tests/rate-correctness-test.py -v
"""

import os
import sys

import pandas as pd
import pytest

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from helpers.electricity_rate_helpers import PGE_RATE_PLANS, BASELINE_ALLOWANCES
from pipeline.steps.step9b_cooptimize_core import _hourly_import_rate


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def etou_c():
    return PGE_RATE_PLANS["E-TOU-C"]


@pytest.fixture
def etou_d():
    return PGE_RATE_PLANS["E-TOU-D"]


# Timestamps used across tests. July = summer season (months 6-9).
# weekday() >= 5 means weekend (Saturday=5, Sunday=6).
TUESDAY_JULY_6PM  = pd.Timestamp(2020, 7, 14, 18)  # weekday=1, summer, hour 18
SATURDAY_JULY_6PM = pd.Timestamp(2020, 7, 18, 18)  # weekday=5, summer, hour 18
TUESDAY_JULY_3PM  = pd.Timestamp(2020, 7, 14, 15)  # weekday=1, summer, hour 15 (off-peak for both plans)
TUESDAY_JULY_5PM  = pd.Timestamp(2020, 7, 14, 17)  # weekday=1, summer, hour 17 (peak for E-TOU-D only)
TUESDAY_JULY_8PM  = pd.Timestamp(2020, 7, 14, 20)  # weekday=1, summer, hour 20 (E-TOU-D peak ends at 8pm)
TUESDAY_JAN_6PM   = pd.Timestamp(2020, 1, 14, 18)  # weekday=1, winter, hour 18


# ---------------------------------------------------------------------------
# E-TOU-C peak hour structure
# Source: https://www.pge.com/tariffs/assets/pdf/tariffbook/ELEC_SCHEDS_E-TOU-C.pdf
# ---------------------------------------------------------------------------

class TestETOUCStructure:
    """E-TOU-C: peak hours are 4-9pm (hours 16-20) every day including weekends."""

    def test_weekday_peak_hours_are_4_to_9pm(self, etou_c):
        assert etou_c["summer"]["weekdays"]["peakHours"] == [16, 17, 18, 19, 20]

    def test_weekend_peak_hours_are_same_as_weekday(self, etou_c):
        # E-TOU-C does NOT distinguish weekday vs weekend for peak hours.
        assert etou_c["summer"]["weekends"]["peakHours"] == [16, 17, 18, 19, 20]

    def test_winter_peak_hours_unchanged(self, etou_c):
        assert etou_c["winter"]["weekdays"]["peakHours"] == [16, 17, 18, 19, 20]


# ---------------------------------------------------------------------------
# E-TOU-D peak hour structure
# Source: https://www.pge.com/tariffs/assets/pdf/tariffbook/ELEC_SCHEDS_E-TOU-D.pdf
# ---------------------------------------------------------------------------

class TestETOUDStructure:
    """E-TOU-D: peak hours are 5-8pm (hours 17-19) on weekdays only. No weekend peak."""

    def test_weekday_peak_hours_are_5_to_8pm(self, etou_d):
        assert etou_d["summer"]["weekdays"]["peakHours"] == [17, 18, 19]

    def test_weekend_has_no_peak(self, etou_d):
        # Critical: E-TOU-D has no weekend peak period.
        assert etou_d["summer"]["weekends"]["peakHours"] == []

    def test_winter_weekday_peak_hours_unchanged(self, etou_d):
        assert etou_d["winter"]["weekdays"]["peakHours"] == [17, 18, 19]

    def test_winter_weekend_has_no_peak(self, etou_d):
        assert etou_d["winter"]["weekends"]["peakHours"] == []


# ---------------------------------------------------------------------------
# E-TOU-C rate values (hand-verified against March 2026 PG&E tariff sheet)
# Source: data/utility-rates/pge/pge-residential-electric-rate-plan-pricing.pdf
# Effective: March 1, 2026
# The code models all consumption at the above-baseline rate.
# ---------------------------------------------------------------------------

class TestETOUCRates:

    def test_summer_weekday_peak_rate(self, etou_c):
        # Summer peak (4–9pm every day): above-baseline 52¢
        rate = _hourly_import_rate(etou_c, TUESDAY_JULY_6PM)
        assert rate == pytest.approx(0.52)

    def test_summer_weekend_peak_rate_matches_weekday(self, etou_c):
        # E-TOU-C applies the same peak rate on weekends: above-baseline 52¢
        rate = _hourly_import_rate(etou_c, SATURDAY_JULY_6PM)
        assert rate == pytest.approx(0.52)

    def test_summer_off_peak_rate(self, etou_c):
        # 3pm is before the 4pm peak window: above-baseline off-peak 40¢
        rate = _hourly_import_rate(etou_c, TUESDAY_JULY_3PM)
        assert rate == pytest.approx(0.40)

    def test_winter_weekday_peak_rate(self, etou_c):
        # Winter peak (4–9pm every day): above-baseline 40¢
        rate = _hourly_import_rate(etou_c, TUESDAY_JAN_6PM)
        assert rate == pytest.approx(0.40)


# ---------------------------------------------------------------------------
# E-TOU-D rate values (hand-verified against March 2026 PG&E tariff sheet)
# Source: data/utility-rates/pge/pge-residential-electric-rate-plan-pricing.pdf
# Effective: March 1, 2026
# ---------------------------------------------------------------------------

class TestETOUDRates:

    def test_summer_weekday_peak_rate(self, etou_d):
        # Summer peak (5–8pm weekdays): 48¢
        rate = _hourly_import_rate(etou_d, TUESDAY_JULY_6PM)
        assert rate == pytest.approx(0.48)

    def test_summer_weekend_is_always_off_peak(self, etou_d):
        # 6pm Saturday: no peak for E-TOU-D on weekends; off-peak 34¢
        rate = _hourly_import_rate(etou_d, SATURDAY_JULY_6PM)
        assert rate == pytest.approx(0.34)

    def test_summer_off_peak_before_peak_window(self, etou_d):
        # 3pm Tuesday: off-peak because E-TOU-D peak starts at 5pm; 34¢
        rate = _hourly_import_rate(etou_d, TUESDAY_JULY_3PM)
        assert rate == pytest.approx(0.34)

    def test_summer_peak_starts_at_5pm(self, etou_d):
        # Hour 17 = 5pm = first peak hour: 48¢
        rate = _hourly_import_rate(etou_d, TUESDAY_JULY_5PM)
        assert rate == pytest.approx(0.48)

    def test_summer_peak_ends_before_8pm(self, etou_d):
        # Hour 20 = 8pm = outside peak window [17, 18, 19]; off-peak 34¢
        rate = _hourly_import_rate(etou_d, TUESDAY_JULY_8PM)
        assert rate == pytest.approx(0.34)

    def test_winter_weekday_peak_rate(self, etou_d):
        # Winter peak (5–8pm weekdays): 39¢
        rate = _hourly_import_rate(etou_d, TUESDAY_JAN_6PM)
        assert rate == pytest.approx(0.39)


# ---------------------------------------------------------------------------
# Baseline allowances
# ---------------------------------------------------------------------------

class TestBaselineAllowances:
    """Territory T is the model default. Territory V (Alameda) is documented as a
    known simplification: the model uses T instead of V, slightly underestimating
    baseline credits for Alameda County."""

    def test_territory_T_summer_baseline(self):
        assert BASELINE_ALLOWANCES["PGE"]["E-TOU-C"]["territories"]["T"]["summer"] == 6.5

    def test_territory_V_alameda_summer_baseline(self):
        # Alameda is territory V. The model defaults to T (6.5), not V (7.1).
        # This test documents the gap — it is not a bug, it is a known simplification.
        assert BASELINE_ALLOWANCES["PGE"]["E-TOU-C"]["territories"]["V"]["summer"] == 7.1

    def test_territory_T_is_lower_than_V(self):
        t = BASELINE_ALLOWANCES["PGE"]["E-TOU-C"]["territories"]["T"]["summer"]
        v = BASELINE_ALLOWANCES["PGE"]["E-TOU-C"]["territories"]["V"]["summer"]
        assert t < v, (
            "Territory T baseline should be lower than V. "
            "Using T for Alameda slightly underestimates baseline credits."
        )
