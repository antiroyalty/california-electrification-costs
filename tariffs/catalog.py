from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import pandas as pd

from .calendar import day_types
from .import_rates import ImportRateSchedule
from .models import CustomerSegment, NBTScenario, TariffBundle, Utility


DEFAULT_EXPORT_DATA = Path(__file__).resolve().parents[1] / "data" / "tariffs" / "nbt_export_rates.csv"
DEFAULT_ACC_PLUS_DATA = Path(__file__).resolve().parents[1] / "data" / "tariffs" / "acc_plus_rates.csv"


@dataclass(frozen=True)
class ExportCreditSchedule:
    utility: Utility
    billing_year: int
    nbt_vintage: int
    rows: pd.DataFrame

    def __post_init__(self) -> None:
        required = {"month", "day_type", "hour_start", "component", "rate_usd_per_kwh"}
        missing = required - set(self.rows.columns)
        if missing:
            raise ValueError(f"Export schedule is missing columns: {sorted(missing)}")
        for component in ("generation", "delivery", "total"):
            subset = self.rows[self.rows["component"] == component]
            if len(subset) != 576:
                raise ValueError(
                    f"{self.utility.value} NBT{self.nbt_vintage} {component} schedule must have "
                    f"exactly 576 observations; found {len(subset)}"
                )
            if subset.duplicated(["month", "day_type", "hour_start"]).any():
                raise ValueError(f"Duplicate month/day/hour rows in {component} schedule")
            if set(subset["month"]) != set(range(1, 13)):
                raise ValueError(f"{component} schedule must cover months 1 through 12")
            if set(subset["hour_start"]) != set(range(24)):
                raise ValueError(f"{component} schedule must cover hours 0 through 23")
            if set(subset["day_type"]) != {"weekday", "weekend_holiday"}:
                raise ValueError(f"{component} schedule has invalid day types")
            if (subset["rate_usd_per_kwh"] < 0).any():
                raise ValueError(f"{component} schedule contains negative rates")

    def rates_for(
        self,
        timestamps: Iterable[pd.Timestamp],
        *,
        component: str = "total",
    ) -> list[float]:
        if component not in {"generation", "delivery", "total"}:
            raise ValueError(f"Unknown export-rate component {component!r}")
        index = pd.DatetimeIndex(pd.to_datetime(list(timestamps)))
        lookup = self.rows[self.rows["component"] == component].set_index(
            ["month", "day_type", "hour_start"]
        )["rate_usd_per_kwh"]
        types = day_types(index)
        keys = list(zip(index.month, types, index.hour))
        try:
            return [float(lookup.loc[key]) for key in keys]
        except KeyError as exc:
            raise KeyError(f"No {component} export rate for key {exc.args[0]!r}") from exc


class TariffCatalog:
    def __init__(
        self,
        export_data_path: str | Path = DEFAULT_EXPORT_DATA,
        acc_plus_data_path: str | Path = DEFAULT_ACC_PLUS_DATA,
    ):
        self.export_data_path = Path(export_data_path)
        self.acc_plus_data_path = Path(acc_plus_data_path)

    def _read_export_data(self) -> pd.DataFrame:
        if not self.export_data_path.exists():
            raise FileNotFoundError(
                f"Normalized NBT export data not found: {self.export_data_path}. "
                "Run scripts/build_nbt_export_schedules.py."
            )
        data = pd.read_csv(self.export_data_path)
        expected = {
            "utility",
            "billing_year",
            "nbt_vintage",
            "service_type",
            "customer_segment",
            "month",
            "day_type",
            "hour_start",
            "component",
            "rate_usd_per_kwh",
            "source_id",
        }
        missing = expected - set(data.columns)
        if missing:
            raise ValueError(f"Normalized NBT export data is missing columns: {sorted(missing)}")
        return data

    def export_schedule(
        self,
        utility: str | Utility,
        scenario: NBTScenario,
    ) -> ExportCreditSchedule:
        parsed = Utility.parse(utility)
        data = self._read_export_data()
        rows = data[
            (data["utility"] == parsed.value)
            & (data["billing_year"] == scenario.billing_year)
            & (data["nbt_vintage"] == scenario.nbt_vintage)
            & (data["service_type"] == scenario.service_type.value)
            & (data["customer_segment"] == "all")
        ].copy()
        if rows.empty:
            available = (
                data[data["utility"] == parsed.value][["billing_year", "nbt_vintage"]]
                .drop_duplicates()
                .sort_values(["billing_year", "nbt_vintage"])
                .to_dict("records")
            )
            raise KeyError(
                f"No export schedule for {parsed.value}, billing_year={scenario.billing_year}, "
                f"nbt_vintage={scenario.nbt_vintage}. Available: {available}"
            )
        return ExportCreditSchedule(parsed, scenario.billing_year, scenario.nbt_vintage, rows)

    def acc_plus_rate(self, utility: str | Utility, scenario: NBTScenario) -> float:
        if not scenario.include_acc_plus:
            return 0.0
        parsed = Utility.parse(utility)
        if not self.acc_plus_data_path.exists():
            raise FileNotFoundError(f"ACC Plus source data not found: {self.acc_plus_data_path}")
        data = pd.read_csv(self.acc_plus_data_path)
        required = {"utility", "nbt_vintage", "customer_segment", "rate_usd_per_kwh", "source_id"}
        missing = required - set(data.columns)
        if missing:
            raise ValueError(f"ACC Plus data is missing columns: {sorted(missing)}")
        rows = data[
            (data["utility"] == parsed.value)
            & (data["nbt_vintage"] == scenario.nbt_vintage)
            & (data["customer_segment"] == scenario.customer_segment.value)
        ]
        if len(rows) != 1:
            raise KeyError(
                f"Expected exactly one ACC Plus rate for {parsed.value}, NBT{scenario.nbt_vintage}, "
                f"segment={scenario.customer_segment.value}; found {len(rows)}"
            )
        rate = float(rows["rate_usd_per_kwh"].item())
        if rate < 0:
            raise ValueError("ACC Plus rate cannot be negative")
        return rate

    def bundle(
        self,
        utility: str | Utility,
        scenario: NBTScenario,
        *,
        import_plan: str | None = None,
        non_bypassable_rate: float | None = None,
    ) -> TariffBundle:
        parsed = Utility.parse(utility)
        return TariffBundle(
            utility=parsed,
            scenario=scenario,
            import_schedule=ImportRateSchedule.resolve(
                parsed, import_plan, non_bypassable_rate=non_bypassable_rate
            ),
            export_schedule=self.export_schedule(parsed, scenario),
            acc_plus_rate=self.acc_plus_rate(parsed, scenario),
        )
