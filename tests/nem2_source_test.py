import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "data" / "tariffs" / "nem2_source_manifest.json"


EXPECTED_SOURCE_HASHES = {
    "cpuc_nem2_decision_d16-01-044_2026-08-17": (
        "1017b539c380a2b56da939d9f53fa911283fa5da8bd0b981255283fe603ec8a8"
    ),
    "pge_nem2_rules_2026-08-17": (
        "1b9d13fdb3b3f5b6356e45a88c75fe2c4276ebeba82a79aad0d38f04dc0e795f"
    ),
    "pge_nem2_billing_guide_2026-08-17": (
        "7e21c21cd3554e761174f782fcde6cc3bf47f20d45c7ad83d009c8e6448761db"
    ),
    "sce_nem2_rules_2026-08-17": (
        "20a1e2cc75e20573fa75905dc1e1606e447b7aa4ac695341519d179ae241f1dc"
    ),
    "sce_nem2_billing_guide_2026-08-17": (
        "20795f89efc53121fff87c6847f1790829823eb5be5543a71b93d217a604151b"
    ),
    "sdge_nem2_rules_2026-08-17": (
        "2cd0b84467a8d82df0d8e3c995d204f1ddea78d4cf9ec91b339c081f77040edf"
    ),
}

EXPECTED_SOURCE_DETAILS = {
    "cpuc_nem2_decision_d16-01-044_2026-08-17": {
        "url": (
            "https://docs.cpuc.ca.gov/PublishedDocs/Published/G000/M158/K181/"
            "158181678.pdf"
        ),
        "archive_path": "sources/nem2_rules/cpuc/2026-08-17/D16-01-044.pdf",
        "page_count": 141,
    },
    "pge_nem2_rules_2026-08-17": {
        "url": (
            "https://www.pge.com/tariffs/assets/pdf/tariffbook/"
            "ELEC_SCHEDS_NEM2.pdf"
        ),
        "archive_path": (
            "sources/nem2_rules/pge/2026-08-17/ELEC_SCHEDS_NEM2.pdf"
        ),
        "page_count": 50,
    },
    "pge_nem2_billing_guide_2026-08-17": {
        "url": (
            "https://www.pge.com/assets/pge/docs/account/billing-and-assistance/"
            "nem-2-bundled-true-up-base-services-charge.pdf"
        ),
        "archive_path": (
            "sources/nem2_rules/pge/2026-08-17/"
            "NEM2_TRUE_UP_BILLING_GUIDE.pdf"
        ),
        "page_count": 4,
    },
    "sce_nem2_rules_2026-08-17": {
        "url": (
            "https://www.sce.com/sites/default/files/custom-files/PDF_Files/"
            "ELECTRIC_SCHEDULES_NEM-ST.pdf"
        ),
        "archive_path": (
            "sources/nem2_rules/sce/2026-08-17/ELECTRIC_SCHEDULES_NEM-ST.pdf"
        ),
        "page_count": 39,
    },
    "sce_nem2_billing_guide_2026-08-17": {
        "url": (
            "https://www.sce.com/sites/default/files/custom-files/PDF_Files/"
            "NEM-2.0-Bill-Guide-20260625.pdf"
        ),
        "archive_path": (
            "sources/nem2_rules/sce/2026-08-17/"
            "NEM2_MONTHLY_BILLING_GUIDE.pdf"
        ),
        "page_count": 7,
    },
    "sdge_nem2_rules_2026-08-17": {
        "url": (
            "https://scg-uofa-api-prd-hzczb4hja0g6dcfv.a03.azurefd.net/"
            "scg-uofa-wpubtm-prd/tariff/?utilId=SDGE&bookId=ELEC&tarfKey=871"
        ),
        "archive_path": (
            "sources/nem2_rules/sdge/2026-08-17/ELECTRIC_SCHEDULE_NEM-ST.pdf"
        ),
        "page_count": 35,
    },
}


def _manifest() -> dict:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def test_nem2_manifest_has_governing_decision_and_three_utility_tariffs():
    manifest = _manifest()
    assert manifest["schema_version"] == 1
    assert manifest["created_on"] == "2026-08-17"

    sources = manifest["sources"]
    assert {source["source_id"] for source in sources} == set(
        EXPECTED_SOURCE_HASHES
    )
    assert {
        source["utility"]
        for source in sources
        if source["source_type"] == "tariff_schedule"
    } == {"PG&E", "SCE", "SDG&E"}

    decisions = [
        source
        for source in sources
        if source["source_type"] == "regulatory_decision"
    ]
    assert len(decisions) == 1
    assert decisions[0]["authority"] == "CPUC"
    assert decisions[0]["decision_id"] == "D.16-01-044"
    assert decisions[0]["decision_date"] == "2016-01-28"


def test_nem2_source_archives_match_reviewed_files_and_manifest_hashes():
    manifest = _manifest()
    archive_paths = [source["archive_path"] for source in manifest["sources"]]
    assert len(archive_paths) == len(set(archive_paths))

    for source in manifest["sources"]:
        source_id = source["source_id"]
        expected_details = EXPECTED_SOURCE_DETAILS[source_id]
        assert source["source_group"] == "nem2_rules"
        assert source["archive_status"] == "archived"
        assert source["retrieved_on"] == "2026-08-17"
        assert source_id.endswith(source["retrieved_on"])
        assert f"/{source['retrieved_on']}/" in source["archive_path"]
        assert source["format"] == "pdf"
        assert source["url"] == expected_details["url"]
        assert source["archive_path"] == expected_details["archive_path"]
        assert source["page_count"] == expected_details["page_count"]

        expected_hash = EXPECTED_SOURCE_HASHES[source_id]
        assert source["sha256"] == expected_hash

        source_path = MANIFEST_PATH.parent / source["archive_path"]
        assert source_path.is_file(), source_id
        payload = source_path.read_bytes()
        assert payload.startswith(b"%PDF-")
        assert payload.rstrip().endswith(b"%%EOF")
        assert hashlib.sha256(payload).hexdigest() == expected_hash


def test_nem2_tariff_identity_is_explicit_for_each_utility():
    sources = {
        source["utility"]: source
        for source in _manifest()["sources"]
        if source["source_type"] == "tariff_schedule"
    }

    assert sources["PG&E"]["tariff_id"] == "NEM2"
    assert sources["SCE"]["tariff_id"] == "NEM-ST"
    assert sources["SDG&E"]["tariff_id"] == "NEM-ST"
    assert "NEM2" in sources["PG&E"]["document_title"]
    assert "NEM-ST" in sources["SCE"]["document_title"]
    assert "NEM-ST" in sources["SDG&E"]["document_title"]

    assert sources["PG&E"]["url"].startswith("https://www.pge.com/")
    assert sources["SCE"]["url"].startswith("https://www.sce.com/")
    assert sources["SDG&E"]["landing_url"].startswith(
        "https://tariffsprd.sdge.com/"
    )
