"""Cost precision never substitutes for a physical, certified dispatch."""

from dataclasses import asdict
import json
import time
from types import SimpleNamespace

import pulp
import pytest
from scipy.optimize import OptimizeResult

from pipeline import solver
from pipeline.solver import CostCertificate, SolverOptions, SolverRun
from pipeline.steps import step9b_cooptimize_core as core


@pytest.mark.parametrize("kwargs", [
    {"backend": "unknown"}, {"annual_cost_gap_usd": -1},
    {"annual_cost_gap_usd": float("nan")}, {"annual_cost_gap_usd": float("inf")},
    {"time_limit_seconds": 0}, {"time_limit_seconds": -1},
    {"time_limit_seconds": float("inf")}, {"time_limit_seconds": float("nan")},
])
def test_invalid_solver_controls_fail_before_solving(kwargs):
    with pytest.raises(ValueError):
        SolverOptions(**kwargs)


def _binary_problem():
    problem = pulp.LpProblem("certificate", pulp.LpMinimize)
    x = pulp.LpVariable("x", cat=pulp.LpBinary)
    problem += x >= 0.5
    problem += 4 * x + 25
    return problem


@pytest.mark.parametrize("backend", ["highs", "cbc"])
def test_real_backends_include_fixed_costs_in_the_bound(backend):
    problem = _binary_problem()
    certificate = getattr(solver, f"solve_{backend}")(
        problem, SolverOptions(backend=backend), time.monotonic() + 30,
    )
    assert certificate.objective_usd == pytest.approx(29)
    assert certificate.lower_bound_usd == pytest.approx(29)


def test_highs_rejects_runtimes_that_drop_the_absolute_gap(monkeypatch):
    import scipy

    monkeypatch.setattr(scipy, "__version__", "1.11.4")
    with pytest.raises(RuntimeError, match=r"SciPy >=1.16.1.*explicitly select the CBC"):
        solver.solve_highs(_binary_problem(), SolverOptions(), time.monotonic() + 20)


def test_highs_timeout_returns_a_bound_and_keeps_economic_and_time_controls(monkeypatch):
    import scipy.optimize

    captured = {}

    def timed_out(**kwargs):
        captured.update(kwargs["options"])
        return OptimizeResult(status=1, x=[1], fun=4, mip_dual_bound=3.5, message="Time limit")

    monkeypatch.setattr(scipy.optimize, "milp", timed_out)
    certificate = solver.solve_highs(_binary_problem(), SolverOptions(), time.monotonic() + 20)
    assert captured["mip_abs_gap"] == 1
    assert captured["mip_rel_gap"] == 0
    assert 0 < captured["time_limit"] <= 20
    assert certificate == CostCertificate(29, 28.5, "time_limit")


@pytest.mark.parametrize("bound", [None, float("nan"), float("inf"), 5])
def test_highs_cannot_accept_an_absent_or_invalid_mip_bound(monkeypatch, bound):
    import scipy.optimize

    monkeypatch.setattr(scipy.optimize, "milp", lambda **kwargs: OptimizeResult(
        status=1, x=[1], fun=4, mip_dual_bound=bound, message="Time limit",
    ))
    with pytest.raises(RuntimeError, match="bound"):
        solver.solve_highs(_binary_problem(), SolverOptions(), time.monotonic() + 20)


@pytest.mark.parametrize("result", [
    OptimizeResult(status=1, x=None, message="Time limit"),
    OptimizeResult(status=2, x=None, message="Infeasible"),
])
def test_highs_requires_a_candidate(monkeypatch, result):
    import scipy.optimize

    monkeypatch.setattr(scipy.optimize, "milp", lambda **kwargs: result)
    with pytest.raises(RuntimeError, match="no usable candidate"):
        solver.solve_highs(_binary_problem(), SolverOptions(), time.monotonic() + 20)


@pytest.mark.parametrize("termination", [
    "Optimal solution found (within gap tolerance)", "Stopped on time limit",
])
def test_cbc_preserves_the_bound_instead_of_trusting_pulp_optimal_status(termination):
    log = f"Result - {termination}\nObjective value: 4.00000000\nLower bound: 3.500\n"
    certificate = solver.cbc_cost_certificate(log, 29, 25)
    assert certificate.lower_bound_usd == pytest.approx(28.4995)
    assert certificate.objective_usd - certificate.lower_bound_usd == pytest.approx(.5005)
    assert certificate.termination != "optimal"


@pytest.mark.parametrize("log", [
    "Result - Stopped on time limit\nNo feasible solution found\nLower bound: 0.000",
    "Result - Stopped on time limit\nObjective value: 4.00000000",
    "Result - Optimal solution found (within gap tolerance)",
    "Result - Problem proven infeasible", "unrecognized output",
])
def test_cbc_unknown_or_incomplete_proofs_are_rejected(log):
    with pytest.raises(RuntimeError):
        solver.cbc_cost_certificate(log, 29, 25)


def test_solver_run_keeps_the_strongest_round_bound(monkeypatch):
    certificates = iter([
        CostCertificate(40, 38.5, "time_limit"),
        CostCertificate(40, 39.25, "time_limit"),
    ])
    monkeypatch.setattr(solver, "solve_highs", lambda *args: next(certificates))

    run = SolverRun(SolverOptions(annual_cost_gap_usd=1))
    run.solve_round(object())
    run.solve_round(object())
    report = run.finalize(40)

    assert report.round_count == 2
    assert report.lower_bound_usd == pytest.approx(39.25)
    assert report.optimality_gap_usd == pytest.approx(0.75)


@pytest.mark.parametrize("replayed_cost", [float("nan"), float("inf")])
def test_solver_run_rejects_a_nonfinite_replayed_cost(monkeypatch, replayed_cost):
    monkeypatch.setattr(
        solver,
        "solve_highs",
        lambda *args: CostCertificate(40, 40, "optimal"),
    )
    run = SolverRun(SolverOptions())
    run.solve_round(object())
    with pytest.raises(RuntimeError, match="must be finite"):
        run.finalize(replayed_cost)


def test_solver_run_requires_a_certificate_before_finalizing():
    with pytest.raises(RuntimeError, match="without a cost certificate"):
        SolverRun(SolverOptions()).finalize(40)


def _no_solar_inputs():
    return core.CooptInputs([100], [0], [.4], [.1])


@pytest.mark.parametrize("gap,accepted", [(0.5, True), (1.0, True), (1.001, False)])
def test_final_dispatch_must_meet_cost_gap_even_with_a_feasible_timeout(monkeypatch, gap, accepted):
    original = solver.solve_cbc

    def timed_out(problem, options, deadline):
        result = original(problem, options, deadline)
        return CostCertificate(result.objective_usd, result.objective_usd - gap, "time_limit")

    monkeypatch.setattr(solver, "solve_cbc", timed_out)
    options = SolverOptions(backend="cbc")
    if not accepted:
        with pytest.raises(RuntimeError, match="annual cost gap.*exceeds"):
            core._solve_lp(_no_solar_inputs(), solver_options=options)
    else:
        result = core._solve_lp(_no_solar_inputs(), solver_options=options)
        assert result.total_cost == pytest.approx(40)
        assert result.solver.optimality_gap_usd == pytest.approx(gap)
        assert result.solver.lower_bound_usd == pytest.approx(40 - gap)


def _meter_case():
    return core.CooptInputs([1, 1], [1, 0], [.2, .2], [2, .05])


def test_economic_tolerance_does_not_allow_simultaneous_meter_flows(monkeypatch):
    original = solver.solve_cbc

    def invalid_second_round(problem, options, deadline):
        certificate = original(problem, options, deadline)
        if "grid_import_mode_0" in problem.variablesDict():
            for name, value in {"pv2load_0": .5, "grid2load_0": .5, "pv2grid_0": 1.5}.items():
                problem.variablesDict()[name].varValue = value
        return certificate

    monkeypatch.setattr(solver, "solve_cbc", invalid_second_round)
    with pytest.raises(RuntimeError, match="Meter-direction constraint violated solver tolerance"):
        core._solve_lp(
            _meter_case(),
            fixed_pv_kw=2,
            fixed_batt_kwh=0,
            solver_options=SolverOptions(backend="cbc"),
        )


def test_time_budget_is_shared_by_all_meter_rounds(monkeypatch):
    now = [time.monotonic()]
    clock = SimpleNamespace(monotonic=lambda: now[0])
    monkeypatch.setattr(solver, "time", clock)
    calls = []

    def uses_budget(problem, options, deadline):
        calls.append(deadline)
        now[0] = deadline + .01
        return CostCertificate(40, 40, "optimal")

    monkeypatch.setattr(solver, "solve_highs", uses_budget)
    run = SolverRun(SolverOptions())
    run.solve_round(object())
    with pytest.raises(RuntimeError, match="County optimization time budget exhausted"):
        run.solve_round(object())
    assert len(calls) == 1


def test_stricter_cost_tolerance_remains_available():
    result = core._solve_lp(_meter_case(), fixed_pv_kw=2, fixed_batt_kwh=0,
                            solver_options=SolverOptions("cbc", 0))
    assert result.solver.optimality_gap_usd <= 1e-6


def test_step9b_forwards_settings_and_saves_the_cost_certificate(tmp_path, monkeypatch):
    import pandas as pd
    from pipeline.steps import step9b_cooptimize_pv_battery as step
    from tariffs import NBTAnnualTerms, NBTScenario, TariffCatalog

    options = SolverOptions("cbc", .25, 60)
    tariff = TariffCatalog().bundle("PG&E", NBTScenario())
    times = pd.date_range("2026-01-01", periods=2, freq="h")
    terms = NBTAnnualTerms.from_tariff(tariff, times)
    inputs = core.CooptInputs([1, 1], [0, 0], list(terms.import_rates),
                              list(terms.export_rates), nbt_terms=terms)
    result = core._solve_lp(inputs, solver_options=options)
    county = tmp_path / "inputs/full_electric_ev_coopt/single-family-detached/alameda"
    county.mkdir(parents=True)
    (county / "weather_TMY_alameda.csv").touch()
    (county / "combined_profiles_full_electric_ev_coopt_alameda.csv").touch()
    monkeypatch.setattr(step, "prepare_weather_and_load", lambda *args: (object(), [1] * 8760))
    monkeypatch.setattr(step, "pv_timeseries_ac_kwh", lambda *args: [0] * 8760)
    monkeypatch.setattr(step, "_write_step9_outputs", lambda *args: None)

    def solve(inputs, **kwargs):
        assert kwargs["solver_options"] == options
        return result

    monkeypatch.setattr(step, "_solve_lp", solve)
    step.process(str(tmp_path / "inputs"), str(tmp_path / "outputs"),
                 "full_electric_ev_coopt", "single-family-detached", ["alameda"],
                 solver_options=options)
    output = tmp_path / "outputs/full_electric_ev_coopt/single-family-detached"
    saved = json.loads((output / "alameda/coopt_solver_alameda.json").read_text())
    assert saved["options"] == asdict(options)
    assert saved["optimality_gap_usd"] == result.solver.optimality_gap_usd
    assert len(saved["rounds"]) == result.solver_rounds
    capacities = pd.read_csv(output / "CAPITAL_COSTS/electrified_assets.csv")
    assert capacities.iloc[0]["Solver Backend"] == "cbc"
    assert capacities.iloc[0]["Solver Lower Bound (USD/year)"] == pytest.approx(
        result.solver.lower_bound_usd,
    )
