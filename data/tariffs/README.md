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
the six official inputs. The builder rejects missing hours, duplicates,
conflicting MIDAS values, negative values, and any schedule that does not have
exactly 576 observations per component.

`acc_plus_rates.csv` stores the separate flat ACC Plus adders by utility,
interconnection vintage, and customer segment. Sources:

- PG&E Advice 7174-E: https://www.pge.com/tariffs/assets/pdf/adviceletter/ELEC_7174-E.pdf
- SCE Schedule NBT: https://www.sce.com/sites/default/files/custom-files/PDF_Files/ELECTRIC_SCHEDULES_NBT.pdf
- CPUC Net Billing Tariff overview: https://www.cpuc.ca.gov/NEM/

Required import schedules and component splits are sourced from:

- PG&E E-ELEC, effective March 1, 2026: https://www.pge.com/tariffs/assets/pdf/tariffbook/ELEC_SCHEDS_E-ELEC.pdf
- SCE TOU-D Option PRIME, effective June 25, 2026: the official `ELECTRIC_SCHEDULES_TOU-D.pdf` in https://www.sce.com/regulatory/regulatory-information/tariff-books/rates-pricing-choices
- SDG&E EV-TOU-5, effective June 1, 2026: https://www.sdge.com/sites/default/files/regulatory/6-1-26%20Schedule%20EV-TOU-5%20Total%20Rates%20Table.pdf
