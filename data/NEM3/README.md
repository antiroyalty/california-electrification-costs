# NEM 3.0 Export Rate Data

## Data Source

The hourly export rate tables come from the **CPUC Avoided Cost Calculator (ACC)**, 2024 edition.
The ACC is updated biennially; the 2024 version is the latest available as of early 2026.
The next update (2026 ACC) is in development but not yet published.

- **CPUC DER Cost-Effectiveness page** (ACC downloads):
  https://www.cpuc.ca.gov/dercosteffectiveness
- **Governing decision**: CPUC Decision D.22-12-056 (R.20-08-020) establishes the
  Net Billing Tariff (NEM 3.0) with hourly export compensation based on ACC values.
- **2024 ACC adoption**: Resolution E-5328, adopted November 2024 per D.24-08-007.
- **2024 ACC documentation (PDF)**:
  https://www.cpuc.ca.gov/-/media/cpuc-website/divisions/energy-division/documents/demand-side-management/acc-models-latest-version/2024-acc-documentation-v1b_clean_posted_nowm.pdf

## Files

| File | Description |
|------|-------------|
| `PG&E_2024_ACC_12x24_Export_Rates.xlsx` | PG&E hourly export rates by climate zone (source Excel) |
| `SCE_2024_ACC_12x24_Export_Rates.xlsx` | SCE hourly export rates by climate zone (source Excel) |
| `SDGE_2024_ACC_12x24_Export_Rates.xlsx` | SDG&E hourly export rates by climate zone (source Excel) |
| `BuildingClimateZonesByZIPCode_ada.xlsx` | CEC building climate zone to ZIP code mapping |
| `county_to_climate_zone.csv` | Maps (utility, county) pairs to ACC climate zones |
| `utility-county-climatezone/` | Extracted per-zone CSVs used at runtime (see its own README) |

## Climate Zone Mapping

`county_to_climate_zone.csv` maps each county to its ACC climate zone for the serving utility.
The climate zones (CZ1, CZ2, CZ3A, ..., CZ16) correspond to sheets in the utility Excel files.
`BuildingClimateZonesByZIPCode_ada.xlsx` contains the underlying ZIP-to-climate-zone lookup
(Table 4-11: Utility Baseline Territory to Avoided Cost Calculator Climate Zone Mapping).
