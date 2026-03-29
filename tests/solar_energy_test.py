"""Solar production sanity checks against NREL PVWatts benchmarks.

Tests verify that the SAM-modeled solar production for the Alameda County
baseline scenario is consistent with published solar resource data for
CEC Climate Zone 3 (Bay Area).

Source: NREL PVWatts Calculator for Oakland, CA (37.8°N, 122.3°W)
  South-facing, 20° tilt, standard residential losses (14%): ~1,450 kWh/kW-DC/yr
  https://pvwatts.nrel.gov/pvwatts.php

The solar profile is read from sam_optimized_load_profiles_alameda.csv,
which is the direct step9 output. The 'PV AC (kWh)' column contains the
AC energy delivered by the solar array each hour (before battery dispatch).
Timestamps begin 2018-01-01 (TMY weather year used by step8/step9).

All tests skip gracefully if the file is absent (e.g., step9 not yet run).
"""
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
BASE_DIR = os.path.join(REPO_ROOT, "data", "loadprofiles", "baseline", HOUSING_TYPE, COUNTY_SLUG)
SOLAR_PROFILE_PATH = os.path.join(BASE_DIR, f"sam_optimized_load_profiles_{COUNTY_SLUG}.csv")

_SUMMER_MONTHS = frozenset({6, 7, 8})
_WINTER_MONTHS = frozenset({12, 1, 2})
_NIGHTTIME_HOURS = frozenset(range(0, 5)) | frozenset(range(20, 24))  # 8 pm–5 am PST


def _load_solar_df() -> pd.DataFrame | None:
    if not os.path.exists(SOLAR_PROFILE_PATH):
        return None
    df = pd.read_csv(SOLAR_PROFILE_PATH)
    df["timestamp"] = pd.to_datetime(df["Unnamed: 0"])
    return df


# ---------------------------------------------------------------------------
# Annual total
# ---------------------------------------------------------------------------

class TestSolarProductionAnnualTotal:
    """Annual solar production is within the plausible range for a Bay Area residential system.

    Source: NREL PVWatts for Oakland CA (37.8°N, 122.3°W):
      ~1,450 kWh/kW-DC/yr (south-facing, 20° tilt, 14% system losses).
      Typical CA residential system: 3–7 kW-DC.
      Plausible annual range:
        3 kW × 1,200 kWh/kW = 3,600 kWh (conservative low end)
        7 kW × 1,700 kWh/kW = 11,900 kWh (generous high end)

    The model sizes the system to cover annual load (~5,558 kWh baseline),
    implying ~3–4 kW DC and ~4,000–6,000 kWh annual production.
    """

    def test_annual_production_in_plausible_range(self) -> None:
        """annual solar production is 3,000–10,000 kWh, consistent with a 2–7 kW Bay Area system."""
        df = _load_solar_df()
        if df is None:
            pytest.skip(f"Solar profile not found: {SOLAR_PROFILE_PATH}")
        annual_kwh = float(df["PV AC (kWh)"].sum())
        assert 3_000 <= annual_kwh <= 10_000, (
            f"Annual solar production: {annual_kwh:.0f} kWh. "
            f"Expected 3,000–10,000 kWh for a 2–7 kW Bay Area system. "
            f"NREL PVWatts Oakland: ~1,450 kWh/kW-DC/yr. "
            f"Below 3,000: system may be undersized or solar model broken. "
            f"Above 10,000: system appears oversized for a typical SF home."
        )


# ---------------------------------------------------------------------------
# Seasonal shape
# ---------------------------------------------------------------------------

class TestSolarSeasonalShape:
    """Solar production follows the expected Bay Area seasonal pattern.

    Source: NREL PVWatts monthly production estimates for Oakland CA.
      Jun–Aug: ~550–650 kWh/month (long days, high irradiance)
      Dec–Feb: ~140–200 kWh/month (short days, low sun angle)
      Summer/winter 3-month ratio: ~3–4× for CZ3.

    A wrong seasonal shape would indicate a timezone mismatch, incorrect
    weather file, or a solar model that ignores irradiance variation.
    """

    def test_summer_winter_production_ratio(self) -> None:
        """Jun–Aug solar production is 2.5–4.5× the Dec–Feb production.

        NREL PVWatts Oakland 3-month sums (3.4 kW system):
          Jun+Jul+Aug ≈ 1,835 kWh; Dec+Jan+Feb ≈ 590 kWh → ratio ≈ 3.1.
        Below 2.5: solar model is too flat (not responsive to seasons).
        Above 4.5: winter production suppressed below reality.
        """
        df = _load_solar_df()
        if df is None:
            pytest.skip(f"Solar profile not found: {SOLAR_PROFILE_PATH}")
        months = df["timestamp"].dt.month
        solar = df["PV AC (kWh)"]
        summer = float(solar[months.isin(_SUMMER_MONTHS)].sum())
        winter = float(solar[months.isin(_WINTER_MONTHS)].sum())
        assert winter > 0, "Winter solar production is zero — check weather file or solar model."
        ratio = summer / winter
        assert 2.5 <= ratio <= 4.5, (
            f"Summer/winter production ratio: {ratio:.2f} "
            f"(summer {summer:.0f} kWh, winter {winter:.0f} kWh). "
            f"Expected 2.5–4.5 for Bay Area CZ3. "
            f"NREL PVWatts Oakland: ~3.1 for a south-facing system."
        )

    def test_peak_production_month_is_summer(self) -> None:
        """the month with highest total production is June, July, or August."""
        df = _load_solar_df()
        if df is None:
            pytest.skip(f"Solar profile not found: {SOLAR_PROFILE_PATH}")
        monthly = df.groupby(df["timestamp"].dt.month)["PV AC (kWh)"].sum()
        peak_month = int(monthly.idxmax())
        assert peak_month in {6, 7, 8}, (
            f"Peak production month: {peak_month} (expected June/July/August). "
            f"A non-summer peak indicates a weather file or timestamp alignment problem. "
            f"NREL PVWatts Oakland: July is typically the peak production month."
        )

    def test_spring_production_exceeds_deep_winter(self) -> None:
        """March + April production exceeds December + January production.

        Spring solar angles are higher than deep winter, so production should
        be meaningfully higher despite similar or greater cloud cover.
        NREL PVWatts Oakland: Mar+Apr ≈ 870 kWh vs Dec+Jan ≈ 375 kWh (~2.3×).
        If this fails, the weather file irradiance may not capture the seasonal arc.
        """
        df = _load_solar_df()
        if df is None:
            pytest.skip(f"Solar profile not found: {SOLAR_PROFILE_PATH}")
        months = df["timestamp"].dt.month
        solar = df["PV AC (kWh)"]
        spring = float(solar[months.isin({3, 4})].sum())
        deep_winter = float(solar[months.isin({12, 1})].sum())
        assert spring > deep_winter, (
            f"Spring (Mar+Apr) {spring:.0f} kWh ≤ deep winter (Dec+Jan) {deep_winter:.0f} kWh. "
            f"NREL PVWatts Oakland: spring is ~2.3× deep winter. "
            f"Check weather file irradiance values or the solar model's seasonal response."
        )


# ---------------------------------------------------------------------------
# Physics constraints
# ---------------------------------------------------------------------------

class TestSolarPhysicsConstraints:
    """Solar production satisfies basic physical constraints.

    No energy should be produced at night (9 pm–6 am). All hourly values
    must be non-negative. These tests catch bugs in the solar model such as
    AC coupling losses producing negative values, a constant-load model
    ignoring time-of-day, or timestamp alignment errors that shift production
    to nighttime hours.
    """

    def test_no_nighttime_production(self) -> None:
        """solar production is exactly zero during hours 8 pm–5 am (PST, the weather file timezone).

        The TMY weather file from step8 uses local standard time (PST = UTC-8, no DST).
        Hour 5 (5:00–6:00 am PST) is legitimately post-sunrise in summer (= 6:00–7:00 am PDT),
        so pre-dawn production at hour 5 is physically real and excluded from this check.
        Similarly, hour 19 (7:00–8:00 pm PST = 8:00–9:00 pm PDT) is post-sunset, correctly zero.

        The unambiguously dark window is 8 pm–5 am PST (hours 20–23 and 0–4). Any production
        in this window indicates a solar model bug or a timestamp alignment error that has
        shifted daytime production into deep nighttime hours.
        """
        df = _load_solar_df()
        if df is None:
            pytest.skip(f"Solar profile not found: {SOLAR_PROFILE_PATH}")
        hours = df["timestamp"].dt.hour
        night_production = float(df.loc[hours.isin(_NIGHTTIME_HOURS), "PV AC (kWh)"].sum())
        assert night_production == 0.0, (
            f"Deep-nighttime (8 pm–5 am PST, hours 20–4) solar production: {night_production:.3f} kWh. "
            f"Expected exactly 0.0. Check timestamp alignment in step8/step9."
        )

    def test_all_hourly_values_non_negative(self) -> None:
        """all hourly solar production values are non-negative (no phantom reverse flow)."""
        df = _load_solar_df()
        if df is None:
            pytest.skip(f"Solar profile not found: {SOLAR_PROFILE_PATH}")
        solar = pd.to_numeric(df["PV AC (kWh)"], errors="coerce")
        negative_count = int((solar < 0).sum())
        assert negative_count == 0, (
            f"{negative_count} hours have negative solar production. "
            f"Check AC conversion logic in step9_solar_storage_dispatch_core.py "
            f"(likely a clip(lower=0) missing after temperature derate)."
        )
