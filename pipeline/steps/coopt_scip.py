"""Solve the existing PuLP physical model with shared NBT accounting in SCIP."""

import pulp
from pyscipopt import Model, quicksum

from tariffs.accounting_scip import ScipArithmetic


def solve_nbt_with_scip(problem, terms, imports, exports, weights):
    """Preserve all physical constraints and replace only the bill objective."""
    model = Model("NBT household cost")
    model.hideOutput()
    model.setRealParam("numerics/feastol", 1e-8)
    model.setRealParam("limits/gap", 1e-6)
    try:
        variables = list(problem.variables())
        mapped = {
            v: model.addVar(
                name=v.name,
                lb=v.lowBound,
                ub=v.upBound,
                vtype="I" if v.cat == pulp.LpInteger else "C",
            )
            for v in variables
        }

        def expression(value):
            affine = pulp.LpAffineExpression(value)
            return quicksum(float(c) * mapped[v] for v, c in affine.items()) + affine.constant

        for name, constraint in problem.constraints.items():
            lhs = expression(constraint)
            if constraint.sense == pulp.LpConstraintEQ:
                model.addCons(lhs == 0, name=name)
            elif constraint.sense == pulp.LpConstraintLE:
                model.addCons(lhs <= 0, name=name)
            elif constraint.sense == pulp.LpConstraintGE:
                model.addCons(lhs >= 0, name=name)
            else:
                raise ValueError(f"Unsupported physical constraint sense: {constraint.sense}")
        bill = terms.bill(
            [expression(v) for v in imports], [expression(v) for v in exports], weights,
            ScipArithmetic(model), missing_rate_lower_bound=terms.adjustment_rate is None,
        )
        model.setObjective(expression(problem.objective) + bill.amount_due_usd, "minimize")
        model.optimize()
        status = str(model.getStatus())
        if status != "optimal" and not (status == "gaplimit" and model.getGap() <= 1e-6):
            raise RuntimeError(f"SCIP NBT optimization did not reach the required gap: {status}")
        for variable in variables:
            variable.varValue = float(model.getVal(mapped[variable]))
        return float(model.getVal(bill.amount_due_usd))
    finally:
        model.freeProb()
