"""Federal purchase-credit amounts for explicitly eligible household purchases.

Rules live in appliances.federal_credits. This calculation applies their amounts
to declared eligible costs for one taxpayer and one tax year. It does not establish
eligibility, calculate a tax return, or assign a receipt date to a credit.
"""

from dataclasses import dataclass
from enum import Enum
from math import isfinite
from numbers import Real

from appliances.federal_credits import FEDERAL_ITC_25D, FEDERAL_25C, FEDERAL_30D


class FederalCreditCase(Enum):
    """Which federal credit families the research comparison includes."""

    NONE = "no_federal_credits"
    PV_STORAGE = "solar_storage_federal_credits"
    ALL = "all_modeled_federal_credits"


@dataclass(frozen=True)
class HouseholdFederalCredits:
    """Potential purchase credits in dollars, before tax-liability limits."""

    pv_25d_usd: float
    storage_25d_usd: float
    heat_pumps_25c_usd: float
    vehicle_30d_usd: float

    @property
    def total_usd(self) -> float:
        return (
            self.pv_25d_usd + self.storage_25d_usd
            + self.heat_pumps_25c_usd + self.vehicle_30d_usd
        )


def _nonnegative_finite(value: float, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError(f"{name} must be a finite, nonnegative number")
    try:
        value = float(value)
    except OverflowError as exc:
        raise ValueError(f"{name} must be a finite, nonnegative number") from exc
    if not isfinite(value) or value < 0:
        raise ValueError(f"{name} must be a finite, nonnegative number")
    return value


def evaluate_federal_purchase_credits(
    *,
    case: FederalCreditCase,
    pv_eligible_basis_usd: float,
    storage_eligible_basis_usd: float,
    storage_capacity_kwh: float,
    space_heat_pump_eligible_basis_usd: float,
    water_heat_pump_eligible_basis_usd: float,
    eligible_vehicle_credit_usd: float,
) -> HouseholdFederalCredits:
    """Itemize the credit amounts for one initial household purchase bundle.

    Supply qualifying installed costs after required basis adjustments, before
    these federal credits. Zero means absent or explicitly ineligible, not missing.
    Storage costs must qualify apart from the capacity test applied here. The two
    heat-pump inputs share one annual cap; no other purchase consumes that cap.
    The vehicle amount must be declared from buyer/vehicle eligibility, not inferred
    from its purchase price. Full vehicle eligibility is never assumed by default.

    The caller must establish eligible acquisition/installation dates and other
    legal conditions from the registry. Cases select credit families, not calendar
    years. Returned amounts precede tax-liability and realization limits. They are
    not annual savings, replacement subsidies, or a tax refund. State/local and
    federally funded rebates are excluded; do not supply a mixed-incentive net cost.
    """
    if not isinstance(case, FederalCreditCase):
        raise ValueError("case must be a FederalCreditCase")
    pv_basis = _nonnegative_finite(pv_eligible_basis_usd, "pv_eligible_basis_usd")
    storage_basis = _nonnegative_finite(
        storage_eligible_basis_usd, "storage_eligible_basis_usd"
    )
    capacity = _nonnegative_finite(storage_capacity_kwh, "storage_capacity_kwh")
    space_basis = _nonnegative_finite(
        space_heat_pump_eligible_basis_usd, "space_heat_pump_eligible_basis_usd"
    )
    water_basis = _nonnegative_finite(
        water_heat_pump_eligible_basis_usd, "water_heat_pump_eligible_basis_usd"
    )
    vehicle_credit = _nonnegative_finite(
        eligible_vehicle_credit_usd, "eligible_vehicle_credit_usd"
    )
    if storage_basis > 0 and capacity == 0:
        raise ValueError("Positive storage_eligible_basis_usd requires positive storage_capacity_kwh")
    if vehicle_credit > FEDERAL_30D.maximum_credit_usd:
        raise ValueError("eligible_vehicle_credit_usd exceeds the federal per-vehicle maximum")

    # Validate every input even when the selected case excludes that credit.
    if case is FederalCreditCase.NONE:
        return HouseholdFederalCredits(0.0, 0.0, 0.0, 0.0)

    pv_credit = FEDERAL_ITC_25D.fraction * pv_basis
    storage_credit = (
        FEDERAL_ITC_25D.fraction * storage_basis
        if capacity >= FEDERAL_ITC_25D.minimum_storage_capacity_kwh else 0.0
    )
    if case is FederalCreditCase.PV_STORAGE:
        return HouseholdFederalCredits(pv_credit, storage_credit, 0.0, 0.0)

    # Keep 25C as a household amount instead of allocating a second cap to each item.
    heat_pump_credit = min(
        FEDERAL_25C.fraction * space_basis + FEDERAL_25C.fraction * water_basis,
        FEDERAL_25C.annual_cap_usd,
    )
    return HouseholdFederalCredits(
        pv_credit, storage_credit, heat_pump_credit, vehicle_credit
    )
