# Superseded NBT mapping notes: County → Territory/Zone Mappings

> The NBT export-rate mapping described below is obsolete. Official schedules
> are utility × billing year × interconnection vintage, not county × building
> climate zone. See `NBT_TARIFF_MODEL.md`. Non-NBT baseline territories may
> still be relevant to retail baseline allowances.

This note summarizes where county-to-territory/zone logic shows up in the pipeline, and how to thread CSV-backed mappings through gas/electric retail rates and NEM 3.0 export credits. It also calls out solar irradiance inputs, which are per-county weather rather than climate-zone based.

## Summary of Current Behavior

- NEM 3.0 export credits
  - Uses `data/NEM3/county_to_climate_zone.csv` for (utility, county_slug) → `climate_zone`.
  - Loads ACC tables only from `data/NEM3/export_rates/{zone}_{UTIL}.csv` (CSV-only; no Excel).
  - Multiple zones per county are blended by weights if present; otherwise a single zone is used as-is.

- Electricity (retail import) rates — step12
  - Retail bills are computed from plan structures in `helpers/electricity_rate_helpers.py`.
  - Baseline allowances/regions (e.g., PG&E P/Q/…/Z, SCE 5/6/…/16) exist in that helper, but step12 currently does not choose a territory per county; it uses flat plan rates and does not apply territory-specific baseline credits/allowances.

- Gas rates — step11
  - Territory-specific baseline allowances are used, but the county→territory mapping is hard-coded in `helpers/gas_rate_helpers.py` and is incomplete/approximate.

- Solar irradiance
  - Step 9 reads per-county weather from `data/loadprofiles/<scenario>/<housing>/<county>/weather_TMY_<county>.csv`.
  - There is no climate-zone logic for irradiance — it’s county weather driven.

## Recommended CSVs (single source of truth)

- Electric baseline territories (for retail import bills):
  - File: `data/NEM3/county_to_electric_territory.csv`
  - Columns: `utility, county_slug, electric_territory`
    - PG&E uses letters `P,Q,R,S,T,V,W,X,Y,Z`.
    - SCE uses numbers `5,6,8,9,10,13,14,15,16`.
    - SDG&E: define `coastal/inland` or leave empty if not needed.

- Gas baseline territories:
  - File: `data/NEM3/county_to_gas_territory.csv`
  - Columns: `utility, county_slug, gas_territory`
    - Replace the in-code dicts in `helpers/gas_rate_helpers.py` with this mapping.

- NEM 3.0 export rates (already in use):
  - File: `data/NEM3/county_to_climate_zone.csv` with `utility, county_slug, climate_zone`.
  - Tables in `data/NEM3/export_rates/{climate_zone}_{UTIL}.csv`.

## Wiring plan — Gas (step11)

1) Add a loader in `step11_evaluate_gas_rates.py`:

```python
import os
import pandas as pd
from helpers.main_helpers import slugify_county_name

_DEF_GAS_MAP = None

def _load_gas_territory_map(base_dir: str = "data/NEM3") -> dict[tuple[str, str], str]:
    global _DEF_GAS_MAP
    if _DEF_GAS_MAP is not None:
        return _DEF_GAS_MAP
    path = os.path.join(base_dir, "county_to_gas_territory.csv")
    df = pd.read_csv(path)
    out = {}
    for _, r in df.iterrows():
        util = str(r["utility"]).strip().upper()
        cslug = slugify_county_name(str(r["county_slug"]))
        terr = str(r["gas_territory"]).strip()
        out[(util, cslug)] = terr
    _DEF_GAS_MAP = out
    return out
```

2) Replace `get_territory_for_county`:

```python
def get_territory_for_county(county, utility):
    m = _load_gas_territory_map()
    key = (utility, slugify_county_name(county))
    if key not in m:
        raise ValueError(f"Missing gas territory for {utility}, {county}")
    return m[key]
```

This removes the hard-coded mappings and ensures all gas billing is territory-correct.

## Wiring plan — Electricity baseline territories (step12)

Goal: apply baseline allowances/credits based on the customer’s territory.

1) Add a loader similar to gas, e.g., `data/NEM3/county_to_electric_territory.csv`:

```python
_DEF_ELEC_MAP = None

def _load_electric_territory_map(base_dir: str = "data/NEM3") -> dict[tuple[str, str], str]:
    global _DEF_ELEC_MAP
    if _DEF_ELEC_MAP is not None:
        return _DEF_ELEC_MAP
    path = os.path.join(base_dir, "county_to_electric_territory.csv")
    df = pd.read_csv(path)
    out = {}
    for _, r in df.iterrows():
        util = str(r["utility"]).strip().upper()
        cslug = slugify_county_name(str(r["county_slug"]))
        terr = str(r["electric_territory"]).strip()
        out[(util, cslug)] = terr
    _DEF_ELEC_MAP = out
    return out
```

2) Compute a monthly baseline credit and subtract it from monthly energy charges before fixed/minimum bills. For example inside `calculate_nem3_annual_costs` (or retail import path), after summing monthly import energy:

```python
# After computing energy_charge, before minimum/fixed
territory = _load_electric_territory_map().get((utility, slugify_county_name(county_slug)))
if territory:
    # Look up daily baseline allowance for this plan + season + territory
    daily_kwh = BASELINE_ALLOWANCES[utility][plan_name]["territories"][territory][season]
    days = days_in_month(month)
    baseline_kwh_month = daily_kwh * days
    baseline_credit_rate = plan_details.get("baseline_credit", 0.0)  # if provided in plan
    energy_charge = max(0.0, energy_charge - baseline_kwh_month * baseline_credit_rate)
```

Notes:
- You can store `baseline_credit` or similar in the plan definitions, or infer it from the “AfterBaselineCredit” sections already present in `electricity_rate_helpers.py`.
- For SCE plans with `superOffPeak` and tiered structures, keep the simple approach initially: apply a flat baseline kWh credit at a plan-level rate. Refinements can come later.
- Thread `county_slug` into the billing function where needed so the territory can be resolved per county.

## NEM 3.0 (confirmation)

- `helpers/nem3_export_rates.py` is now CSV-only. All Excel scanning/loaders have been removed.
- The function `get_export_rate_table_for_zone(base_dir, utility, climate_zone)` loads `{zone}_{UTIL}.csv` from `export_rates/` and raises if missing.
- `get_export_rate_table_for_county` requires `county_to_climate_zone.csv` rows; it blends multiple zones by weight if present.

## Solar irradiance and climate zones

- Step 9 uses per-county TMY weather CSVs; there’s no climate-zone mapping here.
- If you want “zone scenarios” for PV (e.g., using canonical zone weather), add a `data/NEM3/climate_zone_to_weather.csv` (e.g., `climate_zone, weather_path`) and an option to override the county weather when running zone scenarios.

## Validation checklist

- Add a small script to verify mapping coverage and CSV presence:
  - Every `(utility, county_slug)` in `county_to_climate_zone.csv` has existing `{zone}_{UTIL}.csv` in `export_rates/`.
  - Every `(utility, county_slug)` in `county_to_gas_territory.csv` resolves to a valid territory present in gas `BASELINE_ALLOWANCES`.
  - Every `(utility, county_slug)` in `county_to_electric_territory.csv` resolves to a valid territory present in electric `BASELINE_ALLOWANCES`.

- Consider CI checks to fail fast if any mapping is incomplete.
