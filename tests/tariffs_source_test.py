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
IMPORT_DATA_PATH = ROOT / "data" / "tariffs" / "import_rate_snapshots.json"
IMPORT_MANIFEST_PATH = ROOT / "data" / "tariffs" / "import_source_manifest.json"
TRUE_UP_MANIFEST_PATH = ROOT / "data" / "tariffs" / "true_up_source_manifest.json"


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


def test_normalized_schedule_values_are_semantically_stable():
    """Pin values and keys without depending on CSV line endings or column order."""

    data = _data().sort_values(
        [
            "utility", "billing_year", "nbt_vintage", "service_type",
            "customer_segment", "component", "month", "day_type", "hour_start",
        ]
    )
    digest = hashlib.sha256()
    for row in data.itertuples(index=False):
        fields = (
            row.utility,
            str(int(row.billing_year)),
            str(int(row.nbt_vintage)),
            row.service_type,
            row.customer_segment,
            str(int(row.month)),
            row.day_type,
            str(int(row.hour_start)),
            row.component,
            f"{float(row.rate_usd_per_kwh):.6f}",
            row.source_id,
        )
        digest.update(("\x1f".join(fields) + "\n").encode("utf-8"))
    assert digest.hexdigest() == "1cba4a7cc5e9429841b4cbe058228fb9256b69ff4c94d7858c90abb6f15b78b6"


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
    assert bundle.import_schedule.rates_for(weekday_peak) == [pytest.approx(0.59291)]
    assert bundle.import_schedule.rates_for(weekday_peak, component="generation") == [
        pytest.approx(0.29667)
    ]
    assert bundle.import_schedule.rates_for(weekday_peak, component="delivery") == [
        pytest.approx(0.29624)
    ]
    assert bundle.import_schedule.rates_for(weekend_peak) == [pytest.approx(0.40182)]
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
    assert schedule.rates_for([pd.Timestamp("2026-10-05 00:00")]) == [pytest.approx(0.13090)]
    assert schedule.rates_for([pd.Timestamp("2026-11-02 00:00")]) == [pytest.approx(0.12332)]


def test_import_tariffs_are_the_explicit_august_9_2026_snapshot():
    expected = {
        "PG&E": ("E-ELEC", "2026-06-01", "pge_e_elec_2026-06-01"),
        "SCE": ("TOU-D-PRIME", "2026-06-01", "sce_tou_d_prime_2026-06-01"),
        "SDG&E": ("EV-TOU-5", "2026-08-01", "sdge_ev_tou_5_2026-08-01"),
    }
    for utility, (plan_name, effective_date, source_id) in expected.items():
        schedule = TariffCatalog().bundle(utility, NBTScenario()).import_schedule
        assert schedule.snapshot_as_of == "2026-08-09"
        assert schedule.plan_name == plan_name
        assert schedule.effective_date == effective_date
        assert schedule.source_id == source_id


def test_catalog_never_silently_substitutes_a_different_import_snapshot_date():
    with pytest.raises(KeyError, match="No import tariff snapshot for 2026-08-08"):
        TariffCatalog().bundle(
            "PG&E",
            NBTScenario(tariff_snapshot_date="2026-08-08"),
        )


@pytest.mark.parametrize(
    "utility,timestamp,total,generation,delivery",
    [
        ("PG&E", "2026-07-06 18:00", 0.55214, 0.25288, 0.29926),
        ("SCE", "2026-07-06 18:00", 0.59291, 0.29667, 0.29624),
        ("SDG&E", "2026-08-03 18:00", 0.80205, 0.48396, 0.31809),
    ],
)
def test_exact_snapshot_peak_rates_reconcile(utility, timestamp, total, generation, delivery):
    schedule = TariffCatalog().bundle(utility, NBTScenario()).import_schedule
    timestamps = [pd.Timestamp(timestamp)]
    assert schedule.rates_for(timestamps) == [pytest.approx(total)]
    assert schedule.rates_for(timestamps, component="generation") == [
        pytest.approx(generation)
    ]
    assert schedule.rates_for(timestamps, component="delivery") == [
        pytest.approx(delivery)
    ]
    assert generation + delivery == pytest.approx(total)


def test_import_snapshot_units_and_all_hourly_components_are_valid():
    payload = json.loads(IMPORT_DATA_PATH.read_text(encoding="utf-8"))
    assert payload["snapshot_as_of"] == "2026-08-09"
    assert len(payload["schedules"]) == 3
    timestamps = pd.date_range("2026-01-01", "2026-12-31 23:00", freq="h")
    for utility in ("PG&E", "SCE", "SDG&E"):
        schedule = TariffCatalog().bundle(utility, NBTScenario()).import_schedule
        assert schedule.plan_details["rate_unit"] == "USD/kWh"
        total = pd.Series(schedule.rates_for(timestamps))
        generation = pd.Series(schedule.rates_for(timestamps, component="generation"))
        delivery = pd.Series(schedule.rates_for(timestamps, component="delivery"))
        assert len(total) == 8760
        assert total.notna().all()
        assert total.between(0.05, 1.0).all()
        assert (total - generation - delivery).abs().max() <= 1e-9


@pytest.mark.parametrize("utility", ["PG&E", "SCE", "SDG&E"])
def test_archived_import_tariff_matches_manifest_hash(utility):
    manifest = json.loads(IMPORT_MANIFEST_PATH.read_text(encoding="utf-8"))
    source = next(row for row in manifest["sources"] if row["utility"] == utility)
    assert source["archive_status"] == "archived"
    source_path = IMPORT_MANIFEST_PATH.parent / source["archive_path"]
    assert source_path.exists()
    assert hashlib.sha256(source_path.read_bytes()).hexdigest() == source["sha256"]


def test_every_import_schedule_has_an_honest_source_manifest_entry():
    snapshot = json.loads(IMPORT_DATA_PATH.read_text(encoding="utf-8"))
    manifest = json.loads(IMPORT_MANIFEST_PATH.read_text(encoding="utf-8"))
    assert manifest["snapshot_as_of"] == snapshot["snapshot_as_of"] == "2026-08-09"

    schedule_sources = {row["source_id"] for row in snapshot["schedules"]}
    manifest_sources = {row["source_id"] for row in manifest["sources"]}
    assert manifest_sources == schedule_sources
    for source in manifest["sources"]:
        assert source["checked_on"] == "2026-08-09"
        assert source["archive_status"] == "archived"
        assert source["sha256"]


def test_true_up_manifest_has_the_expected_source_groups_and_utility_coverage():
    manifest = json.loads(TRUE_UP_MANIFEST_PATH.read_text(encoding="utf-8"))
    assert manifest["schema_version"] == 1
    assert manifest["retrieved_on"] == "2026-08-10"

    sources = manifest["sources"]
    assert {source["source_id"] for source in sources} == {
        "pge_nbt_rules_2026-08-10",
        "sce_nbt_rules_2026-08-10",
        "sdge_nbt_rules_2026-08-10",
        "pge_monthly_nsc_rates_2026-08-10",
        "sce_monthly_nsc_rates_2026-08-10",
        "sdge_monthly_nsc_rates_2026-08-10",
        "sdge_annual_true_up_methodology_2026-08-10",
    }
    assert {
        source["utility"]
        for source in sources
        if source["source_type"] == "tariff_schedule"
    } == {"PG&E", "SCE", "SDG&E"}
    assert {
        source["utility"]
        for source in sources
        if source["source_type"] == "monthly_nsc_rates"
    } == {"PG&E", "SCE", "SDG&E"}
    archive_paths = [source["archive_path"] for source in sources]
    assert len(archive_paths) == len(set(archive_paths))


def test_true_up_source_archives_match_manifest_hashes_and_formats():
    manifest = json.loads(TRUE_UP_MANIFEST_PATH.read_text(encoding="utf-8"))
    for source in manifest["sources"]:
        assert source["archive_status"] == "archived"
        assert source["url"].startswith("https://")
        source_path = TRUE_UP_MANIFEST_PATH.parent / source["archive_path"]
        assert source_path.is_file(), source["source_id"]
        payload = source_path.read_bytes()
        assert hashlib.sha256(payload).hexdigest() == source["sha256"]
        if source["format"] == "pdf":
            assert source_path.suffix == ".pdf"
            assert payload.startswith(b"%PDF-")
        elif source["format"] == "html":
            assert source_path.suffix == ".html"
            assert b"<html" in payload.lower()
        else:
            pytest.fail(f"Unsupported source format: {source['format']}")


def test_import_snapshot_rejects_wrong_currency_unit_before_billing(tmp_path):
    payload = json.loads(IMPORT_DATA_PATH.read_text(encoding="utf-8"))
    payload["schedules"][0]["rate_unit"] = "cents/kWh"
    bad_path = tmp_path / "wrong-unit.json"
    bad_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="rate_unit='USD/kWh'"):
        TariffCatalog(import_snapshot_data_path=bad_path).bundle("PG&E", NBTScenario())


def test_import_snapshot_rejects_a_hundredfold_rate_before_billing(tmp_path):
    payload = json.loads(IMPORT_DATA_PATH.read_text(encoding="utf-8"))
    payload["schedules"][0]["summer"]["weekdays"]["peak"] = 55.214
    bad_path = tmp_path / "hundredfold-rate.json"
    bad_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="implausible total rate"):
        TariffCatalog(import_snapshot_data_path=bad_path).bundle("PG&E", NBTScenario())
