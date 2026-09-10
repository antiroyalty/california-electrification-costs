"""Shared credit equations for numeric billing and optimization expressions.

Each tuple is either one combined energy pool or generation/delivery pools.
All amounts are dollars for the month or annual settlement being evaluated.
Callers validate dollar inputs and choose the utility's pools before calling.
Only minimum and proportional allocation require a solver-specific operation.
"""

from dataclasses import dataclass
from typing import Generic, Protocol, TypeVar


Amount = TypeVar("Amount")


class AccountingArithmetic(Protocol[Amount]):
    def minimum(self, left: Amount, right: Amount) -> Amount: ...

    def proportional(
        self, amount: Amount, eligible: tuple[Amount, ...]
    ) -> tuple[Amount, ...]: ...


class NumericArithmetic:
    @staticmethod
    def minimum(left: float, right: float) -> float:
        return min(left, right)

    @staticmethod
    def proportional(amount: float, eligible: tuple[float, ...]) -> tuple[float, ...]:
        if len(eligible) == 1:
            return (amount,)
        total = sum(eligible)
        fraction = amount / total if total > 0 else 0.0
        return tuple(value * fraction for value in eligible)


def _validate_pools(*amounts: tuple) -> None:
    if len({len(values) for values in amounts}) != 1 or len(amounts[0]) not in (1, 2):
        raise ValueError("Accounting requires matching combined or generation/delivery pools")


def monthly_payment(eligible, applied_base, nbc, fixed, applied_bonus):
    _validate_pools(eligible, applied_base)
    return (
        sum(charge - credit for charge, credit in zip(eligible, applied_base))
        + nbc
        + fixed
        - applied_bonus
    )


def paid_eligible_energy(eligible, applied_base, bonus_to_energy):
    _validate_pools(eligible, applied_base, bonus_to_energy)
    return tuple(
        charge - base - bonus
        for charge, base, bonus in zip(eligible, applied_base, bonus_to_energy)
    )


def annual_bill_adjustment(adjustment, applied_adjustment, applied_prior, nsc):
    _validate_pools(adjustment, applied_adjustment, applied_prior)
    return (
        sum(charge - credit for charge, credit in zip(adjustment, applied_adjustment))
        - sum(applied_prior)
        - nsc
    )


@dataclass(frozen=True)
class MonthlyValues(Generic[Amount]):
    applied_base: tuple[Amount, ...]
    applied_bonus: Amount
    bonus_to_energy: tuple[Amount, ...]
    closing_base: tuple[Amount, ...]
    closing_bonus: Amount
    paid_eligible: tuple[Amount, ...]
    payment: Amount


def monthly_accounting(
    *,
    eligible: tuple[Amount, ...],
    nbc: Amount,
    fixed: Amount,
    opening_base: tuple[Amount, ...],
    opening_bonus: Amount,
    earned_base: tuple[Amount, ...],
    earned_bonus: Amount,
    arithmetic: AccountingArithmetic[Amount],
) -> MonthlyValues[Amount]:
    """Use eligible base credits first, then apply bonus to energy and other charges."""
    _validate_pools(eligible, opening_base, earned_base)
    available_base = tuple(a + b for a, b in zip(opening_base, earned_base))
    applied_base = tuple(
        arithmetic.minimum(bank, charge) for bank, charge in zip(available_base, eligible)
    )
    remaining_energy = tuple(
        charge - credit for charge, credit in zip(eligible, applied_base)
    )
    available_bonus = opening_bonus + earned_bonus
    applied_bonus = arithmetic.minimum(available_bonus, sum(remaining_energy) + nbc + fixed)
    bonus_to_energy = arithmetic.proportional(
        arithmetic.minimum(applied_bonus, sum(remaining_energy)), remaining_energy
    )
    return MonthlyValues(
        applied_base=applied_base,
        applied_bonus=applied_bonus,
        bonus_to_energy=bonus_to_energy,
        closing_base=tuple(
            bank - credit for bank, credit in zip(available_base, applied_base)
        ),
        closing_bonus=available_bonus - applied_bonus,
        paid_eligible=paid_eligible_energy(eligible, applied_base, bonus_to_energy),
        payment=monthly_payment(eligible, applied_base, nbc, fixed, applied_bonus),
    )


@dataclass(frozen=True)
class AnnualValues(Generic[Amount]):
    applied_adjustment: tuple[Amount, ...]
    applied_prior: tuple[Amount, ...]
    forfeited_base: tuple[Amount, ...]
    closing_base: tuple[Amount, ...]
    closing_bonus: Amount
    bill_adjustment: Amount


def annual_accounting(
    *,
    opening_base: tuple[Amount, ...],
    opening_bonus: Amount,
    prior_paid: tuple[Amount, ...],
    adjustment: tuple[Amount, ...],
    nsc: Amount,
    offset_prior_payments: bool,
    carry_base_credit: bool,
    arithmetic: AccountingArithmetic[Amount],
) -> AnnualValues[Amount]:
    """Recoup surplus, offset eligible prior payments, then carry or expire base credit."""
    _validate_pools(opening_base, prior_paid, adjustment)
    if not isinstance(offset_prior_payments, bool) or not isinstance(carry_base_credit, bool):
        raise TypeError("Annual accounting rules must be boolean")
    zero = tuple(value * 0 for value in opening_base)
    applied_adjustment = tuple(
        arithmetic.minimum(bank, charge) for bank, charge in zip(opening_base, adjustment)
    )
    remaining = tuple(bank - credit for bank, credit in zip(opening_base, applied_adjustment))
    applied_prior = (
        tuple(arithmetic.minimum(bank, paid) for bank, paid in zip(remaining, prior_paid))
        if offset_prior_payments
        else zero
    )
    remaining = tuple(bank - credit for bank, credit in zip(remaining, applied_prior))
    return AnnualValues(
        applied_adjustment=applied_adjustment,
        applied_prior=applied_prior,
        forfeited_base=zero if carry_base_credit else remaining,
        closing_base=remaining if carry_base_credit else zero,
        closing_bonus=opening_bonus,
        bill_adjustment=annual_bill_adjustment(
            adjustment, applied_adjustment, applied_prior, nsc
        ),
    )
