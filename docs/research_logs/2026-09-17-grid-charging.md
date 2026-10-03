# Grid-charging sensitivity — September 17, 2026

The completed comparison covers **94 cases: both households in all 47 modeled
counties**. Allowing grid charging preserves zero storage in all 36 PG&E counties
and all 10 SCE counties. San Diego, assigned to SDG&E, is the only material
exception under the modeled costs and operating rules.

| Assigned utility | Counties | Result for both households |
|---|---:|---|
| PG&E | 36 | Zero storage; any benefit from grid charging is below $1/year. |
| SCE | 10 | Zero storage; any benefit from grid charging is below $1/year. |
| SDG&E | 1 | Storage becomes beneficial in San Diego; report certified cost ranges rather than exact optimal sizes. |

All **92 non-San-Diego cases** meet the usual $1/year optimality criterion.
None uses grid charging. The largest certified ceiling on its possible benefit
is **$0.981/year**. Differences between saved design costs are at most $0.135/year
and reflect numerical solution differences, not use of grid charging.

San Diego's certified optimal-cost savings are approximately
**$29.16–$44.16/year for gas/ICE** and **$57.27–$85.14/year for electric/EV**.
These savings include annualized solar and battery costs. The separate interval
runs establish a positive effect without claiming exact optimal capacities.
All 94 cases passed physical and billing checks. A separate final check reloaded
the saved dispatch and energy-origin files and reconciled all 94 bills.

## Question and comparison

Does allowing batteries to charge from the grid change optimal solar capacity,
battery capacity, or annual cost? Compare both modeled household types across
the same 47 counties. Change only permission to charge from the grid.

The existing optimizer tracks stored energy by origin. Grid-charged energy can
supply the home but cannot be exported. Solar-charged energy can supply the home
or earn export credits. Grid purchases include battery charging. Annual exports
remain capped at annual imports. No utility-approval claim follows from these
modeled operating rules.

The baseline comes from the September 15 cost refresh, which preserves the
September 14 hourly optimizations. The new run uses model HEAD
`916e380117a422c7e809db655481cd0462e6d4f4`. The intervening optimizer change
batches required meter constraints earlier; it preserves the feasible set and
objective. No production-model code changes accompany this sensitivity.

The run record is
[`analysis_results/runs/2026-09-17_916e380_grid_charging`](../../analysis_results/runs/2026-09-17_916e380_grid_charging/).
It preserves source hashes, the execution driver, logs, solver certificates,
full-precision capacities, dispatch, stored-energy origins, and comparisons.
Source results are read without overwriting them. The main county batch uses six
subprocesses, each with one HiGHS thread. Default attempts use a 300-second solve
budget and require an annual cost gap of at most $1. Time limits are cooperative;
some successful finalizations exceeded that elapsed time. Failed cases are
preserved and not accepted.

The initial batch was stopped after four of six representative cases missed the
$1/year certificate. The final selection contains two original Los Angeles
successes, 90 successful cost-ceiling retries, and the two San Diego interval
runs. The complete receipt lists every selected file and its validation status.

Explicit execution retries use the saved feasible baseline cost plus $0.01 as
an objective ceiling. The allowance covers saved-objective precision. This
cannot exclude a globally cost-minimizing design because grid charging expands
the feasible choices. Additional San Diego attempts use saved meter directions
as unfixed starting hints and capacity bounds obtained from auxiliary relaxed
programs under that same cost ceiling. These tighten the search without imposing
a new research capacity limit. One gas-case attempt declares a 900-second budget
including the auxiliary programs. That additional precision attempt was stopped
after separate validated intervals established positive savings for both
households. Each attempt retains its own settings and log.
The starting-hint and auxiliary-capacity-bound experiments are not selected
results. No failed or interrupted candidate is included in the comparison.

Separate San Diego interval runs explicitly allow a **$30/year** objective gap.
They retain all physical, energy-origin, and bill-replay checks. They are not
accepted as $1-converged optimal sizes and do not replace central results.
Their purpose is to determine whether even the conservative savings bound is
positive. This can establish an economic direction without estimating the exact
optimal capacity to the central solve's precision.

The compared cost is annualized solar and storage capital plus electricity.
Other household costs are unchanged within each pair, so this difference also
equals the change in total household cost. This experiment does not revisit
no-solar tariff selection, incentives, equipment prices, or NEM 2 compensation.

## Validation and interpretation

Before adding tests, the existing focused optimizer, NBT, battery annualization,
and solver-control suites passed: **157 tests**. Twelve new analytical tests
passed without changing existing expectations. They cover charging costs and
losses, prohibited grid-origin exports, mixed charging with solar-origin exports,
and declining unprofitable storage for all three utilities.
The combined focused suite passed **169 tests**.

Each full-year case must match saved demand, weather-derived solar availability,
timestamps, and hourly prices. Its bill is replayed with charging purchases.
Separate solar-origin and grid-origin balances must close over the year. Capital
costs use full-precision capacities and the shared 25-year battery accounting.
The expanded choice set cannot worsen the optimum; pairwise comparisons allow
the recorded solver bounds and baseline objective serialization precision.

For each choice set, let $L$ be the certified lower cost bound and $U$ the cost of
the validated feasible design. True optimal savings from enabling grid charging
then lie in

$$
\max(0, L_{\mathrm{off}}-U_{\mathrm{on}})
\leq S \leq U_{\mathrm{off}}-L_{\mathrm{on}}.
$$

The saved intervals include an additional $0.0001 allowance for baseline cost
serialization. A positive lower endpoint establishes lower optimal cost with
grid charging, even if its exact optimum has not converged within $1/year.
If the new candidate never charges from the grid, it is also feasible under
the original rule. Its own cost then replaces the older baseline's upper bound,
tightening the savings ceiling to the new candidate's solver gap, with a
$0.000001 floating-point allowance. Small differences between two saved designs
can reflect solver precision; they are not automatically a grid-charging benefit.

Report actual battery capacities and cost bounds. The $1/year objective tolerance
does not prove that a tiny nonzero capacity is meaningfully better than zero.
Findings describe representative county households, not every household within
a county. Grouping by assigned utility can reveal patterns, but load and weather
also vary; this comparison does not isolate the tariff's causal effect.

The validated San Diego examples have 1.50 kWh of storage for gas/ICE and 2.87 kWh
for electric/EV. Both average about 1.54 complete cycles per day through the
modeled 20–90% charge window. This is greater than the one-cycle-per-day assumption
in the preliminary arithmetic. It helps explain a positive result despite that
screening calculation falling short of annualized battery cost.
The optimized dispatch combines solar and grid charging; the preliminary
calculation considered grid charging alone. The smaller examples can also use
their available capacity more frequently than a full 12.5 kWh unit.
These are feasible continuous sizes, not established commercial product choices
or exact global optima. Gradual capacity loss and augmentation costs remain
excluded; more frequent cycling could make these modest benefits less durable.

## Separate follow-up

The Step 9b module docstring advertises `--allow-grid-charging`, but its CLI parser
does not expose that option and calls `process` with grid charging disabled.
This run uses the working Python interface. Correcting the CLI documentation or
exposing the flag remains outside this comparison's scope.
