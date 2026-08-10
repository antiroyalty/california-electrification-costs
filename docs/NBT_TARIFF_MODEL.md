# Net Billing Tariff model

This repository models the California Net Billing Tariff (often called NEM
3.0) through the `tariffs/` package. There is one runtime path shared by PV and
battery co-optimization and annual bill evaluation.

## Research unit and tariff dimensions

The result remains one representative household per county. A county selects
one representative investor-owned utility through
`CountyServiceAssignment`; the utility selects its tariff. NBT export prices
do not use CEC building climate zones, so climate-zone data is not part of the
export-rate key.

An export schedule is keyed by utility, billing calendar year, interconnection
application vintage, bundled service, month, weekday versus weekend/holiday,
hour start (0 through 23), and generation/delivery component.

Import prices use a separate current-snapshot convention. The headline method
is **annualized household economics under tariffs in effect as of August 9,
2026**. The PG&E E-ELEC, SCE TOU-D-PRIME, and SDG&E EV-TOU-5 tariffs in effect
on that date are applied to the standardized 8,760-hour profile. This produces
a comparable annualized result; it does not claim to reconstruct every tariff
change that occurred during calendar 2026.

The default is a standard, non-equity customer applying for interconnection
and receiving service in 2026. Alternate vintages must be selected explicitly.
The normalized runtime dataset includes NBT 2024 and NBT 2026 vintages at
calendar-year 2026 prices.

## Source and validation contract

Official PG&E price sheets and SCE/SDG&E MIDAS files are normalized by
`scripts/build_nbt_export_schedules.py`. The builder requires exactly 576
observations for every component schedule (12 × 2 × 24), rejects duplicates
and conflicting values, and verifies that total equals generation plus
delivery. `data/tariffs/source_manifest.json` records official URLs and SHA-256
hashes. `data/tariffs/acc_plus_rates.csv` stores the separate flat ACC Plus
adder. `data/tariffs/import_rate_snapshots.json` and
`data/tariffs/import_source_manifest.json` provide the equivalent source and
identity contract for retail import prices.

Runtime lookups do not contain zero-rate, first-plan, missing-hour, or
synthetic-timestamp fallbacks. Missing schedules and malformed profiles raise
errors.

Official references:

- CPUC NBT overview: https://www.cpuc.ca.gov/NEM/
- PG&E EEC price sheets: https://www.pge.com/assets/pge/docs/vanities/PGE-EEC-Price-Sheets.zip
- PG&E Schedule NBT: https://www.pge.com/tariffs/assets/pdf/tariffbook/ELEC_SCHEDS_NBT.pdf
- PG&E Advice 7174-E: https://www.pge.com/tariffs/assets/pdf/adviceletter/ELEC_7174-E.pdf
- SCE Schedule NBT: https://www.sce.com/sites/default/files/custom-files/PDF_Files/ELECTRIC_SCHEDULES_NBT.pdf
- SCE export pricing: https://www.sce.com/customer-service-center/help-center/solar/solar-billing-plan/understanding-export-pricing
- SDG&E export pricing: https://www.sdge.com/solar/solar-billing-plan/export-pricing
- PG&E E-ELEC: https://www.pge.com/tariffs/assets/pdf/tariffbook/ELEC_SCHEDS_E-ELEC.pdf
- SCE residential tariff book (TOU-D Option PRIME): https://www.sce.com/regulatory/regulatory-information/tariff-books/rates-pricing-choices
- SDG&E EV-TOU-5: https://www.sdge.com/sites/default/files/regulatory/8-1-26%20Schedule%20EV-TOU-5%20Total%20Rates%20Table.pdf

## Billing order

The interval meter data must have non-negative, aligned imports and exports,
and cannot import and export in one interval. Each monthly ledger calculates
imports, earns base EEC and ACC Plus separately, applies base EEC only to
eligible volumetric charges, and then applies ACC Plus to remaining energy,
NBC, and fixed charges.

Annual net-surplus settlement is not yet a complete domain primitive. SDG&E
profiles with annual net surplus currently fail loudly because an explicit
net-surplus compensation price is required. The utility-specific true-up work
and the known asymmetry in the current implementation are recorded in
`docs/research_logs/2026-08-09.md`; neither a zero credit nor a retail-credit
carryover should be interpreted as implemented NSC policy.

Generation and delivery components are preserved on both sides of the ledger.
Generation EEC can offset only eligible generation import charges, and delivery
EEC can offset only eligible delivery import charges. Utility-specific NBC and
non-offsettable recovery-charge components remain outside those credit buckets.

## Optimization safeguards

Step 9b and Step 12 resolve the same `TariffBundle`. The optimizer includes
base EEC plus ACC Plus in the marginal export signal, uses the required NBT
import plan (PG&E E-ELEC, SCE TOU-D-PRIME, SDG&E EV-TOU-5), and maps TMY
profile values onto the explicit billing calendar.

Official export prices can exceed retail prices during a small number of
late-summer evening hours. The optimization therefore enforces one meter
direction per interval. It first solves a continuous relaxation, adds tight
binary disjunctions only at intervals that actually import and export
simultaneously, and repeats until the relaxed global optimum is physically
feasible. That stopping condition proves global optimality for the full meter
model: the solution is both a relaxation lower bound and feasible for the full
problem. PuLP constructs the model and SciPy HiGHS solves it.

PV is limited to 150% of modeled annual load. Optimized representative-household
storage is limited to an explicit, configurable 40 kWh, with battery power at
most 1C. The limit supplies tight per-interval import/export bounds and is
recorded in output diagnostics; fixed-size sensitivity runs explicitly override
it with their requested capacity. Coarse 12×24 runs remain the recommended mode
for large low-cost capex grids; full 8,760-hour chronology is used for headline
county solutions and targeted sensitivities.

Step 12 is authoritative for the realized annual bill because it implements
monthly credit banks. Step 9b currently uses marginal hourly credits rather
than embedding the entire monthly ledger in the mixed-integer optimization;
unused-credit saturation should therefore remain visible as an optimization
versus realized-bill diagnostic.

## Tests

Tests pin source hashes, 576-point cardinality, hour conversion, component
arithmetic, official maxima, and ACC Plus values. Behavior and invariant tests
cover calendar classification, strict inputs, credit order, NBC isolation,
meter direction, energy balance, and financial reconciliation. Assumption
tests bound annual energy, credit, rate, and bill magnitudes, and a file-level
integration test exercises TMY calendarization through Step 12.
