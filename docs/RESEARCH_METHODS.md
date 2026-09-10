# Research methods and approach

This is the maintained narrative for the research paper. It explains what the
model measures, how it works, and where its conclusions apply. Detailed formulas
and source references remain in the [methods manifest](methods.yaml).
The narrative uses Markdown with LaTeX equations. A later LaTeX export should
derive from this file, so the prose and equations have one maintained source.

## Implementation status

Reviewed against commit `9212ed1` on September 10, 2026. The shared monthly and
annual NBT accounting introduced in `1634760` remains the implemented billing
method for optimization and reporting. The research author has approved
three simplifications: exclude ACC Plus, prohibit annual net exports, and
settle eligible base credits annually. These changes are **approved but not
yet implemented or validated on research results**. The sections below label
the current and planned accounting separately.

Update this status when integration and validation are complete. Older results
remain results of their recorded model version until regenerated. Use the
[accounting closure note](HOUSEHOLD_COST_RECONCILIATION.md) for worked tariff
examples and the history of the detailed model.
That integration has unit-test and representative-case validation. A full
research rerun remains outstanding. Shared billing does not yet mean that every
capital-cost annualization agrees; the remaining difference is described below.
The approved capital-cost reconciliation retains a 25-year study period and
15-year battery life. It adds a remaining-value credit at year 25 and uses
the same calculation in optimization and reporting. This change is also
**pending implementation and validation**.

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
Free sizing permits zero solar and zero battery capacity. If that is the
least-cost choice, the model does not recommend adoption for that case. A
solar/storage comparison must report both selected capacities: savings with
solar alone do not establish that adding a battery is economical.

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

The current statewide Claims 2 and 3 use `baseline_ice_car`, `full_electric_ev`,
and `full_electric_ev_coopt`. Their gas/vehicle reference retains fixed
solar/storage. These figures compare total scenario costs and fixed versus
optimized equipment; they do not by themselves supply both matched adoption
comparisons needed for $P_{c,e}$. The package-effect equation above defines the
required research comparison, not a result already established by those figures.
The mappings and arithmetic are in the
[publication data collector](../figure_builder/datasets.py).

## Households, energy profiles, and tariffs

The publication data cover 47 counties, with one representative single-family
detached household per county. Household demand uses building end-use profiles
and modeled changes for electric appliances and vehicles. Weather inputs produce
solar output per unit of installed capacity. The analysis uses standardized
8,760-hour profiles, mapped to the modeled billing calendar.
The solar/storage cost and tariff case studies use four counties: Alameda,
Fresno, Los Angeles, and San Diego. Their results have a narrower geographic
scope than the 47-county scenario comparisons.

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
The policy regime and incentive capture are separate assumptions. Full, half,
and no capture apply only to incentives available in the selected regime.
For solar/storage in the modeled post-ITC regime, all three capture cases have
the same net cost because the modeled federal credit is zero. Other appliance
incentives must be evaluated from their own declared inputs.
See the [tariff data documentation](../data/tariffs/README.md) and
[publication builder](../figure_builder/README.md).

## Household costs and system selection

The principal cost measure is equivalent annual cost (EAC): an annual amount that
combines equipment purchases with recurring electricity, gas, and applicable
vehicle operating costs. Solar and storage costs come from the same equipment
cost definitions used in sizing. The standard real discount rate is 7%.
The existing solar/storage objective uses a 25-year horizon and includes battery
replacement after its modeled 15-year life. Appliance costs use their declared
service lives. The [methods manifest](methods.yaml) gives the annualization
formulas and capital-cost sources.

Equipment service life and the investment comparison period are different
assumptions. The approved study period is 25 years, matching the assumed solar
life. This is within the Department of Energy's typical 20–30-year photovoltaic
performance period; it does not imply that all panels fail at year 25.
See [DOE's performance-period guidance](https://www.energy.gov/cmei/femp/life-cycle-photovoltaic-systems-prepare-end-performance-period).

**Remaining annualization difference:** the statewide EAC collector currently
annualizes storage over its 15-year service life and solar over its 25-year
service life. It does not impose a single 15-year study horizon. Both paths
assume a 15-year battery life; only the optimizer includes two battery purchases
within a 25-year comparison period. The implemented coefficients are:

$$
\alpha_{\mathrm{opt}}
= \frac{1 + (1+r)^{-15}}{\sum_{t=1}^{25}(1+r)^{-t}}
\approx 0.116912,
\qquad
\alpha_{\mathrm{report}}
= \frac{r(1+r)^{15}}{(1+r)^{15}-1}
\approx 0.109795,
\quad r=0.07.
$$

Each coefficient converts one dollar of battery capital cost into dollars per
year. At the same capacity and unit price, the optimizer's battery capital-cost
term is about 6.5% higher. This is not a 6.5% difference in total household cost.
The optimizer gives no credit for the replacement battery's remaining life at
the end of year 25. The discrepancy is recorded here, not corrected in code.
See [the annualization functions](../evaluations/eac.py) and
[the reporting collectors](../helpers/plot_scenario_comparison_helper.py).

**Approved reconciliation — pending implementation:** both paths will use
a battery purchase at year 0, replacement at year 15, and a remaining-value
credit at year 25. The replacement then has five of its 15 years remaining.
Its credit is one-third of the modeled replacement cost. Discount that credit
from year 25, subtract it from discounted purchases, and annualize the result:

$$
\alpha_{\mathrm{shared}}
= \frac{1 + (1+r)^{-15} - \tfrac{1}{3}(1+r)^{-25}}
{\sum_{t=1}^{25}(1+r)^{-t}}
\approx 0.111642,
\quad r=0.07.
$$

For a modeled battery purchase cost $C$, annual battery capital cost is
$C\alpha_{\mathrm{shared}}$. Both purchases use the same cost in constant dollars
and the same modeled incentive treatment. For $C=\$10{,}000$, the year-25 credit
is $3,333.33, its present value is $614.16, and annual capital cost is $1,116.42.
These are expected accounting examples, not regenerated research results.

This proportional credit estimates remaining service value, rather than a
future resale price. NIST describes the same remaining-life approach in
[its life-cycle costing manual, section 4.5.3](https://tsapps.nist.gov/publication/get_pdf.cfm?pub_id=934909).
Implementation must test these cash flows independently, retain existing tests,
and investigate failures before updating any expected results. It must also
check that optimizer and reporting costs agree for the same equipment and inputs.

The auxiliary net-present-value diagnostic uses upfront costs and repeated
annual savings, without adding a battery replacement. Its result therefore
has a different cash-flow boundary from the optimizer. The principal research
comparisons above use equivalent annual cost.

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
In Claim 1, current-law market points use full-year runs; the 2025 ITC points
use the reduced chronology. The four-cell NBT/NEM 2 policy comparison uses
the reduced chronology consistently, with full-year checks reported separately.

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
that year. PG&E's modeled year-end offsets can cover earlier eligible payments
and carry remaining base credits. SCE applies such offsets and expires the
remainder. SDG&E retains the no-backward-offset and expiry convention documented
in the accounting closure note. These are study treatments; consistency checks
do not independently verify every utility interpretation.

A competitive positive-surplus candidate with a missing required
adjustment rate stops for the source; the model does not invent a rate.
When an adjustment rate is missing, the optimizer may omit its nonnegative
charge to form an optimistic cost bound. It accepts that solution only if
annual net surplus is zero, when the omitted charge is also zero. It then
replays the flows through numeric accounting and rejects bill discrepancies
above $0.001. The current NBT solver is SCIP; NEM 2 uses HiGHS by default.

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
| County equipment costs include imputed values | The heat-pump cost inputs use the median of available counties where source data are absent: three counties for space heating and nine for water heating. These are not local price observations. | Identify these counties in cost interpretation and refresh their inputs when local data become available. |
| Battery annualization differs between sizing and statewide EAC reporting | For the same battery, the current optimizer uses a capital-cost term about 6.5% higher. Shared electricity billing does not resolve this difference. | Implement the approved 25-year calculation with replacement and remaining value in both paths, then check affected battery-cost comparisons. |
| Approved battery remaining-value and replacement-cost assumptions | The pending method values five remaining years at one-third of replacement cost. It assumes unchanged real purchase costs and incentive treatment. Future prices, incentives, and resale values can differ; the direction of error is uncertain. | State these assumptions with the results. Use a focused sensitivity if they could change an adoption conclusion. |
| The 2025 incentive sensitivity simplifies eligibility | Its continuous battery sizing uses an ITC-adjusted unit price without a separate 3 kWh eligibility constraint. The appliance policy registry also records separate caps for each appliance under the 25C heat-pump credit, in place of a combined household cap. Affected 2025 cases can overstate incentives. | Check sub-3-kWh battery conclusions and whole-household cases using both heating credits if these support a published claim. These issues do not change zero-credit post-ITC inputs. |
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
