import json
from pathlib import Path

import pandas as pd
import pytest


ROOT = Path(__file__).resolve().parents[1]
DATA_PATH = ROOT / "data" / "tariffs" / "nsc_rates.csv"
MANIFEST_PATH = ROOT / "data" / "tariffs" / "true_up_source_manifest.json"


EXPECTED_RATES = {
    "PG&E": [
        0.03116,
        0.03025,
        0.02962,
        0.02860,
        0.02897,
        0.02862,
        0.03089,
        0.02684,
    ],
    "SCE": [
        0.01840,
        0.01769,
        0.01848,
        0.01818,
        0.01864,
        0.01815,
        0.01736,
        0.01697,
    ],
    "SDG&E": [
        0.02934,
        0.02735,
        0.02800,
        0.02044,
        0.01592,
        0.01243,
        0.01170,
        0.01306,
    ],
}


def _data() -> pd.DataFrame:
    return pd.read_csv(DATA_PATH)


def test_normalized_nsc_data_has_exact_source_shape_and_values():
    data = _data()
    assert len(data) == 24
    assert set(data["utility"]) == set(EXPECTED_RATES)
    assert set(data["true_up_month"]) == {
        f"2026-{month:02d}" for month in range(1, 9)
    }
    assert set(data["rate_unit"]) == {"USD/kWh"}
    assert not data.duplicated(["utility", "true_up_month"]).any()
    for utility, rates in EXPECTED_RATES.items():
        actual = data[data["utility"] == utility].sort_values("true_up_month")[
            "rate_usd_per_kwh"
        ]
        assert actual.tolist() == pytest.approx(rates, abs=1e-12)


def test_every_nsc_row_links_to_the_correct_archived_monthly_source():
    data = _data()
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    sources = {
        source["source_id"]: source
        for source in manifest["sources"]
        if source["source_type"] == "monthly_nsc_rates"
    }
    assert set(data["source_id"]) == set(sources)
    unique_sources = data[["utility", "source_id"]].drop_duplicates()
    for utility, source_id in unique_sources.itertuples(index=False, name=None):
        assert sources[source_id]["utility"] == utility


def test_august_snapshot_rates_are_exact_and_in_a_wholesale_ballpark():
    data = _data().set_index(["utility", "true_up_month"])
    expected = {"PG&E": 0.02684, "SCE": 0.01697, "SDG&E": 0.01306}
    for utility, rate in expected.items():
        actual = data.loc[(utility, "2026-08"), "rate_usd_per_kwh"]
        assert actual == pytest.approx(rate, abs=1e-12)
        assert 0.005 < actual < 0.10
