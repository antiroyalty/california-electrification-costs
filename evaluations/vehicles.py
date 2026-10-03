from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


REQUIRED_LEDGER_COLUMNS = {
    "county_slug",
    "incentive_scenario",
    "appliance_category",
    "appliance_type",
    "annual_operating_cost",
}

VEHICLE_ROW_TYPES = {
    "vehicle_charging": "electric",
    "vehicle_fuel": "gas",
}


class VehicleLedgerValidationError(ValueError):
    """The capital ledger cannot support a requested vehicle-cost calculation."""


@dataclass(frozen=True)
class VehicleAnnualAdders:
    """Annual vehicle operating costs for one county and incentive case."""

    ev_operating_usd_per_year: float
    ice_operating_usd_per_year: float


def _required_text(value: str, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise VehicleLedgerValidationError(f"{field} must be non-empty text")
    return value.strip().lower()


def vehicle_annual_adders_from_ledger(
    ledger_df: pd.DataFrame,
    *,
    county_slug: str,
    incentive_scenario: str,
) -> VehicleAnnualAdders:
    """Select one county and incentive case and return its vehicle O&M adders.

    Incentive cases are alternative evaluations of the same household. The
    function therefore selects one case before reading vehicle costs. A valid
    selected case can omit either vehicle type, which represents an explicit
    zero for that type. Missing requested cases, malformed costs, and duplicate
    vehicle rows raise ``VehicleLedgerValidationError``.
    """
    if not isinstance(ledger_df, pd.DataFrame):
        raise VehicleLedgerValidationError("ledger_df must be a pandas DataFrame")

    missing_columns = sorted(REQUIRED_LEDGER_COLUMNS - set(ledger_df.columns))
    if missing_columns:
        raise VehicleLedgerValidationError(
            f"Vehicle ledger is missing columns: {', '.join(missing_columns)}"
        )

    requested_county = _required_text(county_slug, "county_slug")
    requested_incentive = _required_text(incentive_scenario, "incentive_scenario")
    df = ledger_df.copy()

    for column in ("county_slug", "incentive_scenario"):
        if not df[column].map(
            lambda value: isinstance(value, str) and bool(value.strip())
        ).all():
            raise VehicleLedgerValidationError(
                f"Vehicle ledger {column} must contain non-empty text"
            )
        df[column] = df[column].str.strip().str.lower()

    county_rows = df[df["county_slug"] == requested_county]
    if county_rows.empty:
        raise VehicleLedgerValidationError(
            f"Vehicle ledger has no rows for county '{requested_county}'"
        )

    selected = county_rows[
        county_rows["incentive_scenario"] == requested_incentive
    ]
    if selected.empty:
        raise VehicleLedgerValidationError(
            "Vehicle ledger has no rows for "
            f"county '{requested_county}', incentive '{requested_incentive}'"
        )

    vehicle_rows = selected[selected["appliance_type"].isin(VEHICLE_ROW_TYPES)].copy()
    for appliance_type, expected_category in VEHICLE_ROW_TYPES.items():
        rows = vehicle_rows[vehicle_rows["appliance_type"] == appliance_type]
        if len(rows) > 1:
            raise VehicleLedgerValidationError(
                "Vehicle ledger has duplicate rows for "
                f"county '{requested_county}', incentive '{requested_incentive}', "
                f"appliance '{appliance_type}'"
            )
        if not rows.empty and rows.iloc[0]["appliance_category"] != expected_category:
            raise VehicleLedgerValidationError(
                f"Vehicle ledger appliance '{appliance_type}' must have category "
                f"'{expected_category}'"
            )

    if not vehicle_rows.empty:
        try:
            vehicle_rows["annual_operating_cost"] = pd.to_numeric(
                vehicle_rows["annual_operating_cost"], errors="raise"
            )
        except (TypeError, ValueError) as exc:
            raise VehicleLedgerValidationError(
                "Vehicle ledger annual_operating_cost must be numeric"
            ) from exc
        if not np.isfinite(vehicle_rows["annual_operating_cost"]).all():
            raise VehicleLedgerValidationError(
                "Vehicle ledger annual_operating_cost must be finite"
            )

    def cost_for(appliance_type: str) -> float:
        rows = vehicle_rows[vehicle_rows["appliance_type"] == appliance_type]
        return 0.0 if rows.empty else float(rows.iloc[0]["annual_operating_cost"])

    return VehicleAnnualAdders(
        ev_operating_usd_per_year=cost_for("vehicle_charging"),
        ice_operating_usd_per_year=cost_for("vehicle_fuel"),
    )
