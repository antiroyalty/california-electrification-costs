import csv
from decimal import Decimal
import json
from pathlib import Path

import pytest

from scripts.build_eec_adjustment_rates import (
    _rate,
    _select_complete_months,
    _validate_unit_source,
    build_rows,
    parse_sce_html,
    parse_sdge_html,
)


ROOT = Path(__file__).resolve().parents[1]
SCE_SOURCE = (
    ROOT
    / "data"
    / "tariffs"
    / "sources"
    / "nsc"
    / "sce"
    / "2026-08-11"
    / "eec-adjustment-pricing.html"
)
SDGE_SOURCE = (
    ROOT
    / "data"
    / "tariffs"
    / "sources"
    / "nsc"
    / "sdge"
    / "2026-08-10"
    / "understanding-your-solar-bill.html"
)
MANIFEST_PATH = ROOT / "data" / "tariffs" / "true_up_source_manifest.json"
NORMALIZED_PATH = ROOT / "data" / "tariffs" / "eec_adjustment_rates.csv"


def test_sce_archived_html_extracts_exact_component_rates():
    rows = parse_sce_html(SCE_SOURCE, year=2026, through_month=8)
    assert rows == [
        ("2026-01", Decimal("0.04662"), Decimal("0.01281")),
        ("2026-02", Decimal("0.04647"), Decimal("0.01288")),
        ("2026-03", Decimal("0.04669"), Decimal("0.01290")),
        ("2026-04", Decimal("0.04878"), Decimal("0.01401")),
        ("2026-05", Decimal("0.04702"), Decimal("0.01308")),
        ("2026-06", Decimal("0.04630"), Decimal("0.01287")),
        ("2026-07", Decimal("0.04769"), Decimal("0.01326")),
        ("2026-08", Decimal("0.04576"), Decimal("0.01291")),
    ]


def test_sdge_archived_html_extracts_exact_normalized_component_rates():
    rows = parse_sdge_html(SDGE_SOURCE, year=2026, through_month=8)
    assert rows == [
        ("2026-01", Decimal("0.11405"), Decimal("0.03415")),
        ("2026-02", Decimal("0.11301"), Decimal("0.03359")),
        ("2026-03", Decimal("0.11162"), Decimal("0.03270")),
        ("2026-04", Decimal("0.10871"), Decimal("0.03141")),
        ("2026-05", Decimal("0.10378"), Decimal("0.02968")),
        ("2026-06", Decimal("0.09768"), Decimal("0.02781")),
        ("2026-07", Decimal("0.09065"), Decimal("0.02548")),
        ("2026-08", Decimal("0.08672"), Decimal("0.02427")),
    ]


def test_sdge_negative_bill_line_items_are_normalized_to_positive_debits():
    assert _rate("-0.08672", source=Path("sdge.html"), expect_negative=True) == (
        Decimal("0.08672")
    )
    with pytest.raises(ValueError, match="Expected a negative bill adjustment rate"):
        _rate("0.08672", source=Path("sdge.html"), expect_negative=True)


def test_sce_positive_source_rates_must_not_change_sign():
    with pytest.raises(ValueError, match="Expected a nonnegative adjustment rate"):
        _rate("-0.04576", source=Path("sce.html"), expect_negative=False)


def test_normalizer_rejects_a_missing_month_instead_of_truncating():
    observed = [
        ("2026-01", Decimal("0.05"), Decimal("0.01")),
        ("2026-03", Decimal("0.05"), Decimal("0.01")),
    ]
    with pytest.raises(ValueError, match=r"Missing EEC adjustment months.*2026-02"):
        _select_complete_months(
            observed,
            year=2026,
            through_month=3,
            source=Path("source.html"),
        )


def test_normalizer_rejects_likely_cents_per_kwh_values():
    with pytest.raises(ValueError, match="1.00 USD/kWh normalization guardrail"):
        _rate("4.576", source=Path("sce.html"), expect_negative=False)


def test_committed_normalized_data_exactly_matches_a_source_rebuild():
    expected = build_rows(MANIFEST_PATH, year=2026, through_month=8)
    with NORMALIZED_PATH.open(encoding="utf-8", newline="") as handle:
        actual = list(csv.DictReader(handle))
    assert actual == expected


@pytest.mark.parametrize(
    "utility,source_id",
    [
        ("SCE", "sce_nbt_rules_2026-08-10"),
        ("SDG&E", "sdge_nbt_rules_2026-08-10"),
    ],
)
def test_archived_tariffs_validate_adjustment_rate_units(utility, source_id):
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    assert _validate_unit_source(MANIFEST_PATH, manifest, utility) == source_id
