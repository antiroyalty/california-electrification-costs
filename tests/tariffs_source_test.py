import hashlib
import json
from pathlib import Path

import pandas as pd
import pytest

from tariffs import CustomerSegment, NBTScenario, TariffCatalog, resolve_county_service_assignment
from tariffs.calendar import day_types


ROOT = Path(__file__).resolve().parents[1]
DATA_PATH = ROOT / "data" / "tariffs" / "nbt_export_rates.csv"
MANIFEST_PATH = ROOT / "data" / "tariffs" / "source_manifest.json"


def _data() -> pd.DataFrame:
    return pd.read_csv(DATA_PATH)


def test_normalized_source_has_exact_complete_schedule_shape():
    data = _data()
    assert len(data) == 3 * 2 * 3 * 576
    assert set(data["utility"]) == {"PG&E", "SCE", "SDG&E"}
    assert set(data["nbt_vintage"]) == {2024, 2026}
    assert set(data["billing_year"]) == {2026}
    assert set(data["component"]) == {"generation", "delivery", "total"}
    assert set(data["day_type"]) == {"weekday", "weekend_holiday"}

    keys = ["utility", "billing_year", "nbt_vintage", "component"]
    for key, schedule in data.groupby(keys):
        assert len(schedule) == 576, key
        assert set(schedule["month"]) == set(range(1, 13)), key
        assert set(schedule["hour_start"]) == set(range(24)), key
        assert not schedule.duplicated(["month", "day_type", "hour_start"]).any(), key


def test_hour_conversion_is_zero_through_twenty_three_not_one_through_twenty_four():
    data = _data()
    assert data["hour_start"].min() == 0
    assert data["hour_start"].max() == 23
    counts = data.groupby(["utility", "nbt_vintage", "component", "hour_start"]).size()
    assert set(counts) == {24}


def test_total_rate_is_exact_sum_of_generation_and_delivery_components():
    data = _data()
    pivot = data.pivot(
        index=["utility", "billing_year", "nbt_vintage", "month", "day_type", "hour_start"],
        columns="component",
        values="rate_usd_per_kwh",
    )
    assert (pivot["total"] - pivot["generation"] - pivot["delivery"]).abs().max() <= 1e-6


@pytest.mark.parametrize(
    "utility,vintage,expected_max",
    [
        ("PG&E", 2024, 2.521390),
        ("PG&E", 2026, 1.192890),
        ("SCE", 2024, 2.421180),
        ("SCE", 2026, 1.147240),
        ("SDG&E", 2024, 2.650945),
        ("SDG&E", 2026, 1.069771),
    ],
)
def test_exact_official_bundled_schedule_maxima(utility, vintage, expected_max):
    data = _data()
    schedule = data[
        (data["utility"] == utility)
        & (data["nbt_vintage"] == vintage)
        & (data["component"] == "total")
    ]
    assert schedule["rate_usd_per_kwh"].max() == pytest.approx(expected_max, abs=1e-9)


def test_exact_source_archive_hashes_are_pinned_in_manifest():
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    hashes = {(row["utility"], row["nbt_vintage"]): row["sha256"] for row in manifest["sources"]}
    assert hashes == {
        ("PG&E", 2024): "2f8487e887e44bce84a8a42aa38824e6ba27aac45534a9e53a6422bbc81aece6",
        ("PG&E", 2026): "02287c528047d04f69843a9d66b9e527b04a6a570c7c8695ee00e1428c573822",
        ("SCE", 2024): "655b4de792d01f4350651e2f6eaf6f24c494f0f89dcaf4097139bfc5f33310ff",
        ("SCE", 2026): "bede133b7ebe5afdb5e57152f55e17a116087b7cc82f337dbd9ea56306368957",
        ("SDG&E", 2024): "23791bb46eda4ccf6cbd899c5e9c4fbd0c9383ad667e2f47fd6c16b9c217ddf9",
        ("SDG&E", 2026): "688e8d741a2e5326ebf368ae6b1e2f59742b82b831fa356744ce39b3b57d5356",
    }


def test_export_rate_distribution_is_in_an_expected_research_ballpark():
    data = _data()
    total = data[data["component"] == "total"]
    for key, schedule in total.groupby(["utility", "nbt_vintage"]):
        # These are guardrails, not tariff definitions: exact tariff values are
        # asserted separately above. A unit error or stale near-retail table
        # would fail these bounds immediately.
        assert 0.07 < schedule["rate_usd_per_kwh"].mean() < 0.12, key
        assert schedule["rate_usd_per_kwh"].median() < 0.10, key
        assert 1.0 < schedule["rate_usd_per_kwh"].max() < 3.0, key


def test_catalog_uses_weekend_holiday_schedule_on_tariff_holidays():
    schedule = TariffCatalog().export_schedule("SCE", NBTScenario())
    holiday = pd.Timestamp("2026-07-04 18:00")
    expected = schedule.rows[
        (schedule.rows["component"] == "total")
        & (schedule.rows["month"] == 7)
        & (schedule.rows["day_type"] == "weekend_holiday")
        & (schedule.rows["hour_start"] == 18)
    ]["rate_usd_per_kwh"].item()
    assert schedule.rates_for([holiday]) == [pytest.approx(expected)]


def test_cross_year_observed_holiday_is_classified_as_weekend_holiday():
    # New Year's Day 2022 fell on Saturday and was observed Friday, Dec. 31.
    assert day_types([pd.Timestamp("2021-12-31 12:00")]) == ["weekend_holiday"]


def test_normalized_data_file_itself_is_stable():
    digest = hashlib.sha256(DATA_PATH.read_bytes()).hexdigest()
    # This catches accidental source-data edits. Update only by rerunning the
    # audited builder and reviewing source hashes plus exact sentinel tests.
    assert digest == "a2aee866c47a93db151c3555f9b65487816aa6feea0f574f5e576d34e4096127"


@pytest.mark.parametrize(
    "utility,standard,equity",
    [("PG&E", 0.0088, 0.0360), ("SCE", 0.0160, 0.0370), ("SDG&E", 0.0, 0.0)],
)
def test_exact_2026_vintage_acc_plus_adders(utility, standard, equity):
    catalog = TariffCatalog()
    assert catalog.acc_plus_rate(
        utility,
        NBTScenario(nbt_vintage=2026, customer_segment=CustomerSegment.STANDARD),
    ) == pytest.approx(standard)
    assert catalog.acc_plus_rate(
        utility,
        NBTScenario(nbt_vintage=2026, customer_segment=CustomerSegment.EQUITY),
    ) == pytest.approx(equity)


def test_county_selects_utility_but_does_not_select_a_climate_zone_schedule():
    alameda = resolve_county_service_assignment("Alameda County")
    los_angeles = resolve_county_service_assignment("Los Angeles County")
    assert alameda.utility.value == "PG&E"
    assert los_angeles.utility.value == "SCE"
    assert not hasattr(alameda, "climate_zone")


def test_exact_current_sce_prime_import_components_and_nbc_split():
    bundle = TariffCatalog().bundle("SCE", NBTScenario())
    weekday_peak = [pd.Timestamp("2026-07-06 18:00")]
    weekend_peak = [pd.Timestamp("2026-07-05 18:00")]
    assert bundle.import_schedule.rates_for(weekday_peak) == [pytest.approx(0.59910)]
    assert bundle.import_schedule.rates_for(weekday_peak, component="generation") == [
        pytest.approx(0.29667)
    ]
    assert bundle.import_schedule.rates_for(weekday_peak, component="delivery") == [
        pytest.approx(0.30243)
    ]
    assert bundle.import_schedule.rates_for(weekend_peak) == [pytest.approx(0.40801)]
    assert bundle.import_schedule.rates_for(weekend_peak, component="generation") == [
        pytest.approx(0.10558)
    ]
    assert bundle.import_schedule.non_bypassable_rate == pytest.approx(0.01398)


def test_exact_current_pge_and_sdge_non_offsettable_import_rates():
    assert TariffCatalog().bundle("PG&E", NBTScenario()).import_schedule.non_bypassable_rate \
        == pytest.approx(0.01621)
    assert TariffCatalog().bundle("SDG&E", NBTScenario()).import_schedule.non_bypassable_rate \
        == pytest.approx(0.02099)


def test_sdge_ev_tou_5_treats_october_as_summer_and_november_as_winter():
    schedule = TariffCatalog().bundle("SDG&E", NBTScenario()).import_schedule
    assert schedule.rates_for([pd.Timestamp("2026-10-05 00:00")]) == [pytest.approx(0.12852)]
    assert schedule.rates_for([pd.Timestamp("2026-11-02 00:00")]) == [pytest.approx(0.12115)]
