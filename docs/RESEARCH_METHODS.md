# Research methods and approach

This is the maintained narrative for the research paper. It explains what the
model measures, how it works, and where its conclusions apply. Detailed formulas
and source references remain in the [methods manifest](methods.yaml).
The narrative uses Markdown with LaTeX equations. A later LaTeX export should
derive from this file, so the prose and equations have one maintained source.

## Implementation status

Updated on September 11, 2026. **All three accounting simplifications are
implemented:** omit ACC Plus, require annual exports no greater than imports,
and settle base credits annually within each utility's eligible pools.
Optimization and reporting use one annual cost equation. Unused credits have
no value outside the modeled year. This is a research cost model, not a
reconstruction of monthly utility statements.

Battery capital accounting uses a 25-year study period and 15-year battery life.
Optimization and EAC reporting share replacement costs and the remaining-value
credit at year 25. The September 11 core rerun at `8a98b96` covers 47 counties,
the three paper scenarios, and the supporting baseline at full-year resolution.
The [results and claim assessment](research_logs/2026-09-11.md) records its
findings and validation. Other electrification scenarios, ITC and battery-price
sensitivities, and NEM 2 comparisons retain their earlier model versions.

The [accounting closure note](HOUSEHOLD_COST_RECONCILIATION.md) preserves the
worked tariff examples and the earlier model's history. Frozen examples compare
old and new accounting without replacing old expected values. The annual model
preserves the PG&E/SCE examples and deliberately changes the SDG&E late-credit
example from $148 to $138. Matched 288-hour Alameda checks preserve both the
free-sizing result and fixed 10 kWh result, with optimizer/reporting agreement.
The core rerun completed sizing, billing, capital reporting, and county
diagnostics. All 141 paper scenario/county annual bills reconciled within
$0.001; the strict statewide validator passed 49 checks. Auxiliary payback
outputs remain outside the validated EAC conclusions because their optimized
EV comparison selects a different baseline.

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
The solar/storage objective and EAC reporting use a 25-year horizon. Battery costs
include replacement after 15 years and a credit for remaining life at study end.
Appliance costs use their declared service lives.
The [methods manifest](methods.yaml) gives the annualization
formulas and capital-cost sources.

Equipment service life and the investment comparison period are different
assumptions. The approved study period is 25 years, matching the assumed solar
life. This is within the Department of Energy's typical 20–30-year photovoltaic
performance period; it does not imply that all panels fail at year 25.
See [DOE's performance-period guidance](https://www.energy.gov/cmei/femp/life-cycle-photovoltaic-systems-prepare-end-performance-period).

Both paths count a battery purchase at year 0, replacement at year 15, and
a remaining-value credit at year 25. The replacement then has five of its
15 years remaining.
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
The same coefficient is used in county EAC cost charts and the SAM comparison's
capital-cost scoring. The shared function also handles other declared lifetimes:
it counts purchases strictly before study end and credits the last battery's
remaining fraction. It accepts finite, nonnegative discount rates and finite,
positive lifetimes and study periods. A zero discount rate gives $1/n$ per year,
where $n$ is battery life in years.
See [the annualization functions](../evaluations/eac.py) and
[the reporting collectors](../helpers/plot_scenario_comparison_helper.py).

Independent cash-flow tests cover the numerical example, replacement boundaries,
zero interest, multiple replacements, incentive cases, and optimizer/reporting
agreement. Existing tests remain in place to detect regressions. See
[the battery accounting tests](../tests/battery_annualization_test.py).

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

The default numerical stopping rule accepts a physically valid design within
**$1/year of the model optimum**. Each intermediate solver model supplies a
lower cost bound, $L$. The final design's replayed annual cost, $C$, must satisfy
$0 \leq C-L \leq \epsilon$, where the default $\epsilon$ is $1/year.
We retain the strongest bound across meter-constraint rounds. Numerical
comparisons allow $10^{-6}$ dollars for floating-point roundoff. This cost
tolerance does not relax energy conservation, meter direction, or billing checks.
The certificate uses full-precision capacities. Rounding in saved capacity
tables can add the separate reporting difference documented below.

HiGHS remains the default backend and requires SciPy 1.16.1 or later, the
validated minimum version. The earlier SciPy 1.11.4 wrapper drops the
absolute-gap setting. CBC can be selected explicitly. Each county
sizing/dispatch problem has a default 300-second budget shared across
model construction and all solver rounds. Data preparation and optional
sensitivity cases are separate; each sensitivity solve has its own budget.
Solver limits are cooperative, so finalization and validation can add overhead.
A timeout is accepted only if the available candidate passes the cost bound
and all physical checks. Otherwise the run stops with an error.

`Config.coopt_solver` contains these settings as `SolverOptions`. Step 9b also
exposes `--solver-backend`, `--solver-cost-gap-usd`, and
`--solver-time-limit-seconds`. County outputs record the settings, elapsed time,
cost gap, and lower bound. A `coopt_solver_<county>.json` file records each round.
CBC's printed bounds are adjusted downward for their displayed rounding.
Changing a backend is an explicit run choice; there is no automatic retry.

The $1 bound concerns annual cost, not identical equipment capacities. Nearly
equal-cost systems can have different sizes. A claim about a battery adoption
threshold therefore needs a tighter tolerance or a separate comparison around
that threshold. The validated results at `8a98b96` retain their original solver
settings; this update does not regenerate the publication results.

An isolated full-year check of this stopping rule retained the saved capacities
and annual objectives for San Diego, Alameda, and Los Angeles. Their solves
took 93, 154, and 144 seconds; all bills replayed within $0.001. See the
[local benchmark record](../analysis_results/solver_controls_3ea830b/README.md).
These timings combine a runtime update with the new stopping tolerance.

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

## Annual electricity accounting

The optimizer and reporter aggregate hourly charges and base export credits
into annual eligible pools. SCE combines generation and delivery. PG&E and
SDG&E keep separate generation and delivery pools. Base credits cannot pay
fixed charges or non-bypassable charges, which are charges protected from these
credits. Credits apply only up to the annual amount owed in each pool.

The `tariffs.nbt` module owns the annual tariff terms, credit settlement, and
numeric bill ledger. The optimizer supplies solver expressions to this domain
calculation. It does not define a separate billing formula.

The research model makes three explicit simplifications:

1. **Exclude ACC Plus.** Hourly base export credits remain included. The model
   has no bonus balance or feature switch. Archived bonus rates document the
   excluded benefit; the omission does not change household tariff eligibility.
2. **Require annual exports no greater than imports.** Hourly exports remain
   allowed. This constraint excludes annual net-exporting designs and removes
   their surplus payments and credit adjustments. Fixed designs obey the same
   cap. Profiles above it must be regenerated before reporting.
3. **Settle base credits annually within eligible pools.** Credits earned late
   in the year can offset earlier eligible charges. There are no monthly banks,
   opening balances, or credit transfers between modeled years. Unused credits
   have no future value. This timing approximation can favor SDG&E relative to
   the former no-backward-offset convention.

The annual energy constraint is:

$$
\sum_{h \in \mathcal H} w_h x_h \leq
\sum_{h \in \mathcal H} w_h i_h.
$$

Here, $x_h$ and $i_h$ are exported and imported energy in interval $h$, in kWh.
The set $\mathcal H$ contains the modeled hourly intervals. The weight $w_h$
is one for full-year hours or the number of represented days for a monthly
representative hour. Both sides therefore measure annual energy in kWh.

Exports include both direct solar exports and battery exports. Imports include
both household supply and any permitted grid charging. The existing 150%-of-load
limit on available NBT solar generation remains separate. A fixed array can
meet the export cap by curtailing generation, which means leaving some available
solar energy unused. The model does not reduce its installed capacity or cost.

The solver imposes the inequality directly. Numeric reporting and validation
treat an excess of at most $10^{-6}$ kWh as numerical equality.
This is one milliwatt-hour per modeled year. It prevents rounding noise from
rejecting a dispatch at the cap. Larger excesses fail the
research checks; validation does not alter the recorded meter flows.

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

The optimizer represents each positive part with a remaining-charge variable
$z_p$, subject to $z_p \geq C_p-E_p$ and $z_p \geq 0$. Because the objective
minimizes $F+N+\sum_p z_p$, these bounds give the exact annual bill at the
optimum. They require one continuous variable for SCE or two for PG&E/SDG&E.
No financial binary variables or nonlinear allocations are needed. Physical
meter-direction constraints still use binary variables where required.
NBT and NEM 2 use HiGHS by default; CBC is also supported.

Numeric reporting evaluates the same equation directly. Optimization replays
its selected flows through this calculation and rejects discrepancies above
$0.001. Shared code establishes consistency. Independent dollar examples and
source evidence establish the intended meaning of the calculation.

For a teaching example, suppose annual eligible charges are $20 generation and
$40 delivery, and credits are $30 generation and $5 delivery. Fixed charges are
$25 and non-bypassable charges are $4. The combined SCE pool gives a $54 bill:
`25 + 4 + max(60 - 35, 0)`. Separate pools give $64:
`25 + 4 + max(20 - 30, 0) + max(40 - 5, 0)`. These are illustrative amounts.

With zero opening balances, no bonus, no annual net surplus, and no value for
ending balances, this annual formula matches the former PG&E and SCE
annual-cost equations. Their modeled year-end offsets already allowed remaining
base credits to cover earlier eligible payments. It changes the former SDG&E
convention, which expired unused credits without those backward offsets.

The monthly accounting engine and SCIP adapter have been removed. Archived
tariff sources and frozen examples preserve the evidence for the former model.
There is one maintained NBT research calculation.

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
| Battery remaining-value and replacement-cost assumptions | The method values five remaining years at one-third of replacement cost. It assumes unchanged real purchase costs and incentive treatment. Future prices, incentives, and resale values can differ; the direction of error is uncertain. | State these assumptions with the results. Use a focused sensitivity if they could change an adoption conclusion. |
| Older results and auxiliary tools can use different capital accounting | The core scenarios were regenerated at `8a98b96`. Other cached sizing and reports retain their recorded versions. Standalone solar/battery/combined sweeps, the older Step 9 size optimizer, and auxiliary NPV diagnostics retain separate conventions. | Use the dated claim assessment for current evidence. Align an auxiliary tool before using it for a comparison under these methods. |
| Auxiliary payback uses a different baseline for the optimized EV case | Its comparison selects `baseline` rather than `baseline_ice_car`. These payback outputs do not support the current Claims 2/3 EAC conclusions, which select their scenarios explicitly. | Correct and validate the payback comparison before citing it. |
| The 2025 incentive sensitivity simplifies eligibility | Its continuous battery sizing uses an ITC-adjusted unit price without a separate 3 kWh eligibility constraint. The appliance policy registry also records separate caps for each appliance under the 25C heat-pump credit, in place of a combined household cap. Affected 2025 cases can overstate incentives. | Check sub-3-kWh battery conclusions and whole-household cases using both heating credits if these support a published claim. These issues do not change zero-credit post-ITC inputs. |
| Battery augmentation costs and gradual capacity loss omitted centrally | Storage is treated more favorably than a model that charges for maintaining capacity. Round-trip efficiency losses and the declared replacement remain included. | Add an explicit degradation or augmentation-cost sensitivity if needed. |
| Equipment-size bounds, specified charging/export rules, and fixed-design comparisons | An optimum applies within its declared feasible choices. A fixed-design result is not an unrestricted economic optimum. | Report binding constraints and test an expanded domain for an affected claim. |
| Continuous sizing has no minimum commercial unit size | The optimizer can select very small positive capacities. These values indicate a modeled cost optimum, not an available product or a forecast of adoption. | State their scale. Use minimum unit sizes or a discrete equipment catalog if product-level decisions are needed. |
| ACC Plus omitted | Savings for eligible households can be understated. For a fixed dispatch with zero opening banks, omitted benefit is at most exported kWh times the applicable bonus rate. Unused bonus credits have no current-year value. This bound alone does not establish unchanged optimal sizing. | The sourced standard-customer 2026 rates imply at most $8.80 per 1,000 exported kWh for PG&E, $16 for SCE, and $0 for SDG&E. Apply the bound to affected publication cases before considering a separate sensitivity. |
| Annual net-export cap implemented for NBT research | Profitable net-exporting dispatches are excluded. Fixed arrays may curtail generation to comply. A binding cap can link permitted exports to added electrification load and affect the apparent package effect. This is a study constraint, not a utility rule. | Identify binding cases from annual meter totals. For an affected claim, compare with the pre-cap implementation at `9b61415`, using matched inputs and accounting assumptions. |
| Annual credit timing | SDG&E savings may be overstated relative to the former no-backward-offset convention. A late credit could offset an early charge in the annual model. | Bound the difference using unused eligible credits and earlier eligible payments; inspect affected San Diego cases. |
| No opening credits or value for balances after the modeled year | Results omit benefits from a household's existing bank or future use of unused credits. | Use a separately specified future-use sensitivity if a claim requires it; opening balances are not supported centrally. |
| Persisted equipment capacities use two decimal places | Downstream capital reporting can differ slightly from the optimizer, which uses full precision. The core rerun at `8a98b96` had a maximum difference of $1.37/year, in San Mateo; all annual electricity bills reconciled. | Preserve full precision in capacity artifacts and round only presentation in a separate correction. |
| Cost tolerance and finite solver budget | New solves allow up to $1/year of cost suboptimality, subject to unchanged physical checks. This does not bound capacity differences. Difficult cases can fail the five-minute budget. | Record the cost certificate. Use a tighter tolerance for capacity-threshold claims. Adding tariff-identified meter constraints together is a pending performance change. |
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
