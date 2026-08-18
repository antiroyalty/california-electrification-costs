from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum
from typing import TYPE_CHECKING, Sequence

import pandas as pd

if TYPE_CHECKING:
    from .catalog import ExportCreditSchedule
    from .import_rates import ImportRateSchedule


class Utility(str, Enum):
    PGE = "PG&E"
    SCE = "SCE"
    SDGE = "SDG&E"

    @classmethod
    def parse(cls, value: str | "Utility") -> "Utility":
        if isinstance(value, cls):
            return value
        normalized = str(value).strip().upper().replace(" ", "").replace(".", "")
        aliases = {
            "PGE": cls.PGE,
            "PG&E": cls.PGE,
            "SCE": cls.SCE,
            "SDGE": cls.SDGE,
            "SDG&E": cls.SDGE,
        }
        try:
            return aliases[normalized]
        except KeyError as exc:
            raise ValueError(f"Unsupported utility {value!r}; expected PG&E, SCE, or SDG&E") from exc


class ServiceType(str, Enum):
    BUNDLED = "bundled"


class CustomerSegment(str, Enum):
    STANDARD = "standard_non_equity"
    EQUITY = "equity"


class ExportCompensationRegime(str, Enum):
    """Export-compensation policy used by a sizing counterfactual."""

    NBT_2026 = "nbt_2026"
    NEM2_AT_2026_RETAIL_RATES = "nem2_at_2026_retail_rates"

    @classmethod
    def parse(
        cls,
        value: str | "ExportCompensationRegime",
    ) -> "ExportCompensationRegime":
        if isinstance(value, cls):
            return value
        try:
            return cls(str(value))
        except ValueError as exc:
            expected = ", ".join(member.value for member in cls)
            raise ValueError(
                f"Unsupported export-compensation regime {value!r}; "
                f"expected one of: {expected}"
            ) from exc

    @property
    def max_pv_to_annual_load_ratio(self) -> float:
        """Policy-specific annual PV-generation sizing limit."""

        if self is ExportCompensationRegime.NBT_2026:
            return 1.5
        return 1.0


@dataclass(frozen=True)
class NBTScenario:
    """Explicit policy choices needed to resolve one NBT tariff bundle.

    ``nbt_vintage`` is the calendar year of the interconnection application.
    ``billing_year`` selects the prices used for the modeled bill year.
    """

    billing_year: int = 2026
    nbt_vintage: int = 2026
    service_type: ServiceType = ServiceType.BUNDLED
    customer_segment: CustomerSegment = CustomerSegment.STANDARD
    include_acc_plus: bool = True
    tariff_snapshot_date: str = "2026-08-09"
    true_up_month: str = "2026-08"

    def __post_init__(self) -> None:
        if self.billing_year < 2023:
            raise ValueError("NBT billing_year must be 2023 or later")
        if self.nbt_vintage < 2023:
            raise ValueError("NBT interconnection vintage must be 2023 or later")
        if self.nbt_vintage > self.billing_year:
            raise ValueError("NBT interconnection vintage cannot be after the billing year")
        if self.service_type is not ServiceType.BUNDLED:
            raise NotImplementedError("Only bundled-service NBT tariffs are modeled")
        try:
            date.fromisoformat(self.tariff_snapshot_date)
        except ValueError as exc:
            raise ValueError("tariff_snapshot_date must be an ISO date (YYYY-MM-DD)") from exc
        try:
            parsed_true_up_month = datetime.strptime(self.true_up_month, "%Y-%m")
        except (TypeError, ValueError) as exc:
            raise ValueError("true_up_month must be a canonical YYYY-MM string") from exc
        if parsed_true_up_month.strftime("%Y-%m") != self.true_up_month:
            raise ValueError("true_up_month must be a canonical YYYY-MM string")
        if parsed_true_up_month.year != self.billing_year:
            raise ValueError("true_up_month must fall within billing_year")


@dataclass(frozen=True)
class EnergyFlows:
    timestamps: pd.DatetimeIndex
    import_kwh: Sequence[float]
    export_kwh: Sequence[float]

    def validated_frame(self) -> pd.DataFrame:
        timestamps = pd.DatetimeIndex(pd.to_datetime(self.timestamps))
        imports = pd.Series(self.import_kwh, dtype=float).reset_index(drop=True)
        exports = pd.Series(self.export_kwh, dtype=float).reset_index(drop=True)
        if not (len(timestamps) == len(imports) == len(exports)):
            raise ValueError(
                "timestamps, import_kwh, and export_kwh must have identical lengths; "
                f"got {len(timestamps)}, {len(imports)}, and {len(exports)}"
            )
        if timestamps.hasnans:
            raise ValueError("timestamps contain missing values")
        if timestamps.has_duplicates:
            raise ValueError("timestamps must be unique")
        if (imports < 0).any() or (exports < 0).any():
            raise ValueError("import_kwh and export_kwh must be non-negative")
        simultaneous = (imports > 1e-9) & (exports > 1e-9)
        if simultaneous.any():
            first = int(simultaneous[simultaneous].index[0])
            raise ValueError(
                "A meter interval cannot simultaneously import and export; "
                f"first violation is row {first}"
            )
        return pd.DataFrame({"timestamp": timestamps, "import_kwh": imports, "export_kwh": exports})


@dataclass(frozen=True)
class TariffBundle:
    utility: Utility
    scenario: NBTScenario
    import_schedule: "ImportRateSchedule"
    export_schedule: "ExportCreditSchedule"
    acc_plus_rate: float
    acc_plus_source_id: str | None

    def __post_init__(self) -> None:
        if self.acc_plus_rate < 0:
            raise ValueError("ACC Plus rate cannot be negative")
        if self.scenario.include_acc_plus and not self.acc_plus_source_id:
            raise ValueError("Included ACC Plus rate must declare a source_id")
