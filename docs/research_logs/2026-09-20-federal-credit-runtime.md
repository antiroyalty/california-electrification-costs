# Federal-credit runtime validation

The new search bounds resolve three of the four credited designs rejected by
the [initial pilot](2026-09-20-federal-credit-pilot.md). Both Alameda regression
cases also pass. San Diego electric/EV still fails the default five-minute
budget. Its remaining cost gap falls from $94.05/year to $3.09/year.

This change preserves the pilot's model and $1/year acceptance limit. It does
not change credit eligibility, equipment prices, tariffs, dispatch permissions,
or the declared 40 kWh storage ceiling. It reduces the solver's search using
proved cost and energy bounds. Validation ran from `992c4db` with uncommitted
changes identified by SHA-256. Those changes are now committed as `ca1214a`.
See the [September 21 investigation](2026-09-21-federal-credit-runtime.md) for
the remaining San Diego electric case.

## Default-budget results

Each row uses 8,760 hours and a 300-second solver budget. The reported elapsed
time includes model construction, preprocessing, and final validation. Limits
are cooperative; failed calls can exceed the requested duration.

| County / household | Previous credited solve | Revised elapsed time | Revised annual cost gap | Result |
|---|---|---:|---:|---|
| Alameda / gas-ICE | Accepted, 206 s | 103 s | $0.9801 | Accepted |
| Alameda / electric-EV | Accepted, 178 s | 72 s | $0.6474 | Accepted |
| Los Angeles / gas-ICE | Rejected at 300 s and 600 s | 71 s | $0.8099 | Accepted |
| Los Angeles / electric-EV | Rejected at 300 s | 101 s | $0.9927 | Accepted |
| San Diego / gas-ICE | Rejected at 300 s | 257 s | $0.9169 | Accepted |
| San Diego / electric-EV | Rejected at 300 s | 303 s | $3.0892 | Rejected |

These are single local measurements, not runtime guarantees. The two Alameda
objectives reproduce the previous accepted costs. Their costs remain consistent
with both old and new optimality certificates.

San Diego gas/ICE selects 2.15 kW of solar and 3.81 kWh of storage under the
pilot's conditional full-credit assumptions. The accepted Alameda and Los
Angeles designs select zero storage. These are sizing validations. The refreshed
matched household comparison and statewide federal-credit results remain pending.

## Why the search is smaller

A feasible solar-only design bounds the minimum possible sizing cost. A relaxed
optimization then bounds the largest battery that could match that cost. If it
cannot reach credit eligibility, another relaxation bounds uncredited storage.
The final search retains zero capacity and all potentially optimal designs.

The reduced capacity also limits hourly exports. An exporting home must serve
its own load from solar and usable stored energy. Combining that energy limit
with the existing flow constraints strengthens the meter-direction calculation.
The [methods narrative](../RESEARCH_METHODS.md) and [formula manifest](../methods.yaml)
describe the equations, numerical guards, and scope.

Auxiliary solves use the original shared time budget. Their objectives can
differ from the household sizing objective. Their certificates are saved under
`auxiliary_solves` and never enter the final household cost certificate.

## Validation and artifacts

The isolated directory is
`analysis_results/runs/2026-09-20_992c4db_credit_runtime/`.
`validation_v1/started.json` records input and model hashes. Its `progress.json`
and `finished.json` record five acceptances and one rejection. Rejected runs
have no accepted design artifacts.

`verify_saved_designs.py` independently checks the five saved designs. It
reconstructs discounted purchase, replacement, remaining-value, and initial-credit
cash flows. It also replays the saved utility bill and verifies load balance,
solar availability, cyclic storage with losses, power and charge limits,
exclusive meter direction, and the annual export cap. Capital costs agree within
$10^{-8}$ dollars/year; the bill replay differences are zero. Physical checks use the
existing 0.001 kWh artifact tolerance.

The 255 existing focused tests passed before and after the implementation.
Their expected results were preserved. The final regression suite passed all
514 tests in 23.62 seconds; its output is `final_regression_tests.log`.
New tests cover fixed-design references
around the credit threshold, zero storage, weighted export caps, charging/export
permissions, shared deadlines, auxiliary proof separation, and state restoration
after errors. A near-zero bound test caught a numerical presolve problem. The
search ceiling now has an outward 1 Wh floor, which still permits zero storage.

Exploratory credit formulations, explicit credit alternatives, additional solar
bounds, and native HiGHS 1.15.1 did not resolve all default-budget failures.
Their logs remain isolated. They are not part of the production change.

## Follow-up

An explicit 600-second check of San Diego electric/EV also failed. It ended in
606 seconds with a $2.1847/year gap. The candidate sizing objective was
$3,323.6639/year and its certified lower bound was $3,321.4792/year. No design
was accepted. Its separate `validation_sd_electric_600s/` record preserves the
larger budget, identical model hashes, and rejection. The default budget stays
at 300 seconds; there is no automatic retry or relaxed acceptance criterion.

Keep this remaining case separate from the validated improvements. A possible
next step is to derive a tighter feasible cost from the first dispatch by
redirecting simultaneous exports to household load, then repeat capacity bounding.
That construction needs its own physical and accounting tests before use. It
is not implemented here. Do not expand statewide or label the refreshed pilot
complete while the declared acceptance criterion remains unmet.

A new fixed-size reference also exposed an existing CBC rounding rejection.
Both the prior optimizer core and the revised core reject the same example
because the reported lower bound slightly exceeds the replayed bill. The default
HiGHS path passes. Record this as a separate CBC certificate correction; do not
weaken the cost check or include it silently in this runtime change. The
reproduction is `cbc_existing_roundoff.log` in the isolated directory.
