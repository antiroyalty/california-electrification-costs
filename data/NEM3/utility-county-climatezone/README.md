This folder holds per-utility, per-climate-zone NEM 3.0 export tables in CSV form.

File naming
- <UTIL>_<ZONE>_12x24.csv or <UTIL>_<ZONE>.csv
  - Examples: PGE_CZ3A_12x24.csv, SCE_ZONE5_12x24.csv

Accepted CSV formats
1) Long form with columns: month,hour,rate
   - month: 1..12
   - hour: 0..23
   - rate: $/kWh (float)

2) Wide 12×24 matrix
   - 12 rows (months), 24 columns (hours 0..23 or 1..24)

How to generate
- Use helpers/extract_nem3_sheet_to_csv.py to extract a sheet from the utility Excel:
  python3 helpers/extract_nem3_sheet_to_csv.py \
    --xlsx data/NEM3/PG&E_2024_ACC_12x24_Export_Rates.xlsx \
    --utility "PG&E" \
    --zone CZ3A \
    --out data/NEM3/utility-county-climatezone/PGE_CZ3A_12x24.csv

- To generate all climate zones for a utility at once:
  for zone in CZ1 CZ2 CZ3A CZ3B CZ4 CZ5 CZ6 CZ7 CZ8 CZ9 CZ10 CZ11 CZ12 CZ13 CZ14 CZ16; do
    python3 helpers/extract_nem3_sheet_to_csv.py \
      --xlsx "data/NEM3/PG&E_2024_ACC_12x24_Export_Rates.xlsx" \
      --utility "PG&E" \
      --zone "$zone" \
      --out "data/NEM3/utility-county-climatezone/PGE_${zone}_12x24.csv"
  done

Lookup behavior
- helpers/nem3_export_rates.get_export_rate_table_for_county() loads the CSV here
  based on the utility and the county's climate_zone from data/NEM3/county_to_climate_zone.csv.
