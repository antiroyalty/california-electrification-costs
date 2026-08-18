"""NEM 2 billing primitives for the current-tariff counterfactual.

This module models bundled residential service under the annual billing
option. It keeps three charge bases separate:

* retail energy charges and credits net by time-of-use period;
* tariff-defined NBCs apply to positive imports in each meter interval;
* later recovery charges apply to positive monthly net consumption.

The annual true-up collects a positive retail-energy balance, expires a
negative retail-energy balance, and compensates annual net-surplus kWh at the
source-selected NSC rate.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
import json
import math
from pathlib import Path
from typing import Mapping

import pandas as pd

from .import_rates import ImportRateSchedule
from .models import EnergyFlows, ServiceType, Utility
from .true_up import NetSurplusCompensationRate


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_NEM2_RATE_TREATMENT_DATA = (
    ROOT / "data" / "tariffs" / "nem2_rate_treatment.json"
)
DEFAULT_IMPORT_SOURCE_MANIFEST = (
    ROOT / "data" / "tariffs" / "import_source_manifest.json"
)
DEFAULT_NEM2_SOURCE_MANIFEST = (
    ROOT / "data" / "tariffs" / "nem2_source_manifest.json"
)
DEFAULT_NEM2_DECISION_SOURCE_ID = "cpuc_nem2_decision_d16-01-044_2026-08-17"
RATE_RECONCILIATION_TOLERANCE = 1e-9


def _finite_rate(value: object, field_name: str, *, allow_negative: bool = False) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be numeric") from exc
    if not math.isfinite(parsed):
        raise ValueError(f"{field_name} must be finite")
    if not allow_negative and parsed < 0:
        raise ValueError(f"{field_name} must be non-negative")
    if abs(parsed) > 5:
        raise ValueError(f"{field_name} exceeds the 5 USD/kWh guardrail")
    return parsed


def _canonical_month(value: str, field_name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a canonical YYYY-MM string")
    try:
        parsed = datetime.strptime(value, "%Y-%m")
    except ValueError as exc:
        raise ValueError(f"{field_name} must be a canonical YYYY-MM string") from exc
    if parsed.strftime("%Y-%m") != value:
        raise ValueError(f"{field_name} must be a canonical YYYY-MM string")
    return value


@dataclass(frozen=True)
class NEM2Scenario:
    """Policy choices for a current-rate NEM 2 billing counterfactual.

    This scenario is not a historical bill reconstruction. It applies one
    source-locked retail tariff snapshot to a standardized profile and uses
    the annual billing option for a bundled residential customer.
    """

    billing_year: int = 2026
    tariff_snapshot_date: str = "2026-08-09"
    true_up_month: str = "2026-08"
    service_type: ServiceType = ServiceType.BUNDLED

    def __post_init__(self) -> None:
        if self.billing_year < 2017:
            raise ValueError("NEM 2 billing_year must be 2017 or later")
        try:
            date.fromisoformat(self.tariff_snapshot_date)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "tariff_snapshot_date must be an ISO date (YYYY-MM-DD)"
            ) from exc
        true_up_month = _canonical_month(self.true_up_month, "true_up_month")
        if int(true_up_month[:4]) != self.billing_year:
            raise ValueError("true_up_month must fall within billing_year")
        if self.service_type is not ServiceType.BUNDLED:
            raise NotImplementedError("Only bundled-service NEM 2 tariffs are modeled")

    @property
    def research_label(self) -> str:
        return f"nem2_at_{self.billing_year}_retail_rates"


@dataclass(frozen=True)
class NEM2RateTreatment:
    utility: Utility
    snapshot_as_of: str
    interval_nbc_components: tuple[tuple[str, float], ...]
    interval_nbc_rate_usd_per_kwh: float
    monthly_net_consumption_components: tuple[tuple[str, float], ...]
    monthly_net_consumption_rate_usd_per_kwh: float
    retail_credit_exclusion_rate_usd_per_kwh: float
    monthly_net_consumption_basis: str
    import_source_id: str
    regulatory_decision_source_id: str
    utility_rules_source_id: str
    billing_method_source_id: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "utility", Utility.parse(self.utility))
        try:
            snapshot_as_of = date.fromisoformat(self.snapshot_as_of).isoformat()
        except (TypeError, ValueError) as exc:
            raise ValueError("snapshot_as_of must be an ISO date") from exc
        object.__setattr__(self, "snapshot_as_of", snapshot_as_of)

        interval_components = self._validated_components(
            self.interval_nbc_components,
            "interval_nbc_components",
        )
        monthly_components = self._validated_components(
            self.monthly_net_consumption_components,
            "monthly_net_consumption_components",
        )
        object.__setattr__(self, "interval_nbc_components", interval_components)
        object.__setattr__(
            self, "monthly_net_consumption_components", monthly_components
        )

        interval_rate = _finite_rate(
            self.interval_nbc_rate_usd_per_kwh,
            "interval_nbc_rate_usd_per_kwh",
        )
        monthly_rate = _finite_rate(
            self.monthly_net_consumption_rate_usd_per_kwh,
            "monthly_net_consumption_rate_usd_per_kwh",
        )
        exclusion_rate = _finite_rate(
            self.retail_credit_exclusion_rate_usd_per_kwh,
            "retail_credit_exclusion_rate_usd_per_kwh",
        )
        object.__setattr__(self, "interval_nbc_rate_usd_per_kwh", interval_rate)
        object.__setattr__(
            self, "monthly_net_consumption_rate_usd_per_kwh", monthly_rate
        )
        object.__setattr__(
            self, "retail_credit_exclusion_rate_usd_per_kwh", exclusion_rate
        )

        self._require_reconciliation(
            sum(rate for _, rate in interval_components),
            interval_rate,
            "interval NBC components",
        )
        self._require_reconciliation(
            sum(rate for _, rate in monthly_components),
            monthly_rate,
            "monthly net-consumption components",
        )
        self._require_reconciliation(
            interval_rate + monthly_rate,
            exclusion_rate,
            "retail credit exclusion",
        )
        if self.monthly_net_consumption_basis != "positive_monthly_net_kwh":
            raise ValueError(
                "monthly_net_consumption_basis must be "
                "'positive_monthly_net_kwh'"
            )
        for field_name in (
            "import_source_id",
            "regulatory_decision_source_id",
            "utility_rules_source_id",
            "billing_method_source_id",
        ):
            if not str(getattr(self, field_name)).strip():
                raise ValueError(f"{field_name} must be non-empty")

    @staticmethod
    def _validated_components(
        components: tuple[tuple[str, float], ...],
        field_name: str,
    ) -> tuple[tuple[str, float], ...]:
        parsed: list[tuple[str, float]] = []
        names: set[str] = set()
        for component, rate in components:
            name = str(component).strip()
            if not name:
                raise ValueError(f"{field_name} contains an empty component name")
            if name in names:
                raise ValueError(f"{field_name} contains duplicate component {name!r}")
            names.add(name)
            parsed.append(
                (
                    name,
                    _finite_rate(
                        rate,
                        f"{field_name}[{name}]",
                        allow_negative=True,
                    ),
                )
            )
        return tuple(parsed)

    @staticmethod
    def _require_reconciliation(actual: float, expected: float, label: str) -> None:
        if abs(actual - expected) > RATE_RECONCILIATION_TOLERANCE:
            raise ValueError(
                f"NEM 2 {label} do not reconcile: {actual} != {expected}"
            )

    @property
    def interval_nbc_component_rates(self) -> Mapping[str, float]:
        return dict(self.interval_nbc_components)

    @property
    def monthly_net_consumption_component_rates(self) -> Mapping[str, float]:
        return dict(self.monthly_net_consumption_components)


class NEM2RateTreatmentSchedule:
    """Strict lookup for current, source-linked NEM 2 charge treatment."""

    def __init__(
        self,
        data_path: str | Path = DEFAULT_NEM2_RATE_TREATMENT_DATA,
        import_source_manifest_path: str | Path = DEFAULT_IMPORT_SOURCE_MANIFEST,
        nem2_source_manifest_path: str | Path = DEFAULT_NEM2_SOURCE_MANIFEST,
    ) -> None:
        self.data_path = Path(data_path)
        self.import_source_manifest_path = Path(import_source_manifest_path)
        self.nem2_source_manifest_path = Path(nem2_source_manifest_path)

    @staticmethod
    def _load_json(path: Path, label: str) -> dict:
        if not path.is_file():
            raise FileNotFoundError(f"{label} not found: {path}")
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError(f"{label} must contain a JSON object")
        return payload

    def resolve(
        self,
        utility: str | Utility,
        *,
        snapshot_as_of: str,
    ) -> NEM2RateTreatment:
        parsed_utility = Utility.parse(utility)
        data = self._load_json(self.data_path, "NEM 2 rate-treatment data")
        if data.get("schema_version") != 1:
            raise ValueError("Unsupported NEM 2 rate-treatment schema_version")
        if data.get("rate_unit") != "USD/kWh":
            raise ValueError("NEM 2 rate treatment must declare rate_unit='USD/kWh'")
        if data.get("snapshot_as_of") != snapshot_as_of:
            raise KeyError(
                f"No NEM 2 rate treatment for {snapshot_as_of}; available snapshot is "
                f"{data.get('snapshot_as_of')}. Add a source-locked snapshot instead "
                "of reusing another date."
            )
        matches = [
            row
            for row in data.get("rates", [])
            if row.get("utility") == parsed_utility.value
        ]
        if len(matches) != 1:
            raise KeyError(
                f"Expected one NEM 2 rate treatment for {parsed_utility.value}; "
                f"found {len(matches)}"
            )
        row = matches[0]
        treatment = NEM2RateTreatment(
            utility=parsed_utility,
            snapshot_as_of=str(data["snapshot_as_of"]),
            interval_nbc_components=self._components(
                row, "interval_nbc_components"
            ),
            interval_nbc_rate_usd_per_kwh=row.get(
                "interval_nbc_rate_usd_per_kwh"
            ),
            monthly_net_consumption_components=self._components(
                row, "monthly_net_consumption_components"
            ),
            monthly_net_consumption_rate_usd_per_kwh=row.get(
                "monthly_net_consumption_rate_usd_per_kwh"
            ),
            retail_credit_exclusion_rate_usd_per_kwh=row.get(
                "retail_credit_exclusion_rate_usd_per_kwh"
            ),
            monthly_net_consumption_basis=str(
                row.get("monthly_net_consumption_basis", "")
            ),
            import_source_id=str(row.get("import_source_id", "")),
            regulatory_decision_source_id=str(
                data.get("regulatory_decision_source_id", "")
            ),
            utility_rules_source_id=str(row.get("utility_rules_source_id", "")),
            billing_method_source_id=str(
                row.get("billing_method_source_id", "")
            ),
        )
        self._validate_sources(treatment)
        return treatment

    @staticmethod
    def _components(row: dict, field_name: str) -> tuple[tuple[str, float], ...]:
        raw = row.get(field_name)
        if not isinstance(raw, list):
            raise ValueError(f"{field_name} must be a list")
        components: list[tuple[str, float]] = []
        for item in raw:
            if not isinstance(item, dict):
                raise ValueError(f"{field_name} entries must be objects")
            components.append((item.get("component", ""), item.get("rate_usd_per_kwh")))
        return tuple(components)

    def _validate_sources(self, treatment: NEM2RateTreatment) -> None:
        import_manifest = self._load_json(
            self.import_source_manifest_path, "Import source manifest"
        )
        nem2_manifest = self._load_json(
            self.nem2_source_manifest_path, "NEM 2 source manifest"
        )
        import_sources = {
            source.get("source_id"): source
            for source in import_manifest.get("sources", [])
        }
        import_source = import_sources.get(treatment.import_source_id)
        if import_source is None:
            raise ValueError(
                f"NEM 2 import_source_id {treatment.import_source_id!r} is absent "
                "from the import source manifest"
            )
        if import_source.get("utility") != treatment.utility.value:
            raise ValueError("NEM 2 import_source_id belongs to another utility")

        nem2_sources = {
            source.get("source_id"): source
            for source in nem2_manifest.get("sources", [])
        }
        decision_source = nem2_sources.get(
            treatment.regulatory_decision_source_id
        )
        if decision_source is None:
            raise ValueError(
                "NEM 2 regulatory_decision_source_id is absent from the source "
                "manifest"
            )
        if decision_source.get("source_type") != "regulatory_decision":
            raise ValueError(
                "NEM 2 regulatory_decision_source_id is not a regulatory decision"
            )
        for field_name in ("utility_rules_source_id", "billing_method_source_id"):
            source_id = getattr(treatment, field_name)
            source = nem2_sources.get(source_id)
            if source is None:
                raise ValueError(
                    f"NEM 2 {field_name} {source_id!r} is absent from the source manifest"
                )
            if source.get("utility") != treatment.utility.value:
                raise ValueError(f"NEM 2 {field_name} belongs to another utility")


@dataclass(frozen=True)
class NEM2TariffBundle:
    utility: Utility
    scenario: NEM2Scenario
    import_schedule: ImportRateSchedule
    rate_treatment: NEM2RateTreatment
    nsc_rate: NetSurplusCompensationRate | None = None

    def __post_init__(self) -> None:
        parsed_utility = Utility.parse(self.utility)
        object.__setattr__(self, "utility", parsed_utility)
        if self.import_schedule.utility is not parsed_utility:
            raise ValueError("NEM 2 import schedule belongs to another utility")
        if self.rate_treatment.utility is not parsed_utility:
            raise ValueError("NEM 2 rate treatment belongs to another utility")
        if self.import_schedule.snapshot_as_of != self.scenario.tariff_snapshot_date:
            raise ValueError("NEM 2 import schedule snapshot does not match scenario")
        if self.rate_treatment.snapshot_as_of != self.scenario.tariff_snapshot_date:
            raise ValueError("NEM 2 rate treatment snapshot does not match scenario")
        if (
            abs(
                self.import_schedule.non_bypassable_rate
                - self.rate_treatment.retail_credit_exclusion_rate_usd_per_kwh
            )
            > RATE_RECONCILIATION_TOLERANCE
        ):
            raise ValueError(
                "Import-schedule non-offsettable rate does not reconcile to the "
                "NEM 2 retail-credit exclusion rate"
            )
        if self.nsc_rate is not None:
            if self.nsc_rate.utility is not parsed_utility:
                raise ValueError("NEM 2 NSC rate belongs to another utility")
            if self.nsc_rate.true_up_month != self.scenario.true_up_month:
                raise ValueError("NEM 2 NSC rate month does not match scenario")


@dataclass(frozen=True)
class NEM2MonthlyBill:
    month: int
    import_kwh: float
    export_kwh: float
    offsettable_import_charge_usd: float
    retail_export_credit_usd: float
    net_energy_balance_usd: float
    interval_nbc_charge_usd: float
    monthly_net_consumption_kwh: float
    monthly_net_consumption_charge_usd: float
    fixed_charge_usd: float
    amount_due_before_true_up_usd: float
    ending_energy_balance_usd: float


@dataclass(frozen=True)
class NEM2BillLedger:
    utility: Utility
    billing_year: int
    research_label: str
    months: tuple[NEM2MonthlyBill, ...]
    energy_charge_due_at_true_up_usd: float
    expired_retail_credit_usd: float
    net_surplus_kwh: float
    nsc_credit_usd: float
    nsc_rate_usd_per_kwh: float | None
    nsc_rate_source_id: str | None
    import_source_id: str
    utility_rules_source_id: str
    billing_method_source_id: str
    regulatory_decision_source_id: str

    @property
    def annual_import_kwh(self) -> float:
        return sum(month.import_kwh for month in self.months)

    @property
    def annual_export_kwh(self) -> float:
        return sum(month.export_kwh for month in self.months)

    @property
    def annual_offsettable_import_charge_usd(self) -> float:
        return sum(month.offsettable_import_charge_usd for month in self.months)

    @property
    def annual_retail_export_credit_usd(self) -> float:
        return sum(month.retail_export_credit_usd for month in self.months)

    @property
    def annual_interval_nbc_charge_usd(self) -> float:
        return sum(month.interval_nbc_charge_usd for month in self.months)

    @property
    def annual_monthly_net_consumption_charge_usd(self) -> float:
        return sum(
            month.monthly_net_consumption_charge_usd for month in self.months
        )

    @property
    def annual_fixed_charge_usd(self) -> float:
        return sum(month.fixed_charge_usd for month in self.months)

    @property
    def monthly_amount_due_usd(self) -> float:
        return sum(month.amount_due_before_true_up_usd for month in self.months)

    @property
    def true_up_bill_adjustment_usd(self) -> float:
        return self.energy_charge_due_at_true_up_usd - self.nsc_credit_usd

    @property
    def annual_amount_due_usd(self) -> float:
        return self.monthly_amount_due_usd + self.true_up_bill_adjustment_usd


def calculate_nem2_bill(
    flows: EnergyFlows,
    tariff: NEM2TariffBundle,
) -> NEM2BillLedger:
    """Calculate an annual-billing-option NEM 2 ledger."""

    frame = flows.validated_frame()
    years = set(frame["timestamp"].dt.year)
    if years != {tariff.scenario.billing_year}:
        raise ValueError(
            "Energy-flow timestamps must be calendarized to billing year "
            f"{tariff.scenario.billing_year}; found years {sorted(years)}"
        )
    timestamps = pd.DatetimeIndex(frame["timestamp"])
    frame["retail_import_rate_usd_per_kwh"] = tariff.import_schedule.rates_for(
        timestamps
    )
    exclusion_rate = (
        tariff.rate_treatment.retail_credit_exclusion_rate_usd_per_kwh
    )
    frame["offsettable_rate_usd_per_kwh"] = (
        frame["retail_import_rate_usd_per_kwh"] - exclusion_rate
    )
    if (frame["offsettable_rate_usd_per_kwh"] < -1e-12).any():
        first = int(
            frame.index[frame["offsettable_rate_usd_per_kwh"] < -1e-12][0]
        )
        raise ValueError(
            "NEM 2 retail-credit exclusion exceeds the retail rate at row "
            f"{first}"
        )
    frame["month"] = frame["timestamp"].dt.month

    running_energy_balance_usd = 0.0
    month_rows: list[NEM2MonthlyBill] = []
    for month, group in frame.groupby("month", sort=True):
        import_kwh = float(group["import_kwh"].sum())
        export_kwh = float(group["export_kwh"].sum())
        offsettable_import_charge_usd = float(
            (
                group["import_kwh"] * group["offsettable_rate_usd_per_kwh"]
            ).sum()
        )
        retail_export_credit_usd = float(
            (
                group["export_kwh"] * group["offsettable_rate_usd_per_kwh"]
            ).sum()
        )
        net_energy_balance_usd = (
            offsettable_import_charge_usd - retail_export_credit_usd
        )
        running_energy_balance_usd += net_energy_balance_usd

        interval_nbc_charge_usd = (
            import_kwh
            * tariff.rate_treatment.interval_nbc_rate_usd_per_kwh
        )
        monthly_net_consumption_kwh = max(import_kwh - export_kwh, 0.0)
        monthly_net_consumption_charge_usd = (
            monthly_net_consumption_kwh
            * tariff.rate_treatment.monthly_net_consumption_rate_usd_per_kwh
        )
        days = pd.DatetimeIndex(group["timestamp"]).normalize().unique()
        fixed_charge_usd = sum(
            tariff.import_schedule.daily_fixed_charge(pd.Timestamp(day))
            for day in days
        )
        amount_due_before_true_up_usd = (
            interval_nbc_charge_usd
            + monthly_net_consumption_charge_usd
            + fixed_charge_usd
        )
        month_rows.append(
            NEM2MonthlyBill(
                month=int(month),
                import_kwh=import_kwh,
                export_kwh=export_kwh,
                offsettable_import_charge_usd=offsettable_import_charge_usd,
                retail_export_credit_usd=retail_export_credit_usd,
                net_energy_balance_usd=net_energy_balance_usd,
                interval_nbc_charge_usd=interval_nbc_charge_usd,
                monthly_net_consumption_kwh=monthly_net_consumption_kwh,
                monthly_net_consumption_charge_usd=(
                    monthly_net_consumption_charge_usd
                ),
                fixed_charge_usd=fixed_charge_usd,
                amount_due_before_true_up_usd=amount_due_before_true_up_usd,
                ending_energy_balance_usd=running_energy_balance_usd,
            )
        )

    annual_import_kwh = float(frame["import_kwh"].sum())
    annual_export_kwh = float(frame["export_kwh"].sum())
    net_surplus_kwh = max(annual_export_kwh - annual_import_kwh, 0.0)
    nsc_credit_usd = 0.0
    nsc_rate_usd_per_kwh = None
    nsc_rate_source_id = None
    if net_surplus_kwh > 1e-9:
        if tariff.nsc_rate is None:
            raise ValueError(
                "Annual NEM 2 net exporter requires a source-selected NSC rate"
            )
        nsc_rate_usd_per_kwh = tariff.nsc_rate.rate_usd_per_kwh
        nsc_rate_source_id = tariff.nsc_rate.source_id
        nsc_credit_usd = net_surplus_kwh * nsc_rate_usd_per_kwh

    return NEM2BillLedger(
        utility=tariff.utility,
        billing_year=tariff.scenario.billing_year,
        research_label=tariff.scenario.research_label,
        months=tuple(month_rows),
        energy_charge_due_at_true_up_usd=max(running_energy_balance_usd, 0.0),
        expired_retail_credit_usd=max(-running_energy_balance_usd, 0.0),
        net_surplus_kwh=net_surplus_kwh,
        nsc_credit_usd=nsc_credit_usd,
        nsc_rate_usd_per_kwh=nsc_rate_usd_per_kwh,
        nsc_rate_source_id=nsc_rate_source_id,
        import_source_id=tariff.import_schedule.source_id,
        utility_rules_source_id=tariff.rate_treatment.utility_rules_source_id,
        billing_method_source_id=tariff.rate_treatment.billing_method_source_id,
        regulatory_decision_source_id=(
            tariff.rate_treatment.regulatory_decision_source_id
        ),
    )
