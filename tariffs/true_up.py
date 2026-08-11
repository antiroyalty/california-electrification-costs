"""Source-linked primitives for annual NBT true-up inputs."""

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
DEFAULT_TRUE_UP_SOURCE_MANIFEST = (
    ROOT / "data" / "tariffs" / "true_up_source_manifest.json"
)
MAX_NSC_RATE_USD_PER_KWH = 0.25


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
