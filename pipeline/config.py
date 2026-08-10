from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from evaluations.constants import DEFAULT_DISCOUNT_RATE
from tariffs.models import CustomerSegment, NBTScenario, ServiceType


@dataclass
class Config:
    """Shared configuration for pipeline runs.

    This intentionally mirrors the options used across existing scripts and
    cost_service, providing a single object to pass through module boundaries.
    """

    scenario: str
    housing_type: str
    counties: List[str] = field(default_factory=list)

    # Paths
    base_input_dir: str = "data/loadprofiles"
    output_dir: str = "analysis_results"

    # Rate planning and evaluation settings
    rate_plans: Optional[Dict[str, Dict[str, str]]] = None
    electricity_variant: str = "nem3"
    incentive: str = "full_incentives"
    discount_rate: float = DEFAULT_DISCOUNT_RATE
    agg: str = "mean"

    # Sensitivity override: non-offsettable volumetric charge ($/kWh). None =
    # resolve the plan's `nonBypassableRate` from the source-locked import
    # tariff snapshot (see ImportRateSchedule.resolve).
    nbc_dollars_per_kwh_override: Optional[float] = None

    # Net Billing Tariff policy scenario. The default represents a system that
    # applies for interconnection and is billed in 2026. Vintage is explicit
    # because it materially changes both EEC shapes and the ACC Plus adder.
    nbt_billing_year: int = 2026
    nbt_vintage: int = 2026
    nbt_customer_segment: str = CustomerSegment.STANDARD.value
    nbt_include_acc_plus: bool = True
    # Current-snapshot method: apply tariffs in effect on this date to the
    # standardized 8,760-hour billing-year profile. A different date must have
    # its own source-locked snapshot; the catalog never falls back silently.
    nbt_tariff_snapshot_date: str = "2026-08-09"

    # Representative-household storage sizing domain. This explicit upper
    # bound is also what makes the full-year meter-direction formulation
    # numerically tight; sensitivity runs should override and report it.
    max_battery_kwh: float = 40.0

    def nbt_scenario(self) -> NBTScenario:
        return NBTScenario(
            billing_year=self.nbt_billing_year,
            nbt_vintage=self.nbt_vintage,
            service_type=ServiceType.BUNDLED,
            customer_segment=CustomerSegment(self.nbt_customer_segment),
            include_acc_plus=self.nbt_include_acc_plus,
            tariff_snapshot_date=self.nbt_tariff_snapshot_date,
        )
