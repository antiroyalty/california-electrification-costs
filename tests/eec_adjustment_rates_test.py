import json
from pathlib import Path

import pandas as pd
import pytest

from tariffs import AverageRetailExportCompensationSchedule, Utility


ROOT = Path(__file__).resolve().parents[1]
DATA_PATH = ROOT / "data" / "tariffs" / "eec_adjustment_rates.csv"
MANIFEST_PATH = ROOT / "data" / "tariffs" / "true_up_source_manifest.json"

EXPECTED_RATES = {
    "SCE": {
        "generation": [
            0.04662,
            0.04647,
            0.04669,
            0.04878,
            0.04702,
            0.04630,
            0.04769,
            0.04576,
        ],
        "delivery": [
            0.01281,
            0.01288,
            0.01290,
            0.01401,
            0.01308,
            0.01287,
            0.01326,
            0.01291,
        ],
    },
    "SDG&E": {
        "generation": [
            0.11405,
            0.11301,
            0.11162,
            0.10871,
            0.10378,
            0.09768,
            0.09065,
            0.08672,
        ],
        "delivery": [
            0.03415,
            0.03359,
            0.03270,
            0.03141,
            0.02968,
            0.02781,
            0.02548,
            0.02427,
        ],
    },
}


def _data() -> pd.DataFrame:
    return pd.read_csv(DATA_PATH)


def _write_data(tmp_path: Path, mutator) -> Path:
    data = _data()
    mutated = mutator(data)
    if mutated is not None:
        data = mutated
    path = tmp_path / "eec_adjustment_rates.csv"
    data.to_csv(path, index=False)
    return path


def test_normalized_data_has_exact_source_shape_components_and_values():
    data = _data()
    assert len(data) == 16
    assert set(data["utility"]) == set(EXPECTED_RATES)
    assert set(data["true_up_month"]) == {
        f"2026-{month:02d}" for month in range(1, 9)
    }
    assert set(data["rate_unit"]) == {"USD/kWh"}
    assert set(data["unit_source_id"]) == {
        "sce_nbt_rules_2026-08-10",
        "sdge_nbt_rules_2026-08-10",
    }
    assert not data.duplicated(["utility", "true_up_month"]).any()
    for utility, components in EXPECTED_RATES.items():
        rows = data[data["utility"] == utility].sort_values("true_up_month")
        assert rows["generation_rate_usd_per_kwh"].tolist() == pytest.approx(
            components["generation"], abs=1e-12
        )
        assert rows["delivery_rate_usd_per_kwh"].tolist() == pytest.approx(
            components["delivery"], abs=1e-12
        )


@pytest.mark.parametrize(
    "utility,generation,delivery,source_id",
    [
        ("SCE", 0.04576, 0.01291, "sce_monthly_eec_adjustment_rates_2026-08-11"),
        ("SDG&E", 0.08672, 0.02427, "sdge_annual_true_up_methodology_2026-08-10"),
    ],
)
def test_schedule_resolves_exact_august_rate_and_source(
    utility,
    generation,
    delivery,
    source_id,
):
    resolved = AverageRetailExportCompensationSchedule.from_csv().resolve(
        utility, "2026-08"
    )
    assert resolved.utility is Utility.parse(utility)
    assert resolved.generation_rate_usd_per_kwh == pytest.approx(
        generation, abs=1e-12
    )
    assert resolved.delivery_rate_usd_per_kwh == pytest.approx(delivery, abs=1e-12)
    assert resolved.source_id == source_id


def test_schedule_fails_explicitly_for_missing_pge_source_data():
    schedule = AverageRetailExportCompensationSchedule.from_csv()
    with pytest.raises(KeyError, match=r"PG&E.*found 0.*Available: \[\]"):
        schedule.resolve("PG&E", "2026-08")


def test_every_row_links_to_the_correct_adjustment_source():
    data = _data()
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    sources = {
        source["source_id"]: source
        for source in manifest["sources"]
        if source.get("source_type") == "monthly_eec_adjustment_rates"
        or "monthly_eec_adjustment_rates"
        in source.get("additional_source_types", [])
    }
    assert set(data["source_id"]) == set(sources)
    for utility, source_id in data[["utility", "source_id"]].drop_duplicates().itertuples(
        index=False, name=None
    ):
        assert sources[source_id]["utility"] == utility


@pytest.mark.parametrize(
    "mutator,message",
    [
        (lambda data: data.drop(columns="rate_unit"), "missing columns"),
        (lambda data: data.iloc[0:0], "data is empty"),
        (
            lambda data: pd.concat([data, data.iloc[[0]]], ignore_index=True),
            "duplicate utility/true_up_month",
        ),
        (lambda data: data.assign(true_up_month="2026-8"), "canonical YYYY-MM"),
        (lambda data: data.assign(utility="SDGE"), "non-canonical utility"),
        (lambda data: data.assign(rate_unit="cents/kWh"), "rate_unit"),
        (
            lambda data: data.assign(generation_rate_usd_per_kwh="not-a-rate"),
            "non-numeric",
        ),
        (
            lambda data: data.assign(delivery_rate_usd_per_kwh=float("nan")),
            "missing",
        ),
        (
            lambda data: data.assign(generation_rate_usd_per_kwh=float("inf")),
            "non-finite",
        ),
        (
            lambda data: data.assign(delivery_rate_usd_per_kwh=-0.01),
            "negative normalized",
        ),
        (
            lambda data: data.assign(generation_rate_usd_per_kwh=4.576),
            "1 USD/kWh guardrail",
        ),
        (
            lambda data: data.assign(source_sign_convention="unknown"),
            "source_sign_convention",
        ),
        (
            lambda data: data.assign(source_id="missing-source"),
            "absent from the manifest",
        ),
        (
            lambda data: data.assign(unit_source_id="missing-unit-source"),
            "unit_source_id.*absent from the manifest",
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
        AverageRetailExportCompensationSchedule.from_csv(path)


def test_schedule_rejects_missing_data_or_manifest(tmp_path):
    with pytest.raises(FileNotFoundError, match="Normalized EEC adjustment"):
        AverageRetailExportCompensationSchedule.from_csv(tmp_path / "missing.csv")
    with pytest.raises(FileNotFoundError, match="True-up source manifest"):
        AverageRetailExportCompensationSchedule.from_csv(
            DATA_PATH,
            tmp_path / "missing-manifest.json",
        )
