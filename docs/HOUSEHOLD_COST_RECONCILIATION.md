# Household-cost accounting: publication closure note

## Decision and scope

Finish the existing paper with defensible accounting and a clear methods section.
The research folder's README identifies thesis, figures, and prose as the
remaining work. This note supports that work; it does not establish a new
seven-question research agenda or commit the project to a solver replacement.

The research asks whether solar/storage saves money within each electrification
scenario and whether electrification increases those adoption savings. Use
consistent costs when selecting systems and reporting these comparisons.

Retain the study's existing assumptions unless a demonstrated discrepancy or
a conservative sensitivity bound could change a reported claim. Correct known
billing defects. Prefer a coherent, isolated accounting model when code changes
are needed, with conceptual clarity guiding the design. A larger redesign is
not a prerequisite for completing every accounting check.

Source conclusions, retained conventions, and arithmetic checks below have
different evidentiary status. This note does not independently certify every
utility rule. The implementation status appears at the end.

## Disposition of the former seven prerequisites

| Item | Decision for this paper |
|---|---|
| 1. SCE bundled credit eligibility | Adjudicated below: use combined eligible energy charges. Check the effect of the current component restriction on the affected results. |
| 2. SDG&E credits against earlier charges | Retain the implemented no-backward-offset convention for the closure assessment. Bound the alternative by eligible remaining credits and prior payments. Reopen only if that bound can affect a claim. This is not independent confirmation of the tariff interpretation. |
| 3. ACC Plus allocation | Retain the implemented proportional allocation across remaining energy components. State it as an accounting convention and bound its effect by the affected bonus dollars. Do not start a separate allocation model. |
| 4. Billing calendar | Retain the modeled calendar year. The configured true-up month selects settlement rates; it does not establish an actual household billing anniversary. State that approximation. |
| 5. Horizon and ending balances | Retain representative-year billing and the existing 25-year equipment annualization. Report residual base/bonus balances separately from current bill savings; use zero additional terminal value centrally and face value as a sensitivity bound. Do not introduce future-tariff forecasts. |
| 6. Missing PG&E surplus rates | Existing code requires these only for positive annual net exports. They are unnecessary for the net-import examples. Preserve the explicit failure for affected exporters; obtain a rate only when a reported or competitive candidate requires it. |
| 7. Verification of existing billing | This is a bounded validation task, not a new research question. Compare the relevant worked answers with the current calculator, and record differences before implementing corrections. |

Items 2-6 are closed as prerequisites to starting that bounded check. They are
not declarations that every utility rule is validated or every effect is small.

## SCE adjudication: Example 5

Use bundled service. Eligible import charges are $20 generation and $40
delivery. NBCs are $4 and the fixed charge is $25. Export credits are $30
generation-related plus $5 delivery-related. Exclude the bonus for this check.

**Expected SCE payment: $54, with no remaining base credit.**

`($20 + $40 - $35) + $4 + $25 = $54`.

The basis is [SCE Schedule NBT](https://www.sce.com/sites/default/files/custom-files/PDF_Files/ELECTRIC_SCHEDULES_NBT.pdf):
Rates 3.a.i on sheet 4 includes delivery and generation in bundled Energy
Charges; Rates 3.a.ii on sheets 5-6 defines bundled export credits; Special
Condition 4.b on sheet 22 applies those credits to the defined Energy Charges.
The separate-provider restrictions in Special Condition 4.f concern unbundled
service. The decomposition of export prices alone does not impose separate
credit-use limits on bundled customers.

This source-based adjudication replaces the earlier open interpretation.
The pre-integration calculator applied separate component limits to every utility.
That gave $64 and a $10 generation bank in this example. PG&E explicitly uses
those component restrictions, so its $64 outcome remains appropriate here.
Assess SCE monthly application and settlement consistently when checking the
effect. The $10 monthly difference is not necessarily a $10 annual difference.

## Compact independent examples

### Teaching inputs

Examples 1-3 use PG&E bundled service, a 2026 non-equity vintage, and zero
opening balances unless specified. Each of twelve months imports 200 kWh and
exports 100 kWh in separate intervals. Annual exports are below imports.

Monthly eligible charges are $20 generation and $40 delivery, plus $4 NBCs and
a $25 fixed charge. Delivery export credit is $5 and ACC Plus is $0.88
(100 kWh x the PG&E 2026 bonus of $0.00880/kWh). All other prices and charges
are teaching inputs, not predicted bills. Repeat them in Year 2 only to
isolate credit carryover.

[PG&E Schedule NBT](https://www.pge.com/tariffs/assets/pdf/tariffbook/ELEC_SCHEDS_NBT.pdf),
Special Conditions 2.d-h, sheets 17-19, supports component restrictions,
eligible annual offsets, and continuing-service carryover. The bonus table
is on sheet 11. The archived tariff hashes were checked against
`data/tariffs/true_up_source_manifest.json`; PG&E and SCE live sources were
also checked on September 9, 2026.

| Example | Calculation | Expected result |
|---|---|---|
| 1. All credits used | Earn $10 generation credit monthly. Pay $20 - $10 + $40 - $5 + $4 + $25 - $0.88. | $73.12/month; $877.44/year; no ending credit. |
| 2. Unused generation credit | Earn $20/month in months 1-11 and $30 in month 12. Apply $240 of $250 earned. | $63.12/month; $757.44/year; $10 generation credit survives settlement. Counting all earned credits would instead give $747.44. |
| 3. Next-year use | Carry the $10 from Example 2. Earn $20/month in months 13-23 and $10 in month 24. | Month 24 still costs $63.12. Year 2 costs $757.44, versus $767.44 without the opening bank. Ending bank is zero. |
| 4. Carry versus expiry | Exclude bonus. Year 1 earns $25 generation and $45 delivery monthly against $20/$40 eligible charges. Year 2 earns $15/$35 monthly. | Year 1 pays $348 and leaves $120 before settlement. PG&E carries it and pays $348 in Year 2. SCE/SDG&E forfeit it and pay $468 in Year 2. Two-year totals: $696 versus $816. |
| 5. SCE bundled eligibility | The source adjudication above applies $35 against $60 eligible charges. | $54/month for SCE, versus $64 with PG&E's component restrictions. |
| 6. Separate bonus bank | Base credits cover eligible energy. Apply $35 available bonus to $29 NBC/fixed charges, then carry the remainder to another $29 bill. | Pay $0, carry $6 bonus, then pay $23 with no new bonus. |
| 7. Net-surplus settlement | Separate synthetic annual case: imports 100 kWh, exports 110 kWh, unused base credit $1, no prior eligible payments. Adjustment $0.06/kWh; NSC $0.03/kWh. | Debit $0.60; $0.40 base credit remains and is forfeited under SCE/SDG&E; NSC entitlement is $0.30. NSC is not a cash-out of the original $1 bank. |

Example 3 totals $1,514.88 over two years under both accounting methods because
all earned credits are eventually used. A known $10 benefit one year later is
worth $9.34579 at 7%; the timing difference from immediate face value is $0.65421.
This does not make an unknown $10 balance worth $9.35.

For Example 4, no eligible energy charges were paid during Year 1, so backward
offsets cannot affect its answer. SCE's residual forfeiture follows Special
Condition 4.e, sheet 23. SDG&E's follows Special Condition 3.f, sheet 8, in the
[identified archive](../data/tariffs/sources/nbt_rules/sdge/2026-08-10/ELECTRIC_SCHEDULE_NBT.pdf).
Its live tariff endpoint was unavailable in the earlier source check.
Example 7 uses synthetic rates and does not supply missing PG&E tariff data.
A settlement credit, an NSC entitlement, and an actual cash refund remain
distinct ledger items.

## Sensitivity bounds and stopping rule

Use bounds on saved results before adding simulations or research dimensions.

- **Backward annual offsets:** the largest additional offset is bounded by
  `min(remaining generation credit, prior eligible generation payments)` plus
  the corresponding delivery term. This is zero in Examples 2 and 4.
- **Bonus allocation:** changing allocation can affect settlement by at most
  the bonus dollars allocated differently to eligible charges. Examples 1-3
  have no competing residual generation/delivery charges after base credits,
  so the proportional split is immaterial there. Example 6 also avoids it.
- **Future use of an existing bank:** its additional discounted bill benefit
  lies between zero and its face value, assuming no interest on credits and a
  nonnegative discount rate. The interval for Example 2's $10 bank is $0-$10;
  only Example 3's specified one-year timing difference is below $1.
- **Surplus-rate uncertainty:** for surplus energy q, the adjustment difference
  is bounded by q times the supported adjustment-rate range. It is zero when
  q is zero. Do not invent a rate range for a positive-export case.
- **Reported comparisons:** propagate the bounds through the claim's arithmetic.
  For the difference in adoption savings between two electrification scenarios,
  conservatively add the uncertainties of its four bill terms. Include bounds
  for competing designs when assessing whether their ranking could change.

Close an issue when its bound cannot change the stated conclusion or reported
precision. Record the convention and bound in the methods or limitations.
If a bound overlaps an adoption threshold or a relevant ranking, inspect that
case. A bound from one selected design does not prove global optimality.
Do not describe these effects as sub-dollar across the research without
checking the affected outputs. No statewide sensitivity result is claimed here.

## Test baseline and regression review

Before implementation changes, run the existing test suite and record the
commit, command, passes, failures, and skips. Investigate baseline failures so
later failures can be distinguished from pre-existing problems. The billing
integration baseline at `557c589` passed 642 tests, with 3 skipped, using
`python -m pytest -q tests/ figure_builder/tests/`. The test environment uses
Python 3.11 and includes the declared `pdfplumber` dependency.

Add new tests for corrected behavior using the independent worked examples and
tariff conclusions. Where applicable, confirm that these tests expose the old
defect before the correction. Include opening balances and future carryover.

Examine every existing test that fails after a change. Determine whether the
failure reveals a regression, an incorrect old expectation, or an input or
environment problem. Do not delete, weaken, or overwrite tests merely because
the new implementation produces different outputs. Change an old expectation
only when independent evidence establishes why it is wrong; document that
evidence, the old and corrected behavior, and preserve its relevant coverage
for review. New outputs alone are not evidence of correctness.

Run the focused tests during development and the required suite before each
commit review. Report unresolved failures explicitly; do not treat the change
as validated until they have been explained and resolved.

## Implementation and publication consequence

Keep one accounting definition for system selection and reporting. An isolated
accounting module remains a useful design direction. The earlier proposal to
make standalone billing solver-dependent is an option, not a commitment.
Use conceptual clarity and removal of duplicate financial rules to evaluate
any necessary refactor; the size of the patch is not the design criterion.

The immediate output is the SCE conclusion, relevant current-calculator checks,
and a short statement of which published costs or rankings they affect.
Existing code behavior is evidence of implementation, not tariff correctness.
Agreement between optimizer and reporting establishes consistency; the
independent examples check the underlying accounting.

This note does not require a new billing platform, actual-customer calibration,
or a multi-year forecast before writing the paper. Continue thesis, figures,
and prose alongside the bounded correction. Implementation follows the
repository's review and commit protocol.

## Billing integration review

Monthly billing now calls `accounting.settle_month`. The true-up adapter keeps
energy and source-rate validation, then calls `accounting.settle_year`. The
old credit-application calculations have been removed from both adapters.
Detailed ledger values now live in `.accounting`. SCE uses a combined balance;
Step 12 logs total prior eligible energy payments. Annual cost access is unchanged.
Billing accepts explicit opening balances and exposes closing balances for
subsequent years. Unused-credit diagnostics include any supplied opening bank.

One existing numeric expectation required correction: the SCE settlement test
used a $47 credit and $5 forfeiture. Its $82 balance covers the $60 adjustment
and all $20 of prior eligible payments, leaving $2 to forfeit. Including $30
NSC gives a $50 credit. This follows the pooling adjudication above. Other
existing numeric expectations were retained; account fields and input types
were migrated. The new monthly SCE tests failed on the old calculator first.

A new regression test exposed roundoff at zero eligible charges. Subtracting
monthly totals could produce a tiny negative and trigger strict validation.
Subtracting the non-offsettable rate before aggregation preserves exact zero.

Saved profiles for Alameda, Orange, and San Diego were compared before and
after integration, for `baseline_coopt` and full home electrification
(`heat_pump_and_induction_stove_and_water_heating_coopt`). All six annual bills
agree within $0.000000001. These profiles have no unused credits; this check
does not establish the statewide effect or whether design rankings change.
Step 12 also wrote and verified three county result files in a temporary directory.
The final full suite passed 663 tests, with 3 skipped, using the baseline command.
The focused accounting, billing, and true-up suites passed all 129 tests.
Optimizer integration and any necessary result reruns remain a later review unit.

## Optimizer integration review

The baseline at `a0fccbf` passed 698 tests, with 3 skipped. This includes the
shared-equation tests committed after billing integration.

Step 9b now minimizes annualized equipment cost plus the shared NBT bill and
any specified degradation cost. Hourly imports and exports produce monthly
charges and credits. The same accounting equations apply those credits in
optimization and reporting. The physical constraints remain defined once in
PuLP. A SCIP adapter adds the accounting objective, including the retained
proportional bonus allocation. NEM 2 keeps its existing HiGHS formulation.

The study starts with zero balances and assigns no terminal value to remaining
banks. The result itemizes earned credits, payments, expiry, and carryover.
`import_cost` now includes NBT fixed charges. `export_credit` is the net bill
reduction after annual settlement; earned credit remains a separate diagnostic.
The optimizer replays its normalized flows through numeric accounting and
rejects a bill discrepancy above $0.001.

A missing surplus-adjustment rate remains explicit. Omitting this nonnegative
adjustment gives a lower bound: an adjustment can only increase payment or
reduce the credit available for prior-payment offsets. A no-surplus solution
has the same cost with any such rate. The optimizer can therefore certify that
solution within its relative optimality tolerance of 0.000001. A competitive
positive-surplus solution stops the run and requires the missing source rate.
The bound is never reported as a numeric bill for a positive-surplus case.

Integration tests show both smaller PV selection after credit saturation and
battery dispatch changes when export credits cannot pay the remaining bill.
They also check independent billing replay, true-up, weighted representative
days, and missing-rate failure. One plotting fixture needed a complete tariff;
its title assertion remains intact. Metadata expectations now identify SCIP
for NBT and include annual settlement. Existing numeric billing expectations
remain unchanged. Statewide result reruns remain outside this review unit.

The full 8,760-hour Orange County `baseline_coopt` validation selected
1.207884 kW PV and zero battery capacity. Its annual bill was $1,722.770855;
independent reporting agreed within $0.001. The run took 407 seconds and two
meter-constraint rounds. Representative-day runs also completed for Alameda
and San Diego, in 71 and 5 seconds respectively. These validate integration;
they do not establish statewide changes or a runtime bound for every scenario.
The Step 9b writer also passed a no-equipment boundary run in a temporary
directory, including the new payment and credit-balance columns.

The final command `python -m pytest -q tests/ figure_builder/tests/` passed
723 tests, with the same 3 skips. `git diff --check` passed. The complete
`cost_service.py` pipeline and statewide reruns were not run in this unit.
