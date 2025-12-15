"""
Helpers for NEM 3.0 (Net Billing Tariff) export rates and default options.

This module provides a lightweight interface to obtain hourly export
compensation tables (ACC-derived, month x hour) and default NEM3 options
per utility. The initial values here are placeholders so the pipeline can
run end-to-end. Replace with real tables sourced from CPUC/utility filings.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
import os
import pandas as pd
from helpers.main_helpers import slugify_county_name


def _zeros_table() -> Dict[int, List[float]]:
    """Return a 12x24 table (dict) of zeros (dollars per kWh)."""
    return {m: [0.0] * 24 for m in range(1, 13)}


def get_export_rate_table(utility: str) -> Dict[int, List[float]]:
    """Return month->24hr ACC-based export rates ($/kWh) for the given utility.

    Replace the placeholder data below with the actual NBT export
    compensation tables (12x24) for the model year.
    """
    util = (utility or "").strip().upper()
    if "PG&E" in util or util == "PGE":
        return _zeros_table()
    if util == "SCE":
        return _zeros_table()
    if "SDG&E" in util or util in ("SDGE", "SDG&E"):
        return _zeros_table()
    # default
    return _zeros_table()


def _find_excel_for_utility(base_dir: str, utility: str) -> Optional[str]:
    """Return a path to an Excel file for a given utility inside base_dir/NEM3.

    Accepts flexible naming, e.g., 'PGE', 'PG&E', 'SCE', 'SDGE', 'SDG&E'.
    """
    u = (utility or "").lower().replace("&", "").replace(".", "").replace(" ", "")
    candidates = []
    try:
        for root, _, files in os.walk(base_dir):
            for f in files:
                if f.lower().endswith((".xlsx", ".xls")):
                    fnorm = f.lower().replace("&", "").replace(".", "").replace(" ", "")
                    if any(tag in fnorm for tag in (u,)):
                        candidates.append(os.path.join(root, f))
    except Exception:
        return None
    # Prefer files closer to base_dir (shorter path)
    return sorted(candidates, key=lambda p: (p.count(os.sep), len(p)))[0] if candidates else None


def _normalize_util(util: str) -> str:
    return (util or "").strip().replace("&", "").replace(" ", "").replace(".", "").upper().replace("PGEE", "PGE")


def _load_export_rates_from_csv(base_dir: str, utility: str, climate_zone: Optional[str]) -> Optional[Dict[int, List[float]]]:
    """Try loading a 12x24 or long-form CSV override for a specific utility + climate zone.

    Naming conventions searched (under base_dir):
      - <UTIL>_<ZONE>_12x24.csv (e.g., PGE_CZ3A_12x24.csv)
      - <UTIL>_<ZONE>.csv
      - PG&E forms also accepted as PGE
    """
    if not climate_zone:
        return None
    u = _normalize_util(utility)
    z = (climate_zone or "").strip()
    # Search in a dedicated overrides folder first, then in the base_dir root
    overrides_dir = os.path.join(base_dir, "utility-county-climatezone")
    candidates = [
        os.path.join(overrides_dir, f"{u}_{z}_12x24.csv"),
        os.path.join(overrides_dir, f"{u}_{z}.csv"),
        os.path.join(base_dir, f"{u}_{z}_12x24.csv"),
        os.path.join(base_dir, f"{u}_{z}.csv"),
        os.path.join(base_dir, f"{utility}_{z}_12x24.csv"),
        os.path.join(base_dir, f"{utility}_{z}.csv"),
    ]
    for path in candidates:
        if os.path.exists(path):
            try:
                df = pd.read_csv(path)
                table = _parse_12x24_table(df)
                if table is not None:
                    return table
            except Exception:
                continue
    return None


def _parse_12x24_table(df: pd.DataFrame) -> Optional[Dict[int, List[float]]]:
    """Try to coerce a DataFrame into a 12x24 month-hour table of floats.

    Supports two layouts:
      1) Matrix: 12 rows (months), 24 columns (hours 0..23 or 1..24)
      2) Long: columns include 'month' and 'hour' and 'rate'
    """
    # Case 2: long form
    lower_cols = [str(c).strip().lower() for c in df.columns]
    if all(col in lower_cols for col in ["month", "hour"]) and any(c in lower_cols for c in ["rate", "value", "export", "acc"]):
        cmonth = df.columns[lower_cols.index("month")]
        chour = df.columns[lower_cols.index("hour")]
        # pick rate-like column
        for cand in ("rate", "value", "export", "acc"):
            if cand in lower_cols:
                crate = df.columns[lower_cols.index(cand)]
                break
        pivot = df[[cmonth, chour, crate]].copy()
        pivot[cmonth] = pd.to_numeric(pivot[cmonth], errors="coerce").astype("Int64")
        pivot[chour] = pd.to_numeric(pivot[chour], errors="coerce").astype("Int64")
        pivot[crate] = pd.to_numeric(pivot[crate], errors="coerce").fillna(0.0)
        out: Dict[int, List[float]] = {}
        for m in range(1, 13):
            sub = pivot[pivot[cmonth] == m]
            if sub.empty:
                out[m] = [0.0] * 24
                continue
            # build hour list 0..23
            row = [0.0] * 24
            for _, r in sub.iterrows():
                h = int(r[chour])
                if 0 <= h <= 23:
                    row[h] = float(r[crate])
            out[m] = row
        return out

    # Case 1: wide 12x24
    # Identify 24 numeric columns; allow hour labels 0..23 or 1..24 or strings containing hour numbers
    # Drop non-numeric columns except maybe the first if it's 'month'
    df2 = df.copy()
    # Try to detect a month column and drop it
    if any(str(c).strip().lower() in ("month", "mon") for c in df2.columns[:2]):
        for c in df2.columns[:2]:
            if str(c).strip().lower() in ("month", "mon"):
                df2 = df2.drop(columns=[c])
                break
    # Keep first 24 columns
    if df2.shape[1] >= 24:
        df2 = df2.iloc[:, :24]
        # Coerce to floats
        df2 = df2.apply(pd.to_numeric, errors="coerce").fillna(0.0)
        # Need at least 12 rows; if more, take first 12
        if df2.shape[0] >= 12:
            df2 = df2.iloc[:12, :]
            out = {m + 1: [float(x) for x in df2.iloc[m, :].tolist()] for m in range(12)}
            return out
    return None


def _load_export_rates_from_excel(base_dir: str, utility: str, climate_zone: Optional[str]) -> Optional[Dict[int, List[float]]]:
    path = _find_excel_for_utility(base_dir, utility)
    if not path:
        return None
    try:
        # Strategy: if climate_zone is provided and matches a sheet, read that sheet; else try first sheet
        xls = pd.ExcelFile(path)
        sheet = None
        if climate_zone and climate_zone in xls.sheet_names:
            sheet = climate_zone
        else:
            # Try sheet with 'Rates' keyword; else first sheet
            sheet = next((s for s in xls.sheet_names if 'rate' in s.lower()), xls.sheet_names[0])
        df = pd.read_excel(path, sheet_name=sheet)
        table = _parse_12x24_table(df)
        if table is not None:
            return table
        # Fallback: iterate all sheets and pick first parseable
        for s in xls.sheet_names:
            try:
                df2 = pd.read_excel(path, sheet_name=s)
                table = _parse_12x24_table(df2)
                if table is not None:
                    return table
            except Exception:
                continue
    except Exception as e:
        print(f"[NEM3] Failed to read Excel for {utility}: {e}")
    return None


def _load_county_to_zone_mapping(base_dir: str) -> Dict[Tuple[str, str], str]:
    """Load optional county→climate_zone mapping from CSV at base_dir/county_to_climate_zone.csv.

    Expected columns: utility, county_slug, climate_zone
    """
    mapping: Dict[Tuple[str, str], str] = {}
    csv_path = os.path.join(base_dir, "county_to_climate_zone.csv")
    if not os.path.exists(csv_path):
        return mapping
    try:
        df = pd.read_csv(csv_path)
        util_col = next((c for c in df.columns if c.strip().lower() in ("utility", "iou")), None)
        county_col = next((c for c in df.columns if c.strip().lower() in ("county_slug", "county")), None)
        zone_col = next((c for c in df.columns if c.strip().lower() in ("climate_zone", "zone")), None)
        if not (util_col and county_col and zone_col):
            return mapping
        for _, r in df.iterrows():
            util = str(r[util_col]).strip().upper()
            cslug = slugify_county_name(str(r[county_col]))
            zone = str(r[zone_col]).strip()
            mapping[(util, cslug)] = zone
    except Exception as e:
        print(f"[NEM3] Failed to read mapping CSV: {e}")
    return mapping


def get_export_rate_table_for_county(base_dir: str, utility: str, county_name_or_slug: str) -> Dict[int, List[float]]:
    """Return ACC-based export table for a county by selecting a climate zone.

    Strict mode: requires an explicit county→climate_zone mapping and a CSV
    override for (utility, zone). No Excel fallback is attempted. Fails loudly
    with a descriptive error if inputs are missing.
    """
    util = (utility or "").strip().upper()
    cslug = slugify_county_name(county_name_or_slug)
    # Require an explicit mapping
    mapping = _load_county_to_zone_mapping(base_dir)
    zone = mapping.get((util, cslug), None)
    if not zone:
        raise RuntimeError(
            "NEM3 export-rate lookup failed: missing county→climate_zone mapping. "
            f"Add a row to {os.path.join(base_dir, 'county_to_climate_zone.csv')} with columns: "
            f"utility={util}, county_slug={cslug}, climate_zone=<SHEET_OR_ZONE>."
        )
    # Require a CSV override for this utility+zone
    table = _load_export_rates_from_csv(base_dir, utility, zone)
    if table is None:
        util_tag = _normalize_util(utility)
        raise RuntimeError(
            "NEM3 export-rate lookup failed: no CSV override found for utility/zone. "
            f"Provide a 12x24 or long-form CSV at one of: "
            f"{os.path.join(base_dir, 'utility-county-climatezone', util_tag + '_' + zone + '_12x24.csv')} or {os.path.join(base_dir, 'utility-county-climatezone', util_tag + '_' + zone + '.csv')}"
        )
    return table


@dataclass
class NEM3Options:
    nbc_dollars_per_kwh: float = 0.0
    fixed_charge_monthly: float = 0.0
    minimum_bill_monthly: float = 0.0
    true_up_month: int = 12
    nsc_dollars_per_kwh: float = 0.0


def default_options_for_utility(utility: str) -> NEM3Options:
    util = (utility or "").strip().upper()
    if "PG&E" in util or util == "PGE":
        return NEM3Options(nbc_dollars_per_kwh=0.0, fixed_charge_monthly=0.0, minimum_bill_monthly=0.0)
    if util == "SCE":
        return NEM3Options(nbc_dollars_per_kwh=0.0, fixed_charge_monthly=0.0, minimum_bill_monthly=0.0)
    if "SDG&E" in util or util in ("SDGE", "SDG&E"):
        return NEM3Options(nbc_dollars_per_kwh=0.0, fixed_charge_monthly=0.0, minimum_bill_monthly=0.0)
    return NEM3Options()
