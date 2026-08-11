import json
from pathlib import Path

import pandas as pd
import pytest

from tariffs import NetSurplusCompensationSchedule, Utility


ROOT = Path(__file__).resolve().parents[1]
DATA_PATH = ROOT / "data" / "tariffs" / "nsc_rates.csv"
MANIFEST_PATH = ROOT / "data" / "tariffs" / "true_up_source_manifest.json"


def _data() -> pd.DataFrame:
    return pd.read_csv(DATA_PATH)


def _write_data(tmp_path: Path, mutator) -> Path:
    data = _data()
    mutated = mutator(data)
    if mutated is not None:
        data = mutated
    path = tmp_path / "nsc_rates.csv"
    data.to_csv(path, index=False)
    return path


@pytest.mark.parametrize(
    "utility,expected_rate,expected_source",
    [
        ("PG&E", 0.02684, "pge_monthly_nsc_rates_2026-08-10"),
        ("SCE", 0.01697, "sce_monthly_nsc_rates_2026-08-10"),
        ("SDG&E", 0.01306, "sdge_monthly_nsc_rates_2026-08-10"),
    ],
)
def test_resolve_returns_exact_rate_and_source_identity(
    utility,
    expected_rate,
    expected_source,
):
    resolved = NetSurplusCompensationSchedule.from_csv().resolve(utility, "2026-08")
    assert resolved.utility.value == utility
    assert resolved.true_up_month == "2026-08"
    assert resolved.rate_usd_per_kwh == pytest.approx(expected_rate, abs=1e-12)
    assert resolved.source_id == expected_source


def test_resolve_accepts_canonical_utility_aliases():
    resolved = NetSurplusCompensationSchedule.from_csv().resolve("sdge", "2026-08")
    assert resolved.utility is Utility.SDGE


def test_resolve_requires_an_explicit_canonical_available_month():
    schedule = NetSurplusCompensationSchedule.from_csv()
    with pytest.raises(ValueError, match="canonical YYYY-MM"):
        schedule.resolve("PG&E", "2026-8")
    with pytest.raises(KeyError, match=r"true_up_month=2026-09.*Available"):
        schedule.resolve("PG&E", "2026-09")
    with pytest.raises(ValueError, match="Unsupported utility"):
        schedule.resolve("SMUD", "2026-08")


@pytest.mark.parametrize(
    "mutator,message",
    [
        (lambda data: data.drop(columns="rate_unit"), "missing columns"),
        (lambda data: data.iloc[0:0], "data is empty"),
        (
            lambda data: pd.concat([data, data.iloc[[0]]], ignore_index=True),
            "duplicate utility/true_up_month",
        ),
        (
            lambda data: data.assign(true_up_month="2026-8"),
            "canonical YYYY-MM",
        ),
        (lambda data: data.assign(utility="PGE"), "non-canonical utility"),
        (lambda data: data.assign(rate_unit="cents/kWh"), "rate_unit"),
        (lambda data: data.assign(rate_usd_per_kwh="not-a-rate"), "non-numeric"),
        (lambda data: data.assign(rate_usd_per_kwh=float("nan")), "missing"),
        (lambda data: data.assign(rate_usd_per_kwh=float("inf")), "non-finite"),
        (lambda data: data.assign(rate_usd_per_kwh=-0.01), "negative"),
        (lambda data: data.assign(rate_usd_per_kwh=2.684), "magnitude guardrail"),
        (lambda data: data.assign(source_id="missing-source"), "absent from the manifest"),
        (
            lambda data: data.assign(
                source_id="sce_monthly_nsc_rates_2026-08-10"
            ),
            "belongs to SCE, not PG&E",
        ),
    ],
)
def test_schedule_rejects_malformed_or_unlinked_data(
    tmp_path,
    mutator,
    message,
):
    path = _write_data(tmp_path, mutator)
    with pytest.raises(ValueError, match=message):
        NetSurplusCompensationSchedule.from_csv(path)


def test_schedule_rejects_missing_normalized_data(tmp_path):
    with pytest.raises(FileNotFoundError, match="Normalized NSC rate data"):
        NetSurplusCompensationSchedule.from_csv(tmp_path / "missing.csv")


def test_schedule_rejects_missing_source_manifest(tmp_path):
    with pytest.raises(FileNotFoundError, match="True-up source manifest"):
        NetSurplusCompensationSchedule.from_csv(
            DATA_PATH,
            tmp_path / "missing-manifest.json",
        )


def test_schedule_rejects_duplicate_monthly_source_ids(tmp_path):
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    monthly_source = next(
        source
        for source in manifest["sources"]
        if source["source_type"] == "monthly_nsc_rates"
    )
    manifest["sources"].append(dict(monthly_source))
    manifest_path = tmp_path / "duplicate-source-manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ValueError, match="duplicate monthly NSC source IDs"):
        NetSurplusCompensationSchedule.from_csv(DATA_PATH, manifest_path)
