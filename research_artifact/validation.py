"""Fail-loud validation for a completed research pipeline run.

This module validates outputs that the pipeline already produced. It does not
run optimization, select tariffs, or repair malformed results.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import subprocess
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd

from appliances.battery_storage import BatteryStorageAppliance
from appliances.solar_system import SolarSystemAppliance
from helpers.main_helpers import (
    central_counties,
    norcal_counties,
    socal_counties,
    slugify_county_name,
)
from scenarios import SCENARIOS
from tariffs import NBTScenario, TariffCatalog
from tariffs.calendar import full_year_hourly_index
from tariffs.geography import resolve_county_service_assignment
from tariffs.preflight import preflight_nbt_county


EXPECTED_HOURS = 8_760
FLOW_TOLERANCE_KWH = 1e-6
RECONCILIATION_TOLERANCE_USD = 1e-3
ANNUAL_LOAD_RANGE_KWH = (2_000.0, 30_000.0)
ANNUAL_BILL_RANGE_USD = (0.0, 20_000.0)
MAX_PV_CAPACITY_KW = 15.0
MAX_RATE_USD_PER_KWH = 5.0
MIN_EXPECTED_EXPORT_SPIKE_USD_PER_KWH = 0.5

_RESULT_TIMESTAMP = re.compile(r"_(\d{8}_\d{2})\.csv$")


@dataclass(frozen=True)
class ResearchRunSpec:
    repo_root: Path
    base_input_dir: Path
    scenario: str
    housing_type: str
    counties: tuple[str, ...]
    nbt_scenario: NBTScenario = NBTScenario()
    discount_rate: float = 0.07
    max_battery_kwh: float = 40.0

    def __post_init__(self) -> None:
        if self.scenario not in SCENARIOS:
            raise KeyError(f"Scenario {self.scenario!r} is not defined")
        if not self.scenario.endswith("_coopt"):
            raise ValueError("Research validation requires a _coopt scenario")
        if not self.counties:
            raise ValueError("Research validation requires at least one county")
        if len(set(self.counties)) != len(self.counties):
            raise ValueError("Research validation counties must be unique")
        if self.discount_rate < 0.0:
            raise ValueError("discount_rate must be non-negative")
        if self.max_battery_kwh <= 0.0:
            raise ValueError("max_battery_kwh must be positive")


@dataclass(frozen=True)
class RepositoryState:
    commit: str
    dirty: bool
    commit_time_utc: str


@dataclass(frozen=True)
class ArtifactRecord:
    path: str
    sha256: str
    size_bytes: int
    modified_at_utc: str


@dataclass(frozen=True)
class ValidationCheck:
    check_id: str
    status: str
    message: str
    metrics: dict
    artifacts: tuple[ArtifactRecord, ...] = ()


@dataclass(frozen=True)
class ResearchValidationReport:
    schema_version: int
    generated_at_utc: str
    repository: RepositoryState
    run: dict
    checks: tuple[ValidationCheck, ...]

    @property
    def passed(self) -> bool:
        return all(check.status == "pass" for check in self.checks)

    def to_dict(self) -> dict:
        value = asdict(self)
        value["passed"] = self.passed
        value["summary"] = {
            "passed": sum(check.status == "pass" for check in self.checks),
            "failed": sum(check.status == "fail" for check in self.checks),
            "total": len(self.checks),
        }
        return value


def repository_state(repo_root: Path) -> RepositoryState:
    root = repo_root.resolve()
    commit = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=root, text=True
    ).strip()
    dirty = bool(
        subprocess.check_output(
            ["git", "status", "--porcelain"], cwd=root, text=True
        ).strip()
    )
    commit_time = subprocess.check_output(
        ["git", "show", "-s", "--format=%cI", "HEAD"],
        cwd=root,
        text=True,
    ).strip()
    parsed = datetime.fromisoformat(commit_time).astimezone(timezone.utc)
    return RepositoryState(
        commit=commit,
        dirty=dirty,
        commit_time_utc=parsed.isoformat().replace("+00:00", "Z"),
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _artifact(
    path: Path,
    *,
    repo_root: Path,
    minimum_time: datetime | None,
) -> ArtifactRecord:
    if not path.is_file():
        raise FileNotFoundError(f"Required research artifact not found: {path}")
    modified = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    if minimum_time is not None and modified < minimum_time:
        raise ValueError(
            f"Research artifact predates the source commit: {path}; "
            f"artifact={modified.isoformat()}, commit={minimum_time.isoformat()}"
        )
    try:
        relative = path.resolve().relative_to(repo_root.resolve())
    except ValueError as exc:
        raise ValueError(f"Research artifact is outside the repository: {path}") from exc
    return ArtifactRecord(
        path=relative.as_posix(),
        sha256=_sha256(path),
        size_bytes=path.stat().st_size,
        modified_at_utc=modified.isoformat().replace("+00:00", "Z"),
    )


def _source_manifest_artifacts(
    manifest_path: Path,
    *,
    repo_root: Path,
) -> tuple[ArtifactRecord, ...]:
    manifest = json.loads(manifest_path.read_text())
    sources = manifest.get("sources")
    if not isinstance(sources, list) or not sources:
        raise ValueError(f"{manifest_path} must contain a non-empty sources list")
    records = []
    for index, source in enumerate(sources):
        if source.get("archive_status") != "archived":
            raise ValueError(
                f"{manifest_path} source {index} is not archived: "
                f"{source.get('source_id', source.get('filename', 'unknown'))}"
            )
        archive_path = source.get("archive_path")
        expected_hash = source.get("sha256")
        if not archive_path or not expected_hash:
            raise ValueError(
                f"{manifest_path} source {index} lacks archive_path or sha256"
            )
        archive = manifest_path.parent / archive_path
        record = _artifact(archive, repo_root=repo_root, minimum_time=None)
        if record.sha256 != expected_hash:
            raise ValueError(
                f"Archived source hash mismatch: {archive}; "
                f"expected={expected_hash}, actual={record.sha256}"
            )
        records.append(record)
    return tuple(records)


def _hourly_frame(path: Path, required_columns: Iterable[str]) -> pd.DataFrame:
    frame = pd.read_csv(path)
    missing = set(required_columns) - set(frame.columns)
    if missing:
        raise ValueError(f"{path} is missing columns: {sorted(missing)}")
    if len(frame) != EXPECTED_HOURS:
        raise ValueError(
            f"{path} must contain {EXPECTED_HOURS} rows; found {len(frame)}"
        )
    if frame[list(required_columns)].isna().any().any():
        raise ValueError(f"{path} contains missing required values")
    timestamps = pd.DatetimeIndex(
        pd.to_datetime(frame["timestamp"], errors="raise")
    )
    if timestamps.has_duplicates or timestamps.hasnans:
        raise ValueError(f"{path} timestamps must be unique and complete")
    differences = timestamps.to_series().diff().dropna()
    if not (differences == pd.Timedelta(hours=1)).all():
        raise ValueError(f"{path} timestamps must use one-hour intervals")
    return frame


def _finite_numeric(frame: pd.DataFrame, columns: Iterable[str], path: Path) -> None:
    for column in columns:
        values = pd.to_numeric(frame[column], errors="raise").astype(float)
        if not np.isfinite(values).all():
            raise ValueError(f"{path} column {column!r} contains non-finite values")


def _latest_result(county_dir: Path, subdir: str, prefix: str) -> tuple[Path, str]:
    candidates = sorted((county_dir / "results" / subdir).glob(f"{prefix}_*.csv"))
    if not candidates:
        raise FileNotFoundError(
            f"No {subdir} result matches {prefix}_*.csv in {county_dir}"
        )
    path = candidates[-1]
    match = _RESULT_TIMESTAMP.search(path.name)
    if match is None:
        raise ValueError(f"Result filename lacks a canonical timestamp: {path}")
    return path, match.group(1)


def _validate_bill_frame(
    frame: pd.DataFrame,
    *,
    scenario: str,
    nbt_baseline_may_be_missing: bool,
    path: Path,
) -> None:
    if "scenario" not in frame.columns:
        raise ValueError(f"{path} is missing the scenario column")
    expected_rows = {scenario, f"{scenario}.solarstorage"}
    if set(frame["scenario"]) != expected_rows:
        raise ValueError(
            f"{path} scenario rows do not match {sorted(expected_rows)}"
        )
    indexed = frame.set_index("scenario")
    for column in indexed.columns:
        values = pd.to_numeric(indexed[column], errors="raise")
        for row_name, value in values.items():
            allowed_missing = (
                nbt_baseline_may_be_missing
                and "_NEM3" in column
                and row_name == scenario
            )
            if pd.isna(value):
                if not allowed_missing:
                    raise ValueError(f"{path} has unexpected NaN at {row_name}, {column}")
                continue
            if not math.isfinite(float(value)):
                raise ValueError(f"{path} has non-finite value at {row_name}, {column}")


def _reconcile_bills(
    electricity: pd.DataFrame,
    gas: pd.DataFrame,
    totals: pd.DataFrame,
) -> None:
    elec = electricity.set_index("scenario")
    gas_cost = gas.set_index("scenario")
    total_cost = totals.set_index("scenario")
    if not total_cost.index.equals(elec.index) or not total_cost.index.equals(
        gas_cost.index
    ):
        raise ValueError("Electricity, gas, and total result rows do not align")

    for total_column in total_cost.columns:
        if not total_column.startswith("total.") or "+" not in total_column:
            raise ValueError(f"Malformed total-cost column: {total_column}")
        electricity_name, gas_name = total_column.removeprefix("total.").split(
            "+", 1
        )
        electricity_column = f"electricity.{electricity_name}"
        gas_column = f"gas.{gas_name}"
        if electricity_column not in elec or gas_column not in gas_cost:
            raise ValueError(
                f"{total_column} cannot be reconciled to {electricity_column} "
                f"and {gas_column}"
            )
        expected = elec[electricity_column] + gas_cost[gas_column]
        actual = total_cost[total_column]
        if not np.array_equal(expected.isna().to_numpy(), actual.isna().to_numpy()):
            raise ValueError(f"{total_column} does not preserve missing values")
        valid = expected.notna()
        if not np.allclose(
            expected[valid],
            actual[valid],
            rtol=0.0,
            atol=RECONCILIATION_TOLERANCE_USD,
        ):
            difference = float((expected[valid] - actual[valid]).abs().max())
            raise ValueError(
                f"{total_column} fails cost reconciliation; max difference="
                f"${difference:.6f}"
            )


def _validate_dispatch(
    dispatch: pd.DataFrame,
    exports: pd.DataFrame,
    rates: pd.DataFrame,
    *,
    path: Path,
) -> dict:
    flow_columns = (
        "Load Profile",
        "System to Load",
        "Battery to Load",
        "Grid to Load",
        "System to Battery",
        "Grid to Battery",
        "PV to Grid (kWh)",
        "Battery to Grid (kWh)",
        "Difference",
    )
    _finite_numeric(dispatch, flow_columns, path)
    nonnegative = [column for column in flow_columns if column != "Difference"]
    if (dispatch[nonnegative] < 0.0).any().any():
        raise ValueError(f"{path} contains negative physical flows")
    max_balance_error = float(dispatch["Difference"].abs().max())
    if max_balance_error > FLOW_TOLERANCE_KWH:
        raise ValueError(
            f"{path} load balance exceeds {FLOW_TOLERANCE_KWH} kWh; "
            f"maximum={max_balance_error}"
        )

    imports = dispatch["Grid to Load"] + dispatch["Grid to Battery"]
    dispatch_exports = (
        dispatch["PV to Grid (kWh)"] + dispatch["Battery to Grid (kWh)"]
    )
    simultaneous = (imports > FLOW_TOLERANCE_KWH) & (
        dispatch_exports > FLOW_TOLERANCE_KWH
    )
    if simultaneous.any():
        first = int(simultaneous[simultaneous].index[0])
        raise ValueError(f"{path} imports and exports simultaneously at row {first}")

    published_exports = pd.to_numeric(
        exports["Exports to Grid (kWh)"], errors="raise"
    )
    rate_imports = pd.to_numeric(rates["nem3.imports.kwh"], errors="raise")
    rate_exports = pd.to_numeric(rates["nem3.exports.kwh"], errors="raise")
    comparisons = (
        (dispatch_exports, published_exports, "dispatch export file"),
        (imports, rate_imports, "NBT imports"),
        (dispatch_exports, rate_exports, "NBT exports"),
    )
    for left, right, label in comparisons:
        if not np.allclose(left, right, rtol=0.0, atol=FLOW_TOLERANCE_KWH):
            difference = float(np.max(np.abs(left - right)))
            raise ValueError(f"{path} does not reconcile with {label}; max={difference}")

    annual_load = float(dispatch["Load Profile"].sum())
    lower, upper = ANNUAL_LOAD_RANGE_KWH
    if not lower <= annual_load <= upper:
        raise ValueError(
            f"{path} annual load {annual_load:.1f} kWh is outside "
            f"the {lower:.0f}-{upper:.0f} kWh research range"
        )
    return {
        "annual_load_kwh": annual_load,
        "annual_import_kwh": float(imports.sum()),
        "annual_export_kwh": float(dispatch_exports.sum()),
        "max_load_balance_error_kwh": max_balance_error,
    }


def _validate_prices(
    prices: pd.DataFrame,
    *,
    county: str,
    nbt_scenario: NBTScenario,
    path: Path,
) -> dict:
    columns = ("import_price_usd_per_kwh", "export_price_usd_per_kwh")
    _finite_numeric(prices, columns, path)
    values = prices[list(columns)]
    if (values < 0.0).any().any() or (values > MAX_RATE_USD_PER_KWH).any().any():
        raise ValueError(f"{path} contains a rate outside 0-{MAX_RATE_USD_PER_KWH} USD/kWh")

    assignment = resolve_county_service_assignment(county)
    tariff = TariffCatalog().bundle(assignment.utility, nbt_scenario)
    timestamps = full_year_hourly_index(nbt_scenario.billing_year)
    expected_import = np.asarray(tariff.import_schedule.rates_for(timestamps))
    expected_export = np.asarray(
        tariff.export_schedule.rates_for(timestamps, component="total")
    ) + tariff.acc_plus_rate
    if not np.allclose(
        prices[columns[0]], expected_import, rtol=0.0, atol=1e-12
    ):
        raise ValueError(f"{path} import prices do not match the tariff catalog")
    if not np.allclose(
        prices[columns[1]], expected_export, rtol=0.0, atol=1e-12
    ):
        raise ValueError(f"{path} export prices do not match the tariff catalog")
    maximum_export = float(prices[columns[1]].max())
    if maximum_export < MIN_EXPECTED_EXPORT_SPIKE_USD_PER_KWH:
        raise ValueError(
            f"{path} lacks the expected NBT export-price spike; "
            f"maximum=${maximum_export:.3f}/kWh"
        )
    return {
        "import_mean_usd_per_kwh": float(prices[columns[0]].mean()),
        "export_mean_usd_per_kwh": float(prices[columns[1]].mean()),
        "export_max_usd_per_kwh": maximum_export,
    }


def _validate_county(
    spec: ResearchRunSpec,
    county: str,
    *,
    minimum_time: datetime | None,
) -> tuple[dict, tuple[ArtifactRecord, ...]]:
    county_slug = slugify_county_name(county)
    county_dir = (
        spec.base_input_dir / spec.scenario / spec.housing_type / county_slug
    )
    paths = {
        "weather": county_dir / f"weather_TMY_{county_slug}.csv",
        "combined": county_dir / f"combined_profiles_{spec.scenario}_{county_slug}.csv",
        "dispatch": county_dir / f"solar_storage_dispatch_profiles_{county_slug}.csv",
        "exports": county_dir
        / f"solar_storage_dispatch_profiles_with_exports_{county_slug}.csv",
        "rates": county_dir / f"loadprofiles_for_rates_{county_slug}.csv",
        "prices": county_dir / f"coopt_price_series_{county_slug}.csv",
    }
    artifacts = [
        _artifact(path, repo_root=spec.repo_root, minimum_time=minimum_time)
        for path in paths.values()
    ]

    electricity_path, electricity_time = _latest_result(
        county_dir,
        "electricity",
        f"RESULTS_electricity_annual_costs_{county_slug}",
    )
    gas_path, gas_time = _latest_result(
        county_dir, "gas", f"RESULTS_gas_annual_costs_{county_slug}"
    )
    totals_path, totals_time = _latest_result(
        county_dir, "totals", f"RESULTS_total_annual_costs_{county_slug}"
    )
    if len({electricity_time, gas_time, totals_time}) != 1:
        raise ValueError(
            f"{county_slug} latest billing outputs have different run timestamps: "
            f"electricity={electricity_time}, gas={gas_time}, totals={totals_time}"
        )
    for path in (electricity_path, gas_path, totals_path):
        artifacts.append(
            _artifact(path, repo_root=spec.repo_root, minimum_time=minimum_time)
        )

    combined = _hourly_frame(
        paths["combined"],
        (
            "timestamp",
            "electricity.real_and_simulated.for_typical_county_home.kwh",
        ),
    )
    _finite_numeric(
        combined,
        ("electricity.real_and_simulated.for_typical_county_home.kwh",),
        paths["combined"],
    )
    dispatch = _hourly_frame(
        paths["dispatch"],
        (
            "timestamp",
            "Load Profile",
            "System to Load",
            "Battery to Load",
            "Grid to Load",
            "System to Battery",
            "Grid to Battery",
            "PV to Grid (kWh)",
            "Battery to Grid (kWh)",
            "Difference",
        ),
    )
    exports = _hourly_frame(
        paths["exports"], ("timestamp", "Exports to Grid (kWh)")
    )
    rates = _hourly_frame(
        paths["rates"],
        ("timestamp", "nem3.imports.kwh", "nem3.exports.kwh"),
    )
    prices = _hourly_frame(
        paths["prices"],
        ("timestamp", "import_price_usd_per_kwh", "export_price_usd_per_kwh"),
    )

    dispatch_metrics = _validate_dispatch(
        dispatch, exports, rates, path=paths["dispatch"]
    )
    price_metrics = _validate_prices(
        prices,
        county=county_slug,
        nbt_scenario=spec.nbt_scenario,
        path=paths["prices"],
    )
    preflight = preflight_nbt_county(
        base_input_dir=spec.base_input_dir,
        scenario_name=spec.scenario,
        housing_type=spec.housing_type,
        county=county_slug,
        nbt_scenario=spec.nbt_scenario,
    )

    electricity = pd.read_csv(electricity_path)
    gas = pd.read_csv(gas_path)
    totals = pd.read_csv(totals_path)
    _validate_bill_frame(
        electricity,
        scenario=spec.scenario,
        nbt_baseline_may_be_missing=True,
        path=electricity_path,
    )
    _validate_bill_frame(
        gas,
        scenario=spec.scenario,
        nbt_baseline_may_be_missing=False,
        path=gas_path,
    )
    _validate_bill_frame(
        totals,
        scenario=spec.scenario,
        nbt_baseline_may_be_missing=True,
        path=totals_path,
    )
    _reconcile_bills(electricity, gas, totals)

    solar_row = electricity.set_index("scenario").loc[
        f"{spec.scenario}.solarstorage"
    ]
    nbt_columns = [column for column in solar_row.index if column.endswith("_NEM3")]
    if len(nbt_columns) != 1:
        raise ValueError(
            f"{electricity_path} must contain exactly one NBT billing column"
        )
    nbt_bill = float(solar_row[nbt_columns[0]])
    lower_bill, upper_bill = ANNUAL_BILL_RANGE_USD
    if not lower_bill <= nbt_bill <= upper_bill:
        raise ValueError(
            f"{county_slug} NBT bill ${nbt_bill:.2f} is outside the "
            f"${lower_bill:.0f}-${upper_bill:.0f} research range"
        )

    metrics = {
        **dispatch_metrics,
        **price_metrics,
        "utility": preflight.utility.value,
        "annual_nbt_bill_usd": nbt_bill,
        "billing_output_timestamp": electricity_time,
        "import_source_id": preflight.import_source_id,
        "export_source_ids": list(preflight.export_source_ids),
        "annual_net_surplus_kwh": preflight.net_surplus_kwh,
    }
    return metrics, tuple(artifacts)


def _require_columns(frame: pd.DataFrame, columns: Iterable[str], path: Path) -> None:
    missing = set(columns) - set(frame.columns)
    if missing:
        raise ValueError(f"{path} is missing columns: {sorted(missing)}")


def _validate_shared_outputs(
    spec: ResearchRunSpec,
    *,
    minimum_time: datetime | None,
) -> tuple[dict, tuple[ArtifactRecord, ...]]:
    housing_tag = spec.housing_type.replace("-", "_")
    scenario_root = spec.base_input_dir / spec.scenario / spec.housing_type
    capacity_path = scenario_root / "CAPITAL_COSTS" / "electrified_assets.csv"
    capital_dir = spec.base_input_dir / "capital_costs"
    capital_paths = (
        capital_dir / f"capital_costs_{spec.scenario}_{housing_tag}.csv",
        capital_dir / f"capital_costs_summary_{spec.scenario}_{housing_tag}.csv",
        capital_dir
        / f"capital_costs_summary_with_pv_{spec.scenario}_{housing_tag}.csv",
    )
    generated_paths = (capacity_path, *capital_paths)
    artifacts = [
        _artifact(path, repo_root=spec.repo_root, minimum_time=minimum_time)
        for path in generated_paths
    ]
    manifest_paths = (
        spec.repo_root / "data" / "tariffs" / "import_source_manifest.json",
        spec.repo_root / "data" / "tariffs" / "source_manifest.json",
        spec.repo_root / "data" / "tariffs" / "true_up_source_manifest.json",
    )
    for path in manifest_paths:
        artifacts.append(
            _artifact(path, repo_root=spec.repo_root, minimum_time=None)
        )
        artifacts.extend(
            _source_manifest_artifacts(path, repo_root=spec.repo_root)
        )
    normalized_source_paths = (
        spec.repo_root / "data" / "tariffs" / "import_rate_snapshots.json",
        spec.repo_root / "data" / "tariffs" / "nbt_export_rates.csv",
        spec.repo_root / "data" / "tariffs" / "acc_plus_rates.csv",
        spec.repo_root / "data" / "tariffs" / "eec_adjustment_rates.csv",
        spec.repo_root / "data" / "tariffs" / "nsc_rates.csv",
    )
    artifacts.extend(
        _artifact(path, repo_root=spec.repo_root, minimum_time=None)
        for path in normalized_source_paths
    )

    capacity = pd.read_csv(capacity_path)
    required_capacity = (
        "County",
        "Utility",
        "Import Tariff Plan",
        "Import Tariff Source ID",
        "NBT Billing Year",
        "NBT Interconnection Vintage",
        "Solar Capacity (kW)",
        "Battery Capacity (kWh)",
        "Battery Capacity Upper Bound (kWh)",
        "Coopt Total Cost",
        "Coopt Capex Annual",
        "Coopt Import Cost",
        "Coopt Export Credit",
        "Coopt Degradation Cost",
    )
    _require_columns(capacity, required_capacity, capacity_path)
    expected_counties = {slugify_county_name(county) for county in spec.counties}
    if set(capacity["County"]) != expected_counties:
        missing = expected_counties - set(capacity["County"])
        extra = set(capacity["County"]) - expected_counties
        raise ValueError(
            f"{capacity_path} county set differs; missing={sorted(missing)}, "
            f"extra={sorted(extra)}"
        )
    if capacity["County"].duplicated().any():
        raise ValueError(f"{capacity_path} contains duplicate counties")

    catalog = TariffCatalog()
    numeric_columns = required_capacity[5:]
    _finite_numeric(capacity, numeric_columns, capacity_path)
    for row in capacity.to_dict("records"):
        county = row["County"]
        assignment = resolve_county_service_assignment(county)
        tariff = catalog.bundle(assignment.utility, spec.nbt_scenario)
        identity = (
            row["Utility"],
            row["Import Tariff Plan"],
            row["Import Tariff Source ID"],
        )
        expected_identity = (
            assignment.utility.value,
            tariff.import_schedule.plan_name,
            tariff.import_schedule.source_id,
        )
        if identity != expected_identity:
            raise ValueError(
                f"{capacity_path} has wrong tariff identity for {county}: "
                f"{identity!r}, expected {expected_identity!r}"
            )
        if int(row["NBT Billing Year"]) != spec.nbt_scenario.billing_year:
            raise ValueError(f"{capacity_path} has wrong NBT billing year for {county}")
        if int(row["NBT Interconnection Vintage"]) != spec.nbt_scenario.nbt_vintage:
            raise ValueError(f"{capacity_path} has wrong NBT vintage for {county}")
        pv_kw = float(row["Solar Capacity (kW)"])
        battery_kwh = float(row["Battery Capacity (kWh)"])
        upper_bound = float(row["Battery Capacity Upper Bound (kWh)"])
        if not 0.0 <= pv_kw <= MAX_PV_CAPACITY_KW:
            raise ValueError(f"{county} PV capacity {pv_kw} kW is outside the model range")
        if upper_bound != spec.max_battery_kwh:
            raise ValueError(f"{county} battery bound {upper_bound} kWh is unexpected")
        if not 0.0 <= battery_kwh <= upper_bound:
            raise ValueError(f"{county} battery capacity {battery_kwh} kWh is invalid")
        reconciled = (
            float(row["Coopt Capex Annual"])
            + float(row["Coopt Import Cost"])
            - float(row["Coopt Export Credit"])
            + float(row["Coopt Degradation Cost"])
        )
        if not math.isclose(
            float(row["Coopt Total Cost"]),
            reconciled,
            rel_tol=0.0,
            abs_tol=RECONCILIATION_TOLERANCE_USD,
        ):
            raise ValueError(f"{capacity_path} objective does not reconcile for {county}")

    capital = pd.read_csv(capital_paths[-1])
    _require_columns(
        capital,
        ("county_slug", "solar_kw", "pv_capex", "storage_capex"),
        capital_paths[-1],
    )
    if set(capital["county_slug"]) != expected_counties:
        raise ValueError(f"{capital_paths[-1]} does not cover the requested counties")
    if capital["county_slug"].duplicated().any():
        raise ValueError(f"{capital_paths[-1]} contains duplicate counties")
    merged = capacity.merge(
        capital,
        left_on="County",
        right_on="county_slug",
        validate="one_to_one",
    )
    if not np.allclose(
        merged["Solar Capacity (kW)"], merged["solar_kw"], rtol=0.0, atol=0.01
    ):
        raise ValueError("Step 9b and Step 14 solar capacities do not reconcile")
    expected_pv_capex = merged["solar_kw"] * SolarSystemAppliance.per_kw_cost()
    if not np.allclose(
        merged["pv_capex"], expected_pv_capex, rtol=0.0, atol=0.01
    ):
        raise ValueError("Step 14 PV capital cost does not match the source cost")
    expected_storage = (
        merged["Battery Capacity (kWh)"] * BatteryStorageAppliance.per_kwh_cost()
    )
    if not np.allclose(
        merged["storage_capex"], expected_storage, rtol=0.0, atol=0.01
    ):
        raise ValueError("Step 14 storage capital cost does not match the source cost")

    return (
        {
            "county_count": len(expected_counties),
            "mean_pv_capacity_kw": float(capacity["Solar Capacity (kW)"].mean()),
            "mean_battery_capacity_kwh": float(
                capacity["Battery Capacity (kWh)"].mean()
            ),
            "pv_cost_usd_per_kw": SolarSystemAppliance.per_kw_cost(),
            "battery_cost_usd_per_kwh": BatteryStorageAppliance.per_kwh_cost(),
        },
        tuple(artifacts),
    )


def _run_check(check_id: str, operation) -> ValidationCheck:
    try:
        metrics, artifacts = operation()
    except Exception as exc:
        return ValidationCheck(
            check_id=check_id,
            status="fail",
            message=str(exc),
            metrics={},
        )
    return ValidationCheck(
        check_id=check_id,
        status="pass",
        message="Validation passed",
        metrics=metrics,
        artifacts=artifacts,
    )


def validate_research_run(
    spec: ResearchRunSpec,
    *,
    state: RepositoryState | None = None,
    require_clean: bool = True,
    require_current_artifacts: bool = True,
    generated_at_utc: str | None = None,
) -> ResearchValidationReport:
    """Validate one explicit completed run and retain every county failure."""

    state = state or repository_state(spec.repo_root)
    commit_time = datetime.fromisoformat(
        state.commit_time_utc.replace("Z", "+00:00")
    )
    minimum_time = commit_time if require_current_artifacts else None
    checks = []
    repository_check = ValidationCheck(
        check_id="repository",
        status="fail" if require_clean and state.dirty else "pass",
        message=(
            "Working tree is dirty"
            if require_clean and state.dirty
            else "Repository identity is valid"
        ),
        metrics={"commit": state.commit, "dirty": state.dirty},
    )
    checks.append(repository_check)
    checks.append(
        _run_check(
            "shared_outputs",
            lambda: _validate_shared_outputs(spec, minimum_time=minimum_time),
        )
    )
    for county in spec.counties:
        county_slug = slugify_county_name(county)
        checks.append(
            _run_check(
                f"county:{county_slug}",
                lambda county=county: _validate_county(
                    spec, county, minimum_time=minimum_time
                ),
            )
        )

    generated_at = generated_at_utc or datetime.now(timezone.utc).isoformat().replace(
        "+00:00", "Z"
    )
    return ResearchValidationReport(
        schema_version=1,
        generated_at_utc=generated_at,
        repository=state,
        run={
            "scenario": spec.scenario,
            "housing_type": spec.housing_type,
            "counties": list(spec.counties),
            "county_count": len(spec.counties),
            "discount_rate": spec.discount_rate,
            "max_battery_kwh": spec.max_battery_kwh,
            "nbt": {
                "billing_year": spec.nbt_scenario.billing_year,
                "interconnection_vintage": spec.nbt_scenario.nbt_vintage,
                "customer_segment": spec.nbt_scenario.customer_segment.value,
                "tariff_snapshot_date": spec.nbt_scenario.tariff_snapshot_date,
                "true_up_month": spec.nbt_scenario.true_up_month,
                "include_acc_plus": spec.nbt_scenario.include_acc_plus,
            },
            "require_clean": require_clean,
            "require_current_artifacts": require_current_artifacts,
        },
        checks=tuple(checks),
    )


def report_text(report: ResearchValidationReport) -> str:
    summary = report.to_dict()["summary"]
    lines = [
        f"Research validation: {'PASS' if report.passed else 'FAIL'}",
        f"Commit: {report.repository.commit}",
        f"Scenario: {report.run['scenario']}",
        f"Counties: {report.run['county_count']}",
        (
            f"Checks: {summary['passed']} passed; {summary['failed']} failed; "
            f"{summary['total']} total"
        ),
        "",
    ]
    for check in report.checks:
        lines.append(f"{check.status.upper()} {check.check_id}: {check.message}")
    return "\n".join(lines) + "\n"


def write_report(
    report: ResearchValidationReport,
    output_dir: Path,
    *,
    report_id: str | None = None,
) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    identifier = report_id or (
        f"{report.run['scenario']}-{report.repository.commit[:8]}"
    )
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", identifier):
        raise ValueError("report_id contains unsupported characters")
    json_path = output_dir / f"{identifier}.json"
    text_path = output_dir / f"{identifier}.txt"
    if json_path.exists() or text_path.exists():
        raise FileExistsError(f"Research validation report already exists: {identifier}")
    json_path.write_text(json.dumps(report.to_dict(), indent=2, sort_keys=True) + "\n")
    text_path.write_text(report_text(report))
    return json_path, text_path


def _all_counties() -> tuple[str, ...]:
    names = norcal_counties + central_counties + socal_counties
    return tuple(slugify_county_name(name) for name in names)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Validate a completed research pipeline run"
    )
    parser.add_argument("scenario")
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument("--all-counties", action="store_true")
    selection.add_argument("--counties", nargs="+")
    parser.add_argument("--housing-type", default="single-family-detached")
    parser.add_argument("--base-input-dir", default="data/loadprofiles")
    parser.add_argument("--output-dir", default="analysis_results/research_validation")
    parser.add_argument("--report-id")
    parser.add_argument("--allow-dirty", action="store_true")
    parser.add_argument("--allow-stale-artifacts", action="store_true")
    args = parser.parse_args()

    root = Path.cwd().resolve()
    counties = _all_counties() if args.all_counties else tuple(args.counties)
    spec = ResearchRunSpec(
        repo_root=root,
        base_input_dir=(root / args.base_input_dir).resolve(),
        scenario=args.scenario,
        housing_type=args.housing_type,
        counties=counties,
    )
    report = validate_research_run(
        spec,
        require_clean=not args.allow_dirty,
        require_current_artifacts=not args.allow_stale_artifacts,
    )
    json_path, text_path = write_report(
        report,
        Path(args.output_dir),
        report_id=args.report_id,
    )
    print(report_text(report), end="")
    print(f"JSON: {json_path}")
    print(f"Text: {text_path}")
    raise SystemExit(0 if report.passed else 1)


if __name__ == "__main__":
    main()
