# Federal-credit pilot at fixed NBT rates

The planned three-utility pilot is incomplete. Alameda's three credit comparisons
passed. The four credited Los Angeles and San Diego designs exceeded the accepted
$1/year cost gap. Resolve those solves before expanding statewide.

The pilot tests Alameda, Los Angeles, and San Diego. They represent the model's
PG&E, SCE, and SDG&E assignments. They do not represent all households or all
service territories within those counties.

The model and reporting code are commit
`c3e8e84032842d8ac9cdc6ec34a2ab0c45a505d4`.
The isolated run folder is
`analysis_results/runs/2026-09-20_c3e8e84_federal_pilot/`.
Its `completed_comparisons.json` and `independent_validation.json` identify the
12 validated Alameda cost cells. `pilot_status.json` records incomplete coverage;
there is no full-pilot `complete.json`. Large artifacts remain ignored by Git.

## Accepted results: Alameda only

Solar credits increase chosen PV capacity for both households. Both continue to
select zero storage. The all-credit case uses the same credited designs.

| Household | PV without credits | PV with solar credits | PV generation / annual load, without → with credits | Storage in both cases |
|---|---:|---:|---:|---:|
| Gas appliances and ICE vehicle | 1.23 kW | 1.57 kW | 32.0% → 40.9% | 0 kWh |
| Electric appliances and EV | 1.88 kW | 2.58 kW | 25.6% → 35.3% | 0 kWh |

Annualized modeled household costs are:

| Federal credits | Gas, no solar | Gas, optimized | Electric/EV, no solar | Electric/EV, optimized | Electric minus gas, both optimized |
|---|---:|---:|---:|---:|---:|
| None | $13,949.76 | $13,907.61 | $16,106.05 | $15,793.87 | +$1,886.26 |
| Solar/storage only | $13,949.76 | $13,797.76 | $16,106.05 | $15,620.08 | +$1,822.32 |
| All modeled federal credits | $13,949.76 | $13,797.76 | $15,302.08 | $14,816.11 | +$1,018.34 |

These are dollars per year under the assumptions below. Credits reduce costs but
do not make the modeled electric/EV household cheaper in Alameda. Solar credits
alone lower optimized gas cost by $109.84/year and electric cost by $173.79/year.

The package effect is the electric household's solar-adoption saving minus the
gas household's saving. It rises from $270.04/year without credits to $333.98/year
with solar credits. Adding the appliance credits leaves it at $333.98/year.
Adoption savings include the specified rate-plan change. These are one-county
findings, not new statewide conclusions or a NEM 2 comparison.

## Runtime and unresolved designs

All six no-credit designs passed. Only the two Alameda credited designs passed.
The pilot attempted all 12 planned designs and one explicit retry.

| County / household | No-credit time, accepted | Credited result at the 300-second budget |
|---|---:|---|
| Alameda / gas | 177 s | Accepted in 206 s; gap $0.0124/year |
| Alameda / electric | 47 s | Accepted in 178 s; gap $0.0484/year |
| Los Angeles / gas | 158 s | Rejected; gap $3.1797/year |
| Los Angeles / electric | 49 s | Rejected; gap $4.9797/year |
| San Diego / gas | 29 s | Rejected; gap $59.2129/year |
| San Diego / electric | 32 s | Rejected; gap $94.0487/year |

The Los Angeles gas retry used a 600-second budget and still had a $2.9772/year
gap. Timed-out solver calls took about 316–325 seconds, or 622 seconds for the
retry. The configured solver budget is not a strict process wall-clock limit.

Rejected candidates do not enter the comparison tables. Their results cannot
establish storage or PV choices under credits. A larger time budget alone did not
resolve the tested Los Angeles case. The immediate follow-up is to diagnose the
credited formulation's runtime while preserving its accounting and cost bounds.

## Comparison and assumptions

Each county has a gas-appliance/ICE household and an electric-appliance/EV
household. Each household has a no-solar choice and an optimized solar/storage
choice. Compare three federal-credit cases:

1. No federal credits.
2. Solar/storage credits only.
3. Solar/storage, shared heat-pump, and new-EV credits.

All cases use gross purchase costs and exclude other rebates. Loads, weather,
appliance prices, operating costs, and tariffs stay fixed across credit cases.
The first two cases need separate optimization. The third reuses the second
case's designs because the added appliance credits are constants in sizing.

This is a conditional credit sensitivity. It assumes that all declared purchases
satisfy the applicable purchase dates and other legal requirements. It assumes
full realization. It does not establish eligibility for a typical county
household or reconstruct historical 2025 bills. In particular:

- Apply the 30% credit to eligible initial solar/storage costs. Storage must be
  at least 3 kWh to receive a credit. Receive home credits after one year.
- Declare the electric household's gross space- and water-heating costs eligible.
  Apply the shared $2,000 cap once. No other purchase consumes that cap.
- Declare the electric household eligible for a $7,500 new-EV credit, received
  at purchase. Declare zero heat-pump and EV credits for the gas household.
- Use a 25-year study, 7% real discount rate, and 15-year battery life. Retain
  gross battery replacement cost and one-third remaining value at year 25.
  Apply credits only to initial purchases.
- Retain continuous sizing, the 40 kWh battery ceiling, no grid charging,
  permitted battery exports, the annual export cap, and annual credit settlement.
- Use 2026 NBT billing and interconnection vintage, with the August 9 tariff
  snapshot. Keep the existing retail plans in the no-solar cases.

The unchanged load profiles and corrected appliance ledgers come from the
September 15 cost refresh. The run copies and hashes those inputs. It recomputes
solar/storage designs and utility bills. It does not rebuild the household
loads or replace the archived source files.

The expected annual reduction from adding the EV and heat-pump credits is:

$$
\frac{7500+2000/1.07}{\sum_{y=1}^{25}(1.07)^{-y}}
=\$803.97/\text{year}.
$$

The EV contributes $643.58/year and heat pumps contribute $160.39/year.
Both electric household choices receive these credits. Their identical reduction
therefore cancels from solar-adoption savings and the package effect. The earlier
$944/year EV illustration used a 12-year horizon; it is not this calculation.

## Interpreting the baseline

The earlier statewide comparison included non-federal rebates. This sensitivity
excludes them from every case. Removing their legacy annualized benefit raises
electric-household cost by $1,040.87/year in Alameda, $1,039.22/year in Los Angeles,
and $1,164.14/year in San Diego. This changes both electric household choices
equally, so it does not change their solar-adoption savings.

Do not subtract a new federal-credit benefit directly from the earlier statewide
$415.54 median. That would mix different incentive baselines. This pilot also
cannot establish a new statewide median from three selected counties.

## Validation and reproducibility

The run driver and independent validator are preserved in the isolated folder.
The main driver records the model SHA, runtime versions, input hashes, credit
declarations, solver reports, bill timestamps, and saved accounting records.
It refuses to overwrite a prior run. The README gives reproduction commands.

The regression suite covers optimization, billing, credit amounts, annualization,
county serialization, matched reporting, and methods references. All 491 tests
passed under Python 3.11, NumPy 1.26.4, and SciPy 1.16.1.

For Alameda, saved bills and annual capital costs reconcile with the optimizer.
The largest reporting difference is below $10^{-12}$ dollars/year. The combined numerical
bound is below $0.80/year without credits and $0.061/year with credits.
Independent checks pass for all 12 cost cells: gross appliance costs, initial
credits, battery replacement and remaining value, and single-row vehicle costs.
Saved dispatch also passes energy balance, cyclic state of charge with losses,
battery limits, the annual export cap, and exclusive meter-direction checks.
The additional appliance credits match the independent cash-flow calculation
within $10^{-8}$ dollars/year ($803.97/year when rounded). All recorded model and reused input
hashes matched at collection time. These checks establish numerical consistency,
not empirical equipment performance or household tax eligibility.

Two setup failures remain archived. The first could not serialize an enum in
run metadata. The second detected an incomplete temporary dependency installation
and rejected the older SciPy runtime. Neither accepted a design. The corrected
run driver serializes enums and checks the runtime version before copying inputs.
These changes did not alter model code, the solver backend, or acceptance limits.

The original solve log, retry declaration, and continuation driver remain in
the run folder. The continuation checks input hashes and attempts only the
unattempted designs. It collects only complete county comparisons and records
the excluded cases explicitly. No production model code changed during this unit.

## Scope limits

This pilot preserves the existing home-energy boundary, vehicle input assumptions,
and appliance annualization conventions. It excludes charging away from home and
does not establish equal travel demand. Adoption comparisons include the specified
retail-to-NBT rate-plan change. Solvers bound cost error, not capacity uncertainty.

First resolve the four rejected credited designs and repeat their pilot checks.
Then cover all 47 counties before making statewide claims. Adding state or local
programs, modeling household tax returns, and extending the grid-charging
sensitivity are separate research choices.
