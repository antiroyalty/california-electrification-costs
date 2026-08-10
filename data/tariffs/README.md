# Net Billing Tariff source data

`nbt_export_rates.csv` is the normalized, runtime tariff dataset. Each base
Energy Export Credit schedule has exactly 576 values per component:
12 months × 2 day types × 24 hour-start values. Generation and delivery are
stored separately, with a checked `total` equal to their sum.

The schedules are keyed by utility, calendar billing year, and NBT
interconnection vintage. They are not keyed by county or climate zone. County
continues to be the research unit and selects a representative utility; that
utility selects the schedule.

`source_manifest.json` pins the official source archive hashes and URLs.
Rebuild the normalized file with `scripts/build_nbt_export_schedules.py` and
the six official inputs. `--retrieved-on YYYY-MM-DD` is required and must be
the date those local source files were actually acquired; it is deliberately
not inferred from the rebuild date or filesystem timestamps. The builder
rejects missing hours, duplicates,
conflicting MIDAS values, missing/non-finite/negative rates, source files whose
embedded utility, NBT vintage, or billing year does not match the requested
input slot, and any schedule that does not have exactly 576 observations per
component. MIDAS identity and units are verified from `RateName`, `RIN`,
`DateStart`, and `Unit`; PG&E identity and USD/kWh units are verified from the
PDF's EEC headers and PG&E content marker. A deliberately broad total-schedule
magnitude guardrail additionally rejects likely 100× currency/unit scaling.

`acc_plus_rates.csv` stores the separate flat ACC Plus adders by utility,
interconnection vintage, and customer segment. Sources:

- PG&E Advice 7174-E: https://www.pge.com/tariffs/assets/pdf/adviceletter/ELEC_7174-E.pdf
- SCE Schedule NBT: https://www.sce.com/sites/default/files/custom-files/PDF_Files/ELECTRIC_SCHEDULES_NBT.pdf
- CPUC Net Billing Tariff overview: https://www.cpuc.ca.gov/NEM/

Required import schedules and component splits are sourced from:

`import_rate_snapshots.json` is the authoritative import-rate input for NBT.
The current research convention is **annualized household economics under
tariffs in effect as of 2026-08-09**: one source-locked snapshot is applied to
the standardized 8,760-hour profile. It is not a reconstruction of tariff
changes within calendar 2026. A requested snapshot date must match an actual
stored snapshot; the catalog never substitutes the nearest available date.

The snapshot contains the required NBT import schedules, their generation and
delivery splits, non-offsettable rates, fixed charges, declared units,
effective dates, and source IDs:

- PG&E E-ELEC, effective 2026-06-01: https://www.pge.com/tariffs/assets/pdf/tariffbook/ELEC_SCHEDS_E-ELEC.pdf
- SCE TOU-D Option PRIME, effective 2026-06-01: the official `ELECTRIC_SCHEDULES_TOU-D.pdf` in https://www.sce.com/regulatory/regulatory-information/tariff-books/rates-pricing-choices
- SDG&E EV-TOU-5, effective 2026-08-01: https://www.sdge.com/sites/default/files/regulatory/8-1-26%20Schedule%20EV-TOU-5%20Total%20Rates%20Table.pdf

`import_source_manifest.json` records the exact source URL, date checked,
effective date, archive path, and SHA-256 hash when a local source copy has
been archived. Runtime validation rejects missing hours, duplicate hour
coverage, missing or non-finite values, generation/delivery mismatches,
undeclared units, and likely cents-versus-dollars errors.
