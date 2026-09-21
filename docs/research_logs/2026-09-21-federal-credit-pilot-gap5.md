# Completed federal-credit pilot with a $5/year San Diego limit

The three-county pilot is complete. Both San Diego credited households pass
with the user-approved $5/year cost limit and the existing 300-second budget.
No production algorithm or default changed. The default remains $1/year.
All 36 matched household-cost cells pass independent validation.

This follows the [runtime investigation](2026-09-21-federal-credit-runtime.md).
The model and reporting code are `ca1214aefdf14a5028245e6a3b1e3357164a0abe`.
Outputs are isolated under
`analysis_results/runs/2026-09-21_ca1214a_federal_pilot_gap5/`.
They do not replace the existing statewide publication results.

## Runtime and precision

| San Diego credited household | Solver-run elapsed time | Certified annual cost gap | Solar | Storage |
|---|---:|---:|---:|---:|
| Gas appliances / ICE | 158.2 s | $2.7350 | 2.155 kW | 3.806 kWh |
| Electric appliances / EV | 150.4 s | $4.5495 | 3.275 kW | 6.071 kWh |

Both use `SolverOptions(annual_cost_gap_usd=5, time_limit_seconds=300)`.
Both household types must have the same declared tolerance within a county's
matched comparison. Their complete calls took 159.7 and 151.8 seconds, including
data preparation and saved outputs. Times are single local measurements.

The six no-credit designs retain their accepted $1/year results from `c3e8e84`.
Alameda and Los Angeles credited designs retain the $1/year results validated
in the preceding runtime work, whose model hashes match `ca1214a`. Both San Diego
credited designs were rerun. The rejected $1/year attempts remain archived.

Each household's recorded gap bounds financial suboptimality. It does not bound
capacity differences. The comparison sums the two actual gaps, reporting
reconciliation differences, and serialization allowances. Its conservative
numerical bounds are below $1.63/year in Alameda, $1.81 in Los Angeles, and $7.29
in San Diego for the credited cases. These are not empirical confidence intervals.

## Solar and storage choices

Values are selected feasible designs within their recorded cost bounds.

| County / household | Solar without credits | Solar with credits | Storage without credits | Storage with credits |
|---|---:|---:|---:|---:|
| Alameda / gas | 1.228 kW | 1.573 kW | 0 | 0 |
| Alameda / electric | 1.876 kW | 2.580 kW | 0 | 0 |
| Los Angeles / gas | 1.126 kW | 1.475 kW | 0 | 0 |
| Los Angeles / electric | 1.619 kW | 2.255 kW | 0 | 0 |
| San Diego / gas | 1.325 kW | 2.155 kW | 0.022 kWh | 3.806 kWh |
| San Diego / electric | 1.894 kW | 3.275 kW | 0.031 kWh | 6.071 kWh |

The very small uncredited San Diego batteries are not commercial-sized systems.
Under credits, annual PV generation covers about 40% and 35% of gas and electric
load in Alameda and Los Angeles. It covers 54% and 49% in San Diego.

The San Diego storage finding is larger than numerical uncertainty. The saved
solar-only relaxations bound every feasible solar-only design from below at
$2,183.15/year for gas and $3,414.93/year for electric. The accepted solar/storage
designs cost $2,125.89 and $3,323.66/year. Thus, allowing storage saves at least
$57/year and $91/year, respectively, under these conditional assumptions.
These sizing costs exclude fixed appliance and vehicle costs, which cancel.
The auxiliary bounds establish this solar-only comparison; they are not used
as lower bounds on the unrestricted household optimization.

## Household cost comparisons

The table shows electric/EV minus gas/ICE annual household cost. Both households
choose their own solar/storage design. Positive values mean electric/EV costs more.

| County | No federal credits | Solar/storage credits | All modeled federal credits |
|---|---:|---:|---:|
| Alameda | +$1,886/year | +$1,822/year | +$1,018/year |
| Los Angeles | +$1,953/year | +$1,904/year | +$1,100/year |
| San Diego | +$1,836/year | +$1,748/year | +$944/year |

Credits reduce costs but do not reverse the household cost ranking in these
three counties. Adding the heat-pump and EV credits lowers each electric choice
by $803.97/year: $160.39 for heat pumps and $643.58 for the EV. These are one-time
receipts annualized over the 25-year study, not repeated replacement credits.

Solar/storage credits increase the package effect from $270 to $334/year in
Alameda, $335 to $383 in Los Angeles, and $230 to $318 in San Diego. This effect
is the electric household's solar/storage-adoption saving minus the gas
household's saving. Added appliance credits cancel from that difference because
both electric choices receive them. Adoption savings include the specified
retail-to-NBT rate-plan change.

The figure `federal_credit_pilot.png` shows the household cost differences.
Its SVG, source fingerprints, and plotting driver are in the same run directory.

## Assumptions and claim boundaries

The [initial pilot](2026-09-20-federal-credit-pilot.md) defines the unchanged inputs.
Assume full purchase eligibility and realization: 30% solar/storage credits,
storage eligibility at 3 kWh, a shared $2,000 heat-pump credit, and a $7,500 EV
credit. Home credits arrive after one year; the EV credit arrives at purchase.
Retain the 25-year study, 7% discount rate, 15-year battery replacement, and
one-third remaining battery value at year 25. Grid charging stays disabled.

All cases exclude other rebates and hold 2026 NBT tariffs and vintage fixed.
This is a conditional federal-credit sensitivity, not a reconstruction of 2025
bills or an estimate of typical-household tax eligibility. Do not compare its
cost differences directly with the earlier statewide $415.54 median, whose
incentive baseline included other rebates. Three selected counties do not
establish a statewide result or isolate a tariff's causal effect.

## Validation and reproducibility

All 548 focused regression tests passed. Existing tests and expected results
were unchanged. Independent readback validates 36 cost cells and 12 distinct
optimized designs. It checks gross appliance and vehicle costs, one-time credits,
battery replacement and remaining value, and single-incentive vehicle rows.
Saved dispatch passes load and PV balance, cyclic state of charge with losses,
power limits, no grid charging, exclusive meter direction, and the annual export cap.

All saved NBT bills replay through shared numeric accounting. The two new San
Diego bill differences are exactly zero. Annual capital calculations agree within
$10^{-8}$ dollars. The maximum optimizer/reporting difference across the matched
tables is below $10^{-12}$/year. Physical artifact checks use 0.001 kWh tolerance.
The comparison's recorded numerical bounds reconcile independently to its inputs.

The run directory preserves `validate_sd_electric_gap5.py`,
`validate_sd_gas_gap5.py`, `collect_pilot.py`, `validate_results.py`,
`storage_value_bounds.py`, and `plot_comparison.py`, with their logs and manifests.
Started records identify source and input hashes, Python/NumPy/SciPy versions,
explicit configurations, and reused-file provenance. Collection verified unchanged
model sources and copied inputs. `completed_comparisons.json` and
`independent_validation.json` identify full three-county completion.

The next step is the 47-county federal-credit comparison after reviewing this
pilot. State/local programs, precise commercial battery sizing, and the separate
CBC rounding issue remain outside this review unit.
