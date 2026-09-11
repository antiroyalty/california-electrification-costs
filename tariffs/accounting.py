"""Annual base-credit accounting in dollars, independent of tariffs and solvers.

Each eligible pool settles once. Credits cannot pay fixed or non-bypassable
charges. Unused credits have no value outside the representative year.
"""

from dataclasses import dataclass
import math
from typing import Callable, Generic, TypeVar

Amount = TypeVar("Amount")


@dataclass(frozen=True)
class AnnualCreditSettlement(Generic[Amount]):
    eligible_charge_usd: tuple[Amount, ...]
    earned_base_credit_usd: tuple[Amount, ...]
    remaining_charge_usd: tuple[Amount, ...]
    non_bypassable_charge_usd: Amount
    fixed_charge_usd: float

    @property
    def gross_charge_usd(self):
        return sum(self.eligible_charge_usd) + self.non_bypassable_charge_usd + self.fixed_charge_usd

    @property
    def earned_credit_usd(self):
        return sum(self.earned_base_credit_usd)

    @property
    def applied_credit_usd(self):
        return sum(self.eligible_charge_usd) - sum(self.remaining_charge_usd)

    @property
    def unused_credit_usd(self):
        return self.earned_credit_usd - self.applied_credit_usd

    @property
    def amount_due_usd(self):
        return sum(self.remaining_charge_usd) + self.non_bypassable_charge_usd + self.fixed_charge_usd


def settle_annual_credits(
    eligible_charge_usd: tuple[Amount, ...],
    earned_base_credit_usd: tuple[Amount, ...],
    non_bypassable_charge_usd: Amount,
    fixed_charge_usd: float,
    *,
    positive_part: Callable[[Amount], Amount] | None = None,
) -> AnnualCreditSettlement[Amount]:
    """Return fixed + NBC + sum(max(eligible charge - base credit, 0)).

    Numeric calls validate dollars and use max directly. Optimization supplies
    a positive-part expression, which must be minimized in the bill objective.
    The caller groups generation and delivery into the utility's eligible pools.
    """
    if not eligible_charge_usd or len(eligible_charge_usd) != len(earned_base_credit_usd):
        raise ValueError("Annual charges and credits must identify the same nonempty pools")
    if positive_part is None:
        values = (*eligible_charge_usd, *earned_base_credit_usd,
                  non_bypassable_charge_usd, fixed_charge_usd)
        if any(not math.isfinite(v) or v < 0 for v in values):
            raise ValueError("Annual charges and credits must be finite and non-negative")
        positive_part = lambda value: max(value, 0.0)
    return AnnualCreditSettlement(
        eligible_charge_usd, earned_base_credit_usd,
        tuple(positive_part(charge - credit)
              for charge, credit in zip(eligible_charge_usd, earned_base_credit_usd)),
        non_bypassable_charge_usd, fixed_charge_usd,
    )
