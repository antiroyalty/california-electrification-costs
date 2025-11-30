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


# (Excel discovery removed — CSV-only rates are supported.)


# Simple in-process cache to avoid re-reading tables repeatedly
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


def _norm_util_for_csv_tag(utility: str) -> Optional[str]:
    """Return canonical utility tag as used in export_rates CSV filenames.

    - PG&E -> "PG&E"
    - SCE  -> "SCE"
    - SDG&E/SDGE -> "SDGE"
    """
    u = _norm_util(utility)
    if u.startswith("PGE"):
        return "PG&E"
    if u.startswith("SCE"):
        return "SCE"
    if u.startswith("SDGE") or u.startswith("SDG"):
        return "SDGE"
    return None


def _load_export_rates_from_csv(
    base_dir: str,
    utility: str,
    climate_zone: Optional[str],
) -> Optional[Dict[int, List[float]]]:
    """Load a 12×24 export table from CSVs in base_dir/export_rates.

    Expected filenames: "{zone}_{UTIL}.csv", e.g., "CZ9_SCE.csv", "CZ3A_PG&E.csv", "CZ10_SDGE.csv".
    Performs a prefix match for cases like PG&E where mapping may specify "CZ3"
    but files are split into "CZ3A" / "CZ3B" — in such cases the lexicographically
    first match will be selected (typically "CZ3A").
    """
    if not climate_zone:
        return None
    export_dir = os.path.join(base_dir, "export_rates")
    if not os.path.isdir(export_dir):
        return None
    util_tag = _norm_util_for_csv_tag(utility)
    if not util_tag:
        return None

    zone = str(climate_zone).strip()
    # 1) Exact match first
    exact = os.path.join(export_dir, f"{zone}_{util_tag}.csv")
    candidate_path = exact if os.path.exists(exact) else None
    # 2) Fallback: prefix match (e.g., CZ3 -> CZ3A)
    if candidate_path is None:
        lower_zone = zone.lower()
        suffix = f"_{util_tag}.csv".lower()
        try:
            matches = [
                os.path.join(export_dir, f)
                for f in os.listdir(export_dir)
                if f.lower().startswith(lower_zone) and f.lower().endswith(suffix)
            ]
        except Exception:
            matches = []
        if matches:
            candidate_path = sorted(matches)[0]

    if not candidate_path:
        return None

    try:
        df = pd.read_csv(candidate_path)
        # Keep at most the first 25 columns (month + 24 hours)
        if df.shape[1] > 25:
            df = df.iloc[:, :25]
        # Rename first column to a month-like token for the parser to drop
        first_col = df.columns[0]
        if str(first_col).strip().lower() not in ("month", "mon", "month/hour", "month_hour"):
            df = df.rename(columns={first_col: "month"})
        table = _parse_12x24_table(df)
        return table
    except Exception:
        return None


# (Removed curated folder override — single source of truth is the top-level CSV + export_rates CSVs.)


# (Excel loader removed — CSV-only export rates are supported)


def get_export_rate_table_for_zone(base_dir: str, utility: str, climate_zone: str) -> Dict[int, List[float]]:
    """Public helper: load a 12×24 export table for a specific utility and climate zone from CSVs.

    Looks under `{base_dir}/export_rates` for a file named `{climate_zone}_{UTIL}.csv`.
    For PG&E where mapping may specify `CZ3`, a prefix match will select `CZ3A` or `CZ3B` (first alphabetical).

    Raises FileNotFoundError if no matching CSV is found.
    """
    table = _load_export_rates_from_csv(base_dir, utility, climate_zone)
    if table is None:
        util_tag = _norm_util_for_csv_tag(utility) or utility
        export_dir = os.path.join(base_dir, 'export_rates')
        raise FileNotFoundError(
            f"[NEM3] Missing export rates CSV for {utility} zone={climate_zone}. "
            f"Expected file like '{climate_zone}_{util_tag}.csv' under {export_dir}."
        )
    return table


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
      - sheet_name (ignored; CSV-only)
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
    """Return ACC-based export table for a county by selecting a climate zone (CSV-only).

    Behavior:
      - Requires a row in base_dir/county_to_climate_zone.csv for (utility, county_slug).
      - For each listed climate_zone, loads {zone}_{UTIL}.csv from base_dir/export_rates and blends by weights (if present).
      - No Excel fallback is used.
    """
    util = (utility or "").strip().upper()
    cslug = slugify_county_name(county_name_or_slug)
    # 1) CSV mapping at base_dir/county_to_climate_zone.csv
    mapping = _load_county_to_zone_mapping(base_dir)
    rows = mapping.get((util, cslug))

    # 1) Mapped zones are required. No Excel fallback; require CSVs.
    if not rows:
        raise ValueError(
            f"[NEM3] No county→climate_zone mapping found for utility={util}, county={cslug} in "
            f"{os.path.join(base_dir, 'county_to_climate_zone.csv')}"
        )

    weighted: List[Tuple[Dict[int, List[float]], float]] = []
    for zone, weight, _sheet_name in rows:
        table = _load_export_rates_from_csv(base_dir, utility, zone)
        if table is None:
            util_tag = _norm_util_for_csv_tag(utility) or utility
            export_dir = os.path.join(base_dir, 'export_rates')
            raise FileNotFoundError(
                f"[NEM3] Missing export rates CSV for {utility} zone={zone}. "
                f"Expected file like '{zone}_{util_tag}.csv' under {export_dir}."
            )
        weighted.append((table, weight))

    return _blend_tables(weighted)


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
