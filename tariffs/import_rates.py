from __future__ import annotations

from dataclasses import dataclass
import calendar
from datetime import date
import json
from pathlib import Path
from typing import Iterable

import pandas as pd

from .calendar import day_types
from .models import Utility


DEFAULT_IMPORT_SNAPSHOT_DATA = (
    Path(__file__).resolve().parents[1] / "data" / "tariffs" / "import_rate_snapshots.json"
)
DEFAULT_IMPORT_SNAPSHOT_DATE = "2026-08-09"

REQUIRED_NBT_IMPORT_PLANS = {
    Utility.PGE: "E-ELEC",
    Utility.SCE: "TOU-D-PRIME",
    Utility.SDGE: "EV-TOU-5",
}


def required_nbt_import_plan(utility: str | Utility) -> str:
    return REQUIRED_NBT_IMPORT_PLANS[Utility.parse(utility)]


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


def _component_period(day_rates: dict, component_rates: dict, day_key: str, hour: int) -> str:
    period = _period_for_hour(day_rates, hour)
    if period == "peak" and day_key == "weekends" and "weekendPeak" in component_rates:
        return "weekendPeak"
    return period


def _validate_snapshot_date(value: str) -> str:
    try:
        return date.fromisoformat(str(value)).isoformat()
    except ValueError as exc:
        raise ValueError(f"Invalid tariff snapshot date {value!r}; expected YYYY-MM-DD") from exc


def _validate_plan_details(utility: Utility, plan_name: str, details: dict) -> None:
    if details.get("rate_unit") != "USD/kWh":
        raise ValueError(
            f"{utility.value} {plan_name} must declare rate_unit='USD/kWh'; "
            f"found {details.get('rate_unit')!r}"
        )
    if details.get("fixed_charge_unit") != "USD/meter/day":
        raise ValueError(
            f"{utility.value} {plan_name} must declare fixed_charge_unit='USD/meter/day'"
        )
    for field in (
        "nonBypassableRate",
        "generationNonOffsettableRate",
        "deliveryNonOffsettableRate",
    ):
        value = details.get(field)
        if value is None or pd.isna(value) or float(value) < 0:
            raise ValueError(f"{utility.value} {plan_name} has invalid {field}")
    component_rates = details.get("componentRates", {})
    if set(component_rates) != {"generation", "delivery"}:
        raise ValueError(
            f"{utility.value} {plan_name} must define generation and delivery components"
        )

    for season in ("summer", "winter"):
        for day_key in ("weekdays", "weekends"):
            try:
                day_rates = details[season][day_key]
            except KeyError as exc:
                raise ValueError(
                    f"{utility.value} {plan_name} is missing {season}/{day_key}"
                ) from exc
            fixed_charge = day_rates.get("fixedCharge")
            if fixed_charge is None or pd.isna(fixed_charge) or float(fixed_charge) < 0:
                raise ValueError(
                    f"{utility.value} {plan_name} has invalid fixed charge for "
                    f"{season}/{day_key}"
                )
            hour_lists = [
                day_rates[key]
                for key in (
                    "peakHours",
                    "onPeakHours",
                    "midPeakHours",
                    "partPeakHours",
                    "superOffPeakHours",
                    "offPeakHours",
                )
                if key in day_rates
            ]
            covered = [int(hour) for hours in hour_lists for hour in hours]
            if sorted(covered) != list(range(24)):
                raise ValueError(
                    f"{utility.value} {plan_name} {season}/{day_key} must cover each "
                    f"hour 0-23 exactly once; found {covered}"
                )
            for hour in range(24):
                total = _rate_for_hour(day_rates, hour)
                if pd.isna(total) or total < 0 or total > 5:
                    raise ValueError(
                        f"{utility.value} {plan_name} has implausible total rate "
                        f"{total!r} at {season}/{day_key}/{hour}"
                    )
                components = []
                for component in ("generation", "delivery"):
                    season_components = component_rates[component].get(season)
                    if season_components is None:
                        raise ValueError(
                            f"{utility.value} {plan_name} is missing {component}/{season}"
                        )
                    period = _component_period(day_rates, season_components, day_key, hour)
                    value = season_components.get(period)
                    if value is None or pd.isna(value) or float(value) < 0 or float(value) > 5:
                        raise ValueError(
                            f"{utility.value} {plan_name} has invalid {component} rate "
                            f"for {season}/{day_key}/{period}"
                        )
                    components.append(float(value))
                if abs(total - sum(components)) > 1e-6:
                    raise ValueError(
                        f"{utility.value} {plan_name} total does not reconcile to "
                        f"generation + delivery at {season}/{day_key}/{hour}: "
                        f"{total} != {sum(components)}"
                    )


def _load_snapshot_plan(
    path: Path,
    *,
    utility: Utility,
    plan_name: str,
    snapshot_as_of: str,
) -> tuple[dict, str]:
    if not path.exists():
        raise FileNotFoundError(f"Import tariff snapshot not found: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    requested_date = _validate_snapshot_date(snapshot_as_of)
    available_date = _validate_snapshot_date(payload.get("snapshot_as_of", ""))
    if requested_date != available_date:
        raise KeyError(
            f"No import tariff snapshot for {requested_date}; available snapshot is "
            f"{available_date}. Add and source-lock a new snapshot rather than silently "
            "reusing another date."
        )
    matches = [
        row
        for row in payload.get("schedules", [])
        if row.get("utility") == utility.value and row.get("plan_name") == plan_name
    ]
    if len(matches) != 1:
        raise KeyError(
            f"Expected one {utility.value} {plan_name} schedule in {path}; found {len(matches)}"
        )
    details = dict(matches[0])
    _validate_snapshot_date(details.get("effective_date", ""))
    if not details.get("source_id"):
        raise ValueError(f"{utility.value} {plan_name} snapshot is missing source_id")
    _validate_plan_details(utility, plan_name, details)
    return details, available_date


@dataclass(frozen=True)
class ImportRateSchedule:
    utility: Utility
    plan_name: str
    plan_details: dict
    non_bypassable_rate: float = 0.0
    snapshot_as_of: str = DEFAULT_IMPORT_SNAPSHOT_DATE
    effective_date: str = ""
    source_id: str = ""

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
        snapshot_as_of: str = DEFAULT_IMPORT_SNAPSHOT_DATE,
        snapshot_data_path: str | Path = DEFAULT_IMPORT_SNAPSHOT_DATA,
    ) -> "ImportRateSchedule":
        parsed = Utility.parse(utility)
        selected = plan_name or required_nbt_import_plan(parsed)
        required = required_nbt_import_plan(parsed)
        if selected != required:
            raise ValueError(
                f"The source-locked research tariff for {parsed.value} must use "
                f"{required}; received {selected}"
            )
        details, resolved_snapshot_date = _load_snapshot_plan(
            Path(snapshot_data_path),
            utility=parsed,
            plan_name=selected,
            snapshot_as_of=snapshot_as_of,
        )
        if non_bypassable_rate is None:
            try:
                resolved_nbc = float(details["nonBypassableRate"])
            except KeyError as exc:
                raise KeyError(
                    f"Required research plan {parsed.value} {selected} has no "
                    "nonBypassableRate"
                ) from exc
        else:
            resolved_nbc = float(non_bypassable_rate)
        if resolved_nbc < 0:
            raise ValueError("non_bypassable_rate cannot be negative")
        return cls(
            parsed,
            selected,
            details,
            resolved_nbc,
            resolved_snapshot_date,
            str(details["effective_date"]),
            str(details["source_id"]),
        )

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
            summer_end = int(self.plan_details["summer_end_month"])
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
            season_components = component_rates[season]
            period = _component_period(day_rates, season_components, key, int(timestamp.hour))
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
        summer_end = int(self.plan_details["summer_end_month"])
        season = "summer" if 6 <= timestamp.month <= summer_end else "winter"
        key = "weekends" if day_type == "weekend_holiday" else "weekdays"
        day_rates = self.plan_details[season][key]
        try:
            return float(day_rates["fixedCharge"])
        except KeyError as exc:
            raise KeyError(
                f"Required research plan {self.utility.value} {self.plan_name} has no "
                f"fixedCharge for {season}/{key}"
            ) from exc
