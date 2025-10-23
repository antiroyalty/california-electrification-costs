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

Rationale: downstream steps need explicit PV exports to compute ACC credits without re‑deriving PV generation.

### 2) Step 10 — include export series for rate evaluation
Extend `loadprofiles_for_rates_<county>.csv` with a new column for solar+storage cases:
- `solarstorage.electricity.export.kwh` — read from Step 9 (`PV to Grid (kWh)`). If missing (older runs), default to 0.0.

No change to the `default` series (no PV export).

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
- Inputs:
  - `solarstorage.electricity.kwh` (imports = Grid→Load),
  - `solarstorage.electricity.export.kwh` (exports),
  - Timestamps (existing `loadprofiles_for_rates` has `timestamp`).
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

