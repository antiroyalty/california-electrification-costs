"""Pure dollar accounting for bundled NBT service.

SCE uses one eligible energy pool. PG&E and SDG&E use separate generation
and delivery pools. Bonus credits have their own balance and can also pay
non-bypassable and fixed charges. See docs/HOUSEHOLD_COST_RECONCILIATION.md.

Callers supply charges, earned credits, opening balances, and annual rules.
They resolve tariffs, calculate dollar amounts from energy and rates, and
retain source metadata outside this module. No rate lookup or cash refund
is performed here. Values retain full precision until presentation.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from numbers import Real
from operator import add, sub
from typing import Callable


def _usd(value: float, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise TypeError(f"{name} must be a real number in USD")
    try:
        amount = float(value)
    except OverflowError as exc:
        raise ValueError(f"{name} must be finite") from exc
    if not math.isfinite(amount) or amount < 0:
        raise ValueError(f"{name} must be finite and non-negative")
    return amount


@dataclass(frozen=True)
class ComponentAmounts:
    """Dollar amounts restricted to their respective energy components."""

    generation_usd: float
    delivery_usd: float

    def __post_init__(self) -> None:
        for name in ("generation_usd", "delivery_usd"):
            object.__setattr__(self, name, _usd(getattr(self, name), name))
        _usd(self.total_usd, "total_usd")

    @property
    def total_usd(self) -> float:
        return self.generation_usd + self.delivery_usd


@dataclass(frozen=True)
class PooledAmount:
    """One dollar amount eligible across combined energy charges."""

    energy_usd: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "energy_usd", _usd(self.energy_usd, "energy_usd"))

    @property
    def total_usd(self) -> float:
        return self.energy_usd


EnergyAmounts = ComponentAmounts | PooledAmount


def _require_energy(amounts: EnergyAmounts) -> None:
    if type(amounts) not in (ComponentAmounts, PooledAmount):
        raise TypeError("Energy amounts must be ComponentAmounts or PooledAmount")


def _combine_energy(
    left: EnergyAmounts,
    right: EnergyAmounts,
    operation: Callable[[float, float], float],
) -> EnergyAmounts:
    """Apply dollar arithmetic within matching credit restrictions."""
    _require_energy(left)
    _require_energy(right)
    if type(left) is not type(right):
        raise ValueError("Pooled and component energy amounts cannot be mixed")
    if isinstance(left, ComponentAmounts):
        return ComponentAmounts(
            operation(left.generation_usd, right.generation_usd),
            operation(left.delivery_usd, right.delivery_usd),
        )
    return PooledAmount(operation(left.energy_usd, right.energy_usd))


@dataclass(frozen=True)
class CreditBalances:
    base: EnergyAmounts
    bonus_usd: float

    def __post_init__(self) -> None:
        _require_energy(self.base)
        object.__setattr__(self, "bonus_usd", _usd(self.bonus_usd, "bonus_usd"))


@dataclass(frozen=True)
class MonthlySettlement:
    eligible_energy: EnergyAmounts
    non_bypassable_charge_usd: float
    fixed_charge_usd: float
    opening: CreditBalances
    earned: CreditBalances
    base_applied: EnergyAmounts
    bonus_applied_usd: float
    bonus_applied_to_energy: EnergyAmounts
    closing: CreditBalances

    @property
    def paid_eligible_energy(self) -> EnergyAmounts:
        """Energy charges paid after both credits; eligible for annual offsets."""
        after_base = _combine_energy(self.eligible_energy, self.base_applied, sub)
        return _combine_energy(after_base, self.bonus_applied_to_energy, sub)

    @property
    def payment_usd(self) -> float:
        after_base = _combine_energy(self.eligible_energy, self.base_applied, sub)
        return (
            after_base.total_usd
            + self.non_bypassable_charge_usd
            + self.fixed_charge_usd
            - self.bonus_applied_usd
        )


def settle_month(
    *,
    eligible_energy: EnergyAmounts,
    non_bypassable_charge_usd: float,
    fixed_charge_usd: float,
    opening: CreditBalances,
    earned: CreditBalances,
) -> MonthlySettlement:
    """Apply base credits to eligible energy, then bonus credits to the bill.

    Retain the study's convention: bonus pays remaining energy first, in
    proportion to its components, then other charges. This affects which
    prior payments remain eligible for annual offsets.
    """
    if not isinstance(opening, CreditBalances) or not isinstance(earned, CreditBalances):
        raise TypeError("opening and earned must be CreditBalances")
    nbc_usd = _usd(non_bypassable_charge_usd, "non_bypassable_charge_usd")
    fixed_usd = _usd(fixed_charge_usd, "fixed_charge_usd")
    available_base = _combine_energy(opening.base, earned.base, add)
    base_applied = _combine_energy(available_base, eligible_energy, min)
    remaining_energy = _combine_energy(eligible_energy, base_applied, sub)
    available_bonus_usd = _usd(opening.bonus_usd + earned.bonus_usd, "available_bonus_usd")
    before_bonus_usd = _usd(
        remaining_energy.total_usd + nbc_usd + fixed_usd, "before_bonus_usd"
    )
    bonus_applied_usd = min(available_bonus_usd, before_bonus_usd)
    bonus_to_energy_usd = min(bonus_applied_usd, remaining_energy.total_usd)

    if isinstance(remaining_energy, ComponentAmounts):
        fraction = (
            bonus_to_energy_usd / remaining_energy.total_usd
            if remaining_energy.total_usd > 0
            else 0.0
        )
        bonus_to_energy = ComponentAmounts(
            remaining_energy.generation_usd * fraction,
            remaining_energy.delivery_usd * fraction,
        )
    else:
        bonus_to_energy = PooledAmount(bonus_to_energy_usd)

    return MonthlySettlement(
        eligible_energy=eligible_energy,
        non_bypassable_charge_usd=nbc_usd,
        fixed_charge_usd=fixed_usd,
        opening=opening,
        earned=earned,
        base_applied=base_applied,
        bonus_applied_usd=bonus_applied_usd,
        bonus_applied_to_energy=bonus_to_energy,
        closing=CreditBalances(
            _combine_energy(available_base, base_applied, sub),
            available_bonus_usd - bonus_applied_usd,
        ),
    )


@dataclass(frozen=True)
class AnnualSettlement:
    opening: CreditBalances
    prior_paid_eligible_energy: EnergyAmounts
    surplus_adjustment: EnergyAmounts
    nsc_entitlement_usd: float
    offset_prior_payments: bool
    carry_base_credit: bool
    base_applied_to_adjustment: EnergyAmounts
    base_applied_to_prior_payments: EnergyAmounts
    forfeited_base: EnergyAmounts
    closing: CreditBalances

    @property
    def net_bill_adjustment_usd(self) -> float:
        """Added charge (positive) or credit (negative), not a cash refund."""
        unpaid_adjustment = _combine_energy(
            self.surplus_adjustment, self.base_applied_to_adjustment, sub
        )
        return (
            unpaid_adjustment.total_usd
            - self.base_applied_to_prior_payments.total_usd
            - self.nsc_entitlement_usd
        )


def settle_year(
    *,
    opening: CreditBalances,
    prior_paid_eligible_energy: EnergyAmounts,
    surplus_adjustment: EnergyAmounts,
    nsc_entitlement_usd: float,
    offset_prior_payments: bool,
    carry_base_credit: bool,
) -> AnnualSettlement:
    """Apply the surplus adjustment, offset prior payments, then carry or expire.

    ``opening`` is the balance after the final month, before annual settlement.
    Prior eligible payments must already exclude base and bonus applications.
    Callers calculate adjustment and net surplus compensation (NSC) dollars
    from validated surplus kWh and source-linked rates. Explicit zero amounts
    apply when there is no surplus; missing rates are not replaced here.

    The study uses prior offsets and carryover for PG&E, prior offsets and
    expiry for SCE, and expiry without prior offsets for SDG&E. The latter
    remains the bounded study convention identified in the accounting note.
    Bonus balances carry unchanged; NSC is separate from both credit banks.
    """
    if not isinstance(opening, CreditBalances):
        raise TypeError("opening must be CreditBalances")
    for name, value in (
        ("offset_prior_payments", offset_prior_payments),
        ("carry_base_credit", carry_base_credit),
    ):
        if not isinstance(value, bool):
            raise TypeError(f"{name} must be boolean")
    nsc_usd = _usd(nsc_entitlement_usd, "nsc_entitlement_usd")
    zero = _combine_energy(opening.base, opening.base, sub)
    # Validate prior payment restrictions even when backward offsets are disabled.
    _combine_energy(prior_paid_eligible_energy, zero, add)
    to_adjustment = _combine_energy(opening.base, surplus_adjustment, min)
    remaining = _combine_energy(opening.base, to_adjustment, sub)
    to_prior = (
        _combine_energy(remaining, prior_paid_eligible_energy, min)
        if offset_prior_payments
        else zero
    )
    remaining = _combine_energy(remaining, to_prior, sub)
    return AnnualSettlement(
        opening=opening,
        prior_paid_eligible_energy=prior_paid_eligible_energy,
        surplus_adjustment=surplus_adjustment,
        nsc_entitlement_usd=nsc_usd,
        offset_prior_payments=offset_prior_payments,
        carry_base_credit=carry_base_credit,
        base_applied_to_adjustment=to_adjustment,
        base_applied_to_prior_payments=to_prior,
        forfeited_base=zero if carry_base_credit else remaining,
        closing=CreditBalances(remaining if carry_base_credit else zero, opening.bonus_usd),
    )
