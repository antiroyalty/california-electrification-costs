from __future__ import annotations

from dataclasses import dataclass
import calendar
from typing import Iterable, Mapping

import pandas as pd

from helpers.electricity_rate_helpers import PGE_RATE_PLANS, SCE_RATE_PLANS, SDGE_RATE_PLANS

from .calendar import day_types
from .models import Utility


REQUIRED_NBT_IMPORT_PLANS = {
    Utility.PGE: "E-ELEC",
    Utility.SCE: "TOU-D-PRIME",
    Utility.SDGE: "EV-TOU-5",
}


def required_nbt_import_plan(utility: str | Utility) -> str:
    return REQUIRED_NBT_IMPORT_PLANS[Utility.parse(utility)]


RATE_PLANS: Mapping[Utility, Mapping[str, dict]] = {
    Utility.PGE: PGE_RATE_PLANS,
    Utility.SCE: SCE_RATE_PLANS,
    Utility.SDGE: SDGE_RATE_PLANS,
}


def monthly_fixed_charge(plan_details: dict, year: int, month: int) -> float:
    """Return the fixed charge for a calendar month from a legacy plan record.

    Import-rate dictionaries express this as dollars per day. The primitive is
    retained here for non-NBT comparison-plan tests; NBT billing uses
    ``ImportRateSchedule.daily_fixed_charge`` on the actual dates.
    """

    season = "summer" if 6 <= int(month) <= 9 else "winter"
    season_rates = plan_details.get(season)
    if season_rates is None:
        raise KeyError(f"Missing {season} rate section")
    day_rates = season_rates.get("weekdays")
    if day_rates is None:
        raise KeyError(f"Missing weekdays rate section for {season}")
    daily = float(day_rates.get("fixedCharge", 0.0))
    return daily * calendar.monthrange(int(year), int(month))[1]


def _rate_for_hour(day_rates: dict, hour: int) -> float:
    keys = (
        ("peakHours", "peak"),
        ("onPeakHours", "onPeak"),
        ("midPeakHours", "midPeak"),
        ("partPeakHours", "partPeak"),
        ("superOffPeakHours", "superOffPeak"),
    )
    for hours_key, rate_key in keys:
        if hour in day_rates.get(hours_key, []):
            if rate_key not in day_rates:
                raise KeyError(f"{hours_key} matched hour {hour}, but {rate_key} is missing")
            return float(day_rates[rate_key])
    if "offPeak" not in day_rates:
        raise KeyError(f"No explicit period or offPeak rate covers hour {hour}")
    return float(day_rates["offPeak"])


def _period_for_hour(day_rates: dict, hour: int) -> str:
    periods = (
        ("peakHours", "peak"),
        ("onPeakHours", "peak"),
        ("midPeakHours", "midPeak"),
        ("partPeakHours", "partPeak"),
        ("superOffPeakHours", "superOffPeak"),
    )
    for hours_key, period in periods:
        if hour in day_rates.get(hours_key, []):
            return period
    if "offPeak" not in day_rates:
        raise KeyError(f"No explicit period or offPeak rate covers hour {hour}")
    return "offPeak"


@dataclass(frozen=True)
class ImportRateSchedule:
    utility: Utility
    plan_name: str
    plan_details: dict
    non_bypassable_rate: float = 0.0

    @property
    def generation_non_offsettable_rate(self) -> float:
        try:
            plan_total = float(self.plan_details["nonBypassableRate"])
            plan_generation = float(self.plan_details["generationNonOffsettableRate"])
        except KeyError as exc:
            raise KeyError(
                f"Missing non-offsettable rate component for "
                f"{self.utility.value} {self.plan_name}: {exc.args[0]}"
            ) from exc
        if plan_total < 0 or plan_generation < 0 or plan_generation > plan_total:
            raise ValueError(
                f"Invalid non-offsettable rate components for "
                f"{self.utility.value} {self.plan_name}"
            )
        if plan_total == 0:
            return 0.0
        return self.non_bypassable_rate * plan_generation / plan_total

    @property
    def delivery_non_offsettable_rate(self) -> float:
        return self.non_bypassable_rate - self.generation_non_offsettable_rate

    @classmethod
    def resolve(
        cls,
        utility: str | Utility,
        plan_name: str | None = None,
        *,
        non_bypassable_rate: float | None = None,
    ) -> "ImportRateSchedule":
        parsed = Utility.parse(utility)
        selected = plan_name or required_nbt_import_plan(parsed)
        required = required_nbt_import_plan(parsed)
        if selected != required:
            raise ValueError(
                f"NBT customers in {parsed.value} must use {required}; received {selected}"
            )
        try:
            details = RATE_PLANS[parsed][selected]
        except KeyError as exc:
            raise KeyError(
                f"Required NBT import plan {selected} is not defined for {parsed.value}"
            ) from exc
        if non_bypassable_rate is None:
            try:
                resolved_nbc = float(details["nonBypassableRate"])
            except KeyError as exc:
                raise KeyError(
                    f"Required NBT plan {parsed.value} {selected} has no "
                    "nonBypassableRate"
                ) from exc
        else:
            resolved_nbc = float(non_bypassable_rate)
        if resolved_nbc < 0:
            raise ValueError("non_bypassable_rate cannot be negative")
        return cls(parsed, selected, details, resolved_nbc)

    def rates_for(
        self,
        timestamps: Iterable[pd.Timestamp],
        *,
        component: str = "total",
    ) -> list[float]:
        if component not in {"total", "generation", "delivery"}:
            raise ValueError(f"Unknown import-rate component {component!r}")
        index = pd.DatetimeIndex(pd.to_datetime(list(timestamps)))
        types = day_types(index)
        rates: list[float] = []
        for timestamp, day_type in zip(index, types):
            summer_end = 10 if self.utility is Utility.SDGE and self.plan_name == "EV-TOU-5" else 9
            season = "summer" if 6 <= timestamp.month <= summer_end else "winter"
            season_rates = self.plan_details.get(season)
            if season_rates is None:
                raise KeyError(f"Missing {season} rates for {self.utility.value} {self.plan_name}")
            key = "weekends" if day_type == "weekend_holiday" else "weekdays"
            try:
                day_rates = season_rates[key]
            except KeyError as exc:
                raise KeyError(
                    f"Missing {key} rates for {self.utility.value} {self.plan_name} {season}"
                ) from exc
            if component == "total":
                rates.append(_rate_for_hour(day_rates, int(timestamp.hour)))
                continue
            component_rates = self.plan_details.get("componentRates", {}).get(component)
            if component_rates is None:
                raise KeyError(
                    f"Missing {component} import component rates for "
                    f"{self.utility.value} {self.plan_name}"
                )
            period = _period_for_hour(day_rates, int(timestamp.hour))
            season_components = component_rates[season]
            if period == "peak" and key == "weekends" and "weekendPeak" in season_components:
                period = "weekendPeak"
            try:
                rates.append(float(season_components[period]))
            except KeyError as exc:
                raise KeyError(
                    f"Missing {component} {season} {period} rate for "
                    f"{self.utility.value} {self.plan_name}"
                ) from exc
        return rates

    def daily_fixed_charge(self, timestamp: pd.Timestamp) -> float:
        day_type = day_types([timestamp])[0]
        summer_end = 10 if self.utility is Utility.SDGE and self.plan_name == "EV-TOU-5" else 9
        season = "summer" if 6 <= timestamp.month <= summer_end else "winter"
        key = "weekends" if day_type == "weekend_holiday" else "weekdays"
        day_rates = self.plan_details[season][key]
        try:
            return float(day_rates["fixedCharge"])
        except KeyError as exc:
            raise KeyError(
                f"Required NBT plan {self.utility.value} {self.plan_name} has no "
                f"fixedCharge for {season}/{key}"
            ) from exc
