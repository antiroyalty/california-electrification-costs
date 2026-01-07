from __future__ import annotations

from typing import Iterable, Optional

import pandas as pd


def select_row_value_for_plan(
    row: pd.Series,
    *,
    plan_preference: Optional[Iterable[str]] = None,
    variant: Optional[str] = None,
) -> float:
    """Return electricity bill value from a results row (Series) using plan preferences.

    - Considers only 'electricity.*' columns.
    - variant='nem3' restricts to columns ending with '_NEM3'.
      variant='retail' restricts to electricity columns without '_NEM3'.
    - plan_preference: ordered substrings to prioritize matching plans.
    Fallbacks to the first numeric value in the considered columns, or 0.0.
    """
    if row is None or not isinstance(row, (pd.Series,)):
        return 0.0
    try:
        cols = [c for c in row.index if str(c).startswith("electricity.")]
        if not cols:
            # Any numeric in row
            ser = pd.to_numeric(row, errors="coerce").dropna()
            return float(ser.iloc[0]) if not ser.empty else 0.0
        if variant:
            v = str(variant).lower()
            if v == "nem3":
                cols = [c for c in cols if str(c).endswith("_NEM3")]
            elif v == "retail":
                cols = [c for c in cols if not str(c).endswith("_NEM3")]
        if plan_preference:
            for pref in plan_preference:
                sub = [c for c in cols if str(pref).lower() in str(c).lower()]
                if sub:
                    val = pd.to_numeric(row[sub[0]], errors="coerce")
                    if pd.notna(val):
                        return float(val)
        # Fallback: first numeric among considered columns
        for c in cols:
            val = pd.to_numeric(row[c], errors="coerce")
            if pd.notna(val):
                return float(val)
        ser = pd.to_numeric(row, errors="coerce").dropna()
        return float(ser.iloc[0]) if not ser.empty else 0.0
    except Exception:
        return 0.0

