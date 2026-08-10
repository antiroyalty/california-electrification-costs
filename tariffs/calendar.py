from __future__ import annotations

from datetime import date, timedelta
from typing import Iterable

import pandas as pd


def observed_date(day: date) -> date:
    if day.weekday() == 5:
        return day - timedelta(days=1)
    if day.weekday() == 6:
        return day + timedelta(days=1)
    return day


def utility_holidays(year: int) -> frozenset[date]:
    """Return the common California IOU tariff holidays for ``year``.

    The list follows the holidays named in the utilities' residential TOU
    tariffs. Weekend holidays include their weekday observance date.
    """

    fixed = [
        date(year, 1, 1),
        date(year, 7, 4),
        date(year, 11, 11),
        date(year, 12, 25),
    ]
    # Presidents Day, Memorial Day, Labor Day, and Thanksgiving.
    calendar = pd.date_range(f"{year}-01-01", f"{year}-12-31", freq="D")
    mondays_feb = [d.date() for d in calendar if d.month == 2 and d.weekday() == 0]
    mondays_may = [d.date() for d in calendar if d.month == 5 and d.weekday() == 0]
    mondays_sep = [d.date() for d in calendar if d.month == 9 and d.weekday() == 0]
    thursdays_nov = [d.date() for d in calendar if d.month == 11 and d.weekday() == 3]
    variable = [mondays_feb[2], mondays_may[-1], mondays_sep[0], thursdays_nov[3]]
    holidays = set(fixed + variable)
    holidays.update(observed_date(day) for day in fixed)
    return frozenset(holidays)


def day_types(timestamps: Iterable[pd.Timestamp]) -> list[str]:
    index = pd.DatetimeIndex(pd.to_datetime(list(timestamps)))
    years = {int(year) for year in index.year.unique()}
    holidays = set().union(
        *(utility_holidays(year) for year in years | {year - 1 for year in years} | {year + 1 for year in years})
    )
    return [
        "weekend_holiday"
        if timestamp.weekday() >= 5 or timestamp.date() in holidays
        else "weekday"
        for timestamp in index
    ]


def full_year_hourly_index(year: int) -> pd.DatetimeIndex:
    start = pd.Timestamp(year=year, month=1, day=1)
    end = pd.Timestamp(year=year, month=12, day=31, hour=23)
    return pd.date_range(start, end, freq="h")


def calendarize_full_year(timestamps: Iterable[pd.Timestamp], billing_year: int) -> pd.DatetimeIndex:
    """Map a full-year TMY/profile index onto the explicit tariff year.

    Profile values remain in their original order. Calendar attributes used by
    weekday/weekend/holiday tariffs come from ``billing_year``. Partial-year or
    malformed profiles fail rather than being silently projected.
    """

    original = pd.DatetimeIndex(pd.to_datetime(list(timestamps)))
    expected = full_year_hourly_index(billing_year)
    if len(original) != len(expected):
        raise ValueError(
            f"Expected a complete {billing_year} hourly profile with {len(expected)} rows; "
            f"found {len(original)}"
        )
    if original.hasnans or original.has_duplicates:
        raise ValueError("Profile timestamps must be unique and non-missing")
    return expected
