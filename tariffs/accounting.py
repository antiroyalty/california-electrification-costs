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

from .accounting_equations import (
    NumericArithmetic,
    annual_accounting,
    annual_bill_adjustment,
    monthly_accounting,
    monthly_payment,
    paid_eligible_energy,
)


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


def _values(amounts: EnergyAmounts) -> tuple[float, ...]:
    _require_energy(amounts)
    if isinstance(amounts, ComponentAmounts):
        return (amounts.generation_usd, amounts.delivery_usd)
    return (amounts.energy_usd,)


def _from_values(template: EnergyAmounts, values: tuple[float, ...]) -> EnergyAmounts:
    _require_energy(template)
    if isinstance(template, ComponentAmounts):
        return ComponentAmounts(*values)
    return PooledAmount(*values)


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
        return _from_values(
            self.eligible_energy,
            paid_eligible_energy(
                _values(self.eligible_energy),
                _values(self.base_applied),
                _values(self.bonus_applied_to_energy),
            ),
        )

    @property
    def payment_usd(self) -> float:
        return monthly_payment(
            _values(self.eligible_energy),
            _values(self.base_applied),
            self.non_bypassable_charge_usd,
            self.fixed_charge_usd,
            self.bonus_applied_usd,
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
    _require_energy(eligible_energy)
    if not (type(opening.base) is type(earned.base) is type(eligible_energy)):
        raise ValueError("Pooled and component energy amounts cannot be mixed")
    values = monthly_accounting(
        eligible=_values(eligible_energy),
        nbc=nbc_usd,
        fixed=fixed_usd,
        opening_base=_values(opening.base),
        opening_bonus=opening.bonus_usd,
        earned_base=_values(earned.base),
        earned_bonus=earned.bonus_usd,
        arithmetic=NumericArithmetic(),
    )
    _usd(values.payment, "payment_usd")
    return MonthlySettlement(
        eligible_energy=eligible_energy,
        non_bypassable_charge_usd=nbc_usd,
        fixed_charge_usd=fixed_usd,
        opening=opening,
        earned=earned,
        base_applied=_from_values(eligible_energy, values.applied_base),
        bonus_applied_usd=values.applied_bonus,
        bonus_applied_to_energy=_from_values(eligible_energy, values.bonus_to_energy),
        closing=CreditBalances(
            _from_values(eligible_energy, values.closing_base), values.closing_bonus
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
        return annual_bill_adjustment(
            _values(self.surplus_adjustment),
            _values(self.base_applied_to_adjustment),
            _values(self.base_applied_to_prior_payments),
            self.nsc_entitlement_usd,
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
    _require_energy(prior_paid_eligible_energy)
    _require_energy(surplus_adjustment)
    if not (type(opening.base) is type(prior_paid_eligible_energy) is type(surplus_adjustment)):
        raise ValueError("Pooled and component energy amounts cannot be mixed")
    values = annual_accounting(
        opening_base=_values(opening.base),
        opening_bonus=opening.bonus_usd,
        prior_paid=_values(prior_paid_eligible_energy),
        adjustment=_values(surplus_adjustment),
        nsc=nsc_usd,
        offset_prior_payments=offset_prior_payments,
        carry_base_credit=carry_base_credit,
        arithmetic=NumericArithmetic(),
    )
    return AnnualSettlement(
        opening=opening,
        prior_paid_eligible_energy=prior_paid_eligible_energy,
        surplus_adjustment=surplus_adjustment,
        nsc_entitlement_usd=nsc_usd,
        offset_prior_payments=offset_prior_payments,
        carry_base_credit=carry_base_credit,
        base_applied_to_adjustment=_from_values(opening.base, values.applied_adjustment),
        base_applied_to_prior_payments=_from_values(opening.base, values.applied_prior),
        forfeited_base=_from_values(opening.base, values.forfeited_base),
        closing=CreditBalances(
            _from_values(opening.base, values.closing_base), values.closing_bonus
        ),
    )
