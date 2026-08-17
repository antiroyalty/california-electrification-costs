import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pytest

from research_artifact.validation import (
    RepositoryState,
    ResearchRunSpec,
    ResearchValidationReport,
    ValidationCheck,
    _artifact,
    _reconcile_bills,
    _source_manifest_artifacts,
    _validate_bill_frame,
    report_text,
    validate_research_run,
    write_report,
)


def _state(*, dirty: bool = False) -> RepositoryState:
    return RepositoryState(
        commit="abc123def456",
        dirty=dirty,
        commit_time_utc="2026-01-01T00:00:00Z",
    )


def _spec(root: Path) -> ResearchRunSpec:
    return ResearchRunSpec(
        repo_root=root,
        base_input_dir=root / "data" / "loadprofiles",
        scenario="baseline_coopt",
        housing_type="single-family-detached",
        counties=("alameda",),
    )


def test_missing_completed_run_artifacts_fail_instead_of_skip(tmp_path):
    report = validate_research_run(
        _spec(tmp_path),
        state=_state(),
        require_current_artifacts=False,
        generated_at_utc="2026-08-17T20:00:00Z",
    )

    assert not report.passed
    assert [check.status for check in report.checks] == ["pass", "fail", "fail"]
    assert "Required research artifact not found" in report.checks[1].message
    assert "Required research artifact not found" in report.checks[2].message


def test_dirty_repository_fails_public_validation(tmp_path):
    report = validate_research_run(
        _spec(tmp_path),
        state=_state(dirty=True),
        require_current_artifacts=False,
    )

    assert report.checks[0].status == "fail"
    assert report.checks[0].message == "Working tree is dirty"


def test_generated_artifact_must_postdate_source_commit(tmp_path):
    artifact = tmp_path / "generated.csv"
    artifact.write_text("result\n")
    old_timestamp = datetime(2025, 1, 1, tzinfo=timezone.utc).timestamp()
    os.utime(artifact, (old_timestamp, old_timestamp))

    with pytest.raises(ValueError, match="predates the source commit"):
        _artifact(
            artifact,
            repo_root=tmp_path,
            minimum_time=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )


def test_source_manifest_verifies_archived_file_fingerprint(tmp_path):
    archive = tmp_path / "data" / "tariffs" / "sources" / "rate.pdf"
    archive.parent.mkdir(parents=True)
    archive.write_bytes(b"official rate source")
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    manifest = archive.parents[1] / "source_manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "sources": [
                    {
                        "source_id": "official-rate",
                        "archive_path": "sources/rate.pdf",
                        "archive_status": "archived",
                        "sha256": digest,
                    }
                ]
            }
        )
    )

    records = _source_manifest_artifacts(manifest, repo_root=tmp_path)

    assert len(records) == 1
    assert records[0].sha256 == digest
    archive.write_bytes(b"changed rate source")
    with pytest.raises(ValueError, match="Archived source hash mismatch"):
        _source_manifest_artifacts(manifest, repo_root=tmp_path)


def test_total_costs_must_reconcile_to_electricity_plus_gas():
    electricity = pd.DataFrame(
        {
            "scenario": ["baseline_coopt", "baseline_coopt.solarstorage"],
            "electricity.PG&E.E-ELEC_NEM3": [float("nan"), 1_500.0],
        }
    )
    gas = pd.DataFrame(
        {
            "scenario": ["baseline_coopt", "baseline_coopt.solarstorage"],
            "gas.PG&E.G-1": [1_000.0, 1_000.0],
        }
    )
    totals = pd.DataFrame(
        {
            "scenario": ["baseline_coopt", "baseline_coopt.solarstorage"],
            "total.PG&E.E-ELEC_NEM3+PG&E.G-1": [float("nan"), 2_500.0],
        }
    )

    _reconcile_bills(electricity, gas, totals)
    totals.loc[1, "total.PG&E.E-ELEC_NEM3+PG&E.G-1"] = 2_501.0

    with pytest.raises(ValueError, match="fails cost reconciliation"):
        _reconcile_bills(electricity, gas, totals)


def test_baseline_nbt_nan_is_preserved_in_total_cost_output(tmp_path):
    totals = pd.DataFrame(
        {
            "scenario": ["baseline_coopt", "baseline_coopt.solarstorage"],
            "total.PG&E.E-ELEC_NEM3+PG&E.G-1": [float("nan"), 2_500.0],
        }
    )

    _validate_bill_frame(
        totals,
        scenario="baseline_coopt",
        nbt_baseline_may_be_missing=True,
        path=tmp_path / "totals.csv",
    )


def test_report_outputs_are_machine_readable_human_readable_and_immutable(tmp_path):
    report = ResearchValidationReport(
        schema_version=1,
        generated_at_utc="2026-08-17T20:00:00Z",
        repository=_state(),
        run={"scenario": "baseline_coopt", "county_count": 1},
        checks=(
            ValidationCheck(
                check_id="county:alameda",
                status="pass",
                message="Validation passed",
                metrics={"annual_load_kwh": 6_000.0},
            ),
        ),
    )

    json_path, text_path = write_report(report, tmp_path)

    assert json_path.name == "baseline_coopt-abc123de.json"
    assert '"passed": true' in json_path.read_text()
    assert report_text(report).startswith("Research validation: PASS")
    assert "PASS county:alameda" in text_path.read_text()
    with pytest.raises(FileExistsError, match="already exists"):
        write_report(report, tmp_path)


def test_run_spec_rejects_non_cooptimization_scenario(tmp_path):
    with pytest.raises(ValueError, match="requires a _coopt scenario"):
        ResearchRunSpec(
            repo_root=tmp_path,
            base_input_dir=tmp_path / "data" / "loadprofiles",
            scenario="baseline",
            housing_type="single-family-detached",
            counties=("alameda",),
        )
