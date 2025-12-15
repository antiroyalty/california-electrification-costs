"""
Utility: Extract a utility climate-zone sheet from a NEM3 Excel into a 12x24 or long-form CSV

Usage examples
  python3 tools/extract_nem3_sheet_to_csv.py \
    --xlsx data/NEM3/PG&E_2024_ACC_12x24_Export_Rates.xlsx \
    --utility "PG&E" \
    --zone CZ3A \
    --out data/NEM3/PGE_CZ3A_12x24.csv

The output CSV will be readable by helpers.nem3_export_rates (_parse_12x24_table).
"""

from __future__ import annotations

import argparse
import os
import pandas as pd


def _normalize_util(util: str) -> str:
    return (util or "").strip().replace("&", "").replace(" ", "").replace(".", "").upper().replace("PGEE", "PGE")


def _parse_12x24_table(df: pd.DataFrame):
    lower_cols = [str(c).strip().lower() for c in df.columns]
    # Long form
    if all(col in lower_cols for col in ["month", "hour"]) and any(c in lower_cols for c in ["rate", "value", "export", "acc"]):
        cmonth = df.columns[lower_cols.index("month")]
        chour = df.columns[lower_cols.index("hour")]
        for cand in ("rate", "value", "export", "acc"):
            if cand in lower_cols:
                crate = df.columns[lower_cols.index(cand)]
                break
        pivot = df[[cmonth, chour, crate]].copy()
        pivot[cmonth] = pd.to_numeric(pivot[cmonth], errors="coerce").astype("Int64")
        pivot[chour] = pd.to_numeric(pivot[chour], errors="coerce").astype("Int64")
        pivot[crate] = pd.to_numeric(pivot[crate], errors="coerce").fillna(0.0)
        return pivot.rename(columns={cmonth: "month", chour: "hour", crate: "rate"})
    # Wide 12x24: coerce to floats, keep first 24 columns, first 12 rows and add month column
    df2 = df.copy()
    if any(str(c).strip().lower() in ("month", "mon") for c in df2.columns[:2]):
        for c in df2.columns[:2]:
            if str(c).strip().lower() in ("month", "mon"):
                df2 = df2.drop(columns=[c])
                break
    if df2.shape[1] >= 24:
        df2 = df2.iloc[:, :24]
        df2 = df2.apply(pd.to_numeric, errors="coerce").fillna(0.0)
        if df2.shape[0] >= 12:
            df2 = df2.iloc[:12, :]
            df2.insert(0, "month", list(range(1, 13)))
            # Melt to long
            df_long = df2.melt(id_vars=["month"], var_name="hour", value_name="rate")
            df_long["hour"] = pd.to_numeric(df_long["hour"], errors="coerce").fillna(0).astype(int)
            return df_long[["month", "hour", "rate"]]
    return None


def main():
    p = argparse.ArgumentParser(description="Extract NEM3 climate-zone sheet to CSV (long form)")
    p.add_argument("--xlsx", required=True, help="Path to utility Excel file (e.g., data/NEM3/PG&E_2024_ACC_12x24_Export_Rates.xlsx)")
    p.add_argument("--utility", required=True, help="Utility name (PG&E, SCE, SDG&E)")
    p.add_argument("--zone", required=True, help="Climate zone / sheet name to extract (e.g., CZ3A)")
    p.add_argument("--out", help="Output CSV path (default: data/NEM3/utility-county-climatezone/<UTIL>_<ZONE>_12x24.csv)")
    args = p.parse_args()

    util = _normalize_util(args.utility)
    out_path = args.out or os.path.join("data", "NEM3", "utility-county-climatezone", f"{util}_{args.zone}_12x24.csv")
    xls = pd.ExcelFile(args.xlsx)
    sheet = None
    # Match exact zone, else try case-insensitive match
    if args.zone in xls.sheet_names:
        sheet = args.zone
    else:
        for s in xls.sheet_names:
            if s.strip().lower() == args.zone.strip().lower():
                sheet = s
                break
    if sheet is None:
        raise SystemExit(f"Sheet '{args.zone}' not found in {args.xlsx}. Available: {xls.sheet_names}")
    df = pd.read_excel(args.xlsx, sheet_name=sheet)
    df_out = _parse_12x24_table(df)
    if df_out is None or df_out.empty:
        raise SystemExit("Could not coerce sheet to 12x24 or (month,hour,rate) long form.")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    df_out.to_csv(out_path, index=False)
    print(f"Wrote CSV: {os.path.abspath(out_path)}  rows={len(df_out)}")


if __name__ == "__main__":
    main()
