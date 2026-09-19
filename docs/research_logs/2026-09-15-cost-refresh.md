# Corrected matched household costs — September 15, 2026

Electrification increases solar/storage adoption savings in all 47 modeled
counties. It does **not** generally reduce total household cost under these
assumptions. With independently optimized systems, electric/EV costs less in
8 counties and more in 39. The median cost increase is **$415.54/year**.
Allowing each household to decline adoption gives **7 cheaper and 40 more
expensive**, with the same median increase.

This result replaces the original September 14 whole-household headline of
36 cheaper, 10 more expensive, and one numerically unresolved county.
The adoption and package-effect findings remain unchanged.

## Scope and provenance

The [isolated refresh](../../analysis_results/runs/2026-09-15_668a07e_cost_refresh/README.md)
uses reporting commit `668a07e203da6696d4d9363a42ddf95d6cb03c48`.
It reuses the September 14 optimizations at
`11b7dba00e98280abad0654e04e4367e2b12a4fe` and bills stamped `20260914_16`.
Vehicle-dollar corrections do not affect loads, dispatch, or selected capacities.
No new optimization was needed. The original run remains unchanged.

Both households have a no-solar case and an independently optimized case.
The refresh rebuilds 1,692 ledger rows, all 188 comparison cells, the adoption
figure, and 141 auxiliary Step 15 rows. All county summaries are unweighted.
The assumptions remain 2026 NEM 3, post-ITC costs, a 25-year study, and a 7%
discount rate. See the [maintained methods](../RESEARCH_METHODS.md).

## Corrected costs and comparisons

These are **mean annual household costs**, including annualized equipment,
utility bills, and modeled vehicle operating costs.

| Household | No solar/storage | Optimized solar/storage |
|---|---:|---:|
| Gas appliances + gasoline car | $14,218 | $14,103 |
| Electric appliances + EV | $14,977 | $14,527 |

The next table summarizes each county's paired difference. Positive savings
mean that electric/EV costs less. Numerical bounds cover solver precision and
stored-capacity rounding; they do not cover uncertainty in model assumptions.

| Comparison | Electric/EV cheaper | Electric/EV more expensive | Unresolved | Median electrification savings |
|---|---:|---:|---:|---:|
| Neither household adopts solar/storage | 2 | 45 | 0 | −$745.99/year |
| Both use independently optimized solar/storage | 8 | 39 | 0 | −$415.54/year |
| Each chooses its cheaper solar or no-solar option | 7 | 40 | 0 | −$415.54/year |

Humboldt explains the last classification change. Its optimized electric case
costs $25.57/year less than optimized gas. Gas can instead decline adoption and
save $69.52/year, becoming $43.96/year cheaper than optimized electric.
Free sizing on the required NEM 3 plan does not optimize the choice of rate plan.

**Energy spending is a separate result.** Electricity, natural gas, and gasoline
together cost less after electrification in all 47 counties. Median savings are
$1,682.26/year without solar and $2,138.32/year with optimized solar.
These figures exclude equipment, maintenance, and insurance. Home EV charging
is already included in electricity bills. Public/workplace and fast charging
remain intentionally excluded. Equal travel demand has not been established
between the independent ICE mileage and EV charging inputs.

## Adoption savings and the package effect

![Matched adoption savings](../../analysis_results/runs/2026-09-15_668a07e_cost_refresh/figures/matched_adoption_savings.png)

The package effect remains positive beyond numerical bounds in **47/47 counties**.
Its median is **$307.60/year**, with a mean of $335.82 and a range of $219.59–$584.49.
Median adoption savings remain $39.55/year for gas/ICE and $355.58 for electric/EV.

These savings include the change from the declared retail plan to the required
NEM 3 plan. The preserved attribution diagnostic still reconciles to every
refreshed county's package effect. Its mean contributions are $261.54/year from
the plan change, $74.42 from equipment, and −$0.14 from the billing calendar.
About 78% of the mean effect reflects the plan change. The equipment contribution
is positive in every county. This diagnostic does not establish tariff eligibility
without solar or find each household's cheapest eligible plan.

## Why the total-cost headline changed

The original gas ledger effectively used $1,200/year maintenance, despite an
appliance assumption of $283.65. The corrected ledger uses itemized vehicle costs.
The later input review adopted $656.33/year ICE and $324.33/year EV maintenance,
retaining unrounded values. Alpine now uses the approved $4.589/gallon proxy.

| Change relative to the original September 14 output | Annual household-cost change |
|---|---:|
| Gas/ICE, each county except Alpine | −$543.67 |
| Gas/ICE, Alpine | +$1,727.18 |
| Electric/EV, every county | +$202.77 |

Each change applies identically with and without solar/storage. Electrification
savings fall by $746.44/year in the 46 non-Alpine counties. Alpine's savings
increase by $1,524.41/year after correcting its missing fuel cost. Electric/EV
still costs $930.99/year more there with optimized equipment. The proxy is an
explicit assumption, not an observed Alpine gasoline price.

The incentive-selection fix prevents Step 15 from counting three alternative
vehicle rows as three vehicles. Publication EAC already selected its incentive
case, so that fix does not explain the changed publication headline.

## Implications for the three claims

1. **Storage economics remain unchanged.** Both households select zero battery
   in 46 counties. San Diego selects 0.02 kWh for gas/ICE and 0.03 kWh for electric/EV.
   Median solar sizes remain 1.22 and 1.79 kW. Lead with solar and negligible
   storage at the modeled costs; this comparison cannot isolate NEM 3 from ITC withdrawal.
2. **Revise the electrification claim.** Electrification reduces modeled energy
   spending and increases solar adoption savings. It raises total modeled cost
   in most counties once capital and vehicle costs are included. Use the 7/40
   classification when discussing the cheapest of the two available adoption choices.
   Use 8/39 when explicitly comparing the two optimized NEM 3 systems.
3. **Optimization versus fixed equipment remains a separate result.** This
   refresh does not rebuild the September 11 fixed-system case or update its
   $2,010/year median saving. Do not present that older output as refreshed here.

## Verification and remaining limits

All 1,692 ledger rows match independently calculated expected field changes.
All capital summaries remain unchanged. All 188 cost cells match the expected
vehicle-only changes; adoption savings and package effects change by less than
$0.000000000006/year from floating-point arithmetic. The largest paired numerical
bound remains $3.62/year. All archived and copied source-file hashes remain unchanged.

All 141 auxiliary Step 15 rows reconcile independently to the selected household
bills, one vehicle per incentive case, and the current capital-summary formula.
Its first-column tariff selection and capital numerator remain legacy conventions.
Its $0.01 denominator for nonpositive savings is also a legacy convention.
Treat these payback outputs as auxiliary; they do not replace the matched EAC comparison.

The committed implementation previously passed **911 tests, with 3 skipped**.
After the refresh, **92 focused tests passed**, covering vehicle accounting,
incentive and baseline selection, gasoline inputs, methods, and the comparison.
No production model code or existing test expectations changed in this refresh.
The [completion receipt](../../analysis_results/runs/2026-09-15_668a07e_cost_refresh/complete.json)
records run checks, and the [summary receipt](../../analysis_results/runs/2026-09-15_668a07e_cost_refresh/summary.json)
records the statistics and their inputs. The successful recomputation took about
six seconds; source review and documentation are outside that runtime.

Older three-case reports, sensitivities, and archived county diagnostic pages
retain their original cost inputs. Use this refreshed comparison for current
matched whole-household claims. Model limits in the methods remain applicable;
successful arithmetic checks do not establish empirical validity of every input.
