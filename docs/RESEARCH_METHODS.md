# Research methods and approach

This is the maintained narrative for the research paper. It explains what the
model measures, how it works, and where its conclusions apply. Detailed formulas
remain in the [methods manifest](methods.yaml). The [data source catalogue](data_sources.yaml)
records provenance, current uses, and unresolved source gaps. The catalogue links
to a [local archive of Simon La Vieille's report](sources/simon_ev_integration/2026-09-15/README.md).
That August 2025 report preserves the original rationale; it does not define current behavior.
The narrative uses Markdown with LaTeX equations. A later LaTeX export should
derive from this file, so the prose and equations have one maintained source.

## Implementation status

Updated on September 15, 2026. **All three accounting simplifications are
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
$0.001; the strict statewide validator passed 49 checks. Archived auxiliary
payback outputs used a different baseline for the optimized EV comparison.
The September 15 refresh corrects that selection for matched optimized EV payback.
Older archived payback outputs remain unchanged.

The September 14 matched run at `11b7dba` covers both optimized households in
all 47 counties and their no-solar counterfactuals. Its 188 cost cells pass the
comparison checks. All 94 NEM 3 bills reconcile within $0.001, and both statewide
validation reports pass all 49 checks. The [matched results and figure](research_logs/2026-09-14.md)
separate the equipment benefit from the larger tariff-inclusive package effect.

Review of vehicle energy costs found a $916.35/year maintenance discrepancy in
each saved gas-household ledger and a zero gasoline price for Alpine. The ledger
code now uses the vehicle's itemized calculation. Maintenance defaults now
average the first 144,000 miles, replacing the former new-vehicle allowances.
Alpine now uses the explicit gasoline-price proxy described below. The
[September 15 cost refresh](research_logs/2026-09-15-cost-refresh.md) at `668a07e`
applies these corrections to all 188 matched cost cells and refreshes auxiliary
Step 15 output. It reuses the validated sizing and bills; no optimization was needed.
With optimized equipment, electric/EV costs less in 8 counties and more in 39.
Allowing each household to decline adoption gives 7 cheaper and 40 more expensive.
Both comparisons have a median electric/EV cost increase of $415.54/year.
Vehicle dollars cancel within adoption comparisons. The median package effect
remains $307.60/year, positive in all 47 counties. Older reports retain their
original cost inputs and must not replace the refreshed matched comparison.

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

The older three-case Claims 2 and 3 use `baseline_ice_car`, `full_electric_ev`,
and `full_electric_ev_coopt`. Their gas/vehicle reference retains fixed
solar/storage. These figures compare total scenario costs and fixed versus
optimized equipment; they do not by themselves supply both matched adoption
comparisons needed for $P_{c,e}$. The package-effect equation above defines the
required research comparison, not a result already established by those figures.
The mappings and arithmetic are in the
[publication data collector](../figure_builder/datasets.py).

The [matched electrification collector](../figure_builder/electrification.py)
now implements the four-case comparison below. It uses `baseline_ice_car_coopt`
and `full_electric_ev_coopt`, including each scenario's no-solar counterfactual.
The [corrected statewide matched results and figure](research_logs/2026-09-15-cost-refresh.md)
are available. The older three-case figures retain their original comparison.

| Household | No solar or storage | Optimally sized solar and storage |
|---|---|---|
| Gas appliances and gasoline car, $g$ | $C^0_{c,g}$ | $C^*_{c,g}$ |
| Electric appliances and EV, $e$ | $C^0_{c,e}$ | $C^*_{c,e}$ |

Electrification savings without solar/storage are
$E^0_c=C^0_{c,g}-C^0_{c,e}$. Savings when both households can resize solar/storage
are $E^*_c=C^*_{c,g}-C^*_{c,e}$. The latter includes the economic response of the
solar/storage design to electrification. These differences satisfy:

$$
P_{c,e}=E^*_c-E^0_c
=\left(C^0_{c,e}-C^*_{c,e}\right)-\left(C^0_{c,g}-C^*_{c,g}\right).
$$

A positive $P_{c,e}$ means electrification increases adoption savings.
Electrification can reduce household cost while reducing adoption savings;
the collector reports both results separately. This comparison measures combined
building and vehicle electrification. It does not attribute savings to either
part separately.

Within each solar choice, both households use the same utility and electricity
plan. The no-solar plans are PG&E E-TOU-D, SCE TOU-D-4-9PM, and SDG&E TOU-DR1.
The optimized cases use the required NEM 3 plans: E-ELEC, TOU-D-PRIME, and
EV-TOU-5, respectively. Adoption savings therefore include this plan change.
They measure the modeled financial adoption package, including its tariff
treatment. A result with zero solar and storage capacity cannot establish a
benefit from installing those assets.

An optimized NEM 3 system can still cost more than the no-solar retail option.
In that case, declining adoption has lower modeled cost. The cheapest available
option for each household is $\min(C^0,C^*)$. Report this distinction when
comparing whole-household costs; free equipment sizing alone does not optimize
the choice between the two tariff arrangements.

A run diagnostic separates equipment benefits from billing-path changes.
It uses the optimizer's saved hourly load and timestamps for both a zero-export
NEM 3 bill and a retail bill on the same calendar. Differences between calendars,
between plans, and from adding equipment sum to the reported adoption saving.
Their changes between households sum to the package effect. This decomposition
does not establish no-solar tariff eligibility or select the cheapest eligible
plan for each household. The results note reports each contribution separately.

The collector requires four complete cells for each county, 8,760-hour demand
inputs, identical weather files, and matching recorded tariff and optimization
settings. Appliance capital, gas bills, and vehicle operating costs must remain
unchanged between a household's two solar choices. An exact timestamp selects
both annual bill files for each scenario. The source receipt records these
timestamps, SHA-labelled completion files, and hashes of the collected inputs.
It checks that these inputs do not change during collection. Execution history
and unrecorded run overrides still require the isolated model-run record;
file names and hashes alone do not establish that history.

The table retains selected capacities and numerical cost diagnostics. For the
optimized electrification saving and package effect, it reports a conservative
numerical bound:

$$
u_c=\epsilon_{c,g}+\epsilon_{c,e}+|d_{c,g}|+|d_{c,e}|+10^{-4}.
$$

Each $\epsilon$ is the recorded solver cost gap, in dollars per year. Each $d$
is reported solar/storage capital plus electricity cost, minus the saved solver
objective. This captures the separate effect of rounding stored capacities.
The final term covers rounding two saved objectives to four decimal places.
Differences within $u_c$ do not establish a sign at the recorded numerical
precision. This bound does not cover modeling uncertainty or bound capacities.

The matched adoption figure plots $S_{c,g}$ horizontally and $S_{c,e}$ vertically.
Points above the equal-savings diagonal have a positive package effect. Its
headline counts effects greater than $u_c$, and reports the unweighted median
of county effects. This median can differ from the difference of median savings.
Each axis shows an error bar of $\epsilon+|d|+0.00005$ dollars per year.
These bars show numerical bounds, not statistical confidence intervals.
The figure reads the verified four-case source and records its hash, code hashes,
statistics, and output hashes in an adjacent receipt.

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

The [federal-credit registry](../appliances/federal_credits.py) collects the
modeled solar/storage (25D), heat-pump (25C), and new-vehicle (30D) rules in one
place. Each record identifies amounts, applicable dates, eligible costs, tax
treatment, sources, and current implementation limits. The existing regime
helpers import those records; the battery constructor reads its capacity
minimum from the same record. This extraction preserves current calculations.

The separate [household credit calculation](../evaluations/federal_credits.py)
now computes potential purchase credits for explicitly eligible costs. It
supports three cases: no federal credits, solar/storage credits alone, and all
three modeled credit families. It returns separate solar, storage, shared
heat-pump, and vehicle amounts. Reporting can now use these amounts when the
caller explicitly declares their realization and timing. The optimizer core
also supports this accounting for solar/storage. Step 9b county runs accept the
same policy and save its assumptions. The matched comparison now reads these
records and explicit household declarations. The
[three-county pilot](research_logs/2026-09-21-federal-credit-pilot-gap5.md) has passed
independent validation. Its San Diego credited cases use an explicit $5/year
cost limit; reused designs retain their $1/year certificates. The statewide run
remains pending. See the pilot status below.

For one taxpayer's purchases in one eligible tax year, the calculation is:

$$
T_{\mathrm{PV}} = 0.30 B_{\mathrm{PV}},\qquad
T_{\mathrm{storage}} = 0.30 B_{\mathrm{storage}}\mathbf{1}(K\geq3\ \mathrm{kWh}),
$$
$$
T_{\mathrm{heat}} = \min\left[0.30(B_{\mathrm{space}}+B_{\mathrm{water}}),\;2000\right],
\qquad T_{\mathrm{vehicle}} = V.
$$

Each $B$ is eligible installed cost in dollars, after required basis adjustments
and before these federal credits. $K$ is battery capacity in kWh. $V$ is an
explicitly supplied eligible vehicle credit, bounded by the registry's $7,500
maximum. The calculation never assumes full vehicle eligibility. The selected
case sets excluded credit families to zero. Their sum is a purchase credit in
dollars, not annual savings. All rates and limits come from the federal registry.

The heat-pump limit applies once to the two purchases together. No other
purchase consumes that annual cap in this model. For example, $12,000 of eligible
space-heating costs and $4,000 of water-heating costs yield $2,000, not $3,200.
Tests also check battery sizes below, at, and above 3 kWh and itemized totals.
Missing, negative, non-finite, and nonnumeric inputs raise errors, even when a
case excludes the affected credit. Explicit zero means absent or ineligible.

This calculation is conditional on eligibility; it is not a household tax return.
The caller must establish applicable acquisition/installation dates and other
legal requirements. Selecting credit families does not select a calendar year.
The amounts precede tax-liability limits and do not assume a receipt date or
carryforward schedule. They do not grant credits for replacement purchases.
Matched runs require declared eligibility, realization, and timing. The pilot
assumptions below do not establish population-wide eligibility.
State/local and federally funded rebates
are outside that comparison. Default appliance paths still include some rebates,
including county heat-pump rebates. The explicit federal-only reporting path
described below excludes them.

A separate [credit annualization function](../evaluations/eac.py) converts one
declared receipt into an annual cost reduction. The caller supplies the amount
actually realized and its timing. A potential credit is not automatically a
realized credit. The calculation is:

$$
\Delta A_{\mathrm{credit}} = \frac{C}{(1+r)^t}\operatorname{CRF}(r,N).
$$

Here, $C$ is the realized credit in dollars, $r$ is the real annual discount
rate, and $N$ is the study horizon in years. The receipt time $t$ is measured
from the initial purchase: zero means immediate receipt, and one means a year
later. All dollar amounts use the study's constant-dollar basis. Fractional
receipt years are allowed. The function requires $C\geq0$, $r\geq0$, $N>0$,
and $0\leq t\leq N$. It rejects missing, malformed, and non-finite inputs.
At zero discount, the annual reduction is $C/N$.

Subtract this positive reduction from costs calculated before that credit.
Use the 25-year study horizon for a one-time credit, even when the equipment
has a shorter service life. For example, a fully realized $7,500 credit received
at purchase reduces annual cost by $643.58 at 7%. Receipt one year later gives
$601.48/year. The earlier $944/year illustration used a 12-year vehicle horizon;
it does not represent this one-time credit over the 25-year study.

Initial credits do not reduce future replacement costs or remaining value.
For a $10,000 battery, retain the $10,000 year-15 replacement and the one-third
remaining value at year 25. Subtracting one $3,000 credit received at purchase
gives $858.99/year, compared with $1,116.42/year before that credit. Independent
cash-flow tests verify this example and delayed receipt. Credits with different
receipt times must be converted separately and then summed.

The existing EAC calculation and county collectors now accept explicit federal
credit receipts. For this comparison, they start from gross equipment costs
and subtract the annualized initial credits once. They ignore the ledger's
mixed-incentive net prices and the solar/storage summary's old incentive amounts.
This excludes county heat-pump rebates, cooking rebates, and utility EV rebates.
Battery replacement and remaining value use gross costs. Appliance service-life
annualization, energy bills, and vehicle operating costs keep their existing
conventions.

The returned solar and storage capital components each include their own credit
reduction. Electric-appliance capital includes the shared heat-pump and vehicle
reductions. The reported components still sum to total annual household cost.
The receipt declaration retains the four purchase-credit amounts and their
timing. It uses one receipt time for home credits and a separate time for the EV.
It does not infer tax eligibility or treat a potential award as realized.

Every requested scenario and county must have exactly one receipt declaration.
Missing or extra households raise errors. The ledger still selects one incentive
case before reading gross costs and vehicle operating costs; its alternative
rows are not summed. No-solar reporting requires zero solar/storage credits and
does not read a solar/storage summary. Credits exceeding the corresponding gross
purchase cost raise errors. Eligibility, including the battery capacity minimum,
must be established before declaring receipts.

An explicit declaration of zero credits produces the federal-only no-credit
comparison and excludes all other incentives. Omitting the declaration preserves
the existing reporting behavior, including its separately modeled rebates.
The reporting path evaluates supplied equipment sizes and bills. It does not
reoptimize them or update published county results.

The optimizer core accepts an explicit `PVStorageCreditPolicy`. It declares the
credit case, realization fraction $f$ between zero and one, and receipt year $t$.
Unit prices must represent gross eligible installed costs. The annual capital
term becomes:

$$
A_{\mathrm{capital}}
= \alpha_{\mathrm{PV}} C_{\mathrm{PV}}
+ \alpha_{\mathrm{battery}} C_{\mathrm{battery}}
- a(C_{\mathrm{PV}}+Q),\qquad
a=0.30f(1+r)^{-t}\operatorname{CRF}(r,N).
$$

Here, $C_{\mathrm{PV}}$ and $C_{\mathrm{battery}}$ are gross installed costs.
The battery coefficient includes gross replacement and remaining value. $Q$ is
the battery cost eligible for the initial credit. The no-credit case sets $a=0$.
Heat-pump and EV credits stay in household reporting. They are constants when
the household's appliances and load are fixed, so they cannot change optimal
solar/storage sizing.

Free battery sizing adds one binary variable $y$ when a credit is available and
the capacity ceiling permits 3 kWh. The linear constraints are:

$$
K\geq3y,\quad 0\leq Q\leq C_{\mathrm{battery}},\quad
Q\leq My,\quad Q\geq C_{\mathrm{battery}}-M(1-y).
$$

$K$ is battery capacity in kWh. $M$ bounds gross battery cost using the declared
capacity ceiling and the existing power limit of 1 kW per kWh. A credited design
must reach 3 kWh. Smaller batteries remain feasible without credits. Fixed sizes
use their known eligibility and need no extra binary variable. The credit does
not apply again to the year-15 replacement or reduce remaining value at year 25.

After solving, the shared numeric calculator recomputes receipts from the chosen
design. The resulting annual cost must satisfy the solver's cost-bound check.
An eligible free-size solution within $10^{-6}$ kWh below 3 kWh is represented
as exactly 3 kWh. This handles solver precision; fixed sub-threshold inputs
remain ineligible. Tests reconcile independent cash flows and reporting under
linear, NBT, and NEM 2 billing. A synthetic case chooses 2.5 kWh without credits
and 3 kWh with credits; this is a validation example, not a county finding.
See [the optimizer credit tests](../tests/federal_credit_optimizer_test.py).

Credited NBT runs now tighten the battery search before adding meter constraints.
First, a no-battery relaxation proposes a solar size. At that size, a feasible
solar-only dispatch serves load first and curtails exports above the annual cap.
Shared billing plus annual solar capital cost gives an upper bound, $U$, on the
sizing objective. Fixed appliance and vehicle costs cancel in this comparison.
The optimal sizing objective cannot exceed this feasible alternative.

A second relaxation maximizes gross annual battery-capacity cost subject to
the sizing objective at most $U$. Its certified bound gives a safe capacity ceiling.
If that ceiling is below 3 kWh, eligibility is impossible; one further relaxation
bounds the remaining uncredited batteries. The temporary cost constraint is then
removed. The search ceiling is rounded outward by $10^{-6}$ kWh. It is never
tightened below 0.001 kWh, to avoid nearly fixed numerical intervals. This floor
expands the search; it is not a minimum installation size. Zero remains feasible.

The reduced ceiling also tightens hourly export limits. An exporting household
must first serve its load from solar and usable stored energy. Thus:

$$
E_h\leq\max\left(0,\;G_h K_{\mathrm{PV,max}}
+\eta_d(s_{\max}-s_{\min})K_{\mathrm{battery,bound}}-L_h\right).
$$

Here, $E_h$ is exported kWh, $G_h$ is available solar kWh per kW, and $L_h$ is
household load. The state-of-charge fractions are $s_{\min}$ and $s_{\max}$;
$\eta_d$ is discharge efficiency. Charging losses can only reduce this bound.
The existing meter-direction binaries enforce the combined and individual flow
bounds. These steps preserve the economic optimum and the declared credit rules.
They apply to free credited NBT storage sizing with a positive capacity price.
Fixed designs and other accounting paths retain their existing solve sequence.
See [the bound calculations](../pipeline/optimization_bounds.py) and
[their regression tests](../tests/optimization_bounds_test.py).

Omitting this policy preserves existing optimizer calls. Set
`Config.coopt_federal_credit_policy` to use it through the solar/storage module.
That module selects gross appliance prices before calling Step 9b. Direct Step 9b
calls also select gross defaults in this mode. Explicit price overrides must be
gross eligible installed costs. The legacy `incentive` setting does not determine
the new policy's realization fraction.

The Step 9b command line requires the credit case, receipt year, and realization
fraction together. For example, this runs one conditional solar/storage case into
a separate output directory:

```sh
python -m pipeline.steps.step9b_cooptimize_pv_battery \
  --scenario full_electric_ev_coopt --counties alameda \
  --base-input-dir data/loadprofiles --base-output-dir /tmp/federal-credit-check \
  --federal-credit-case solar_storage_federal_credits \
  --credit-receipt-year 1 --credit-realization-fraction 1
```

Each county gets a `coopt_accounting_<county>.json` file. It records the credit
policy and rule snapshot, realized receipts, full-precision capacities, unit and
purchase costs, annual costs, lifetimes, discount rate, dispatch settings, and
tariff identity. The existing solver file retains the cost certificate. Federal
runs also preserve full capacity precision in `electrified_assets.csv`; rounding
must not change credit eligibility or reported costs. A subsequent legacy run
rewrites the accounting file with explicit null credit declarations.

In this mode, missing or incomplete county profiles and failed capacity writes
raise errors. Legacy Step 9b sweeps and non-cooptimized scenarios reject the new
policy. Module 4 also rejects it: its reports do not yet load household receipts.
This prevents those paths from silently ignoring the selected credits. The
saved sizing record covers solar/storage only, including when the selected case
is `all_modeled_federal_credits`. Heat-pump and EV eligibility and receipts still
need explicit household declarations. The matched comparison collector now reads
these records through `--federal-credit-declarations`. Existing publication
results are unchanged. The isolated pilot supplies matched results for Alameda,
Los Angeles, and San Diego. The statewide comparison remains pending.

The declaration file uses JSON with `schema_version: 1` and a `households` list.
Each entry names `scenario` and `county_slug`. It contains the saved
`pv_storage_policy` fields (`case`, `receipt_year`, and `realization_fraction`),
plus six required household inputs:

- `space_heat_pump_eligible_basis_usd` and `water_heat_pump_eligible_basis_usd`;
- `heat_pump_realization_fraction`;
- `eligible_vehicle_credit_usd` and `vehicle_realization_fraction`;
- `vehicle_receipt_year`.

Every requested scenario/county pair must appear exactly once, including explicit
zero bases or vehicle credits for absent or ineligible equipment. All households
must use the same solar/storage policy. Eligibility is a declared assumption,
not a conclusion drawn from the equipment ledger. Declared eligible heating costs
cannot exceed matching gross costs. A positive EV credit requires an EV row.
Heat-pump and vehicle realization fractions can differ from solar/storage capture.
Apply the heat-pump fraction after calculating the shared annual cap. Home credits
share the policy's receipt year; the vehicle uses its separately declared year.

The collector checks saved identities, full-precision capacities, unit and purchase
costs, credit receipts, and the solver's cost bound. It replays annual capital
accounting and checks the saved optimized bill against the selected billing output.
Both households must use matching capital, tariff, and dispatch assumptions.
The current comparison supports the central 7% discount rate, 25-year study,
15-year battery life, and zero degradation charge. Unsupported assumptions fail.
This path uses the saved gross solar/storage costs instead of a legacy capital
summary. It selects one appliance-ledger incentive row for gross costs and vehicle
operations, then excludes all legacy rebates and net-price adjustments.

Heat-pump and EV credits apply equally to a household's cases with and without
solar. They can change whether electrification is cheaper. They cancel from that
household's solar-adoption savings and therefore cannot create a package effect
by themselves. Consequently, the solar/storage-only and all-credit comparisons
can reuse one optimized design when solar/storage capture and receipt timing
match. Adding constant appliance credits needs no additional optimization.
The saved record retains its original case; the output names the reporting case.
Tests check this reuse, cancellation, and the shared $2,000 heat-pump cap using
independent discounted cash flows.

The output retains the existing four-case annual costs and comparison equations.
It also itemizes realized purchase credits in dollars, separately from annual
costs. Its manifest fingerprints the declaration file and saved accounting and
solver records, alongside loads, weather, ledgers, and selected bills. Federal
runs use these records instead of legacy diagnostic completion pages. The model
SHA remains a declared run label; file hashes identify collected inputs, not
their full generation history. This collector does not rerun optimization or
establish legal eligibility. Legacy Module 4 and sweeps remain unsupported for
this mode. Use the dedicated matched collector after completing each isolated run.
Changing credit availability while holding NBT rates and vintage fixed is a
policy sensitivity. It is not a reconstruction of historical 2025 household bills.

The [completed three-county pilot](research_logs/2026-09-21-federal-credit-pilot-gap5.md)
covers Alameda, Los Angeles, and San Diego under all three federal-credit cases.
All 36 matched cost cells passed bill replay and independent cash-flow and
dispatch checks. Both San Diego credited households use an explicit $5/year cost
limit and the existing 300-second budget. The other accepted designs retain their
$1/year certificates. Both household types have matching tolerances within each
county and credit case. The default remains $1/year. The comparison carries
actual solver gaps into its numerical bound; it does not claim precise capacities.

The pilot assumes full eligibility and realization, home credits after one year,
and a $7,500 EV credit at purchase. It excludes other rebates and holds 2026 NBT
rates fixed. Credited San Diego designs select storage; Alameda and Los Angeles
select zero storage. All modeled federal credits still leave electric/EV household
cost higher in these three counties. These are conditional pilot findings, not
statewide conclusions or an estimate of household eligibility.

The $2,000 shared heat-pump credit and EV credit reduce electric-household annual
cost by $803.97 in both solar choices. This constant reduction cancels from
solar-adoption savings and the package effect. The isolated outputs do not replace
existing statewide publication data. The statewide credit comparison remains pending.

The [pilot diagnostic](research_logs/2026-09-21-pilot-diagnostic.md) separates
the annual cost difference into equipment, energy, vehicle upkeep, and credits.
Its independent ledger calculation reconciles all 36 saved household-cost cells.
Before credits, the EV and charger add $1,999/year of capital cost. Space and
water heating add another $1,367–$1,808/year. Energy savings offset part of these
costs. This decomposition is descriptive; it does not isolate each appliance's
effect on electricity demand or optimal solar sizing.

An analytical sensitivity applies DOE's 2025-to-2022 vehicle-premium ratio to
the existing vehicle-only premium. It holds the charger, demand, and credits
fixed. The remaining electrification premium is $495–$650/year in the pilot.
This source-based sensitivity does not replace the declared equipment prices.
The diagnostic also tests a fixed qualifying battery with solar and dispatch
free to change. At a sourced $999/kWh sensitivity price, a 3 kWh battery saves
about $88/year for Los Angeles gas households and $89/year for electric households.
Alameda's same-size battery still loses at that price, as shown by conservative
cost bounds. These checks do not identify the best battery size at the lower
price or recompute the total electrification comparison. See the diagnostic
for solver bounds, rejected attempts, and the limits of the quote benchmark.

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

Reports with and without solar/storage now use one county-level cost
calculation. Both include the same appliance and vehicle purchases, declared
service lives, and vehicle operating costs. The no-solar case sets solar and
storage capital costs to zero and uses the bill for the original household
load. It does not require a solar/storage capital summary. County means and
medians are calculated from these same itemized costs.

Vehicle operating costs separate fuel, maintenance, and insurance. The ICE
vehicle's itemized calculation supplies all three components and their total
directly to Step 14. There is no separate maintenance default in the ledger.

Each incentive case is an alternative evaluation of one household. It is not
an additional household or cost to sum. Vehicle reporting now requires an exact
county and incentive case, then reads at most one ICE row and one EV row. A valid
EV-only case has zero ICE cost, and a valid ICE-only case has zero EV cost. A
missing requested county or incentive case is different from an absent vehicle.
Missing cases, malformed costs, and duplicate vehicle rows raise errors. Explicit
zero costs and finite negative operating-cost adjustments remain valid.

$$
O^{\mathrm{ICE}}_c = \frac{D_c}{\eta_{\mathrm{ICE}}}p_c + M_{\mathrm{ICE}} + I_{\mathrm{ICE}},
\qquad O^{\mathrm{EV}} = M_{\mathrm{EV}} + I_{\mathrm{EV}}.
$$

Here, $D_c$ is annual driving distance in miles, $\eta_{\mathrm{ICE}}$ is fuel
efficiency in miles per gallon, and $p_c$ is the gasoline price in dollars per
gallon. $M$ and $I$ are annual maintenance and insurance costs. All $O$ values
are dollars per year. Residential EV charging is included in the electricity bill.
Public/workplace and DC fast charging are intentionally excluded from both home
load and modeled EV costs. These charging sessions occur away from the home.
Reported costs therefore exclude this transport expenditure. Adding it as a
separate expense is a possible future extension, not a pending accounting fix.
The ICE fuel efficiency remains 24.25 miles per gallon. Annual insurance remains
$1,836 for ICE and $2,040 for EV. Custom maintenance and insurance values use
the same calculation, including explicit zeros. Fuel lookup errors and missing
breakdown fields propagate instead of becoming zero fuel costs.

The gasoline-price table was added on August 6, 2025. Simon attributes it to
AAA, but the exact observation date is unknown. Alpine was left at zero.
We now assign Alpine **$4.589/gallon**, the median of the other 57 positive
county prices in that table. This is an explicit, fixed modeling assumption.
It is not an observed Alpine price or a rule for filling other missing prices.
At 12,000 miles/year and 24.25 mpg, Alpine's annual fuel cost is **$2,270.85**.
Each $1/gallon difference changes that cost by $494.85/year. Missing counties
and nonnumeric, nonfinite, zero, or negative prices raise an error. The other
county prices, mileage assumptions, and fuel efficiency remain unchanged.
See the [source catalogue](data_sources.yaml) for provenance and limitations.

Maintenance includes repairs. Each vehicle uses a constant annual allowance
averaged over 12 years at 12,000 miles/year, or 144,000 miles from new. This
mileage matches the current ICE fuel calculation. The reference applies to
both maintenance allowances; it does not rescale the separate EV charging profile.
Consumer Reports' [Table 2.1](https://advocacy.consumerreports.org/wp-content/uploads/2020/09/Maintenance-Cost-White-Paper-9.24.20-1.pdf)
provides per-mile rates for three successive odometer bands. We apply the first
two rates to 50,000 miles each and the third to the remaining 44,000 miles:

$$
M_{\mathrm{ICE}} = \frac{50{,}000(0.028)+50{,}000(0.060)+44{,}000(0.079)}{12}
= \$656.33/\mathrm{year},
$$
$$
M_{\mathrm{EV}} = \frac{50{,}000(0.012)+50{,}000(0.028)+44{,}000(0.043)}{12}
= \$324.33/\mathrm{year}.
$$

Code retains the unrounded averages. This approximation holds the allowance
constant each year; it does not model individual repair timing. These are the
2020 report's source-dollar rates without an inflation adjustment or a new
California vehicle survey. Changing the reference mileage or ownership period
requires an explicit allowance override. A custom service life does not silently
recalculate maintenance. The [source check and timing sensitivity](research_logs/2026-09-15.md)
record the derivation and remaining limits.

The old ledger used a separate $1,200 maintenance default and overstated ICE
operating costs by $916.35/year relative to the then-declared $283.65 assumption.
The redundant ICE estimator has been removed. The later maintenance review
changed both vehicle allowances. The separate Alpine correction changes its
gasoline input. The September 15 refresh applies all three corrections to the
matched four-case comparison. Older archived publication data remain unchanged.

An [isolated ledger check](../analysis_results/vehicle_cost_accounting_6c14268/README.md)
verified the earlier arithmetic correction across 1,692 rows for both households,
47 counties, and three incentive cases. Only gas-vehicle fuel, operating costs,
and their lifetime totals changed in that check. The subsequent maintenance
change has separate validation because it changes both ICE and EV costs.

Reporting requires the capital ledger, its cost fields, and rows for each
requested county and incentive case. Missing data do not represent free
equipment. Invalid costs, nonpositive service lives, and duplicate equipment
rows raise errors. Explicit zero costs and negative net costs or operating-cost
adjustments remain valid. Both solar choices can select an exact saved bill
timestamp; selecting that timestamp does not establish the provenance of other
input files. The matched four-case dataset supplies the completed comparison.

The shared vehicle selector also supplies Step 15 and the three size-sweep
experiments. The earlier Step 15 path grouped all incentive rows by county and
could count the same household's vehicle operating cost three times. Sweep paths
could replace vehicle-ledger errors with zero. The strict selection corrects this
accounting boundary. It does not change vehicle assumptions, residential-charging
scope, public-charging scope, or dispatch. Existing ledgers are sufficient for
validation; dispatch optimization does not need to run again.

Step 15 also uses one household mapping for both utility bills and vehicle
costs. `full_electric_ev_coopt` compares against `baseline_ice_car_coopt`.
The older `full_electric_ev` and `baseline_ev_car` scenarios compare against
`baseline_ice_car`. Other scenarios retain their plain `baseline` comparison.
The reference uses the selected household's bills without solar. Each incentive
case uses that same household's vehicle costs. Saved-file tests verify the
optimized comparison with and without unrelated plain-baseline files.

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
$C\alpha_{\mathrm{shared}}$. Both purchases use the same cost in constant dollars.
Legacy net-price calls also repeat their incentive treatment. The explicit
federal-only path instead uses gross costs and subtracts an initial credit once.
For gross $C=\$10{,}000$ before federal credits, the year-25 remaining value
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
An optional sensitivity permits grid charging. It tracks solar-origin and
grid-origin stored energy separately. Both can supply the home, but only
solar-origin stored energy can be exported. Charging purchases enter the same
electricity bill and annual import total as other grid purchases. This is a
modeled operating rule, not a verification of utility interconnection approval.
The [September 17 comparison](research_logs/2026-09-17-grid-charging.md) checks
both households in all 47 counties. Zero storage remains within $1/year of
optimal in the 46 PG&E/SCE counties. San Diego has positive certified savings
ranges, about $29–$44/year for gas/ICE and $57–$85/year for electric/EV, including
equipment costs. Its exact optimal sizes are not resolved to the $1 criterion.
These sensitivity results are separate from the central household-cost findings.
Standard optimized storage is limited to 40 kWh, with explicit overrides for
declared sensitivities. Current PV-generation bounds are 150% of annual load
under NBT and 100% under the NEM 2 comparison.

The default numerical stopping rule accepts a physically valid design within
**$1/year of the model optimum**. Each intermediate solver model supplies a
lower cost bound, $L$. The final design's replayed annual cost, $C$, must satisfy
$0 \leq C-L \leq \epsilon$, where the default $\epsilon$ is $1/year$.
We retain the strongest bound across meter-constraint rounds. Numerical
comparisons allow $10^{-6}$ dollars for floating-point roundoff. This cost
tolerance does not relax energy conservation, meter direction, or billing checks.
The certificate uses full-precision capacities. Rounding in saved capacity
tables can add the separate reporting difference documented below.

HiGHS remains the default backend and requires SciPy 1.16.1 or later, the
validated minimum version. The earlier SciPy 1.11.4 wrapper drops the
absolute-gap setting. CBC can be selected explicitly. Each county
sizing/dispatch problem has a default 300-second budget shared across
model construction, bound tightening, and all solver rounds. Data preparation and optional
sensitivity cases are separate; each sensitivity solve has its own budget.
Solver limits are cooperative, so finalization and validation can add overhead.
A timeout is accepted only if the available candidate passes the cost bound
and all physical checks. Otherwise the run stops with an error.

`Config.coopt_solver` contains these settings as `SolverOptions`. Step 9b also
exposes `--solver-backend`, `--solver-cost-gap-usd`, and
`--solver-time-limit-seconds`. County outputs record the settings, elapsed time,
cost gap, and lower bound. A `coopt_solver_<county>.json` file records each round
and labels auxiliary bound calculations separately. An auxiliary objective is
not a lower bound on total household cost and never enters the final certificate.
CBC's printed bounds are adjusted downward for their displayed rounding.
Changing a backend is an explicit run choice; there is no automatic retry.
`SolverRun` owns the shared deadline, selects the configured backend, retains
the round certificates, and validates the final cost bound. Step 9b separately
constructs the model and validates its physical and billing results.

If the first NEM 3 solution imports and exports at once, the next solve adds
meter-direction constraints for all hours where export prices meet or exceed
import prices. Annual credit limits can hide some of these hours in the first
solution. Adding them together avoids discovering each group through another
solve. A physically valid first solution needs no additional meter constraints.
The NEM 2 constraint-generation rule is unchanged. This changes the order in
which physical constraints enter the solver, not the economic or physical model.

A [paired full-year benchmark](../analysis_results/sd_gas_runtime_0d0e9ac/README.md)
changed San Diego gas/ICE from a 314-second budget failure to a 35-second success.
The electric/EV case fell from 96 to 37 seconds. Alameda and Los Angeles gas/ICE
cases increased from 169 to 187 and 161 to 168 seconds. All accepted objectives
and capacities matched; all four revised bills replayed exactly and retained
cost gaps below $1/year. These are single measurements, not guaranteed runtimes.
The batch adds work to some cases that already needed only one correction round.

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
Annual export-credit settlement needs no binary variables or nonlinear
allocations. Physical meter-direction constraints still use binary variables
where required. The optional federal purchase-credit path can add one separate
binary variable for battery eligibility.
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
| Adoption includes an import-rate plan change | The four-case collector matches plans between households within each solar choice. It compares the declared retail plan without solar to the required NEM 3 plan with optimized equipment. Adoption savings and the package effect therefore include the tariff transition. | Report the aligned-load diagnostic, which separates calendar, plan, and equipment contributions. Choosing the cheapest eligible no-solar plan remains outside this comparison. |
| Retail and NEM 3 use different calendars | Retail bills retain the source profile calendar; NEM 3 uses the declared 2026 calendar. The aligned-load diagnostic bounds the package-effect difference at $3.64/year across the matched run. All 47 signs remain positive. | Use one calendar in future reporting. This bounded difference does not explain the tariff-inclusive or within-tariff equipment finding. |
| Building and vehicle electrification are bundled | The matched comparison identifies their combined household-cost effect. It cannot attribute the effect to appliances or the EV separately. | Add matched intermediate scenarios if separate attribution becomes a research question. |
| Vehicle charging and driving use independent reference inputs | Home charging repeats a statewide 2030 fleet-average day. The pilot uses 1,682 kWh/year at home, or 47.5% of its source's 3,540 kWh across all locations. ICE fuel uses 12,000 miles/year. Equal transport service has not been established. | Retain the declared home-charging boundary. Describe comparisons as conditional modeled costs, not complete equal-mileage vehicle ownership costs. Normalizing demand requires a separate reviewed input change. See the source catalogue and pilot diagnostic. |
| Charging away from home is intentionally outside the model scope | Home load includes residential charging only. Public/workplace and DC fast charging costs are also excluded, so reported household costs do not cover all transport expenditure. Simon's $642.54/year estimate remains historical context. | A future extension could verify those prices and demand, then add a separate expense outside the home electricity bill. This is not required for publication within the stated scope. A constant expense cancels within each household's adoption comparison. |
| Some vehicle input provenance remains incomplete | Simon identifies AAA gasoline prices, but the snapshot date and exact citation are missing. The $3,000 utility rebate lacks program-specific support. Insurance uses older national estimates, and the 12-year vehicle-life citation describes batteries. | Use the source catalogue to resolve material gaps and state the remaining reference assumptions. These findings do not change inputs in this documentation review. |
| Alpine gasoline uses a proxy; the original price date is unknown | Alpine uses $4.589/gallon, the unweighted median of the other 57 stored county prices. This does not establish its local price. Each $1/gallon difference changes annual fuel cost by $494.85. | Retain this explicit assumption and check price sensitivity if Alpine's classification drives a claim. Replace it with a documented observation when revisiting gasoline inputs. |
| Older vehicle-cost reports retain superseded inputs | The September 15 matched comparison uses corrected ICE arithmetic, revised maintenance, and the Alpine proxy. Older three-case reports and county diagnostic displays retain their original costs. | Cite the refreshed matched comparison. Rebuild an older report before using its total household costs under current assumptions. Vehicle-dollar corrections cancel within adoption differences. |
| Constant vehicle repair and maintenance allowances | The allowances average 144,000 miles from new using older survey rates. They do not represent county or vehicle-model variation, inflation, or actual repair timing. At 7%, the flat allowance increases the ICE-minus-EV maintenance difference by $21.93/year against a 12-year calculation with mileage bands applied each year. | Use the documented constant allowance for the current comparison. A future sensitivity can update prices or ownership patterns. The timing check covers maintenance alone; it is not a full household-cost uncertainty bound. |
| Known profiles and prices throughout an optimization run | Dispatch assumes advance knowledge of the modeled year. Real controllers face forecast errors, which can reduce achievable savings. | Compare a controller with limited forecasts on the same cases. |
| Reduced 12 × 24 sensitivity chronology | Averaging can change cycling, usable credits, and optimal capacities. Mixed-resolution comparisons cannot isolate a policy effect by themselves. | Use full-year checks for findings near a threshold or sensitive to chronology. |
| Declared equipment costs, lifetimes, and incentive cases | These are sourced inputs, not a survey of prices available to every household. DOE's 2025 vehicle-premium benchmark is below the implemented 2022 value. A later battery quote median is $999/kWh versus the central $1,461/kWh model benchmark. | Report the bounded pilot sensitivities and their source limitations. These comparisons differ in vintage, sampling, and system size. They do not automatically replace central assumptions. |
| County equipment costs include imputed values | The heat-pump cost inputs use the median of available counties where source data are absent: three counties for space heating and nine for water heating. These are not local price observations. | Identify these counties in cost interpretation and refresh their inputs when local data become available. |
| Battery remaining-value and replacement-cost assumptions | The method values five remaining years at one-third of replacement cost. It assumes unchanged real purchase costs. Legacy net-price calls repeat incentive treatment; the explicit federal-only path grants only an initial credit. Future prices and resale values can differ; the direction of error is uncertain. | State these assumptions with the results. Use a focused sensitivity if they could change an adoption conclusion. |
| Older results and auxiliary tools can use different capital accounting | The core scenarios were regenerated at `8a98b96`. Other cached sizing and reports retain their recorded versions. Standalone solar/battery/combined sweeps, the older Step 9 size optimizer, and auxiliary NPV diagnostics retain separate conventions. | Use the dated claim assessment for current evidence. Align an auxiliary tool before using it for a comparison under these methods. |
| Auxiliary payback retains legacy conventions | The September 15 refresh reconciles all 141 matched optimized-EV payback rows using the corrected household and incentive selection. First-column tariff selection, capital-summary conventions, and a $0.01 denominator for nonpositive savings remain. Missing-bill handling is permissive; this refresh independently verifies every required bill. | Use the explicit matched EAC collector for publication. Address these conventions if payback becomes a paper result. Older archived payback outputs remain unchanged. |
| The legacy 2025 incentive sensitivity simplifies eligibility | Its continuous battery sizing uses an ITC-adjusted unit price without a separate 3 kWh eligibility constraint. Legacy appliance calculations apply the 25C cap separately to space and water heating. Affected 2025 cases can overstate incentives. The explicit federal-only optimizer and household calculator enforce these limits. | Rerun affected comparisons through the new path before using them for published claims. These issues do not change zero-credit post-ITC inputs. |
| Federal purchase credits are conditional on declared eligibility and realization | The amount calculation enforces the shared heat-pump cap and battery threshold. Reporting now applies explicit realized amounts and times to gross costs and excludes other incentives. It does not infer qualifying dates, buyer/product eligibility, or tax liability. Home credits share one receipt time. Treating potential credits as guaranteed receipts could overstate savings. | Declare eligibility and realization assumptions for the comparison. Separate receipt times or installments require an explicit extension. Receipts beyond the study require an explicit model change. Default reports and saved county results remain unchanged. |
| Federal-only pilot coverage is limited | Three selected counties pass matched reporting; statewide coverage remains pending. San Diego credited cases use a $5/year cost limit; other designs retain $1/year certificates. Full eligibility and realization are conditional assumptions, and excluding other rebates changes the baseline from earlier results. | Complete the statewide comparison before making statewide claims. Preserve accounting checks and report numerical cost bounds. State eligibility, realization, and timing assumptions; collection does not establish them. Legacy sweeps and Module 4 remain unsupported. |
| Battery augmentation costs and gradual capacity loss omitted centrally | Storage is treated more favorably than a model that charges for maintaining capacity. Round-trip efficiency losses and the declared replacement remain included. More frequent cycling with grid charging could increase this bias. | Report cycling when interpreting a grid-charging result. Add an explicit degradation or augmentation-cost sensitivity if needed. |
| Equipment-size bounds, specified charging/export rules, and fixed-design comparisons | An optimum applies within its declared feasible choices. A fixed-design result is not an unrestricted economic optimum. | Report binding constraints and test an expanded domain for an affected claim. |
| Central cases exclude grid charging | The matched 94-case check preserves zero storage in the 46 PG&E/SCE counties but establishes a small positive storage benefit in San Diego. Exact San Diego sizes remain unresolved; its cost ranges have positive lower bounds. | Report this exception alongside the central findings. Stored grid energy remains ineligible for export. County differences combine assigned utility tariffs with local load and weather; they do not isolate a tariff's causal effect. |
| Continuous sizing has no minimum commercial unit size | The optimizer can select very small positive capacities. These values indicate a modeled cost optimum, not an available product or a forecast of adoption. | State their scale. Use minimum unit sizes or a discrete equipment catalog if product-level decisions are needed. |
| ACC Plus omitted | Savings for eligible households can be understated. For a fixed dispatch with zero opening banks, omitted benefit is at most exported kWh times the applicable bonus rate. Unused bonus credits have no current-year value. This bound alone does not establish unchanged optimal sizing. | The sourced standard-customer 2026 rates imply at most $8.80 per 1,000 exported kWh for PG&E, $16 for SCE, and $0 for SDG&E. Apply the bound to affected publication cases before considering a separate sensitivity. |
| Annual net-export cap implemented for NBT research | Profitable net-exporting dispatches are excluded. Fixed arrays may curtail generation to comply. A binding cap can link permitted exports to added electrification load and affect the apparent package effect. This is a study constraint, not a utility rule. | Identify binding cases from annual meter totals. For an affected claim, compare with the pre-cap implementation at `9b61415`, using matched inputs and accounting assumptions. |
| Annual credit timing | SDG&E savings may be overstated relative to the former no-backward-offset convention. A late credit could offset an early charge in the annual model. | Bound the difference using unused eligible credits and earlier eligible payments; inspect affected San Diego cases. |
| No opening credits or value for balances after the modeled year | Results omit benefits from a household's existing bank or future use of unused credits. | Use a separately specified future-use sensitivity if a claim requires it; opening balances are not supported centrally. |
| Legacy equipment-capacity CSVs use two decimal places | Downstream capital reporting can differ slightly from the optimizer, which uses full precision. The core rerun at `8a98b96` had a maximum difference of $1.37/year, in San Mateo; all annual electricity bills reconciled. New explicit federal runs preserve full capacity precision to keep credit eligibility and costs consistent. | Preserve full precision in legacy capacity artifacts and round only presentation in a separate correction. |
| Cost tolerance and finite solver budget | The default allows $1/year of cost suboptimality. The federal-credit pilot explicitly uses $5/year for both San Diego credited households, with unchanged physical checks. Neither limit bounds capacity differences. Difficult cases can still fail the five-minute budget. Auxiliary bound calculations can add work when the original problem was already easy. | Record each tolerance and certificate; propagate actual cost gaps into comparisons. Bound tightening and meter-constraint batching do not guarantee a runtime or identical capacities. Use a tighter tolerance for capacity-threshold claims. |
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
