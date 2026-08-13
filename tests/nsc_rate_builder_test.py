from decimal import Decimal
from pathlib import Path

import pytest

from scripts.build_nsc_rates import (
    _parse_pge_table,
    _select_complete_months,
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
    / "2026-08-10"
    / "net-surplus-compensation.html"
)
SDGE_SOURCE = (
    ROOT
    / "data"
    / "tariffs"
    / "sources"
    / "nsc"
    / "sdge"
    / "2026-08-10"
    / "excess-generation.html"
)


def test_pge_table_requires_exact_usd_per_kwh_header():
    bad_table = [
        ["True-up Month", "NSC Rate* (cents/kWh)"],
        ["Aug. 2026", "2.684"],
    ]
    with pytest.raises(ValueError, match="headers/units"):
        _parse_pge_table(
            bad_table, source=Path("pge.pdf"), year=2026, through_month=8
        )


def test_sce_archived_html_extracts_exact_2026_months_and_rates():
    rows = parse_sce_html(SCE_SOURCE, year=2026, through_month=8)
    assert rows == [
        ("2026-01", Decimal("0.01840")),
        ("2026-02", Decimal("0.01769")),
        ("2026-03", Decimal("0.01848")),
        ("2026-04", Decimal("0.01818")),
        ("2026-05", Decimal("0.01864")),
        ("2026-06", Decimal("0.01815")),
        ("2026-07", Decimal("0.01736")),
        ("2026-08", Decimal("0.01697")),
    ]


def test_sdge_archived_html_extracts_exact_2026_months_and_rates():
    rows = parse_sdge_html(SDGE_SOURCE, year=2026, through_month=8)
    assert rows == [
        ("2026-01", Decimal("0.02934")),
        ("2026-02", Decimal("0.02735")),
        ("2026-03", Decimal("0.02800")),
        ("2026-04", Decimal("0.02044")),
        ("2026-05", Decimal("0.01592")),
        ("2026-06", Decimal("0.01243")),
        ("2026-07", Decimal("0.01170")),
        ("2026-08", Decimal("0.01306")),
    ]


def test_normalizer_rejects_a_missing_month_instead_of_truncating():
    observed = [("2026-01", Decimal("0.02")), ("2026-03", Decimal("0.02"))]
    with pytest.raises(ValueError, match=r"Missing NSC months.*2026-02"):
        _select_complete_months(
            observed,
            year=2026,
            through_month=3,
            source=Path("source.html"),
        )
