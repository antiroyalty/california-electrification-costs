# What explains the federal-credit pilot?

The household-cost arithmetic reconciles. The remaining electrification premium
comes mainly from equipment purchases. It is not evidence that solar adoption
fails to save money. The price check changes the Los Angeles storage conclusion: a 3 kWh battery
can save money at a lower sourced price. Price vintage and the vehicle service
boundary therefore limit broad claims about adoption or total household costs.

This diagnostic uses committed model `72cd7cf` in an isolated checkout. It reads
the accepted pilot at `analysis_results/runs/2026-09-21_ca1214a_federal_pilot_gap5/`.
New artifacts are in `analysis_results/runs/2026-09-21_72cd7cf_pilot_diagnostic/`.
It changes no production algorithm, tariff, price, load, or publication result.

## Where the annual cost difference comes from

Positive values mean the electric/EV household costs more than gas/ICE.
Both households optimize solar/storage. All modeled federal credits are fully
realized; other rebates are excluded. Costs are equivalent annual dollars.

| Component | Alameda | Los Angeles | San Diego |
|---|---:|---:|---:|
| Vehicle and charger capital, before federal credit | +1,999 | +1,999 | +1,999 |
| Space-heating capital, before federal credit | +1,217 | +1,101 | +729 |
| Water-heating capital, before federal credit | +591 | +266 | +690 |
| Cooking equipment | +160 | +160 | +160 |
| Solar/storage capital, after its credits | +205 | +159 | +518 |
| Electricity, gas, and gasoline combined | -2,221 | -1,653 | -2,221 |
| Vehicle maintenance and insurance combined | -128 | -128 | -128 |
| Heat-pump and EV credits | -804 | -804 | -804 |
| **Net annual difference** | **+1,018** | **+1,100** | **+944** |

Rounded components can differ by a dollar from rounded totals. The exact
components reconcile within $0.0000001/year for all 36 saved cost cells.
The figure is `costs/household_cost_breakdown.png`, with a matching SVG.

The vehicle purchase premium is $15,876: $49,115 for the EV plus a $1,400 charger,
compared with $34,639 for ICE. Both use a 12-year service life. At 7%, that
premium contributes $1,998.82/year before the initial credit. The one-time
$7,500 credit contributes $643.58/year over the 25-year study.

The comparison charges equipment capital to both households. It is not a
comparison against keeping an already-paid-off gas car and appliances forever.
The decomposition does not attribute combined energy savings to individual
appliances; their demands and system-sizing responses interact.

## Bounded input checks

**Vehicle purchase premium.** The implemented values reproduce DOE's 2022
midsize-SUV benchmark, adjusted by the model's existing 1.034 factor.
The newer [DOE 2025 report, Table ES-3](https://www.energy.gov/sites/default/files/2025-01/2025.01.13_DOE_Incremental_Cost_Report_for_publication.pdf)
compares an $11,000 vehicle premium with $14,600 in the earlier report, both
in 2024 dollars. Apply their ratio to the model's $14,476 vehicle-only premium.
Retain the charger, household demand, service life, and initial credit.

This sensitivity reduces annual cost by **$449.40** in each county. The remaining
premiums are **$568.95, $650.29, and $494.52**, respectively. This is a ratio
sensitivity, not a new price survey or a whole-model inflation adjustment.
It improves electrification economics materially but does not reverse these
three classifications on its own.

**Vehicle life.** Changing both vehicle capital lives from 12 to 15 years reduces
the annual premium by $255.72. This is an illustrative sensitivity, not a newly
verified retirement age. It retains initial credits and operating allowances.
Remaining premiums are $762.62, $843.97, and $688.20. The cited source for the
central 12-year value concerns vehicle batteries, so whole-vehicle life remains
a declared assumption.

**Heat-pump purchases.** All six saved purchase costs match the tracked county
median inputs. Space-heating costs are $20,855, $19,800, and $16,415.15; water
heating is $7,977, $5,016.54, and $8,885. The
[TECH dataset description](https://techcleanca.com/heat-pump-data/heat-pump-data-visuals/)
identifies paid incentive applications as its population. These are installation
project costs, not equipment-only prices or a sample of every household.
The original export date and aggregation receipt remain unresolved.

For an interpretable threshold, reducing both electric heat-pump purchase prices
by the same proportion would close the remaining all-credit premium at about
**32.2%, 40.4%, and 34.0%**, respectively. Loads, lives, other costs, and the
still-binding $2,000 credit cap stay fixed. These thresholds are not evidence
that those discounts are available. Changing only the EV-plus-charger purchase
cost would require an additional $8,088, $8,734, or $7,497 reduction, respectively.

**Vehicle service and charging.** All three saved EV profiles contain
**1,682.33 kWh/year at home** and **3,540.21 kWh/year across all source charging
locations**. The residential share is **47.52%**. ICE gasoline costs assume
12,000 miles/year. If the all-location energy represented 12,000 miles, it would
imply 29.50 kWh/100 miles. This conditional calculation does not establish actual
mileage, the source fleet's efficiency, or equal service with the modeled SUV.

The current home-charging boundary remains intentional. No public-charging cost
or extra home load was added. Charging sources represent a fleet mixture, while
capital represents a generic BEV SUV. Therefore, use the narrower description
“modeled household costs under specified vehicle inputs,” rather than a complete
equal-mileage vehicle ownership comparison. A future demand normalization would
require a separate reviewed input change and new solar/storage optimization.

## Why storage still needs a cost check

The diagnostic fixes a qualifying battery at 3 kWh for both households in
Alameda and Los Angeles. Solar capacity, battery power, and hourly dispatch remain
free. The initial purchase receives 30% at year 1; the year-15 replacement receives
no credit. Year 25 retains one-third of gross battery cost as remaining value.

At the central $1,460.64/kWh, a 3 kWh battery costs $4,381.92 initially.
The initial credit reduces only the first purchase. It does not reduce the
replacement price, so the credit's proportional effect on lifetime capital cost
is smaller than 30%. Annualized contributions are $376.01 for the initial purchase,
$136.29 for replacement, -$23.09 for remaining value, and -$105.42 for the credit.
The net is **$383.78/year**, a **21.55%** reduction from lifetime capital cost
without the credit. This independently reproduces the intended accounting.

The lower-price check uses the **$999/kWh** marketplace quote median reported by
[EnergySage in April 2025](https://www.energysage.com/press/energysage-marketplace-intel-report-20/).
[NREL's Spring 2025 update, slide 62](https://docs.nlr.gov/docs/fy25osti/95135.pdf)
identifies these storage prices as gross costs. Quotes differ from completed
installations and are not specific to a 3 kWh system in either county.
This is a sensitivity; the central cost remains unchanged.

At a fixed eligible capacity, storage price enters the objective as a constant.
The $999 calculation therefore reuses the optimized PV and dispatch, adjusts
initial and replacement costs and remaining value, and retains the solver gap.
This does not establish the best battery size at the lower price. A winning
candidate can establish that some storage is worthwhile. A losing candidate
cannot establish that every other size loses.

The initial Alameda gas attempt at 300 seconds failed the $5/year acceptance
limit with an $8.15/year gap. It remains archived as rejected. A separate run
uses 600 seconds and the same $5/year requirement. Alameda gas passes with a
$2.76 gap; Alameda electric remains rejected with a $6.79 gap. No rejected
design enters the accepted pilot or the diagnostic cost decomposition.

The diagnostic also captures the initial relaxed model's lower-cost certificate.
This optimistic model omits meter-direction restrictions, so its lower bound
also applies to every physically feasible fixed-battery design. Subtracting the
existing feasible solar-only cost gives a conservative lower bound on the
battery penalty. No relaxed dispatch is presented as a physical design.
A positive bound establishes a loss; a negative bound remains inconclusive.
The separate bound checks take about two seconds each.

For Alameda, even the optimistic bound puts the 3 kWh battery at least
$150.95/year above solar alone for gas and $142.28 for electric. Repricing to
$999/kWh still leaves penalties of at least $29.65 and $20.99. The accepted
gas dispatch narrows its central-price penalty to $170.04–$173.79/year and its
lower-price penalty to $48.75–$52.50/year. Its added battery capital is $383.78,
additional solar capital is $99.42, and its bill saving is $310.40 per year.

Los Angeles gas now has an accepted physical design within $0.90/year of its
fixed-capacity optimum. Its battery adds $383.78/year of capital, extra solar
adds $120.73/year, and the electricity bill falls by $471.46/year. At the central
price, the annual penalty is $33.05 (bounded between $32.15 and $33.86).
At $999/kWh, the same fixed-capacity optimization saves about $88.25/year;
the conservative saving interval is $87.43–$89.15/year against optimal solar alone.
This establishes a positive storage benefit at the lower price, without claiming
that 3 kWh is the unrestricted optimal size.

The fixed-3-kWh break-even price for this gas household is bounded at approximately
$1,331–$1,339/kWh. That is only about 9% below the central $1,461/kWh input.
The result therefore depends materially on the equipment-price assumption.
It does not establish that a real 3 kWh product is available at either quote benchmark.

Los Angeles electric also passes within $1.80/year. Battery capital adds
$383.78/year, extra solar adds $107.38/year, and the bill falls by $459.19/year.
The central-price penalty is $31.98, bounded at $30.17–$32.97. At $999/kWh,
the same candidate saves $89.32/year, with a conservative $88.32–$91.12 range.
Its fixed-capacity break-even price is bounded at approximately $1,335–$1,346/kWh.

| County / household | Central-price annual cost change | At $999/kWh | Evidence |
|---|---:|---:|---|
| Alameda / gas | +$173 | +$52 | Accepted physical dispatch; $2.76 solver gap |
| Alameda / electric | At least +$142 | At least +$20 | Optimistic lower bound; no physical design accepted |
| Los Angeles / gas | +$33 | -$88 | Accepted physical dispatch; $0.90 solver gap |
| Los Angeles / electric | +$32 | -$89 | Accepted physical dispatch; $1.80 solver gap |

Values compare fixed 3 kWh storage, with PV and dispatch optimized, against
solar alone. Negative means a saving. Price repricing preserves the original
fixed-capacity cost certificate. It does not establish new unrestricted optimal
capacities. The full household comparison remains at its original prices;
the table does not claim a revised electrification premium.

## Validation and reproduction

The existing focused baseline passed **233 tests** before the diagnostic change.
The expanded relevant suite passes **320 tests**, including 21 new diagnostic
tests. No existing test or expected result changed. A mistyped cents expectation
in one new test was corrected after checking the independent annuity calculation.

From the committed model checkout, run:

```sh
python scripts/analyze_federal_credit_pilot.py \
  --pilot-dir analysis_results/runs/2026-09-21_ca1214a_federal_pilot_gap5 \
  --output-dir /tmp/new-pilot-cost-breakdown
```

The script refuses an existing output directory. Its manifest records source
hashes. It selects one incentive row, independently discounts gross equipment
costs and initial credits, separates vehicle fuel from upkeep, and reconciles
every item with the saved report. Malformed and incomplete ledgers fail.
The isolated `input_check.py` records the source hashes and analytical input
checks. The storage drivers record model files, original dispatch, tariff source,
solver certificates, full dispatch, physical checks, bill replay, and independent
capital arithmetic. Their run records distinguish rejected attempts.
Three new physical dispatches pass these checks, with zero bill-replay
difference. Four independently regenerated initial-relaxation certificates
bound the fixed-battery cost. The diagnostic captures each first certificate
without changing any model coefficient or constraint. It restores the solver
method after the capture, including on error; dedicated tests check this behavior.
Alameda gas took 385 seconds, Los Angeles gas 603 seconds, and Los Angeles
electric 79 seconds. Alameda electric's 600-second attempt remains rejected;
its decisive loss bound avoids further retries. Solver limits allow finalization
overhead, so elapsed time can exceed the declared solve budget.

## Research interpretation

The cost decomposition supports the pilot's accounting and explains its positive
electrification premiums. The newer vehicle-price sensitivity does not reverse
the household ranking alone. Lower battery pricing can reverse the Los Angeles
storage choice, so zero storage must remain conditional on the declared price. Price, equipment-life, and transport assumptions still limit
generalization. Three counties do not establish a statewide finding.

Statewide federal-credit runs and the NEM 2 pilot remain separate next stages.
Before either stage, review this diagnostic and decide whether to retain the
declared price benchmarks with sensitivities or approve a specific input update.
The home-charging scope can remain bounded, with its interpretation stated clearly.
