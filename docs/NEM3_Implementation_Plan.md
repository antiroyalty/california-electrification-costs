# NEM 3.0 (Net Billing Tariff) — Implementation Plan

This document describes how to implement the California NEM 3.0 (aka Net Billing Tariff) across the three IOUs — PG&E, SCE, and SDG&E — within this repository’s pipeline.

The goal is to correctly compute annual electricity costs for scenarios with solar + storage by applying:
- Retail TOU rates to imports (what the customer pays),
- ACC export rates to exports (what the customer earns),
- Non‑bypassable charges (NBCs) that exports cannot offset,
- Fixed/minimum monthly charges and monthly carry‑forward of export credits,
- Optional year‑end Net Surplus Compensation (NSC) for unused credits.

## Current Pipeline (quick recap)
- Step 9 (solar + storage): writes `sam_optimized_load_profiles_<county>.csv` with flows:
  - `Load Profile`, `System to Load` (PV→Load), `Battery to Load`, `Grid to Load`, `System to Battery` (PV→Battery), `Grid to Battery`, `Battery SOC`, etc.
- Step 10 (rates prep): writes `loadprofiles_for_rates_<county>.csv` with hourly columns:
  - `default.electricity.kwh`, `solarstorage.electricity.kwh` (currently Grid→Load only), and gas.
- Step 12 (electricity bills): multiplies hourly energy by tariff; writes `RESULTS_electricity_annual_costs_*` with rows `{scenario}` and `{scenario}.solarstorage`.
- Step 13 (totals): combines electricity + gas to `RESULTS_total_annual_costs_*` per county.

Today, the solar+storage electricity bill uses only residual imports (Grid→Load) and ignores export credits. NEM 3.0 requires modeling hourly exports and applying ACC export rates and monthly accounting.

## NEM 3.0 mechanics to model
- Imports are billed at retail TOU rates (energy component + NBC component).
- Exports are credited at ACC (Avoided Cost Calculator) export rates by month/hour.
- Exports cannot offset NBCs or fixed charges (non‑bypassable); credits apply only against the energy portion of the import bill.
- Monthly carry‑forward: if monthly export credits exceed energy charges, remaining energy credit carries to future months.
- Year‑end true‑up (optional NSC): remaining credits may be cashed out at an NSC $/kWh rate or forfeited (model‐configurable).
- Minimum monthly bill or fixed charges (utility‑specific) apply regardless of exports.

## Proposed changes by step

### 1) Step 9 — add PV generation and export columns
Add the following columns to `sam_optimized_load_profiles_<county>.csv` (both `step9_my_own_solar_storage.py` and the PySAM variants as feasible):
- `PV AC (kWh)`: hourly PV AC generation time series (already computed internally as `solar_gen`).
- `PV to Grid (kWh)`: hourly net PV export to grid. For the DIY dispatch, this is
  `max(0, PV_AC − System to Load − System to Battery)`.

Keep the core energy balance identity unchanged:
`Load Profile = System→Load + Battery→Load + Grid→Load`.

Rationale: downstream steps need explicit PV exports to compute ACC credits without re‑deriving PV generation.

Battery exports (optional, default OFF):
- Add a new column `Battery to Grid (kWh)` when battery export is enabled.
- Gate with a module‑level toggle, e.g., `ENABLE_BATTERY_EXPORT = False`.
- Discharge split per hour: `Battery to Load = min(target_discharge, residual_load)` and
  `Battery to Grid = max(0, target_discharge − Battery to Load)`.
- Recommended policy: keep `GRID_CHARGING_ENABLED = False` when exporting to avoid grid‑charged arbitrage.

Provenance tracking (recommended if future grid charging is enabled):
- Track two SOC pools: PV‑charged and grid‑charged energy.
- Only allow export credits from the PV‑charged pool; disallow export of grid‑charged energy (compliance).

Guardrails and diagnostics:
- Optional export cap by interconnection/inverter rating `EXPORT_LIMIT_KW` applied to `(PV to Grid + Battery to Grid)`.
- Validate non‑negativity; assert `PV_AC ≥ System→Load + System→Battery + PV→Grid ± ε`.
- Log hourly/annual sums for PV generation, PV→Load, PV→Battery, PV→Grid, Battery→Load, Grid→Battery for QA.

Export potential and eligibility (what “could” be exported):
- Define an instantaneous export cap (kW):
  - `export_cap_kw = min(INVERTER_AC_RATING_KW, EXPORT_LIMIT_KW)` (defaults to inverter rating if no separate limit).
- Compute hourly export budget (kWh): `export_budget = export_cap_kw * Δt` (Δt = 1 hour here).
- PV export potential (kWh):
  - `pv_export_potential = max(0, PV_AC − System→Load − System→Battery)`.
  - Actual PV export: `pv_to_grid = min(pv_export_potential, export_budget)`; reduce `export_budget -= pv_to_grid`.
- Battery export potential (eligible energy only):
  - Track SOC provenance: `soc_pv` (PV‑charged) and `soc_grid` (grid‑charged).
  - Eligible energy (kWh): `eligible_kwh = max(0, (soc_pv − MIN_SOC_FRAC) * BATTERY_CAPACITY_KWH)`.
  - Power limit (kWh): `power_kwh = P_DISCHARGE_MAX_KW * Δt`.
  - Not required by load: we already satisfied load; battery export can use remaining discharge headroom.
  - Actual battery export: `batt_to_grid = min(eligible_kwh * ETA_DISCHARGE, power_kwh, export_budget)`; decrement SOC buckets accordingly.
- Final combined export (kWh): `export_kwh = pv_to_grid + batt_to_grid`.
- If battery export is disabled, set `batt_to_grid = 0` and skip SOC provenance.

### 2) Step 10 — include export series for rate evaluation
Extend `loadprofiles_for_rates_<county>.csv` with a new column for solar+storage cases:
- `solarstorage.electricity.export.kwh` — computed as `(PV to Grid + Battery to Grid)` from Step 9.
  If `Battery to Grid` is absent (older runs or export disabled), treat it as 0.0.

No change to the `default` series (no PV export).

Optional additional outputs (for diagnostics and policy analysis):
- `solarstorage.electricity.export.eligible.kwh` — eligible export credited under NEM 3.0 (PV + PV‑charged battery only).
- `solarstorage.electricity.export.ineligible.kwh` — any export derived from grid‑charged energy (should be 0 if guarded).

### 3) New helpers — NEM 3.0 core logic and data
Add two helper modules under `helpers/`:

- `helpers/nem3_export_rates.py`
  - Provides ACC export prices for each IOU by month and hour.
  - Data model:
    ```python
    # dollars per kWh
    NEM3_EXPORT_RATES = {
      'PG&E': {1: [24 hourly $/kWh], 2: [...], ..., 12: [...]},
      'SCE':  {1: [...], ..., 12: [...]},
      'SDG&E':{1: [...], ..., 12: [...]},
    }
    ```
  - Source can be embedded dicts to start, with an optional CSV loader (e.g., `data/nem3_export_rates/PGE_2025.csv` with 12×24 matrix).

- `helpers/nem3_helpers.py`
  - Implements bill calculation:
    - NBC split per IOU (configurable cents/kWh).
    - Retail import pricing from existing TOU plans (reusing `helpers/electricity_rate_helpers.py`).
    - Monthly buckets using timestamps.
    - Credit carry‑forward across months (credits only apply to energy portion, not NBC/fixed).
    - Minimum bill / fixed charge handling per month.
    - Optional NSC at year‑end.
  - Proposed API:
    ```python
    from dataclasses import dataclass
    from typing import Sequence

    @dataclass
    class NEM3Options:
        nbc_cents_per_kwh: float  # portion of import rate that is non-bypassable
        fixed_charge_monthly: float | None = None  # if not in plan
        minimum_bill_monthly: float | None = None
        true_up_month: int = 12  # 1..12 (billing year end)
        nsc_dollars_per_kwh: float | None = 0.0  # payout for leftover credits

    def compute_nem3_bill(
        timestamps: Sequence[pd.Timestamp],
        import_kwh: Sequence[float],
        export_kwh: Sequence[float],
        retail_rate_plan: dict,  # from RATE_PLANS[utility][plan]
        export_rates_month_hour: dict[int, list[float]],  # 12->24 ACC $/kWh
        options: NEM3Options,
    ) -> dict:
        """Return monthly breakdown and annual total: {
             'monthly': [{'energy_charge':..., 'nbc':..., 'fixed':..., 'export_credit':..., 'total':...}, ...],
             'annual_total': float
        }"""
    ```

### 4) Step 12 — add NEM 3.0 billing path
Enhance `step12_evaluate_electricity_rates.py` to compute, per county/tariff, the solar+storage bill using NEM 3.0:
- Inputs and mapping:
  - Imports: `solarstorage.electricity.kwh` = `Grid to Load` from Step 9.
  - Exports: `solarstorage.electricity.export.kwh` = `PV to Grid` [+ `Battery to Grid` if enabled].
  - Timestamps: from `loadprofiles_for_rates` column `timestamp`.
- For each IOU tariff:
  - Compute retail import charges with existing TOU logic.
  - Split out NBC portion via `NEM3Options.nbc_cents_per_kwh`.
  - Compute ACC export credits by month/hour.
  - Apply monthly carry‑forward, minimum bill/fixed charges, and optional NSC.
- Outputs:
  - Keep existing rows (`{scenario}`, `{scenario}.solarstorage`).
  - For `{scenario}.solarstorage`, record the NEM 3.0 bill.
  - Optionally also include `{scenario}.solarstorage_retail_only` for comparison (imports at retail, no export credit), guarded by a CLI flag.

CLI additions (optional):
- `--nem3` (default true) to enable NEM 3.0 for solarstorage rows.
- `--nsc-rate`, `--nbc-cents`, `--min-bill`, `--fixed-charge` to override per run.

### 5) Step 13 — totals
No schema change. Totals will naturally include the NEM 3.0 electricity costs when `scenario.solarstorage` reflects NEM 3.0 results. Existing downstream consumers (Step 15/18/21) continue to work.

Optionally, if we preserve both variants, Step 13 can include both rows so analysts can choose between `scenario.solarstorage` (nem3) and `scenario.solarstorage_retail_only`.

## Utility‑specific notes

The exact values should be parameterized; below are modeling hooks to support each IOU.

- PG&E
  - Tariffs in repo: `E-TOU-C`, `EV2-A`, `E-ELEC` (import pricing already modeled).
  - Minimum bill: ~$10/month (subject to CARE/FERA and current proceedings).
  - NBCs: configure a cents/kWh value (e.g., ~2–3¢/kWh) that imports must always pay.
  - ACC export: provide 12×24 $/kWh table in `NEM3_EXPORT_RATES['PG&E']`.

- SCE
  - Tariffs in repo: `TOU-D-4-9PM`, `TOU-D-5-8PM`.
  - Minimum bill: ~$10/month; daily fixed charge present in current plan data.
  - NBCs: configure cents/kWh similar to PG&E.
  - ACC export: 12×24 $/kWh table in `NEM3_EXPORT_RATES['SCE']`.

- SDG&E
  - Tariff in repo: `TOU-ELEC` (already has $16/month fixed charge in data).
  - Minimum bill: modeled via fixed charge; still apply NBCs to imports.
  - ACC export: 12×24 $/kWh table in `NEM3_EXPORT_RATES['SDG&E']`.

## Accounting details

- Hour granularity: use the pipeline’s hourly series (8760 points). Map each hour to (month, hour‑of‑day) for ACC lookup.
- Monthly buckets: group by calendar month; maintain a running energy‑only credit balance. Credit cannot reduce NBCs or fixed charges.
- Minimum bill: apply per month to the sum of (energy charge after credits + NBC + fixed). If computed monthly total < min bill, set it to min bill.
- Carry‑forward: any unused energy credit after a month rolls to the next month.
- True‑up: at `options.true_up_month`, cash out remaining credit at `options.nsc_dollars_per_kwh` (or 0 if not configured). Reset credit thereafter.

## Testing plan

- Unit tests in `tests/` for `helpers/nem3_helpers.py`:
  - Import/export synthetic profiles with known results.
  - Validate monthly carry‑forward, minimum bill behavior, NBC isolation, and NSC.
- Golden tests for one county across each IOU using a tiny 48‑hour sample snapshot.
- Integration smoke test: one scenario through Steps 9–13 with `--nem3`, confirming `scenario.solarstorage` decreases by export credits vs retail‑only.

## Implementation steps (sequencing)

1. Step 9: write `PV AC (kWh)` and `PV to Grid (kWh)` columns.
2. Step 10: add `solarstorage.electricity.export.kwh` to `loadprofiles_for_rates`.
3. Add `helpers/nem3_export_rates.py` with ACC tables (seed with placeholders; load from CSVs when available).
4. Add `helpers/nem3_helpers.py` with `NEM3Options` and `compute_nem3_bill`.
5. Step 12: add NEM 3.0 path for `{scenario}.solarstorage` (behind `--nem3` flag defaulting to on).
6. Tests: unit + small integration; update README with a short “Enable NEM 3.0” section.

## Example (pseudo‑code) for monthly accounting

```python
credit = 0.0  # energy-only dollars
annual_total = 0.0
for month in 1..12:
    imp_kwh = hourly_import[month]
    exp_kwh = hourly_export[month]
    imp_rate = retail_energy_rate[month,hour]  # excluding NBC portion
    nbc_rate = options.nbc_cents_per_kwh / 100.0
    acc_rate = export_rates_month_hour[month][hour]

    energy_charge = sum(imp_kwh[h] * imp_rate[h] for h in hours)
    nbc_charge    = sum(imp_kwh[h] * nbc_rate    for h in hours)
    export_credit = sum(exp_kwh[h] * acc_rate[h] for h in hours)

    # apply credit only to energy portion
    energy_net = max(0.0, energy_charge - credit - export_credit)

    month_subtotal = energy_net + nbc_charge + fixed_charge_monthly
    month_total = max(month_subtotal, minimum_bill_monthly)
    annual_total += month_total

    # update carry-forward credit (leftover after covering energy_charge)
    new_credit = max(0.0, (credit + export_credit) - energy_charge)
    credit = new_credit

# Year-end true-up
if options.nsc_dollars_per_kwh and credit > 0:
    # Convert remaining $ credit back to kWh at average export rate for the year, or
    # treat credit as $ and pay at NSC (implementation choice). Simpler: cash out as $ directly.
    pass
```

(Implementation will keep credit units consistent — simplest is to keep credits in dollars throughout.)

## Backward compatibility
- Default behavior can keep `{scenario}.solarstorage` as NEM 3.0; set `--nem3=false` to revert to retail‑only imports.
- Existing columns and file paths remain unchanged; only a new export column is added in Step 10.
- Downstream steps (Step 13/18/21) continue to function; plots will reflect NEM 3.0 once Step 12 writes the updated solarstorage rows.

---
Questions or preferences (for reviewers):
- Provide ACC tables in‑repo as constants vs CSVs under `data/nem3_export_rates/`?
- Default NSC handling: cash‑out at IOU‑specific NSC vs assume 0?
- Keep both `{scenario}.solarstorage` (NEM3) and `{scenario}.solarstorage_retail_only` for comparison?

## Sources and validation

Authoritative CPUC policy and export values
- Net Billing Tariff (NEM 3.0) decision: CPUC Decision D.22‑12‑056 (R.20‑08‑020). Establishes hourly export compensation based on ACC, monthly crediting with carry‑forward, and that export credits cannot offset non‑bypassable charges or fixed/minimum charges.
  - PDF: Search CPUC “Decision D.22‑12‑056” in proceeding R.20‑08‑020 or use the CPUC Decisions repository link for the published PDF.
- CPUC Net Billing Tariff overview and FAQ: high‑level mechanics (ACC export, monthly accounting, true‑up).
  - https://www.cpuc.ca.gov (navigate: Energy > Solar > Net Billing Tariff)
- CPUC Avoided Cost Calculator (ACC) portal: hourly export values and documentation for the applicable year.
  - https://www.cpuc.ca.gov/industries-and-topics/electrical-energy/demand-side-management/avoided-cost-calculator

Retail import pricing (IOU tariff PDFs)
- PG&E Electric Tariff Book (PDFs used in this repo):
  - E‑TOU‑C: https://www.pge.com/tariffs/assets/pdf/tariffbook/ELEC_SCHEDS_E-TOU-C.pdf
  - EV2‑A:  https://www.pge.com/tariffs/assets/pdf/tariffbook/ELEC_SCHEDS_EV2%20(Sch).pdf
  - E‑ELEC:  https://www.pge.com/tariffs/assets/pdf/tariffbook/ELEC_SCHEDS_E-ELEC.pdf
- SCE Tariff Book (find “Schedule TOU‑D (Domestic)”, 4‑9 pm and 5‑8 pm variants):
  - https://www.sce.com/regulatory/tariff-books
  - Download the current PDF for Schedule TOU‑D for the model year and record its effective date.
- SDG&E Tariffs (find “Schedule TOU‑ELEC”, “TOU‑DR1” as applicable):
  - https://www.sdge.com/rates-and-regulations/current-and-effective-tariffs
  - Download the current PDF for the model year and record its effective date.

Non‑bypassable charges (NBCs), fixed/minimum charges
- NBCs are payable on imports and not offsettable by export credits under NBT (see D.22‑12‑056 and IOU NBT tariffs).
- Fixed/minimum charges are specified in each tariff schedule above; model them per the effective PDF.

Paired storage export eligibility (Rule 21 / NBT implementation)
- Under NBT, export from storage is eligible only to the extent the storage was charged by on‑site renewable generation (not the grid). IOUs operationalize this via Rule 21 interconnection, metering, and program rules.
  - CPUC Rule 21 (Interconnection): https://www.cpuc.ca.gov (navigate: Energy > Electric Rule 21)
  - IOU paired‑storage/NBT guidance pages for PG&E/SCE/SDG&E (interconnection program sites).

Customer‑facing “Solar Billing Plan” (useful validation aids)
- PG&E Solar Billing Plan (NBT):
  - https://www.pge.com (navigate: Residential > Solar > Solar Billing Plan)
- SCE Solar Billing Plan:
  - https://www.sce.com (navigate: Residential > Solar > Solar Billing Plan / Net Billing Tariff)
- SDG&E Solar Billing Plan:
  - https://www.sdge.com (navigate: Residential > Solar > Solar Billing Plan)

Model governance and data provenance
- Store import tariff tables and export ACC tables with `effective_on` metadata (YYYY‑MM‑DD) alongside the PDFs.
- Pin the model year (e.g., 2025) and ensure tariff/ACC sources correspond to that year.
- Add a small validation harness comparing one county’s bill to each IOU’s public estimate/calculator, where available.

### Pinned Sources Manifest (example `sources.yaml`)

Below is an example manifest you can commit to the repo (e.g., `docs/sources.yaml`) to lock model inputs to specific, verifiable documents. Update URLs/effective dates as needed for your model year.

```yaml
model_year: 2025

cpuc:
  nem3_decision:
    id: D.22-12-056
    proceeding: R.20-08-020
    # Official PDF link for the published decision (verify on CPUC’s docket site):
    pdf_url: "https://docs.cpuc.ca.gov/"  # replace with the specific PublishedDocs URL
    overview_url: "https://www.cpuc.ca.gov"  # Net Billing Tariff overview/FAQ landing

acc_exports:
  # ACC-based hourly export values used for NBT export compensation
  year: 2025
  official_portal_url: "https://www.cpuc.ca.gov/industries-and-topics/electrical-energy/demand-side-management/avoided-cost-calculator"
  tables:
    pge:
      local_path: data/nem3_export_rates/PGE_ACC_2025.csv
      notes: "12x24 $/kWh table, local copy from ACC/NBT filings"
    sce:
      local_path: data/nem3_export_rates/SCE_ACC_2025.csv
    sdge:
      local_path: data/nem3_export_rates/SDGE_ACC_2025.csv

retail_tariffs:
  pge:
    - plan: E-TOU-C
      effective_on: 2025-02-01  # example; set to actual PDF effective date
      pdf_url: "https://www.pge.com/tariffs/assets/pdf/tariffbook/ELEC_SCHEDS_E-TOU-C.pdf"
    - plan: EV2-A
      effective_on: 2025-02-01
      pdf_url: "https://www.pge.com/tariffs/assets/pdf/tariffbook/ELEC_SCHEDS_EV2%20(Sch).pdf"
    - plan: E-ELEC
      effective_on: 2025-02-01
      pdf_url: "https://www.pge.com/tariffs/assets/pdf/tariffbook/ELEC_SCHEDS_E-ELEC.pdf"
  sce:
    - plan: TOU-D-4-9PM
      effective_on: 2025-02-01
      landing_url: "https://www.sce.com/regulatory/tariff-books"
      pdf_url: ""  # paste direct Schedule TOU-D PDF for the effective date
    - plan: TOU-D-5-8PM
      effective_on: 2025-02-01
      landing_url: "https://www.sce.com/regulatory/tariff-books"
      pdf_url: ""
  sdge:
    - plan: TOU-ELEC
      effective_on: 2025-02-01
      pdf_url: "https://www.sdge.com/sites/default/files/regulatory/2-1-25%20Schedule%20TOU-ELEC%20Total%20Rates%20Table.pdf"
    - plan: TOU-DR1
      effective_on: 2025-02-01
      landing_url: "https://www.sdge.com/rates-and-regulations/current-and-effective-tariffs"
      pdf_url: ""

baselines_and_maps:
  pge_baseline_overview: "https://www.pge.com/en/account/rate-plans/how-rates-work/baseline-allowance.html"
  sce_baseline_region_map_pdf: "https://www.sce.com/sites/default/files/inline-files/Baseline_Region_Map.pdf"

nem3_parameters:
  # Non-bypassable charges portion of import rate (dollars per kWh)
  nbc_dollars_per_kwh:
    pge: 0.025   # placeholder; set per current filings
    sce: 0.025
    sdge: 0.025
  fixed_charge_monthly:
    pge: 10.00   # or 0 if modeled in plan tables
    sce: 0.00    # SCE often has a daily basic charge in plan PDFs
    sdge: 16.00  # TOU-ELEC fixed charge already in plan
  minimum_bill_monthly:
    pge: 10.00
    sce: 10.00
    sdge: 0.00
  true_up_month: 12
  nsc_dollars_per_kwh: 0.00  # NSC payout for leftover credits (often 0 for NBT)

interconnection_and_eligibility:
  rule_21_url: "https://www.cpuc.ca.gov"  # Electric Rule 21 landing page
  paired_storage_guidance:
    pge: "https://www.pge.com"   # link to PG&E NBT/paired storage guidance page
    sce: "https://www.sce.com"
    sdge: "https://www.sdge.com"
```
