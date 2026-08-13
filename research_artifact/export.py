"""Export existing model outputs for the public research companion.

This module does not run an optimization, change a scenario, or recalculate a
tariff. It validates and packages the hourly outputs already written by Step 10.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

from scenarios import SCENARIOS


SCHEMA_VERSION = 1
EXPECTED_HOURS = 8760
IDENTIFIER_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
HOUSING_TYPE_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]*$")
SERIES_COLUMNS = {
    "householdElectricityKwh": "default.electricity.kwh",
    "householdGasTherms": "default.gas.therms",
    "retailGridImportsKwh": "retail.imports.kwh",
    "retailGridExportsKwh": "retail.exports.kwh",
    "nem3GridImportsKwh": "nem3.imports.kwh",
    "nem3GridExportsKwh": "nem3.exports.kwh",
    "solarStorageGasTherms": "solarstorage.gas.therms",
}
REQUIRED_COLUMNS = ("timestamp", *SERIES_COLUMNS.values())


@dataclass(frozen=True)
class ResearchProvenance:
    commit: str
    dirty: bool


@dataclass(frozen=True)
class ReleaseBundle:
    release_id: str
    manifest: bytes
    profiles: dict[str, bytes]


def _json_bytes(value: object) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_identifier(value: str, label: str) -> None:
    if not IDENTIFIER_PATTERN.fullmatch(value):
        raise ValueError(
            f"{label} must contain only lowercase letters, numbers, hyphens, "
            "and underscores"
        )


def _validate_housing_type(value: str) -> None:
    if not HOUSING_TYPE_PATTERN.fullmatch(value):
        raise ValueError(
            "housing type must contain only lowercase letters, numbers, and hyphens"
        )


def repository_provenance(repo_root: Path) -> ResearchProvenance:
    root = repo_root.resolve()
    commit = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=root, text=True
    ).strip()
    dirty = bool(
        subprocess.check_output(
            ["git", "status", "--porcelain"], cwd=root, text=True
        ).strip()
    )
    return ResearchProvenance(commit=commit, dirty=dirty)


def _parse_timestamp(value: str, source_path: Path, row_number: int) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise ValueError(
            f"{source_path} row {row_number} has invalid timestamp {value!r}"
        ) from error
    if parsed.tzinfo is not None:
        raise ValueError(
            f"{source_path} row {row_number} timestamp must preserve the model's naive local time"
        )
    return parsed


def _parse_number(value: str, source_path: Path, row_number: int, column: str) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as error:
        raise ValueError(
            f"{source_path} row {row_number} column {column!r} is not numeric"
        ) from error
    if not math.isfinite(parsed):
        raise ValueError(
            f"{source_path} row {row_number} column {column!r} is not finite"
        )
    return parsed


def _read_profile(
    source_path: Path,
    *,
    repo_root: Path,
    scenario_id: str,
    county_id: str,
    housing_type: str,
) -> dict:
    if not source_path.is_file():
        raise FileNotFoundError(f"Research profile not found: {source_path}")

    with source_path.open(newline="", encoding="utf-8") as source:
        reader = csv.DictReader(source)
        if reader.fieldnames is None:
            raise ValueError(f"Research profile has no header: {source_path}")
        missing = set(REQUIRED_COLUMNS) - set(reader.fieldnames)
        if missing:
            raise ValueError(
                f"{source_path} is missing required columns: {sorted(missing)}"
            )

        timestamps: list[datetime] = []
        series = {name: [] for name in SERIES_COLUMNS}
        for row_number, row in enumerate(reader, start=2):
            timestamps.append(
                _parse_timestamp(row["timestamp"], source_path, row_number)
            )
            for public_name, source_name in SERIES_COLUMNS.items():
                series[public_name].append(
                    _parse_number(row[source_name], source_path, row_number, source_name)
                )

    if len(timestamps) != EXPECTED_HOURS:
        raise ValueError(
            f"{source_path} must contain exactly {EXPECTED_HOURS} hourly rows; "
            f"found {len(timestamps)}"
        )
    for index, (earlier, later) in enumerate(zip(timestamps, timestamps[1:]), start=2):
        if later - earlier != timedelta(hours=1):
            raise ValueError(
                f"{source_path} rows {index} and {index + 1} are not one hour apart"
            )

    try:
        relative_source = source_path.resolve().relative_to(repo_root.resolve())
    except ValueError as error:
        raise ValueError(
            f"Research profile must be inside the repository: {source_path}"
        ) from error

    annual_totals = {
        name: math.fsum(values) for name, values in series.items()
    }
    return {
        "schemaVersion": SCHEMA_VERSION,
        "scenarioId": scenario_id,
        "countyId": county_id,
        "housingType": housing_type,
        "source": {
            "file": relative_source.as_posix(),
            "sha256": _sha256_file(source_path),
        },
        "timeline": {
            "timeBasis": "model-local-naive",
            "intervalMinutes": 60,
            "hourCount": EXPECTED_HOURS,
            "start": timestamps[0].isoformat(sep=" "),
            "end": timestamps[-1].isoformat(sep=" "),
        },
        "annualTotals": annual_totals,
        "hourlySeries": series,
    }


def build_release(
    *,
    repo_root: Path,
    base_input_dir: Path,
    release_id: str,
    scenario_ids: Iterable[str],
    county_ids: Iterable[str],
    housing_type: str = "single-family-detached",
    created_at: str | None = None,
    provenance: ResearchProvenance | None = None,
) -> ReleaseBundle:
    """Build a validated in-memory release from explicit research selections."""

    _validate_identifier(release_id, "release id")
    _validate_housing_type(housing_type)
    scenarios = list(dict.fromkeys(scenario_ids))
    counties = list(dict.fromkeys(county_ids))
    if not scenarios:
        raise ValueError("At least one scenario is required")
    if not counties:
        raise ValueError("At least one county is required")

    for scenario_id in scenarios:
        _validate_identifier(scenario_id, "scenario id")
        if scenario_id not in SCENARIOS:
            raise KeyError(f"Scenario {scenario_id!r} is not defined in scenarios.py")
    for county_id in counties:
        _validate_identifier(county_id, "county id")

    if created_at is None:
        created_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    try:
        parsed_created_at = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError("created_at must be an ISO 8601 timestamp") from error
    if parsed_created_at.tzinfo is None:
        raise ValueError("created_at must include a timezone")

    resolved_root = repo_root.resolve()
    resolved_inputs = base_input_dir.resolve()
    if not resolved_inputs.is_relative_to(resolved_root):
        raise ValueError("base input directory must be inside the research repository")
    research_state = provenance or repository_provenance(resolved_root)

    profile_files: dict[str, bytes] = {}
    manifest_scenarios = []
    for scenario_id in scenarios:
        profile_entries = []
        for county_id in counties:
            source_path = (
                resolved_inputs
                / scenario_id
                / housing_type
                / county_id
                / f"loadprofiles_for_rates_{county_id}.csv"
            )
            profile = _read_profile(
                source_path,
                repo_root=resolved_root,
                scenario_id=scenario_id,
                county_id=county_id,
                housing_type=housing_type,
            )
            public_path = f"profiles/{scenario_id}/{county_id}.json"
            profile_bytes = _json_bytes(profile)
            profile_files[public_path] = profile_bytes
            profile_entries.append(
                {
                    "countyId": county_id,
                    "file": public_path,
                    "sha256": _sha256_bytes(profile_bytes),
                    "sourceSha256": profile["source"]["sha256"],
                }
            )

        definition = SCENARIOS[scenario_id]
        manifest_scenarios.append(
            {
                "id": scenario_id,
                "electricEndUses": sorted(definition["electric"]),
                "gasEndUses": sorted(definition["gas"]),
                "profiles": profile_entries,
            }
        )

    manifest = {
        "schemaVersion": SCHEMA_VERSION,
        "releaseId": release_id,
        "createdAt": created_at,
        "housingType": housing_type,
        "modelUnit": "representative single-family household by county",
        "researchRepository": {
            "name": "cost-of-solar-storage",
            "commit": research_state.commit,
            "dirtyAtExport": research_state.dirty,
        },
        "scenarios": manifest_scenarios,
    }
    return ReleaseBundle(
        release_id=release_id,
        manifest=_json_bytes(manifest),
        profiles=profile_files,
    )


def write_release(bundle: ReleaseBundle, output_root: Path) -> Path:
    """Write a complete release atomically without replacing an existing release."""

    root = output_root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    destination = root / bundle.release_id
    if destination.exists():
        raise FileExistsError(f"Release already exists: {destination}")

    temporary = Path(tempfile.mkdtemp(prefix=f".{bundle.release_id}-", dir=root))
    try:
        for relative_path, content in bundle.profiles.items():
            target = temporary / relative_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
        (temporary / "manifest.json").write_bytes(bundle.manifest)
        temporary.replace(destination)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return destination


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Package existing hourly research outputs for the web companion"
    )
    parser.add_argument("--release-id", required=True)
    parser.add_argument("--scenario", action="append", dest="scenarios", required=True)
    parser.add_argument("--counties", nargs="+", required=True)
    parser.add_argument("--housing-type", default="single-family-detached")
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--base-input-dir", type=Path, default=Path("data/loadprofiles"))
    parser.add_argument("--output-root", type=Path, default=Path("web_artifacts"))
    args = parser.parse_args()

    repo_root = args.repo_root.resolve()
    base_input_dir = args.base_input_dir
    if not base_input_dir.is_absolute():
        base_input_dir = repo_root / base_input_dir
    output_root = args.output_root
    if not output_root.is_absolute():
        output_root = repo_root / output_root

    release = build_release(
        repo_root=repo_root,
        base_input_dir=base_input_dir,
        release_id=args.release_id,
        scenario_ids=args.scenarios,
        county_ids=args.counties,
        housing_type=args.housing_type,
    )
    destination = write_release(release, output_root)
    print(f"Wrote research companion release to {destination}")


if __name__ == "__main__":
    main()
