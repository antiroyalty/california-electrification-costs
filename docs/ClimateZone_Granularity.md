# County + Climate-Zone Granularity — Design Doc

This document proposes how to incorporate climate-zone granularity, alongside county granularity, throughout the analysis pipeline — especially for NEM 3.0 export compensation that varies by utility/climate zone.

## Objectives
- Preserve county-level results (status quo) while adding parallel climate-zone analysis.
- Select the correct IOU export-rate table (NEM3 Excel) per county via a county→climate-zone mapping.
- Produce zone-level rollups in addition to per-county outputs, so plots and comparisons (Step 18/21) can operate at either level.

## Data Model
- Mapping CSV (new): `NEM3/county_to_climate_zone.csv`
  - Columns: `utility, county_slug, climate_zone`
  - Example rows:
    - `PG&E,alameda,P`
    - `SCE,los-angeles,9`
    - `SDG&E,san-diego,coastal`
  - The climate_zone token must match a sheet/tab name or zone label in your NEM3 Excel files.
- NEM3 Excel files: one per IOU under `NEM3/` (can be nested), with either:
  - One sheet per climate zone (recommended), each containing a 12×24 $/kWh month×hour table; or
  - A long table with columns like `month,hour,rate` that the loader can pivot.

## Sources and suggested mappings (TODO)
- PG&E: Use “Baseline Territories” (P,Q,R,S,T,V,W,X,Y,Z). PG&E publishes territory maps and ZIP→territory lists.
- SCE: Use “Baseline Regions” (5,6,8,9,10,13,14,15,16). SCE publishes a baseline region map and often ZIP lists.
- SDG&E: Depending on the source files, use a single zone or a coastal/inland split; if the Excel provides zone names, use them.

TODO (tracked in code and here): Publish `NEM3/county_to_climate_zone.csv` with IOU-appropriate zones and keep it under version control.

## Implementation Plan (by step)

### Step 9 (PV + storage)
- Inputs: per‑county weather CSV at `data/loadprofiles/<scenario>/<housing>/<county>/weather_TMY_<county>.csv` and the per‑county load profile.
- Irradiance used: the Global Horizontal Irradiance (GHI) column from the weather CSV. No POA/tilt transposition is performed.
- Timestamp alignment: weather is rotated by a fixed `WEATHER_SHIFT_HOURS = 8` to line up with local load timestamps.
- PV model (simple PVWatts‑style approximation):
  - Cell temperature: `Tcell ≈ Tamb + ((NOCT − 20) / 800) × GHI`.
  - Temperature derate: `derate = 1 + γ_PDC × (Tcell − 25°C)`.
  - Hourly AC energy: `AC_kWh[h] = system_capacity_kW × (GHI[h]/1000) × PR_base × derate[h]`.
  - Values are clipped to ≥ 0; inverter clipping is not modeled.
- Sizing: capacity is derived to approximately match annual load from annual GHI (via assumed panel efficiency and PR), then scaled by `PV_SIZE_FRACTION`.
- Important: Step 9 does not choose a geographic point (e.g., county centroid) itself — it uses whatever weather CSV is provided upstream for the county. If you want centroid‑based or climate‑zone‑based weather, generate `weather_TMY_<county>.csv` accordingly (or add an optional override that maps a county to a zone‑canonical weather file).
- Outputs (unchanged): writes `sam_optimized_load_profiles_*.csv` (including `PV AC (kWh)` and, in the exports variant, `Exports to Grid (kWh)`).

### Step 10 (Loads for rates)
- Already writes per county `loadprofiles_for_rates_*.csv`, now including:
  - `solarstorage.electricity.export.kwh` (PV exports, with a safe fallback if column missing).
- No change for climate-zone dimension at this step.

### Step 12 (Electricity rates, NEM 3.0)
- Loader uses `helpers/nem3_export_rates.get_export_rate_table_for_county(base_dir='NEM3', utility, county)` to:
  1) Read `NEM3/county_to_climate_zone.csv` to choose a `climate_zone` for (utility, county_slug).
  2) Load the 12×24 month×hour $/kWh matrix from `NEM3/export_rates/{climate_zone}_{UTIL}.csv` (CSV‑only; no Excel fallback).

Where to introduce the mapping:
- Introduce the county→climate_zone mapping right before Step 12 (i.e., once Steps 9–11 have produced the export/import series).
- Practically, keep the mapping file at `NEM3/county_to_climate_zone.csv` and commit it. Step 12 will read it when `--nem3` is used.
- No changes to Steps 9–11 are required; they remain county‑centric and do not depend on the mapping.

Outputs (unchanged schema):
- Per-county annual electricity costs CSV remains the same. `{scenario}.solarstorage` now reflects NEM3 credits using the county’s climate zone export table.

Optional (zone-level rollups):
- Add a `--group-by {county|zone}` (future work). When `zone`, aggregate the per-county NEM3 billed results across counties in the same (utility,zone).
  - Aggregation default: mean of per-county annual costs (consistent with existing county aggregations).
  - Output path suggestion: `results/electricity_by_zone/RESULTS_electricity_annual_costs_zone_<utility>_<zone>_<ts>.csv`.

### Step 13 (Totals)
- Unchanged for per-county outputs.
- Optional (zone-level rollups): mirror Step 12 aggregation to totals and write `results/totals_by_zone/…` files.

### Step 18/19/21 (Comparisons, EAC)
- Support a switch to operate on zone-level aggregates in addition to counties:
  - `--group-by zone` propagates into collectors (e.g., `collect_eac_components`) to aggregate by (utility,zone) clusters.
  - Plots label axes by `<utility> <zone>` or a friendlier alias.

## CLI/Config Additions
- Step 12: `--nem3` (done), future: `--group-by {county|zone}` and `--mapping NEM3/county_to_climate_zone.csv`.
- Global config (optional): `NEM3/manifest.yaml` listing effective model year, Excel base paths, and a normalized zone name set per IOU.

## File/Code Changes (current status)
- Implemented:
  - Step 9: PV export columns.
  - Step 10: export series in `loadprofiles_for_rates`.
  - Step 12: NEM 3.0 monthly accounting and Excel loader with county→zone selection.
- Planned (this doc):
  - Add official county→zone mapping CSV.
  - Add `--group-by zone` variants for Step 12/13 outputs and Step 18/21 aggregations.

## Data Quality & Validation
- Verify that each (utility,zone) combination loads a correct 12×24 export table from Excel (sanity prints/plots).
- Unit tests:
  - Loader: given a tiny Excel (2 months × 3 hours) and a mapping row, verify the matrix extraction.
  - Accounting: known import/export series across month-boundaries; verify monthly carry-forward, NBC split, fixed/min.
- Cross-check:
  - Compare a county’s NEM3 bill vs. IOU “Solar Billing Plan” calculators (spot checks).

## Open Questions
- Multiple utilities per county? Current pipeline picks a single utility per county. If counties span utilities, a finer-grained service territory map (or building-level utility attribution) would be needed.
- Aggregation choice for zone-level: mean vs. median vs. population-weighted mean? Current code uses mean; expose `--agg` (already supported in some steps).
- Battery exports: if enabled in Step 9, ensure only PV-charged energy is eligible for NEM3 credits (track SOC provenance).

## Example Workflow
1) Create `NEM3/county_to_climate_zone.csv` with rows for the initial counties.
2) Run Steps 9–13 with `--nem3` in Step 12 to compute per-county results.
3) (Future) Run Step 12 with `--group-by zone` to also produce zone-level files.
4) Use Step 18/21 with a `--group-by zone` flag to generate zone-level plots and summaries.

---
Questions or preferences:
- Which zone system do we standardize on for each IOU (exact names from Excel or normalized aliases)?
- Do we prefer mean, median, or population-weighted aggregation for zone rollups?
- Should Step 12/13 write both county and zone outputs in one run by default?
