"""Source rate records for NEM 2 settlement and archived NBT surplus evidence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
import math
from pathlib import Path

import pandas as pd

from .models import Utility


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_NSC_DATA = ROOT / "data" / "tariffs" / "nsc_rates.csv"
DEFAULT_EEC_ADJUSTMENT_DATA = (
    ROOT / "data" / "tariffs" / "eec_adjustment_rates.csv"
)
DEFAULT_TRUE_UP_SOURCE_MANIFEST = (
    ROOT / "data" / "tariffs" / "true_up_source_manifest.json"
)
MAX_NSC_RATE_USD_PER_KWH = 0.25
MAX_AVERAGE_RETAIL_EXPORT_RATE_USD_PER_KWH = 1.0


def _nonnegative_finite(value: float, field_name: str) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be numeric") from exc
    if not math.isfinite(parsed):
        raise ValueError(f"{field_name} must be finite")
    if parsed < 0:
        raise ValueError(f"{field_name} must be non-negative")
    return parsed


def _canonical_true_up_month(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("true_up_month must be a canonical YYYY-MM string")
    try:
        parsed = datetime.strptime(value, "%Y-%m")
    except ValueError as exc:
        raise ValueError("true_up_month must be a canonical YYYY-MM string") from exc
    if parsed.strftime("%Y-%m") != value:
        raise ValueError("true_up_month must be a canonical YYYY-MM string")
    return value


@dataclass(frozen=True)
class NetSurplusCompensationRate:
    utility: Utility
    true_up_month: str
    rate_usd_per_kwh: float
    source_id: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "utility", Utility.parse(self.utility))
        object.__setattr__(
            self, "true_up_month", _canonical_true_up_month(self.true_up_month)
        )
        object.__setattr__(
            self,
            "rate_usd_per_kwh",
            _nonnegative_finite(self.rate_usd_per_kwh, "rate_usd_per_kwh"),
        )
        if self.rate_usd_per_kwh > MAX_NSC_RATE_USD_PER_KWH:
            raise ValueError("rate_usd_per_kwh exceeds the NSC magnitude guardrail")
        if not self.source_id:
            raise ValueError("source_id must be non-empty")


@dataclass(frozen=True)
class AverageRetailExportCompensationRate:
    """Utility-wide EEC recoupment rate for one true-up month.

    This is distinct from both the customer's hourly ACC export schedule and
    the monthly NSC rate. Retain source generation/delivery rates for audit;
    The annual NBT research model does not use surplus adjustments.
    """

    utility: Utility
    true_up_month: str
    generation_rate_usd_per_kwh: float
    delivery_rate_usd_per_kwh: float
    source_id: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "utility", Utility.parse(self.utility))
        object.__setattr__(
            self, "true_up_month", _canonical_true_up_month(self.true_up_month)
        )
        for field_name in (
            "generation_rate_usd_per_kwh",
            "delivery_rate_usd_per_kwh",
        ):
            object.__setattr__(
                self,
                field_name,
                _nonnegative_finite(getattr(self, field_name), field_name),
            )
            if getattr(self, field_name) > MAX_AVERAGE_RETAIL_EXPORT_RATE_USD_PER_KWH:
                raise ValueError(f"{field_name} exceeds the 1 USD/kWh guardrail")
        if not self.source_id:
            raise ValueError("source_id must be non-empty")


@dataclass(frozen=True)
class AverageRetailExportCompensationSchedule:
    """Strict lookup for source-normalized true-up EEC adjustment rates."""

    rows: pd.DataFrame
    source_manifest_path: Path = DEFAULT_TRUE_UP_SOURCE_MANIFEST

    @classmethod
    def from_csv(
        cls,
        data_path: str | Path = DEFAULT_EEC_ADJUSTMENT_DATA,
        source_manifest_path: str | Path = DEFAULT_TRUE_UP_SOURCE_MANIFEST,
    ) -> "AverageRetailExportCompensationSchedule":
        path = Path(data_path)
        if not path.is_file():
            raise FileNotFoundError(
                f"Normalized EEC adjustment rate data not found: {path}"
            )
        return cls(pd.read_csv(path), Path(source_manifest_path))

    def __post_init__(self) -> None:
        required = {
            "utility",
            "true_up_month",
            "generation_rate_usd_per_kwh",
            "delivery_rate_usd_per_kwh",
            "rate_unit",
            "source_sign_convention",
            "source_id",
            "unit_source_id",
        }
        missing = required - set(self.rows.columns)
        if missing:
            raise ValueError(
                f"EEC adjustment rate data is missing columns: {sorted(missing)}"
            )
        if self.rows.empty:
            raise ValueError("EEC adjustment rate data is empty")

        rows = self.rows.copy()
        if rows[list(required)].isna().any().any():
            raise ValueError("EEC adjustment rate data contains missing values")
        rate_columns = [
            "generation_rate_usd_per_kwh",
            "delivery_rate_usd_per_kwh",
        ]
        try:
            for column in rate_columns:
                rows[column] = pd.to_numeric(rows[column], errors="raise")
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "EEC adjustment rate data contains non-numeric rates"
            ) from exc
        finite = rows[rate_columns].apply(lambda column: column.map(math.isfinite))
        if not finite.all().all():
            raise ValueError("EEC adjustment rate data contains non-finite rates")
        if (rows[rate_columns] < 0).any().any():
            raise ValueError("EEC adjustment rate data contains negative normalized rates")
        if (
            rows[rate_columns] > MAX_AVERAGE_RETAIL_EXPORT_RATE_USD_PER_KWH
        ).any().any():
            raise ValueError(
                "EEC adjustment rate data exceeds the 1 USD/kWh guardrail"
            )
        if set(rows["rate_unit"]) != {"USD/kWh"}:
            raise ValueError("EEC adjustment rate_unit must be exactly 'USD/kWh'")
        allowed_sign_conventions = {
            "positive_adjustment_rate",
            "negative_bill_line_item",
        }
        if not set(rows["source_sign_convention"]) <= allowed_sign_conventions:
            raise ValueError("EEC adjustment source_sign_convention is unsupported")

        for month in rows["true_up_month"]:
            _canonical_true_up_month(month)
        for utility in rows["utility"]:
            if Utility.parse(utility).value != utility:
                raise ValueError(
                    f"EEC adjustment rate data has non-canonical utility {utility!r}"
                )
        if rows.duplicated(["utility", "true_up_month"]).any():
            raise ValueError(
                "EEC adjustment rate data has duplicate utility/true_up_month rows"
            )

        manifest_path = Path(self.source_manifest_path)
        if not manifest_path.is_file():
            raise FileNotFoundError(f"True-up source manifest not found: {manifest_path}")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        adjustment_sources = [
            source
            for source in manifest["sources"]
            if source.get("source_type") == "monthly_eec_adjustment_rates"
            or "monthly_eec_adjustment_rates"
            in source.get("additional_source_types", [])
        ]
        source_ids = [source["source_id"] for source in adjustment_sources]
        if len(source_ids) != len(set(source_ids)):
            raise ValueError(
                "True-up source manifest has duplicate EEC adjustment source IDs"
            )
        sources = {source["source_id"]: source for source in adjustment_sources}
        manifest_sources = {
            source["source_id"]: source for source in manifest["sources"]
        }
        unique_sources = rows[
            ["utility", "source_id", "unit_source_id"]
        ].drop_duplicates()
        for utility, source_id, unit_source_id in unique_sources.itertuples(
            index=False, name=None
        ):
            if source_id not in sources:
                raise ValueError(
                    f"EEC adjustment source_id {source_id!r} is absent from the manifest"
                )
            if sources[source_id]["utility"] != utility:
                raise ValueError(
                    f"EEC adjustment source_id {source_id!r} belongs to "
                    f"{sources[source_id]['utility']}, not {utility}"
                )
            if unit_source_id not in manifest_sources:
                raise ValueError(
                    f"EEC adjustment unit_source_id {unit_source_id!r} is absent "
                    "from the manifest"
                )
            unit_source = manifest_sources[unit_source_id]
            if unit_source["source_type"] != "tariff_schedule":
                raise ValueError(
                    f"EEC adjustment unit_source_id {unit_source_id!r} is not a "
                    "tariff schedule"
                )
            if unit_source["utility"] != utility:
                raise ValueError(
                    f"EEC adjustment unit_source_id {unit_source_id!r} belongs to "
                    f"{unit_source['utility']}, not {utility}"
                )
        object.__setattr__(self, "rows", rows.reset_index(drop=True))
        object.__setattr__(self, "source_manifest_path", manifest_path)

    def resolve(
        self,
        utility: str | Utility,
        true_up_month: str,
    ) -> AverageRetailExportCompensationRate:
        parsed_utility = Utility.parse(utility)
        canonical_month = _canonical_true_up_month(true_up_month)
        matches = self.rows[
            (self.rows["utility"] == parsed_utility.value)
            & (self.rows["true_up_month"] == canonical_month)
        ]
        if len(matches) != 1:
            available = sorted(
                self.rows[self.rows["utility"] == parsed_utility.value][
                    "true_up_month"
                ].unique()
            )
            raise KeyError(
                f"Expected one EEC adjustment rate for {parsed_utility.value}, "
                f"true_up_month={canonical_month}; found {len(matches)}. "
                f"Available: {available}"
            )
        row = matches.iloc[0]
        return AverageRetailExportCompensationRate(
            utility=parsed_utility,
            true_up_month=canonical_month,
            generation_rate_usd_per_kwh=float(
                row["generation_rate_usd_per_kwh"]
            ),
            delivery_rate_usd_per_kwh=float(row["delivery_rate_usd_per_kwh"]),
            source_id=str(row["source_id"]),
        )


@dataclass(frozen=True)
class NetSurplusCompensationSchedule:
    rows: pd.DataFrame
    source_manifest_path: Path = DEFAULT_TRUE_UP_SOURCE_MANIFEST

    @classmethod
    def from_csv(
        cls,
        data_path: str | Path = DEFAULT_NSC_DATA,
        source_manifest_path: str | Path = DEFAULT_TRUE_UP_SOURCE_MANIFEST,
    ) -> "NetSurplusCompensationSchedule":
        path = Path(data_path)
        if not path.is_file():
            raise FileNotFoundError(f"Normalized NSC rate data not found: {path}")
        return cls(pd.read_csv(path), Path(source_manifest_path))

    def __post_init__(self) -> None:
        required = {
            "utility",
            "true_up_month",
            "rate_usd_per_kwh",
            "rate_unit",
            "source_id",
        }
        missing = required - set(self.rows.columns)
        if missing:
            raise ValueError(f"NSC rate data is missing columns: {sorted(missing)}")
        if self.rows.empty:
            raise ValueError("NSC rate data is empty")

        rows = self.rows.copy()
        if rows[list(required)].isna().any().any():
            raise ValueError("NSC rate data contains missing values")
        try:
            rows["rate_usd_per_kwh"] = pd.to_numeric(
                rows["rate_usd_per_kwh"], errors="raise"
            )
        except (TypeError, ValueError) as exc:
            raise ValueError("NSC rate data contains non-numeric rates") from exc
        if not rows["rate_usd_per_kwh"].map(math.isfinite).all():
            raise ValueError("NSC rate data contains non-finite rates")
        if (rows["rate_usd_per_kwh"] < 0).any():
            raise ValueError("NSC rate data contains negative rates")
        if (rows["rate_usd_per_kwh"] > MAX_NSC_RATE_USD_PER_KWH).any():
            raise ValueError("NSC rate data exceeds the 0.25 USD/kWh magnitude guardrail")
        if set(rows["rate_unit"]) != {"USD/kWh"}:
            raise ValueError("NSC rate_unit must be exactly 'USD/kWh'")

        for month in rows["true_up_month"]:
            _canonical_true_up_month(month)
        for utility in rows["utility"]:
            if Utility.parse(utility).value != utility:
                raise ValueError(f"NSC rate data has non-canonical utility {utility!r}")
        if rows.duplicated(["utility", "true_up_month"]).any():
            raise ValueError("NSC rate data has duplicate utility/true_up_month rows")

        manifest_path = Path(self.source_manifest_path)
        if not manifest_path.is_file():
            raise FileNotFoundError(f"True-up source manifest not found: {manifest_path}")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        monthly_sources = [
            source
            for source in manifest["sources"]
            if source["source_type"] == "monthly_nsc_rates"
        ]
        source_ids = [source["source_id"] for source in monthly_sources]
        if len(source_ids) != len(set(source_ids)):
            raise ValueError("True-up source manifest has duplicate monthly NSC source IDs")
        sources = {source["source_id"]: source for source in monthly_sources}
        unique_sources = rows[["utility", "source_id"]].drop_duplicates()
        for utility, source_id in unique_sources.itertuples(index=False, name=None):
            if source_id not in sources:
                raise ValueError(f"NSC source_id {source_id!r} is absent from the manifest")
            if sources[source_id]["utility"] != utility:
                raise ValueError(
                    f"NSC source_id {source_id!r} belongs to "
                    f"{sources[source_id]['utility']}, not {utility}"
                )
        object.__setattr__(self, "rows", rows.reset_index(drop=True))
        object.__setattr__(self, "source_manifest_path", manifest_path)

    def resolve(
        self,
        utility: str | Utility,
        true_up_month: str,
    ) -> NetSurplusCompensationRate:
        parsed_utility = Utility.parse(utility)
        canonical_month = _canonical_true_up_month(true_up_month)
        matches = self.rows[
            (self.rows["utility"] == parsed_utility.value)
            & (self.rows["true_up_month"] == canonical_month)
        ]
        if len(matches) != 1:
            available = sorted(
                self.rows[self.rows["utility"] == parsed_utility.value][
                    "true_up_month"
                ].unique()
            )
            raise KeyError(
                f"Expected one NSC rate for {parsed_utility.value}, "
                f"true_up_month={canonical_month}; found {len(matches)}. "
                f"Available: {available}"
            )
        row = matches.iloc[0]
        return NetSurplusCompensationRate(
            utility=parsed_utility,
            true_up_month=canonical_month,
            rate_usd_per_kwh=float(row["rate_usd_per_kwh"]),
            source_id=str(row["source_id"]),
        )
