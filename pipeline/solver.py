"""Solver controls and cost certificates for the household optimization model."""

from dataclasses import dataclass
import math
from pathlib import Path
import re
import tempfile
import time
import warnings

COST_CERTIFICATE_ROUNDOFF_USD = 1e-6


@dataclass(frozen=True)
class SolverOptions:
    backend: str = "highs"
    annual_cost_gap_usd: float = 1.0
    time_limit_seconds: float = 300.0

    def __post_init__(self):
        if self.backend not in {"highs", "cbc"}:
            raise ValueError("solver backend must be 'highs' or 'cbc'")
        if not math.isfinite(self.annual_cost_gap_usd) or self.annual_cost_gap_usd < 0:
            raise ValueError("annual_cost_gap_usd must be finite and nonnegative")
        if not math.isfinite(self.time_limit_seconds) or self.time_limit_seconds <= 0:
            raise ValueError("time_limit_seconds must be finite and positive")


@dataclass(frozen=True)
class CostCertificate:
    objective_usd: float
    lower_bound_usd: float
    termination: str

    def __post_init__(self):
        if not all(math.isfinite(v) for v in (self.objective_usd, self.lower_bound_usd)):
            raise RuntimeError("Solver did not provide a finite objective and lower bound")
        if self.lower_bound_usd > self.objective_usd + COST_CERTIFICATE_ROUNDOFF_USD:
            raise RuntimeError("Solver lower bound exceeds the candidate objective")


@dataclass(frozen=True)
class SolverReport:
    options: SolverOptions
    elapsed_seconds: float
    lower_bound_usd: float
    optimality_gap_usd: float
    rounds: tuple[CostCertificate, ...]


def remaining_seconds(deadline: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise RuntimeError("County optimization time budget exhausted; no result accepted")
    return remaining


def solve_highs(problem, options: SolverOptions, deadline: float) -> CostCertificate:
    """Keep PuLP's model and solve its sparse matrix with SciPy/HiGHS."""
    import numpy as np
    import pulp
    import scipy
    # Older SciPy wrappers drop mip_abs_gap even after issuing the forwarding
    # notice. Require the runtime validated with this stopping rule.
    if np.lib.NumpyVersion(scipy.__version__) < "1.16.1":
        raise RuntimeError(
            f"HiGHS absolute cost gaps require SciPy >=1.16.1 (found {scipy.__version__}); "
            "upgrade SciPy or explicitly select the CBC backend"
        )
    from scipy.optimize import Bounds, LinearConstraint, milp
    from scipy.sparse import coo_matrix

    variables = list(problem.variables())
    variable_index = {variable: index for index, variable in enumerate(variables)}
    objective = np.array([float(problem.objective.get(v, 0.0)) for v in variables])
    lower_bounds = [v.lowBound if v.lowBound is not None else -np.inf for v in variables]
    upper_bounds = [v.upBound if v.upBound is not None else np.inf for v in variables]
    integrality = np.array([v.cat == pulp.LpInteger for v in variables], dtype=np.uint8)
    row_indices, column_indices, coefficients = [], [], []
    constraint_lower, constraint_upper = [], []
    for row, constraint in enumerate(problem.constraints.values()):
        for variable, coefficient in constraint.items():
            row_indices.append(row)
            column_indices.append(variable_index[variable])
            coefficients.append(float(coefficient))
        rhs = float(-constraint.constant)
        if constraint.sense == pulp.LpConstraintLE:
            constraint_lower.append(-np.inf)
            constraint_upper.append(rhs)
        elif constraint.sense == pulp.LpConstraintGE:
            constraint_lower.append(rhs)
            constraint_upper.append(np.inf)
        elif constraint.sense == pulp.LpConstraintEQ:
            constraint_lower.append(rhs)
            constraint_upper.append(rhs)
        else:
            raise ValueError(f"Unknown PuLP constraint sense {constraint.sense}")
    matrix = coo_matrix(
        (coefficients, (row_indices, column_indices)),
        shape=(len(constraint_lower), len(variables)),
    ).tocsr()
    # SciPy forwards this documented HiGHS option, but warns because it is not
    # part of SciPy's own option list. Suppress only that forwarding notice.
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore", message=r"Unrecognized options detected: \{'mip_abs_gap'\}.*",
            category=RuntimeWarning,
        )
        result = milp(
            c=objective, integrality=integrality,
            bounds=Bounds(lower_bounds, upper_bounds),
            constraints=LinearConstraint(matrix, constraint_lower, constraint_upper),
            options={
                "presolve": True, "mip_rel_gap": 0.0,
                "mip_abs_gap": options.annual_cost_gap_usd,
                "time_limit": remaining_seconds(deadline),
            },
        )
    if result.status not in {0, 1} or result.x is None:
        raise RuntimeError(
            f"HiGHS returned no usable candidate: status={result.status}, {result.message}"
        )
    # SciPy supplies no MIP bound for a continuous LP. Only a completed LP
    # proves its own objective is the lower bound; a timed-out LP does not.
    lower_bound = result.get("mip_dual_bound")
    if not integrality.any() and result.status == 0:
        lower_bound = result.fun
    if lower_bound is None:
        raise RuntimeError("HiGHS returned no cost lower bound; no result accepted")
    for variable, value in zip(variables, result.x):
        variable.varValue = float(value)
    constant = float(problem.objective.constant)
    return CostCertificate(
        float(result.fun) + constant, float(lower_bound) + constant,
        "time_limit" if result.status == 1 else "optimal_or_gap_satisfied",
    )


def cbc_cost_certificate(log: str, objective_usd: float, constant_usd: float) -> CostCertificate:
    """Read CBC's proof, since PuLP's 'Optimal' label also covers some timeouts."""
    if "Result -" in log:
        summary = log.rsplit("Result -", 1)[1]
        if "No feasible solution found" in summary:
            raise RuntimeError("CBC returned no feasible candidate")
        if "Optimal solution found" in summary and "within gap tolerance" not in summary:
            return CostCertificate(objective_usd, objective_usd, "optimal")
        if "within gap tolerance" in summary or "Stopped on time limit" in summary:
            match = re.search(r"Lower bound:\s+(-?\d+\.\d+)", summary)
            if match is None:
                raise RuntimeError("CBC returned no cost lower bound; no result accepted")
            # CBC rounds its printed bound. Move to the lower end of that
            # rounding interval to avoid overstating the numerical certificate.
            printed = match.group(1)
            rounding_half_unit = 0.5 * 10 ** -len(printed.split(".")[1])
            lower_bound = float(printed) - rounding_half_unit + constant_usd
            return CostCertificate(
                objective_usd, lower_bound,
                "time_limit" if "Stopped on time limit" in summary else "gap_satisfied",
            )
    elif re.search(r"^Optimal objective ", log, re.MULTILINE):
        return CostCertificate(objective_usd, objective_usd, "optimal")
    raise RuntimeError("CBC did not provide a recognized cost certificate")


def solve_cbc(problem, options: SolverOptions, deadline: float) -> CostCertificate:
    import pulp

    with tempfile.TemporaryDirectory(prefix="household-cbc-") as directory:
        log_path = Path(directory) / "solver.log"
        solver = pulp.PULP_CBC_CMD(
            msg=False, gapRel=0.0, gapAbs=options.annual_cost_gap_usd,
            timeLimit=remaining_seconds(deadline), timeMode="elapsed", logPath=str(log_path),
        )
        problem.solve(solver)
        if problem.sol_status not in {pulp.LpSolutionOptimal, pulp.LpSolutionIntegerFeasible}:
            raise RuntimeError(f"CBC returned no feasible candidate: {pulp.LpStatus[problem.status]}")
        return cbc_cost_certificate(
            log_path.read_text(), float(pulp.value(problem.objective)),
            float(problem.objective.constant),
        )
