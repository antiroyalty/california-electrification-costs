"""Cost and energy bounds that preserve the household's economic optimum."""

from dataclasses import dataclass
import math

import pulp

# Do not create an almost-fixed [0, 1e-6] kWh interval. Solver presolve can
# collapse it to the wrong endpoint. A 1 Wh search ceiling expands the bound;
# zero and every potentially optimal capacity remain feasible.
MINIMUM_SEARCH_CEILING_KWH = 0.001


@dataclass(frozen=True)
class BatterySearchBound:
    maximum_kwh: float
    feasible_annual_cost_usd: float


def pv_only_nbt_cost(*, pv_kw, pv_gen_per_kw, load_kwh, weights, terms,
                     pv_annual_cost_per_kw):
    """Price a feasible design: serve load first, then export within the annual cap."""
    if not (len(load_kwh) == len(pv_gen_per_kw) == len(weights)):
        raise ValueError("PV-only bound requires matching load, generation, and weights")
    if any(not math.isfinite(v) or v < 0
           for v in (pv_kw, pv_annual_cost_per_kw, *load_kwh, *pv_gen_per_kw)):
        raise ValueError("PV-only bound requires finite, nonnegative costs and energy")
    imports = [max(0.0, load - pv_kw * solar)
               for load, solar in zip(load_kwh, pv_gen_per_kw)]
    exports = [max(0.0, pv_kw * solar - load)
               for load, solar in zip(load_kwh, pv_gen_per_kw)]
    annual_imports = math.fsum(w * value for w, value in zip(weights, imports))
    annual_exports = math.fsum(w * value for w, value in zip(weights, exports))
    if annual_exports > annual_imports:
        # Curtail surplus PV proportionally. This constructs a feasible upper
        # bound; it need not be the best possible export schedule.
        exports = [value * annual_imports / annual_exports for value in exports]
    return (terms.bill(imports, exports, weights).amount_due_usd
            + pv_kw * pv_annual_cost_per_kw)


def tighten_nbt_battery_bound(
    problem, *, solver_run, pv_size, battery_size, credit_eligible,
    pv_gen_per_kw, load_kwh, weights, terms, pv_annual_cost_per_kw,
    battery_annual_cost_per_kwh, minimum_credited_kwh,
):
    """Exclude capacities that cannot beat a feasible solar-only household.

    The first solve proposes a PV size with no battery. Numeric billing prices
    a physically feasible dispatch at that size. The second solve maximizes
    gross annual battery-capacity cost below that feasible household cost.
    Relaxing eligibility and meter direction can only enlarge this search.
    Its certified bound therefore cannot exclude an optimal physical design.
    """
    if not math.isfinite(battery_annual_cost_per_kwh) or battery_annual_cost_per_kwh <= 0:
        raise ValueError("Battery bound tightening requires positive annual cost per kWh")
    original_bounds = [(v, v.lowBound, v.upBound) for v in (battery_size, credit_eligible)]
    try:
        for variable, _, _ in original_bounds:
            variable.lowBound = variable.upBound = 0.0
        solver_run.solve_auxiliary(problem, purpose="solar_only_meter_relaxation")
        pv_kw = pv_size.value() if pv_size.lowBound != pv_size.upBound else pv_size.lowBound
        if (pv_kw is None or not math.isfinite(pv_kw)
                or pv_kw < -1e-6 or pv_kw > pv_size.upBound + 1e-6):
            raise RuntimeError("Invalid PV capacity in battery bound tightening")
        pv_kw = min(pv_size.upBound, max(0.0, pv_kw))
    finally:
        for variable, lower, upper in original_bounds:
            variable.lowBound, variable.upBound = lower, upper

    feasible_cost = pv_only_nbt_cost(
        pv_kw=pv_kw, pv_gen_per_kw=pv_gen_per_kw, load_kwh=load_kwh,
        weights=weights, terms=terms, pv_annual_cost_per_kw=pv_annual_cost_per_kw,
    )
    objective = problem.objective
    # The dollar margin protects the feasible upper bound from arithmetic roundoff.
    problem += objective <= feasible_cost + 1e-6, "feasible_household_cost_ceiling"
    original_category = credit_eligible.cat
    try:
        credit_eligible.cat = pulp.LpContinuous
        # Keep the auxiliary objective in annual dollars. Negating its lower
        # bound gives an upper bound on gross battery-capacity cost.
        problem.setObjective(-battery_size * battery_annual_cost_per_kwh)
        certificate = solver_run.solve_auxiliary(
            problem, purpose="negative_gross_battery_capacity_annual_cost",
        )
        maximum_kwh = -certificate.lower_bound_usd / battery_annual_cost_per_kwh
        if maximum_kwh + 1e-6 < minimum_credited_kwh:
            # This cost ceiling cannot contain an eligible battery. Propagate
            # that proof before bounding the remaining uncredited capacities.
            credit_eligible.upBound = 0.0
            certificate = solver_run.solve_auxiliary(
                problem, purpose="negative_uncredited_battery_capacity_annual_cost",
            )
            maximum_kwh = min(
                maximum_kwh, -certificate.lower_bound_usd / battery_annual_cost_per_kwh,
            )
    finally:
        credit_eligible.cat = original_category
        credit_eligible.upBound = original_bounds[1][2]
        problem.setObjective(objective)
        del problem.constraints["feasible_household_cost_ceiling"]
    if maximum_kwh < -1e-6:
        raise RuntimeError("Battery capacity upper bound is negative")
    # Expand by the existing capacity feasibility tolerance, never round inward.
    return BatterySearchBound(
        min(battery_size.upBound, max(MINIMUM_SEARCH_CEILING_KWH, maximum_kwh + 1e-6)),
        feasible_cost,
    )


def maximum_meter_export_kwh(*, pv_available_kwh, load_kwh, battery_kwh,
                             usable_soc_fraction, discharge_efficiency):
    """An exporting meter must first serve load from PV and usable stored energy."""
    return max(0.0, pv_available_kwh
               + battery_kwh * usable_soc_fraction * discharge_efficiency - load_kwh)
