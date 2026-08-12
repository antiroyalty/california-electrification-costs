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
    the monthly NSC rate. The two components preserve the utility tariff's
    generation/delivery credit-bank separation.
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
class TrueUpPolicy:
    """Source-linked utility rules for disposing of base EEC at true-up."""

    utility: Utility
    apply_remaining_eec_to_prior_charges: bool
    carry_remaining_eec_forward: bool
    source_id: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "utility", Utility.parse(self.utility))
        if not isinstance(self.apply_remaining_eec_to_prior_charges, bool):
            raise TypeError("apply_remaining_eec_to_prior_charges must be boolean")
        if not isinstance(self.carry_remaining_eec_forward, bool):
            raise TypeError("carry_remaining_eec_forward must be boolean")
        if not self.source_id:
            raise ValueError("source_id must be non-empty")

    @classmethod
    def for_utility(cls, utility: str | Utility) -> "TrueUpPolicy":
        parsed = Utility.parse(utility)
        policies = {
            Utility.PGE: cls(
                utility=Utility.PGE,
                apply_remaining_eec_to_prior_charges=True,
                carry_remaining_eec_forward=True,
                source_id="pge_nbt_rules_2026-08-10",
            ),
            Utility.SCE: cls(
                utility=Utility.SCE,
                apply_remaining_eec_to_prior_charges=True,
                carry_remaining_eec_forward=False,
                source_id="sce_nbt_rules_2026-08-10",
            ),
            Utility.SDGE: cls(
                utility=Utility.SDGE,
                apply_remaining_eec_to_prior_charges=False,
                carry_remaining_eec_forward=False,
                source_id="sdge_nbt_rules_2026-08-10",
            ),
        }
        return policies[parsed]


@dataclass(frozen=True)
class TrueUpSettlement:
    """Auditable result of the annual NBT credit reconciliation.

    ``net_bill_adjustment`` is positive for an added charge and negative for
    an added credit relative to the monthly amounts already paid.
    """

    utility: Utility
    true_up_month: str
    annual_import_kwh: float
    annual_export_kwh: float
    net_surplus_kwh: float
    generation_adjustment_rate_usd_per_kwh: float
    delivery_adjustment_rate_usd_per_kwh: float
    nsc_rate_usd_per_kwh: float
    generation_eec_adjustment_charge: float
    delivery_eec_adjustment_charge: float
    generation_eec_applied_to_adjustment: float
    delivery_eec_applied_to_adjustment: float
    remaining_offsettable_generation_charges: float
    remaining_offsettable_delivery_charges: float
    generation_eec_applied_to_prior_charges: float
    delivery_eec_applied_to_prior_charges: float
    nsc_credit: float
    net_bill_adjustment: float
    ending_generation_credit_bank: float
    ending_delivery_credit_bank: float
    ending_acc_plus_credit_bank: float
    forfeited_generation_credit: float
    forfeited_delivery_credit: float
    policy_source_id: str
    adjustment_rate_source_id: str | None
    nsc_rate_source_id: str | None

    @property
    def total_eec_adjustment_charge(self) -> float:
        return (
            self.generation_eec_adjustment_charge
            + self.delivery_eec_adjustment_charge
        )

    @property
    def total_forfeited_credit(self) -> float:
        return self.forfeited_generation_credit + self.forfeited_delivery_credit


def calculate_true_up_settlement(
    *,
    policy: TrueUpPolicy,
    annual_import_kwh: float,
    annual_export_kwh: float,
    ending_generation_credit_bank: float,
    ending_delivery_credit_bank: float,
    ending_acc_plus_credit_bank: float,
    remaining_offsettable_generation_charges: float,
    remaining_offsettable_delivery_charges: float,
    adjustment_rate: AverageRetailExportCompensationRate | None = None,
    nsc_rate: NetSurplusCompensationRate | None = None,
    true_up_month: str | None = None,
) -> TrueUpSettlement:
    """Settle annual NBT base credits without double-paying net surplus.

    The same annual net-surplus kWh are first recouped at the utility-wide
    average retail export compensation rate and then credited at NSC. Base EEC
    banks offset the component-matched recoupment first. When the utility
    policy permits it, any remaining bank next offsets eligible charges paid
    earlier in the relevant period. ACC Plus is never part of the recoupment
    and passes through unchanged.
    """

    if not isinstance(policy, TrueUpPolicy):
        raise TypeError("policy must be a TrueUpPolicy")
    imports = _nonnegative_finite(annual_import_kwh, "annual_import_kwh")
    exports = _nonnegative_finite(annual_export_kwh, "annual_export_kwh")
    generation_bank = _nonnegative_finite(
        ending_generation_credit_bank, "ending_generation_credit_bank"
    )
    delivery_bank = _nonnegative_finite(
        ending_delivery_credit_bank, "ending_delivery_credit_bank"
    )
    acc_plus_bank = _nonnegative_finite(
        ending_acc_plus_credit_bank, "ending_acc_plus_credit_bank"
    )
    remaining_generation_charges = _nonnegative_finite(
        remaining_offsettable_generation_charges,
        "remaining_offsettable_generation_charges",
    )
    remaining_delivery_charges = _nonnegative_finite(
        remaining_offsettable_delivery_charges,
        "remaining_offsettable_delivery_charges",
    )

    net_surplus_kwh = max(exports - imports, 0.0)
    if (adjustment_rate is None) != (nsc_rate is None):
        raise ValueError("adjustment_rate and nsc_rate must be supplied together")
    if adjustment_rate is None:
        if net_surplus_kwh > 0:
            raise ValueError(
                "Positive annual net exports require adjustment_rate and nsc_rate"
            )
        if true_up_month is None:
            raise ValueError(
                "true_up_month is required when no net-surplus rates apply"
            )
        resolved_true_up_month = _canonical_true_up_month(true_up_month)
        generation_adjustment_rate = 0.0
        delivery_adjustment_rate = 0.0
        resolved_nsc_rate = 0.0
        adjustment_source_id = None
        nsc_source_id = None
    else:
        if not isinstance(
            adjustment_rate, AverageRetailExportCompensationRate
        ):
            raise TypeError(
                "adjustment_rate must be an AverageRetailExportCompensationRate"
            )
        if not isinstance(nsc_rate, NetSurplusCompensationRate):
            raise TypeError("nsc_rate must be a NetSurplusCompensationRate")
        if adjustment_rate.utility is not policy.utility:
            raise ValueError(
                "adjustment_rate utility does not match true-up policy"
            )
        if nsc_rate.utility is not policy.utility:
            raise ValueError("nsc_rate utility does not match true-up policy")
        if adjustment_rate.true_up_month != nsc_rate.true_up_month:
            raise ValueError(
                "adjustment_rate and nsc_rate true-up months do not match"
            )
        if true_up_month is not None and (
            _canonical_true_up_month(true_up_month)
            != adjustment_rate.true_up_month
        ):
            raise ValueError(
                "explicit true_up_month does not match the supplied rates"
            )
        resolved_true_up_month = adjustment_rate.true_up_month
        generation_adjustment_rate = (
            adjustment_rate.generation_rate_usd_per_kwh
        )
        delivery_adjustment_rate = adjustment_rate.delivery_rate_usd_per_kwh
        resolved_nsc_rate = nsc_rate.rate_usd_per_kwh
        adjustment_source_id = adjustment_rate.source_id
        nsc_source_id = nsc_rate.source_id

    generation_adjustment = (
        net_surplus_kwh * generation_adjustment_rate
    )
    delivery_adjustment = (
        net_surplus_kwh * delivery_adjustment_rate
    )
    generation_to_adjustment = min(generation_bank, generation_adjustment)
    delivery_to_adjustment = min(delivery_bank, delivery_adjustment)
    generation_bank -= generation_to_adjustment
    delivery_bank -= delivery_to_adjustment

    generation_to_prior_charges = 0.0
    delivery_to_prior_charges = 0.0
    if policy.apply_remaining_eec_to_prior_charges:
        generation_to_prior_charges = min(
            generation_bank, remaining_generation_charges
        )
        delivery_to_prior_charges = min(delivery_bank, remaining_delivery_charges)
        generation_bank -= generation_to_prior_charges
        delivery_bank -= delivery_to_prior_charges

    forfeited_generation = 0.0
    forfeited_delivery = 0.0
    if not policy.carry_remaining_eec_forward:
        forfeited_generation = generation_bank
        forfeited_delivery = delivery_bank
        generation_bank = 0.0
        delivery_bank = 0.0

    nsc_credit = net_surplus_kwh * resolved_nsc_rate
    unoffset_adjustment = (
        generation_adjustment
        - generation_to_adjustment
        + delivery_adjustment
        - delivery_to_adjustment
    )
    prior_charge_credit = (
        generation_to_prior_charges + delivery_to_prior_charges
    )
    net_bill_adjustment = unoffset_adjustment - prior_charge_credit - nsc_credit

    return TrueUpSettlement(
        utility=policy.utility,
        true_up_month=resolved_true_up_month,
        annual_import_kwh=imports,
        annual_export_kwh=exports,
        net_surplus_kwh=net_surplus_kwh,
        generation_adjustment_rate_usd_per_kwh=(
            generation_adjustment_rate
        ),
        delivery_adjustment_rate_usd_per_kwh=(
            delivery_adjustment_rate
        ),
        nsc_rate_usd_per_kwh=resolved_nsc_rate,
        generation_eec_adjustment_charge=generation_adjustment,
        delivery_eec_adjustment_charge=delivery_adjustment,
        generation_eec_applied_to_adjustment=generation_to_adjustment,
        delivery_eec_applied_to_adjustment=delivery_to_adjustment,
        remaining_offsettable_generation_charges=remaining_generation_charges,
        remaining_offsettable_delivery_charges=remaining_delivery_charges,
        generation_eec_applied_to_prior_charges=generation_to_prior_charges,
        delivery_eec_applied_to_prior_charges=delivery_to_prior_charges,
        nsc_credit=nsc_credit,
        net_bill_adjustment=net_bill_adjustment,
        ending_generation_credit_bank=generation_bank,
        ending_delivery_credit_bank=delivery_bank,
        ending_acc_plus_credit_bank=acc_plus_bank,
        forfeited_generation_credit=forfeited_generation,
        forfeited_delivery_credit=forfeited_delivery,
        policy_source_id=policy.source_id,
        adjustment_rate_source_id=adjustment_source_id,
        nsc_rate_source_id=nsc_source_id,
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
