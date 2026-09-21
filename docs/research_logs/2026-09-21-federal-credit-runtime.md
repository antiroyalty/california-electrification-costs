# Remaining federal-credit runtime investigation

Four targeted refinements failed to bring San Diego electric/EV within the
existing $1/year cost limit and 300-second budget. None is retained in production.
The validated implementation remains `ca1214a`. At the end of this investigation,
the credited pilot had five accepted designs and one unresolved design. The
[approved $5/year follow-up](2026-09-21-federal-credit-pilot-gap5.md) now completes
the pilot without retaining these experimental refinements.

This investigation follows the
[September 20 runtime validation](2026-09-20-federal-credit-runtime.md).
It preserves the same full-year inputs, tariffs, purchase costs, credit assumptions,
dispatch permissions, and research sizing limits. Each probe used an isolated
Python override on the committed model. Production code stayed unchanged.

## Results

Each attempt used San Diego's 8,760-hour electric/EV profile and conditional full
solar/storage credit realization. All final candidates had the same sizing
objective to six decimals: $3,323.663866/year. This objective includes electricity
and annual solar/storage costs. It excludes fixed appliance and vehicle costs.

| Isolated refinement | Elapsed solver-run time | Certified lower cost | Remaining annual gap | Outcome |
|---|---:|---:|---:|---|
| Bound capacity using a feasible solar-and-battery dispatch | 301.2 s | $3,321.500951 | $2.162915 | Rejected |
| Tighten credit constraints to the proved capacity ceiling | 310.6 s | $3,320.430092 | $3.233774 | Rejected |
| Relax the credit-eligibility binary | 310.5 s | $3,321.313755 | $2.350111 | Rejected |
| Prove the uncredited-storage branch cannot be optimal | 303.3 s | $3,321.294516 | $2.369350 | Rejected |

Limits are cooperative, so elapsed time can exceed 300 seconds. These are single
measurements. Repeated candidate costs do not prove global optimality or precise
equipment sizes. No accepted design or publication result was written by these
attempts.

## What the probes established

With grid charging disabled, simultaneous imports and exports can be removed
by sending exported solar or battery energy to household load. This subtracts
the same energy from imports and exports. Battery charging, total discharge,
state of charge, and the annual net energy balance remain unchanged.

Applying this construction to the first relaxed solution gives a feasible
upper cost of $3,323.664374/year. It tightens the battery capacity ceiling from
11.017899 to 7.541317 kWh. The extra bound calculation still does not produce
a final $1/year certificate within the budget.

The fourth probe solves a separate relaxation with the storage credit disabled.
Solar credits remain available. That relaxation has a lower cost bound of
$3,413.461147/year, above the feasible credited alternative. This proves that
the uncredited-storage branch cannot contain an optimum under these inputs.
Removing that branch still does not resolve the final runtime failure.

These constructions remain exploratory. They have not received the additional
unit and saved-artifact validation required for a production implementation.
The isolated script for a conditional export-energy inequality was prepared
but not run; it supplies no runtime evidence.

## Validation and provenance

Before the probes, all 226 tests passed in the existing optimization-bound,
solver-control, federal-credit optimizer, linear optimizer, and NBT suites.
No tests or expected results were changed. Both `docs/methods.yaml` and
`docs/RESEARCH_METHODS.md` were checked. Their implemented-method descriptions
remain accurate, so this documentation-only investigation does not change them.

Artifacts are isolated under
`analysis_results/runs/2026-09-21_ca1214a_credit_runtime/`.
The four executed drivers are `probe_feasible_dispatch.py`,
`probe_credit_capacity.py`, `probe_relaxed_eligibility.py`, and
`probe_proved_eligibility.py`. Each has a matching log and a rejected-run record.
`provenance.json` records the base commit, clean tracked state, and source/input
hashes. It was recorded during the investigation, not before all four probes.

## Approved follow-up

The user approved an explicit $5/year cost limit for the federal-credit pilot.
The follow-up reruns both San Diego credited households at that limit and completes
physical, accounting, and comparison validation. Reused designs retain their
original $1/year certificates. The production default remains $1/year. No failed
attempt has been relabeled as accepted.

An annual cost bound limits financial suboptimality. It does not bound differences
in selected capacities. The completed pilot records each tolerance and retains
the cost bounds when interpreting savings or household comparisons. A claim
about a precise capacity or an adoption threshold may still need a tighter solve.

Further runtime work at $1/year is deferred. The existing CBC rounding issue
remains a separate follow-up.
