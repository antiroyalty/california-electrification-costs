# Research methods and approach

This is the maintained narrative for the research paper. It explains what the
model measures, how it works, and where its conclusions apply. Detailed formulas
and source references remain in the [methods manifest](methods.yaml).
The narrative uses Markdown with LaTeX equations. A later LaTeX export should
derive from this file, so the prose and equations have one maintained source.

## Implementation status

As of September 10, 2026, commit `1634760` uses shared monthly and annual NBT
accounting for optimization and reporting. The research author has approved
three simplifications: exclude ACC Plus, prohibit annual net exports, and
settle eligible base credits annually. These changes are **approved but not
yet implemented or validated on research results**. The sections below label
the current and planned accounting separately.

Update this status when integration and validation are complete. Older results
remain results of their recorded model version until regenerated. Use the
[accounting closure note](HOUSEHOLD_COST_RECONCILIATION.md) for worked tariff
examples and the history of the detailed model.

## Research questions and comparison definitions

The research asks whether solar panels and battery storage reduce costs for a
representative household in each modeled California county under NEM 3. It
also asks whether household electrification increases those adoption savings.
NEM 3 is the common name for California's Net Billing Tariff (NBT).

For a given electrification scenario, define solar/storage adoption savings as
the annual household cost without solar/storage minus the cost with the selected
solar/storage system. Include equipment costs in both sides where applicable.
Positive savings mean that adoption reduces modeled household cost.

$$
S_{c,e} = C^{0}_{c,e} - C^{*}_{c,e}.
$$

Here, $c$ identifies the county and $e$ its electrification scenario.
$C^{0}_{c,e}$ is annual household cost without solar/storage, and
$C^{*}_{c,e}$ includes the economically selected solar/storage system.
$S_{c,e}$ is adoption savings, in dollars per year.

Define the "package deal" effect as adoption savings after electrification
minus adoption savings before electrification. A positive difference means
electrification makes solar/storage adoption more economical. Compare matched
households with the same tariff, equipment-cost assumptions, and sizing method.
This definition requires both adoption comparisons. A chart of total savings
from electrification alone does not establish this effect.

$$
P_{c,e} = S_{c,e} - S_{c,e_0}.
$$

The reference electrification scenario is $e_0$. A positive $P_{c,e}$ indicates
a package effect, measured in additional adoption savings per year.

The scenario's appliance and vehicle choices are specified inputs. The optimizer
selects solar and battery capacities and operation within that scenario. It does
not decide which appliances a household should electrify. Scenario definitions
are maintained in [scenarios.py](../scenarios.py).

## Households, energy profiles, and tariffs

The publication data cover 47 counties, with one representative single-family
detached household per county. Household demand uses building end-use profiles
and modeled changes for electric appliances and vehicles. Weather inputs produce
solar output per unit of installed capacity. The analysis uses standardized
8,760-hour profiles, mapped to the modeled billing calendar.

A county selects one representative utility: PG&E, SCE, or SDG&E. The current
study uses bundled electricity service, standard non-equity customer assumptions,
a 2026 NBT application vintage, and a retail tariff snapshot dated August 9, 2026.
Hourly import prices come from the selected utility plan. Base export prices
vary by utility, month, day type, and hour. Rates are applied to hourly energy
before dollar totals are aggregated; the proposed annual accounting preserves
these price differences.

The NEM 2 comparison uses the same 2026 retail-rate snapshot. It isolates export
compensation rules under those rates. It is not a reconstruction of historical
NEM 2 bills. Federal equipment incentives form a separate comparison axis:
the modeled post-ITC case and a sensitivity with the 2025 30% investment tax
credit. Source identities and case definitions are recorded with each run.
See the [tariff data documentation](../data/tariffs/README.md) and
[publication builder](../figure_builder/README.md).

## Household costs and system selection

The principal cost measure is equivalent annual cost: an annual amount that
combines equipment purchases with recurring electricity, gas, and applicable
vehicle operating costs. Solar and storage costs come from the same equipment
cost definitions used in sizing. The standard real discount rate is 7%.
The solar/storage objective uses a 25-year horizon and includes battery
replacement after its modeled 15-year life. Appliance costs use their declared
service lives. The [methods manifest](methods.yaml) gives the annualization
formulas and capital-cost sources.

Within an electrification scenario, the optimizer minimizes annualized solar
cost plus annualized battery cost plus the electricity bill and any specified
battery-throughput cost. Gas and appliance costs are fixed for that sizing
decision and are included in the complete household comparison.

Each hour must satisfy electricity demand and conserve energy. Battery charge
levels and power flows obey capacity and efficiency limits. The central
co-optimized cases prohibit grid charging and allow battery exports. The meter
cannot import and export simultaneously. The model can curtail unused solar.
Standard optimized storage is limited to 40 kWh, with explicit overrides for
declared sensitivities. Current PV-generation bounds are 150% of annual load
under NBT and 100% under the NEM 2 comparison.

Full-year runs preserve chronological storage operation. Large sensitivity
sweeps also use a reduced profile with 24 representative hours for each of
12 months. These 288 hours are weighted by days in the month, with a daily
battery cycle for each representative month. This approximation loses
day-to-day variation and prolonged sequences of weather and demand. Every
comparison must identify its resolution.

Fixed-size scenarios use prescribed equipment sizes and dispatch rules.
Their savings measure that design. They must be distinguished from results
where the model chooses the least-cost solar/storage design.

## Current detailed electricity accounting

The implemented NBT optimizer and bill reporter use the same accounting
equations. Hourly flows produce monthly charges and credits. Base credits can
pay only eligible energy charges. PG&E and SDG&E retain separate generation
and delivery pools; bundled SCE combines them. Non-bypassable charges are
charges that base export credits cannot offset. Fixed charges also remain
outside these pools.

ACC Plus is a separate export bonus. The current model applies it after base
credits, with its own balance and allocation rules. Annual settlement applies
net-surplus adjustments and compensation where required, then the study's
utility-specific treatment of remaining credits. The modeled year starts with
zero credit balances. Remaining balances receive no additional value beyond
that year. A competitive positive-surplus candidate with a missing required
adjustment rate stops for the source; the model does not invent a rate.

## Approved simplified electricity accounting — pending integration

The three changes below define one annual research model. Both system selection
and reported costs must use this same model after integration.

1. **Exclude ACC Plus.** Retain hourly base export credits. This removes the
   separate bonus balance and proportional allocation. It deliberately omits
   a benefit available to eligible households; it does not mean the bonus is
   absent from their utility tariffs.
2. **Require annual exported energy to be no greater than annual imported
   energy.** Hourly exports remain allowed. This is a research constraint,
   separate from the existing PV-size limit. It excludes annual net-exporting
   designs, removing their net-surplus payments and credit adjustments from
   the scoped calculation. Fixed-design comparisons must respect the same
   domain or be explicitly identified as outside it.
3. **Settle eligible base credits annually within each utility's credit pools.**
   Add hourly dollar charges and credits over the year, then offset each pool's
   charges up to the amount owed. Preserve SCE's combined pool and PG&E/SDG&E's
   component restrictions. Excess credits have no value beyond this modeled year.

The annual energy constraint is:

$$
\sum_{h \in \mathcal H} w_h x_h \leq
\sum_{h \in \mathcal H} w_h i_h.
$$

Here, $x_h$ and $i_h$ are exported and imported energy in interval $h$, in kWh.
The set $\mathcal H$ contains the modeled hourly intervals. The weight $w_h$
is one for full-year hours or the number of represented days for a monthly
representative hour. Both sides therefore measure annual energy in kWh.

The resulting bill is:

$$
B = F + N + \sum_{p \in \mathcal P} \max(C_p - E_p, 0).
$$

Here, $B$ is the annual electricity bill, $F$ is annual fixed charges, and $N$
is annual non-bypassable charges. The set $\mathcal P$ contains the utility's
eligible credit pools. $C_p$ is the annual eligible import charge in pool $p$,
and $E_p$ is the annual base export credit in that pool. All amounts are dollars.

$$
C_p = \sum_{h \in \mathcal H} w_h i_h r^{\mathrm{imp}}_{p,h},
\qquad
E_p = \sum_{h \in \mathcal H} w_h x_h r^{\mathrm{exp}}_{p,h}.
$$

The rates $r^{\mathrm{imp}}_{p,h}$ and $r^{\mathrm{exp}}_{p,h}$ are the eligible
import and base export prices for pool $p$ and interval $h$, in dollars per kWh.
Annual dollar settlement therefore preserves hourly prices and energy flows.

For a teaching example, suppose annual eligible charges are $20 generation and
$40 delivery, and credits are $30 generation and $5 delivery. Fixed charges are
$25 and non-bypassable charges are $4. The combined SCE pool gives a $54 bill:
`25 + 4 + max(60 - 35, 0)`. Separate pools give $64:
`25 + 4 + max(20 - 30, 0) + max(40 - 5, 0)`. These are illustrative amounts.

With zero opening balances, no bonus, no annual net surplus, and no value for
ending balances, this annual formula matches the current PG&E and SCE
annual-cost equations. Their modeled year-end offsets already permit remaining
base credits to cover earlier eligible payments. It changes the retained SDG&E
convention, which expires unused credits without those backward offsets.

These simplifications remove nonlinear financial allocation from the objective.
Physical meter-direction decisions can still require a mixed-integer linear
model: some variables represent discrete operating choices. Integration should
remove the obsolete financial solver machinery rather than maintain two central
research accounting models.

## Known limitations, constraints, and potential future improvements

Future improvements below are options, not a new set of publication prerequisites.
Prioritize a check when the limitation could change a stated conclusion.

| Limitation or constraint | Effect on interpretation | Potential future improvement |
|---|---|---|
| One representative household and utility per county; 47 counties covered | Results do not describe household variation or every utility customer. County summaries are unweighted, so they are not statewide adoption estimates. | Sample household types and service territories; report population-weighted results when appropriate. |
| One standardized demand/weather year and one tariff snapshot | Results are annualized scenarios, not forecasts of actual lifetime bills or a historical before/after study. | Examine additional weather years, demand profiles, and explicitly specified tariff trajectories. |
| Known profiles and prices throughout an optimization run | Dispatch assumes advance knowledge of the modeled year. Real controllers face forecast errors, which can reduce achievable savings. | Compare a controller with limited forecasts on the same cases. |
| Reduced 12 × 24 sensitivity chronology | Averaging can change cycling, usable credits, and optimal capacities. Mixed-resolution comparisons cannot isolate a policy effect by themselves. | Use full-year checks for findings near a threshold or sensitive to chronology. |
| Declared equipment costs, lifetimes, and incentive cases | These are sourced modeling inputs, not a new survey of prices available to every household. | Refresh cost benchmarks or report a focused sensitivity when cost uncertainty affects a claim. |
| Battery augmentation costs and gradual capacity loss omitted centrally | Storage is treated more favorably than a model that charges for maintaining capacity. Round-trip efficiency losses and the declared replacement remain included. | Add an explicit degradation or augmentation-cost sensitivity if needed. |
| Equipment-size bounds, specified charging/export rules, and fixed-design comparisons | An optimum applies within its declared feasible choices. A fixed-design result is not an unrestricted economic optimum. | Report binding constraints and test an expanded domain for an affected claim. |
| ACC Plus omitted in the approved model | Savings for eligible households can be understated. For a fixed dispatch, omitted benefit is bounded by exported kWh times the applicable bonus rate; this alone does not establish unchanged optimal sizing. | Bound its effect on the published comparisons before considering a separate sensitivity. |
| Annual net-export cap in the approved model | Profitable net-exporting designs are excluded. A binding cap can link permitted exports to added electrification load and affect the apparent package effect. | Identify binding cases and compare affected conclusions with the detailed reference model. |
| Annual credit timing in the approved model | SDG&E savings may be overstated relative to the current no-backward-offset convention. A late credit could offset an early charge in the annual model. | Bound the difference using unused eligible credits and earlier eligible payments; inspect affected San Diego cases. |
| No opening credits or value for balances after the modeled year | Results omit benefits from a household's existing bank or future use of unused credits. | Use specified opening balances or a bounded future-use sensitivity for a question that requires them. |
| Financial operating value is the objective | The model assigns no monetary value to outage protection, convenience, or household preferences. It therefore does not explain every adoption decision. | Study resilience or preferences separately when such benefits become part of the research question. |

## Verification and publication boundaries

Use small, independently calculated examples to establish expected accounting
before changing implementation. Check zero credits, excess credits, separate
pools, and values around the annual export cap. Agreement between optimizer
and reporter establishes consistency; it does not independently establish that
the accounting assumptions are correct.

Preserve existing tests and examine failures as possible regressions. Document
the evidence for changing an old expectation. For the approved simplifications,
compare relevant publication cases against the detailed reference model. Focus
on adoption conclusions, cap effects, and the SDG&E timing difference. Expand
that comparison only when a bound or observed difference can affect a claim.

Published results must identify their model commit, inputs, scenario, tariff,
capital-cost assumptions, and temporal resolution. Rebuild affected results
after model changes; cached outputs do not become current when code is edited.
The [publication workflow](../figure_builder/README.md) describes forced
rebuilds and result receipts. Run-specific checks and outcomes belong in those
receipts or review notes, while this document records the method and its limits.
