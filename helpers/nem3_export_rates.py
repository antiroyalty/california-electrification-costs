"""
Helpers for NEM 3.0 (Net Billing Tariff) export rates and default options.

This module provides a lightweight interface to obtain hourly export
compensation tables (ACC-derived, month x hour) and default NEM3 options
per utility. The initial values here are placeholders so the pipeline can
run end-to-end. Replace with real tables sourced from CPUC/utility filings.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple, Iterable
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


# Simple in-process cache to avoid re-reading Excel for each county
_TABLE_CACHE: Dict[Tuple[str, str, str], Dict[int, List[float]]] = {}


def _parse_12x24_table(df: pd.DataFrame) -> Optional[Dict[int, List[float]]]:
    """Try to coerce a DataFrame into a 12x24 month-hour table of floats.

    Supports two layouts:
      1) Matrix: 12 rows (months), 24 columns (hours 0..23 or 1..24)
      2) Long: columns include 'month' and 'hour' and 'rate'
    """
    # Case 2: long form
    lower_cols = [c.strip().lower() for c in df.columns]
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
    month_like = {"month", "mon", "month/hour", "month_hour"}
    if any(str(c).strip().lower() in month_like for c in df2.columns[:2]):
        for c in df2.columns[:2]:
            if str(c).strip().lower() in month_like:
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


def _norm_util(s: str) -> str:
    return (s or "").upper().replace("&", "").replace(".", "").replace(" ", "")


def _try_load_from_ctcz_folder(base_dir: str, utility: str, county_slug: str) -> Optional[Dict[int, List[float]]]:
    """Prefer a curated county→zone folder if present: base_dir/county_to_climate_zone.

    Expects inside that folder:
      - A mapping CSV (name contains 'county_to_climate_zone') with columns: utility, county_slug, climate_zone
      - One or more zone tables like 'CZ9-Table 1.csv' with 12 rows (Jan..Dec) and 24 hour columns (1..24)
    """
    folder = os.path.join(base_dir, "county_to_climate_zone")
    if not os.path.isdir(folder):
        return None

    # Find a mapping file
    mapping_path = None
    for f in os.listdir(folder):
        if f.lower().endswith(".csv") and "county_to_climate_zone" in f.lower():
            mapping_path = os.path.join(folder, f)
            break
    if not mapping_path:
        return None

    try:
        mdf = pd.read_csv(mapping_path)
    except Exception:
        return None

    util_norm = _norm_util(utility)
    # Normalize county slug
    cslug = slugify_county_name(county_slug)
    # Find rows for this utility and county
    cols = {c.strip().lower(): c for c in mdf.columns}
    ucol = cols.get("utility") or cols.get("iou")
    ccol = cols.get("county_slug") or cols.get("county")
    zcol = cols.get("climate_zone") or cols.get("zone")
    if not (ucol and ccol and zcol):
        return None
    subset = mdf[(mdf[ccol].map(lambda x: slugify_county_name(str(x))) == cslug) & (mdf[ucol].map(_norm_util) == util_norm)]
    if subset.empty:
        return None
    # For now, use first match (folder supports one entry today)
    zone = str(subset.iloc[0][zcol]).strip()

    # Locate a zone table CSV whose filename starts with the zone token (case-insensitive)
    zone_path = None
    for f in os.listdir(folder):
        if f.lower().endswith(".csv") and f.lower().startswith(zone.lower()):
            zone_path = os.path.join(folder, f)
            break
    if not zone_path:
        return None

    try:
        df = pd.read_csv(zone_path)
        # Accept wide 12×24 with first column like 'Month/Hour'
        # Keep only the first 25 columns (month + 24 hours)
        if df.shape[1] > 25:
            df = df.iloc[:, :25]
        # Rename first column to 'month' to be dropped by parser
        first_col = df.columns[0]
        if str(first_col).strip().lower() not in ("month", "mon", "month/hour", "month_hour"):
            df = df.rename(columns={first_col: "month"})
        table = _parse_12x24_table(df)
        if table is not None:
            # Cache by folder mapping
            key = (f"ctcz:{folder}", util_norm, cslug)
            _TABLE_CACHE[key] = table
            return table
    except Exception:
        return None
    return None


def _load_export_rates_from_excel(
    base_dir: str,
    utility: str,
    climate_zone: Optional[str],
    *,
    sheet_name: Optional[str] = None,
) -> Optional[Dict[int, List[float]]]:
    """Load a 12×24 export table from the IOU Excel file.

    - If sheet_name is provided and exists, prefer it.
    - Else if climate_zone provided, try exact sheet match, else substring match.
    - Else try a sheet containing 'rate' in its name, else the first sheet.
    Results are cached by (excel_path, sheet_name, climate_zone).
    """
    path = _find_excel_for_utility(base_dir, utility)
    if not path:
        return None
    key = (path, (sheet_name or "").lower(), (climate_zone or "").lower())
    if key in _TABLE_CACHE:
        return _TABLE_CACHE[key]
    try:
        xls = pd.ExcelFile(path)
        chosen_sheet = None
        # 1) explicit sheet override
        if sheet_name and sheet_name in xls.sheet_names:
            chosen_sheet = sheet_name
        # 2) climate-zone exact match
        if chosen_sheet is None and climate_zone and climate_zone in xls.sheet_names:
            chosen_sheet = climate_zone
        # 3) climate-zone substring match (case-insensitive)
        if chosen_sheet is None and climate_zone:
            cz = climate_zone.lower()
            for s in xls.sheet_names:
                if cz in s.lower():
                    chosen_sheet = s
                    break
        # 4) any sheet with 'rate'
        if chosen_sheet is None:
            chosen_sheet = next((s for s in xls.sheet_names if 'rate' in s.lower()), xls.sheet_names[0])

        # Try chosen sheet
        df = pd.read_excel(path, sheet_name=chosen_sheet)
        table = _parse_12x24_table(df)
        if table is not None:
            _TABLE_CACHE[key] = table
            return table

        # Fallback: iterate all sheets and pick first parseable
        for s in xls.sheet_names:
            try:
                df2 = pd.read_excel(path, sheet_name=s)
                table = _parse_12x24_table(df2)
                if table is not None:
                    _TABLE_CACHE[key] = table
                    return table
            except Exception:
                continue
    except Exception as e:
        print(f"[NEM3] Failed to read Excel for {utility}: {e}")
    return None


def _blend_tables(weighted_tables: Iterable[Tuple[Dict[int, List[float]], float]]) -> Dict[int, List[float]]:
    """Blend multiple 12×24 tables with weights (auto-normalized)."""
    # Normalize weights
    items = list(weighted_tables)
    total_w = sum(max(0.0, float(w)) for _, w in items) or 1.0
    normed = [(tbl, (max(0.0, float(w)) / total_w)) for tbl, w in items]
    out: Dict[int, List[float]] = {m: [0.0] * 24 for m in range(1, 13)}
    for tbl, w in normed:
        for m in range(1, 13):
            row = tbl.get(m, [0.0] * 24)
            if len(row) < 24:
                row = list(row) + [0.0] * (24 - len(row))
            for h in range(24):
                out[m][h] += float(row[h]) * w
    return out


def _load_county_to_zone_mapping(base_dir: str) -> Dict[Tuple[str, str], List[Tuple[str, float, Optional[str]]]]:
    """Load county→zone mapping from base_dir/county_to_climate_zone.csv.

    Required columns:
      - utility (or iou)
      - county_slug (or county)
      - climate_zone (or zone)
    Optional columns:
      - weight (fractional share if county spans multiple zones)
      - sheet_name (or sheet) to explicitly select an Excel tab
    Returns: {(UTILITY, county_slug): [(zone, weight, sheet_name), ...]}
    """
    mapping: Dict[Tuple[str, str], List[Tuple[str, float, Optional[str]]]] = {}
    csv_path = os.path.join(base_dir, "county_to_climate_zone.csv")
    if not os.path.exists(csv_path):
        return mapping
    try:
        df = pd.read_csv(csv_path)
        util_col = next((c for c in df.columns if c.strip().lower() in ("utility", "iou")), None)
        county_col = next((c for c in df.columns if c.strip().lower() in ("county_slug", "county")), None)
        zone_col = next((c for c in df.columns if c.strip().lower() in ("climate_zone", "zone")), None)
        weight_col = next((c for c in df.columns if c.strip().lower() == "weight"), None)
        sheet_col = next((c for c in df.columns if c.strip().lower() in ("sheet_name", "sheet")), None)
        if not (util_col and county_col and zone_col):
            return mapping
        for _, r in df.iterrows():
            util = str(r[util_col]).strip().upper()
            cslug = slugify_county_name(str(r[county_col]))
            zone = str(r[zone_col]).strip()
            weight = float(r[weight_col]) if weight_col and pd.notna(r[weight_col]) else 1.0
            sheet_name = str(r[sheet_col]).strip() if sheet_col and pd.notna(r[sheet_col]) else None
            mapping.setdefault((util, cslug), []).append((zone, weight, sheet_name))
    except Exception as e:
        print(f"[NEM3] Failed to read mapping CSV: {e}")
    return mapping


def get_export_rate_table_for_county(base_dir: str, utility: str, county_name_or_slug: str) -> Dict[int, List[float]]:
    """Return ACC-based export table for a county by selecting a climate zone.

    Selection order:
      1) If mapping CSV exists at base_dir/county_to_climate_zone.csv, use it.
      2) Else, attempt to load any table for the utility and use it as a fallback.

    TODO: Provide a robust county→climate_zone mapping per IOU. A suggested approach:
      - For PG&E, reuse baseline territories (P,Q,R,S,T,V,W,X,Y,Z) as zones and map counties accordingly.
      - For SCE, reuse baseline regions (5,6,8,9,10,13,14,15,16).
      - For SDG&E, define a single zone or coastal/inland split per utility publication.
      - Maintain mapping in NEM3/county_to_climate_zone.csv with columns: utility, county_slug, climate_zone.
    """
    util = (utility or "").strip().upper()
    cslug = slugify_county_name(county_name_or_slug)
    # 0) Prefer curated county_to_climate_zone folder if present
    table = _try_load_from_ctcz_folder(base_dir, util, cslug)
    if table is not None:
        return table

    # 1) CSV mapping at base_dir/county_to_climate_zone.csv
    mapping = _load_county_to_zone_mapping(base_dir)
    rows = mapping.get((util, cslug))

    # 1) Mapped zones (possibly multiple with weights)
    if rows:
        weighted: List[Tuple[Dict[int, List[float]], float]] = []
        for zone, weight, sheet_name in rows:
            table = _load_export_rates_from_excel(base_dir, utility, zone, sheet_name=sheet_name)
            if table is not None:
                weighted.append((table, weight))
        if weighted:
            return _blend_tables(weighted)
        # Fall through if nothing parsed

    # 2) Fallback: use IOU Excel first available sheet
    table = _load_export_rates_from_excel(base_dir, utility, None)
    if table is None:
        print(
            f"[NEM3] Missing export rate table for utility={util}, county={cslug}. "
            f"Place ACC 12x24 Excel under {base_dir} and add mapping in county_to_climate_zone.csv."
        )
        return _zeros_table()
    # Warn if mapping missing
    if not rows:
        print(
            f"[NEM3] Warning: No county→climate_zone mapping for utility={util}, county={cslug}. "
            f"Using fallback sheet from Excel. Add a row to {os.path.join(base_dir, 'county_to_climate_zone.csv')}"
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
