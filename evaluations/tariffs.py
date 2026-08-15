from __future__ import annotations

from typing import Iterable, Optional

import pandas as pd


def select_row_value_for_plan(
    row: pd.Series,
    *,
    plan_preference: Optional[Iterable[str]] = None,
    variant: Optional[str] = None,
) -> float:
    """Return one unambiguous electricity bill value from a results row.

    - Considers only 'electricity.*' columns.
    - variant='nem3' restricts to columns ending with '_NEM3'.
      variant='retail' restricts to electricity columns without '_NEM3'.
    - plan_preference: ordered substrings to prioritize matching plans.

    A single numeric candidate is sufficient, even if none of the preference
    tokens match it. Multiple candidates require a matching preference; the
    function never falls back to column order.
    """
    if not isinstance(row, pd.Series):
        raise TypeError("Tariff selection requires a pandas Series")

    columns = [c for c in row.index if str(c).startswith("electricity.")]
    if not columns:
        raise ValueError("Results row has no electricity.* columns")

    if variant is not None:
        normalized_variant = str(variant).lower()
        if normalized_variant == "nem3":
            columns = [c for c in columns if str(c).endswith("_NEM3")]
        elif normalized_variant == "retail":
            columns = [c for c in columns if not str(c).endswith("_NEM3")]
        else:
            raise ValueError(
                f"Unknown electricity tariff variant {variant!r}; "
                "expected 'nem3' or 'retail'"
            )

    numeric_candidates = {
        column: float(value)
        for column in columns
        if pd.notna(value := pd.to_numeric(row[column], errors="coerce"))
    }
    if not numeric_candidates:
        raise ValueError(
            f"No numeric electricity tariff values match variant {variant!r}"
        )

    for preference in plan_preference or ():
        matches = [
            column
            for column in numeric_candidates
            if str(preference).lower() in str(column).lower()
        ]
        if len(matches) == 1:
            return numeric_candidates[matches[0]]
        if len(matches) > 1:
            raise ValueError(
                f"Tariff preference {preference!r} is ambiguous; "
                f"matching columns: {matches}"
            )

    if len(numeric_candidates) == 1:
        return next(iter(numeric_candidates.values()))

    raise ValueError(
        "Electricity tariff selection is ambiguous; provide a preference that "
        f"matches one of: {list(numeric_candidates)}"
    )
