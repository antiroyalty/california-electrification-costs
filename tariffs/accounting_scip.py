"""SCIP implementations of the two operations used by the shared credit equations.

This adapter contains no utility rules. Minimum is an equality enforced by
indicator constraints. Proportional allocation uses a cross-product equality,
which remains defined when both eligible components are zero.
"""

import math
from numbers import Real

from pyscipopt import Model

from .accounting_equations import NumericArithmetic


class ScipArithmetic:
    def __init__(self, model: Model):
        self.model = model

    def _nonnegative(self, value):
        if isinstance(value, Real):
            if isinstance(value, bool) or not math.isfinite(value) or value < 0:
                raise ValueError("Accounting constants must be finite non-negative dollars")
        else:
            self.model.addCons(value >= 0)

    def minimum(self, left, right):
        self._nonnegative(left)
        self._nonnegative(right)
        if isinstance(left, Real) and isinstance(right, Real):
            return min(left, right)
        if (isinstance(left, Real) and left == 0) or (isinstance(right, Real) and right == 0):
            return 0.0
        value = self.model.addVar(name=f"credit_min_{self.model.getNVars()}", lb=0)
        selector = self.model.addVar(name=f"credit_min_branch_{self.model.getNVars()}", vtype="B")
        self.model.addCons(value <= left)
        self.model.addCons(value <= right)
        self.model.addConsIndicator(left - value <= 0, binvar=selector)
        self.model.addConsIndicator(right - value <= 0, binvar=selector, activeone=False)
        return value

    def proportional(self, amount, eligible):
        if len(eligible) not in (1, 2):
            raise ValueError("Proportional allocation requires one or two energy pools")
        self._nonnegative(amount)
        for weight in eligible:
            self._nonnegative(weight)
        constant_weights = all(isinstance(weight, Real) for weight in eligible)
        if isinstance(amount, Real) and constant_weights:
            if amount > sum(eligible):
                raise ValueError("Allocation cannot exceed eligible charges")
        else:
            self.model.addCons(amount <= sum(eligible))
        if isinstance(amount, Real) and amount == 0:
            return tuple(0.0 for _ in eligible)
        if len(eligible) == 1:
            return (amount,)
        if constant_weights:
            if sum(eligible) == 0:
                # A symbolic amount is constrained to zero above.
                return (0.0, 0.0)
            fractions = NumericArithmetic.proportional(1.0, eligible)
            return tuple(amount * fraction for fraction in fractions)
        shares = tuple(
            self.model.addVar(name=f"bonus_share_{self.model.getNVars()}", lb=0)
            for _ in eligible
        )
        self.model.addCons(sum(shares) == amount)
        for share, weight in zip(shares, eligible):
            self.model.addCons(share <= weight)
        self.model.addCons(shares[0] * eligible[1] == shares[1] * eligible[0])
        return shares
