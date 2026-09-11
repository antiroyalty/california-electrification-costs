from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import Enum
import math
from typing import TYPE_CHECKING, Sequence

import pandas as pd

if TYPE_CHECKING:
    from .catalog import ExportCreditSchedule
    from .import_rates import ImportRateSchedule


# One milliwatt-hour per modeled year: numerical equality, not a sizing allowance.
ANNUAL_ENERGY_TOLERANCE_KWH = 1e-6


def annual_net_surplus_kwh(annual_import_kwh: float, annual_export_kwh: float) -> float:
    """Return positive annual meter surplus, treating rounding noise as zero."""
    if any(not math.isfinite(v) or v < 0 for v in (annual_import_kwh, annual_export_kwh)):
        raise ValueError("Annual meter energy must be finite and non-negative")
    surplus_kwh = annual_export_kwh - annual_import_kwh
    return surplus_kwh if surplus_kwh > ANNUAL_ENERGY_TOLERANCE_KWH else 0.0


def require_annual_export_cap(annual_import_kwh: float, annual_export_kwh: float) -> None:
    """Reject meter flows outside the NBT research model's annual energy domain."""
    if annual_net_surplus_kwh(annual_import_kwh, annual_export_kwh) > 0:
        raise ValueError(
            "NBT research requires annual exported kWh <= annual imported kWh; "
            f"imports={annual_import_kwh:.12g}, exports={annual_export_kwh:.12g}. "
            "Regenerate dispatch within the cap before reporting research costs."
        )


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
    tariff_snapshot_date: str = "2026-08-09"

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

    def __post_init__(self) -> None:
        object.__setattr__(self, "utility", Utility.parse(self.utility))
