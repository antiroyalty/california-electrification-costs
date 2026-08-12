import csv
import hashlib
import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from research_artifact.export import (
    EXPECTED_HOURS,
    REQUIRED_COLUMNS,
    ResearchProvenance,
    build_release,
    write_release,
)


def _write_profile(root: Path, *, missing_column: str | None = None) -> Path:
    path = (
        root
        / "data"
        / "loadprofiles"
        / "baseline_coopt"
        / "single-family-detached"
        / "alameda"
        / "loadprofiles_for_rates_alameda.csv"
    )
    path.parent.mkdir(parents=True)
    columns = [column for column in REQUIRED_COLUMNS if column != missing_column]
    start = datetime(2018, 1, 1)
    with path.open("w", newline="", encoding="utf-8") as destination:
        writer = csv.DictWriter(destination, fieldnames=columns)
        writer.writeheader()
        for hour in range(EXPECTED_HOURS):
            row = {
                "timestamp": (start + timedelta(hours=hour)).isoformat(sep=" "),
                "default.electricity.kwh": "1.25",
                "default.gas.therms": "0.1",
                "retail.imports.kwh": "0.8",
                "retail.exports.kwh": "0.2",
                "nem3.imports.kwh": "0.75",
                "nem3.exports.kwh": "0.15",
                "solarstorage.gas.therms": "0.1",
            }
            writer.writerow({key: row[key] for key in columns})
    return path


def _build(root: Path, *, created_at: str = "2026-08-12T03:00:00Z"):
    return build_release(
        repo_root=root,
        base_input_dir=root / "data" / "loadprofiles",
        release_id="paper-draft-1",
        scenario_ids=["baseline_coopt"],
        county_ids=["alameda"],
        created_at=created_at,
        provenance=ResearchProvenance(commit="abc123", dirty=False),
    )


def test_release_preserves_hourly_research_outputs_and_provenance(tmp_path):
    source = _write_profile(tmp_path)

    bundle = _build(tmp_path)
    destination = write_release(bundle, tmp_path / "exports")
    manifest = json.loads((destination / "manifest.json").read_text())
    profile_path = destination / "profiles" / "baseline_coopt" / "alameda.json"
    profile = json.loads(profile_path.read_text())

    assert manifest["schemaVersion"] == 1
    assert manifest["researchRepository"] == {
        "name": "cost-of-solar-storage",
        "commit": "abc123",
        "dirtyAtExport": False,
    }
    assert manifest["scenarios"][0]["electricEndUses"] == ["appliances", "misc"]
    assert manifest["scenarios"][0]["gasEndUses"] == [
        "cooking",
        "heating",
        "hot_water",
    ]
    entry = manifest["scenarios"][0]["profiles"][0]
    assert entry["sha256"] == hashlib.sha256(profile_path.read_bytes()).hexdigest()
    assert entry["sourceSha256"] == hashlib.sha256(source.read_bytes()).hexdigest()

    assert profile["timeline"] == {
        "end": "2018-12-31 23:00:00",
        "hourCount": 8760,
        "intervalMinutes": 60,
        "start": "2018-01-01 00:00:00",
        "timeBasis": "model-local-naive",
    }
    assert len(profile["hourlySeries"]["householdElectricityKwh"]) == 8760
    assert profile["hourlySeries"]["nem3GridImportsKwh"][0] == 0.75
    assert profile["annualTotals"]["householdElectricityKwh"] == 10950.0
    assert profile["annualTotals"]["nem3GridExportsKwh"] == pytest.approx(1314.0)


def test_release_is_deterministic_for_fixed_inputs_and_provenance(tmp_path):
    _write_profile(tmp_path)

    first = _build(tmp_path)
    second = _build(tmp_path)

    assert first.manifest == second.manifest
    assert first.profiles == second.profiles


def test_release_rejects_a_profile_with_missing_columns(tmp_path):
    _write_profile(tmp_path, missing_column="nem3.exports.kwh")

    with pytest.raises(ValueError, match="missing required columns.*nem3.exports.kwh"):
        _build(tmp_path)


def test_release_rejects_scenarios_not_defined_by_the_research(tmp_path):
    with pytest.raises(KeyError, match="not defined in scenarios.py"):
        build_release(
            repo_root=tmp_path,
            base_input_dir=tmp_path / "data" / "loadprofiles",
            release_id="paper-draft-1",
            scenario_ids=["invented_scenario"],
            county_ids=["alameda"],
            created_at="2026-08-12T03:00:00Z",
            provenance=ResearchProvenance(commit="abc123", dirty=False),
        )


def test_release_ids_are_immutable(tmp_path):
    _write_profile(tmp_path)
    bundle = _build(tmp_path)
    output_root = tmp_path / "exports"

    write_release(bundle, output_root)
    with pytest.raises(FileExistsError, match="Release already exists"):
        write_release(bundle, output_root)
