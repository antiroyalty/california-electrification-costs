# Net Billing Tariff source data

`nbt_export_rates.csv` is the normalized, runtime tariff dataset. Each base
Energy Export Credit schedule has exactly 576 values per component:
12 months × 2 day types × 24 hour-start values. Generation and delivery are
stored separately, with a checked `total` equal to their sum.

The schedules are keyed by utility, calendar billing year, and NBT
interconnection vintage. They are not keyed by county or climate zone. County
continues to be the research unit and selects a representative utility; that
utility selects the schedule.

`source_manifest.json` pins the official source archive paths, hashes, and
URLs. The six exact inputs used for the current normalized dataset are stored
under `sources/nbt_export/`. Rebuild the normalized file with
`scripts/build_nbt_export_schedules.py` and those archived inputs.
`--retrieved-on YYYY-MM-DD` is required and must be the date those local source
files were actually acquired; it is deliberately not inferred from the
rebuild date or filesystem timestamps. The builder requires every input to be
under the manifest's `sources/` directory so a rebuild cannot silently replace
the archived evidence with an external file. It rejects missing hours,
duplicates, conflicting MIDAS values, missing/non-finite/negative rates, source
files whose embedded utility, NBT vintage, or billing year does not match the
requested input slot, and any schedule that does not have exactly 576
observations per component. MIDAS identity and units are verified from
`RateName`, `RIN`,
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

## Annual true-up and net-surplus sources

`true_up_source_manifest.json` indexes the official utility evidence acquired
on 2026-08-10 for the future annual true-up implementation. Raw sources are
kept in two groups:

- `sources/nbt_rules/` contains each utility's complete NBT tariff schedule;
- `sources/nsc/` contains monthly NSC rate tables and supplemental true-up
  methodology.

Every manifest entry records its source URL, archive path, format, and SHA-256
hash. The archived files are research evidence only at this stage: billing
does not read them directly, and no NSC rate or settlement behavior is inferred
until a normalized dataset and explicit true-up primitives are implemented.

`nsc_rates.csv` is the normalized monthly rate dataset derived from the three
archived `monthly_nsc_rates` sources. It contains the eight months available in
the common 2026 snapshot, January through August, with one row per utility and
true-up month. Rates retain five decimal places, declare `USD/kWh`, and carry a
manifest `source_id`. Rebuild it with:

```bash
python scripts/build_nsc_rates.py --year 2026 --through-month 8
```

The normalizer verifies source hashes, document identity, table headers and
units, complete month coverage, finite nonnegative values, and a broad NSC
magnitude guardrail before writing. The dataset itself does not select a
true-up month or perform annual settlement. The current research will select
`2026-08` explicitly when true-up is integrated into billing.
