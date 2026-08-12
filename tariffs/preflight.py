"""Fail-loud validation of generated county profiles and NBT tariff inputs."""

from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path
from typing import Sequence

import pandas as pd

from helpers.main_helpers import slugify_county_name

from .calendar import calendarize_full_year
from .catalog import TariffCatalog
from .geography import resolve_county_service_assignment
from .models import EnergyFlows, NBTScenario, Utility
from .true_up import (
    AverageRetailExportCompensationSchedule,
    NetSurplusCompensationSchedule,
)


_REQUIRED_COLUMNS = (
    "timestamp",
    "nem3.imports.kwh",
    "nem3.exports.kwh",
)


@dataclass(frozen=True)
class NBTPreflightResult:
    """Source and energy-flow facts established for one county artifact."""

    county_slug: str
    utility: Utility
    profile_path: Path
    row_count: int
    annual_import_kwh: float
    annual_export_kwh: float
    net_surplus_kwh: float
    import_source_id: str
    export_source_ids: tuple[str, ...]
    adjustment_source_id: str | None
    nsc_source_id: str | None


def _profile_path(
    base_input_dir: str | Path,
    scenario_name: str,
    housing_type: str,
    county_slug: str,
) -> Path:
    return (
        Path(base_input_dir)
        / scenario_name
        / housing_type
        / county_slug
        / f"loadprofiles_for_rates_{county_slug}.csv"
    )


def discover_nbt_profile_counties(
    base_input_dir: str | Path,
    scenario_name: str,
    housing_type: str,
) -> list[str]:
    """Return service-assigned county directories for a generated scenario."""

    scenario_path = Path(base_input_dir) / scenario_name / housing_type
    if not scenario_path.is_dir():
        raise FileNotFoundError(f"Scenario directory not found: {scenario_path}")

    counties = []
    for path in scenario_path.iterdir():
        if not path.is_dir():
            continue
        try:
            resolve_county_service_assignment(path.name)
        except KeyError:
            candidate = _profile_path(
                base_input_dir,
                scenario_name,
                housing_type,
                path.name,
            )
            if candidate.is_file():
                raise KeyError(
                    f"NBT profile directory {path} has no utility assignment"
                )
            # Scenario directories can also contain pipeline products such as
            # CAPITAL_COSTS; without a county profile they are out of scope.
            continue
        counties.append(path.name)

    counties.sort()
    if not counties:
        raise ValueError(f"No county directories found in {scenario_path}")
    return counties


def _validated_flows(path: Path, scenario: NBTScenario) -> EnergyFlows:
    if not path.is_file():
        raise FileNotFoundError(f"NBT profile not found: {path}")
    frame = pd.read_csv(path)
    missing = set(_REQUIRED_COLUMNS) - set(frame.columns)
    if missing:
        raise ValueError(
            f"{path} is missing required NBT columns: {sorted(missing)}"
        )
    required = frame[list(_REQUIRED_COLUMNS)].copy()
    if required.isna().any().any():
        raise ValueError(f"{path} contains missing NBT values")
    try:
        timestamps = pd.DatetimeIndex(
            pd.to_datetime(required["timestamp"], errors="raise")
        )
        imports = pd.to_numeric(
            required["nem3.imports.kwh"], errors="raise"
        ).astype(float)
        exports = pd.to_numeric(
            required["nem3.exports.kwh"], errors="raise"
        ).astype(float)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{path} contains malformed NBT values") from exc
    if not imports.map(math.isfinite).all() or not exports.map(math.isfinite).all():
        raise ValueError(f"{path} contains non-finite NBT energy values")
    for column, values in (
        ("nem3.imports.kwh", imports),
        ("nem3.exports.kwh", exports),
    ):
        negative = values < 0.0
        if negative.any():
            first_row = int(negative[negative].index[0])
            minimum = float(values.min())
            timestamp = required.loc[first_row, "timestamp"]
            raise ValueError(
                f"{path} contains negative {column}; minimum={minimum:.12g}, "
                f"first negative row={first_row}, timestamp={timestamp}"
            )

    flows = EnergyFlows(
        timestamps=calendarize_full_year(timestamps, scenario.billing_year),
        import_kwh=imports.tolist(),
        export_kwh=exports.tolist(),
    )
    flows.validated_frame()
    return flows


def preflight_nbt_county(
    *,
    base_input_dir: str | Path,
    scenario_name: str,
    housing_type: str,
    county: str,
    nbt_scenario: NBTScenario,
    tariff_catalog: TariffCatalog | None = None,
    adjustment_schedule: AverageRetailExportCompensationSchedule | None = None,
    nsc_schedule: NetSurplusCompensationSchedule | None = None,
) -> NBTPreflightResult:
    """Validate one county artifact and every tariff source it will require."""

    county_slug = slugify_county_name(county)
    assignment = resolve_county_service_assignment(county_slug)
    path = _profile_path(
        base_input_dir,
        scenario_name,
        housing_type,
        county_slug,
    )
    validated = _validated_flows(path, nbt_scenario).validated_frame()

    tariff = (tariff_catalog or TariffCatalog()).bundle(
        assignment.utility,
        nbt_scenario,
    )
    import_source_id = tariff.import_schedule.source_id
    export_source_ids = tuple(
        sorted(
            str(value)
            for value in tariff.export_schedule.rows["source_id"].unique()
        )
    )
    if not import_source_id or not export_source_ids:
        raise ValueError(
            f"{assignment.utility.value} tariff sources are missing identity"
        )

    annual_import_kwh = float(validated["import_kwh"].sum())
    annual_export_kwh = float(validated["export_kwh"].sum())
    net_surplus_kwh = max(annual_export_kwh - annual_import_kwh, 0.0)
    adjustment_source_id = None
    nsc_source_id = None
    if net_surplus_kwh > 0.0:
        adjustment = (
            adjustment_schedule
            or AverageRetailExportCompensationSchedule.from_csv()
        ).resolve(assignment.utility, nbt_scenario.true_up_month)
        nsc = (
            nsc_schedule or NetSurplusCompensationSchedule.from_csv()
        ).resolve(assignment.utility, nbt_scenario.true_up_month)
        adjustment_source_id = adjustment.source_id
        nsc_source_id = nsc.source_id

    return NBTPreflightResult(
        county_slug=county_slug,
        utility=assignment.utility,
        profile_path=path,
        row_count=len(validated),
        annual_import_kwh=annual_import_kwh,
        annual_export_kwh=annual_export_kwh,
        net_surplus_kwh=net_surplus_kwh,
        import_source_id=import_source_id,
        export_source_ids=export_source_ids,
        adjustment_source_id=adjustment_source_id,
        nsc_source_id=nsc_source_id,
    )


def preflight_nbt_run(
    *,
    base_input_dir: str | Path,
    scenario_name: str,
    housing_type: str,
    counties: Sequence[str],
    nbt_scenario: NBTScenario,
) -> tuple[list[NBTPreflightResult], list[str]]:
    """Validate multiple counties while retaining every county-level failure."""

    results: list[NBTPreflightResult] = []
    failures: list[str] = []
    for county in counties:
        try:
            results.append(
                preflight_nbt_county(
                    base_input_dir=base_input_dir,
                    scenario_name=scenario_name,
                    housing_type=housing_type,
                    county=county,
                    nbt_scenario=nbt_scenario,
                )
            )
        except Exception as exc:
            failures.append(f"{slugify_county_name(county)}: {exc}")
    return results, failures
