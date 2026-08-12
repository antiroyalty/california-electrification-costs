from pathlib import Path

import pandas as pd
import pytest

from tariffs import (
    NBTScenario,
    Utility,
    discover_nbt_profile_counties,
    preflight_nbt_county,
    preflight_nbt_run,
)


def _write_profile(
    root: Path,
    county: str,
    *,
    annual_import_kwh: float,
    annual_export_kwh: float,
    missing_column: str | None = None,
    missing_value: bool = False,
    simultaneous: bool = False,
    negative_value: bool = False,
    hours: int = 8760,
) -> Path:
    path = (
        root
        / "baseline_coopt"
        / "single-family-detached"
        / county
        / f"loadprofiles_for_rates_{county}.csv"
    )
    path.parent.mkdir(parents=True)
    frame = pd.DataFrame(
        {
            "timestamp": pd.date_range("2018-01-01", periods=hours, freq="h"),
            "nem3.imports.kwh": [annual_import_kwh / hours] * hours,
            "nem3.exports.kwh": [annual_export_kwh / hours] * hours,
        }
    )
    # Keep the interval direction physical while preserving annual totals.
    midpoint = hours // 2
    frame.loc[: midpoint - 1, "nem3.exports.kwh"] = 0.0
    frame.loc[midpoint:, "nem3.imports.kwh"] = 0.0
    frame["nem3.imports.kwh"] *= 2.0
    frame["nem3.exports.kwh"] *= 2.0
    if missing_column:
        frame = frame.drop(columns=missing_column)
    if missing_value:
        frame.loc[0, "nem3.imports.kwh"] = float("nan")
    if simultaneous:
        frame.loc[0, ["nem3.imports.kwh", "nem3.exports.kwh"]] = [1.0, 1.0]
    if negative_value:
        frame.loc[0, "nem3.imports.kwh"] = -1e-12
    frame.to_csv(path, index=False)
    return path


def _preflight(root: Path, county: str):
    return preflight_nbt_county(
        base_input_dir=root,
        scenario_name="baseline_coopt",
        housing_type="single-family-detached",
        county=county,
        nbt_scenario=NBTScenario(),
    )


def test_pge_net_importer_needs_no_surplus_rate_source(tmp_path):
    _write_profile(
        tmp_path,
        "alameda",
        annual_import_kwh=5_000,
        annual_export_kwh=4_000,
    )

    result = _preflight(tmp_path, "alameda")

    assert result.utility is Utility.PGE
    assert result.row_count == 8760
    assert result.annual_import_kwh == pytest.approx(5_000)
    assert result.annual_export_kwh == pytest.approx(4_000)
    assert result.net_surplus_kwh == 0.0
    assert result.adjustment_source_id is None
    assert result.nsc_source_id is None
    assert result.import_source_id
    assert result.export_source_ids


def test_county_discovery_ignores_non_county_pipeline_directories(tmp_path):
    _write_profile(
        tmp_path,
        "alameda",
        annual_import_kwh=5_000,
        annual_export_kwh=4_000,
    )
    internal = (
        tmp_path / "baseline_coopt" / "single-family-detached" / "CAPITAL_COSTS"
    )
    internal.mkdir()

    assert discover_nbt_profile_counties(
        tmp_path,
        "baseline_coopt",
        "single-family-detached",
    ) == ["alameda"]


@pytest.mark.parametrize(
    "county,utility,adjustment_source,nsc_source",
    [
        (
            "los-angeles",
            Utility.SCE,
            "sce_monthly_eec_adjustment_rates_2026-08-11",
            "sce_monthly_nsc_rates_2026-08-10",
        ),
        (
            "san-diego",
            Utility.SDGE,
            "sdge_annual_true_up_methodology_2026-08-10",
            "sdge_monthly_nsc_rates_2026-08-10",
        ),
    ],
)
def test_source_complete_net_exporters_pass(
    tmp_path,
    county,
    utility,
    adjustment_source,
    nsc_source,
):
    _write_profile(
        tmp_path,
        county,
        annual_import_kwh=4_000,
        annual_export_kwh=5_000,
    )

    result = _preflight(tmp_path, county)

    assert result.utility is utility
    assert result.net_surplus_kwh == pytest.approx(1_000)
    assert result.adjustment_source_id == adjustment_source
    assert result.nsc_source_id == nsc_source


def test_pge_net_exporter_fails_on_the_known_missing_adjustment_source(tmp_path):
    _write_profile(
        tmp_path,
        "alameda",
        annual_import_kwh=4_000,
        annual_export_kwh=5_000,
    )

    with pytest.raises(KeyError, match=r"PG&E.*found 0.*Available: \[\]"):
        _preflight(tmp_path, "alameda")


def test_run_preflight_reports_each_failure_without_hiding_valid_counties(tmp_path):
    _write_profile(
        tmp_path,
        "los-angeles",
        annual_import_kwh=5_000,
        annual_export_kwh=4_000,
    )
    _write_profile(
        tmp_path,
        "alameda",
        annual_import_kwh=4_000,
        annual_export_kwh=5_000,
    )

    results, failures = preflight_nbt_run(
        base_input_dir=tmp_path,
        scenario_name="baseline_coopt",
        housing_type="single-family-detached",
        counties=["los-angeles", "alameda"],
        nbt_scenario=NBTScenario(),
    )

    assert [result.county_slug for result in results] == ["los-angeles"]
    assert len(failures) == 1
    assert failures[0].startswith("alameda:")
    assert "PG&E" in failures[0]


@pytest.mark.parametrize(
    "profile_kwargs,message",
    [
        (
            {"missing_column": "nem3.exports.kwh"},
            "missing required NBT columns",
        ),
        ({"missing_value": True}, "missing NBT values"),
        (
            {"negative_value": True},
            r"negative nem3.imports.kwh; minimum=-1e-12, first negative row=0",
        ),
        ({"simultaneous": True}, "simultaneously import and export"),
        ({"hours": 24}, "Expected a complete 2026 hourly profile"),
    ],
)
def test_preflight_fails_loudly_on_malformed_profiles(
    tmp_path,
    profile_kwargs,
    message,
):
    _write_profile(
        tmp_path,
        "los-angeles",
        annual_import_kwh=5_000,
        annual_export_kwh=4_000,
        **profile_kwargs,
    )

    with pytest.raises((ValueError, KeyError), match=message):
        _preflight(tmp_path, "los-angeles")
