#!/usr/bin/env python3
"""Normalize annual true-up EEC adjustment rates from archived sources."""

from __future__ import annotations

import argparse
import csv
from datetime import datetime
from decimal import Decimal, InvalidOperation
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = ROOT / "data" / "tariffs" / "true_up_source_manifest.json"
DEFAULT_OUTPUT = ROOT / "data" / "tariffs" / "eec_adjustment_rates.csv"
UTILITY_ORDER = {"SCE": 0, "SDG&E": 1}
MAX_RATE_USD_PER_KWH = Decimal("1.00")
SOURCE_TYPE = "monthly_eec_adjustment_rates"


class _HTMLTableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[list[str]] = []
        self._row: list[str] | None = None
        self._cell: list[str] | None = None

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag == "tr":
            self._row = []
        elif tag in {"td", "th"} and self._row is not None:
            self._cell = []

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag in {"td", "th"} and self._row is not None and self._cell is not None:
            self._row.append(" ".join("".join(self._cell).split()))
            self._cell = None
        elif tag == "tr" and self._row is not None:
            if self._row:
                self.rows.append(self._row)
            self._row = None
            self._cell = None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _month_key(label: str) -> str:
    normalized = " ".join(label.replace("\xa0", " ").split())
    try:
        return datetime.strptime(normalized, "%B %Y").strftime("%Y-%m")
    except ValueError as exc:
        raise ValueError(f"Unrecognized EEC adjustment month {label!r}") from exc


def _rate(value: str, *, source: Path, expect_negative: bool) -> Decimal:
    try:
        parsed = Decimal(value.strip().replace("$", ""))
    except InvalidOperation as exc:
        raise ValueError(f"Invalid EEC adjustment rate {value!r} in {source}") from exc
    if not parsed.is_finite():
        raise ValueError(f"Non-finite EEC adjustment rate {value!r} in {source}")
    if expect_negative and parsed >= 0:
        raise ValueError(f"Expected a negative bill adjustment rate in {source}")
    if not expect_negative and parsed < 0:
        raise ValueError(f"Expected a nonnegative adjustment rate in {source}")
    magnitude = abs(parsed)
    if magnitude > MAX_RATE_USD_PER_KWH:
        raise ValueError(
            f"EEC adjustment rate {parsed} in {source} exceeds the "
            f"{MAX_RATE_USD_PER_KWH} USD/kWh normalization guardrail"
        )
    return magnitude


def _expected_months(year: int, through_month: int) -> list[str]:
    if year < 2023:
        raise ValueError("EEC adjustment normalization year must be 2023 or later")
    if through_month not in range(1, 13):
        raise ValueError("through_month must be between 1 and 12")
    return [f"{year}-{month:02d}" for month in range(1, through_month + 1)]


def _select_complete_months(
    observed: list[tuple[str, Decimal, Decimal]],
    *,
    year: int,
    through_month: int,
    source: Path,
) -> list[tuple[str, Decimal, Decimal]]:
    expected = _expected_months(year, through_month)
    selected = [row for row in observed if row[0] in expected]
    months = [row[0] for row in selected]
    duplicates = sorted({month for month in months if months.count(month) > 1})
    if duplicates:
        raise ValueError(f"Duplicate EEC adjustment months in {source}: {duplicates}")
    missing = sorted(set(expected) - set(months))
    if missing:
        raise ValueError(f"Missing EEC adjustment months in {source}: {missing}")
    return sorted(selected)


def _html_rows(source: Path) -> tuple[str, list[list[str]]]:
    html = source.read_text(encoding="utf-8")
    parser = _HTMLTableParser()
    parser.feed(html)
    return html, parser.rows


def parse_sce_html(
    source: Path, *, year: int, through_month: int
) -> list[tuple[str, Decimal, Decimal]]:
    html, rows = _html_rows(source)
    if "EEC Adjustment Pricing" not in html:
        raise ValueError(f"SCE EEC adjustment source identity marker is missing: {source}")
    if not any(row[:3] == ["", "Delivery", "Generation"] for row in rows):
        raise ValueError(f"SCE EEC adjustment component headers are missing: {source}")
    observed = []
    for row in rows:
        if len(row) < 3:
            continue
        try:
            month = _month_key(row[0])
        except ValueError:
            continue
        delivery = _rate(row[1], source=source, expect_negative=False)
        generation = _rate(row[2], source=source, expect_negative=False)
        observed.append((month, generation, delivery))
    return _select_complete_months(
        observed, year=year, through_month=through_month, source=source
    )


def parse_sdge_html(
    source: Path, *, year: int, through_month: int
) -> list[tuple[str, Decimal, Decimal]]:
    html, rows = _html_rows(source)
    if "Annual True-Up Adjustment" not in html or "EEC Adjustment Pricing" not in html:
        raise ValueError(f"SDG&E EEC adjustment identity markers are missing: {source}")
    if not any(row[:3] == ["", "Generation", "Delivery"] for row in rows):
        raise ValueError(f"SDG&E EEC adjustment component headers are missing: {source}")
    observed = []
    for row in rows:
        if len(row) < 3:
            continue
        try:
            month = _month_key(row[0])
        except ValueError:
            continue
        generation = _rate(row[1], source=source, expect_negative=True)
        delivery = _rate(row[2], source=source, expect_negative=True)
        observed.append((month, generation, delivery))
    return _select_complete_months(
        observed, year=year, through_month=through_month, source=source
    )


def _provides_source_type(source: dict, source_type: str) -> bool:
    return source.get("source_type") == source_type or source_type in source.get(
        "additional_source_types", []
    )


def _validate_unit_source(manifest_path: Path, manifest: dict, utility: str) -> str:
    matches = [
        source
        for source in manifest["sources"]
        if source["source_type"] == "tariff_schedule"
        and source["utility"] == utility
    ]
    if len(matches) != 1:
        raise ValueError(f"Expected one {utility} tariff source for unit validation")
    metadata = matches[0]
    source = manifest_path.parent / metadata["archive_path"]
    if not source.is_file():
        raise FileNotFoundError(source)
    if _sha256(source) != metadata["sha256"]:
        raise ValueError(f"EEC adjustment unit source hash mismatch: {metadata['source_id']}")
    try:
        import pdfplumber
    except ImportError as exc:
        raise RuntimeError("EEC adjustment unit validation requires pdfplumber") from exc
    with pdfplumber.open(source) as document:
        text = " ".join((page.extract_text() or "") for page in document.pages)
    normalized = " ".join(text.split())
    markers = {
        "SCE": (
            "Average Retail Export Compensation Rate (in $/kWh)",
        ),
        "SDG&E": (
            "Energy Export Credit (EEC): is a $/kWh value",
            "average real-world retail export compensation rates",
        ),
    }
    missing = [marker for marker in markers[utility] if marker not in normalized]
    if missing:
        raise ValueError(
            f"{utility} tariff is missing EEC adjustment unit markers: {missing}"
        )
    return metadata["source_id"]


def build_rows(manifest_path: Path, *, year: int, through_month: int) -> list[dict]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    sources = [
        source
        for source in manifest["sources"]
        if _provides_source_type(source, SOURCE_TYPE)
    ]
    if {source["utility"] for source in sources} != set(UTILITY_ORDER):
        raise ValueError(
            "EEC adjustment manifest must contain one archived SCE and SDG&E source"
        )
    if len(sources) != len(UTILITY_ORDER):
        raise ValueError("EEC adjustment manifest contains duplicate utility sources")

    parsers = {"SCE": parse_sce_html, "SDG&E": parse_sdge_html}
    sign_conventions = {
        "SCE": "positive_adjustment_rate",
        "SDG&E": "negative_bill_line_item",
    }
    rows = []
    for metadata in sorted(sources, key=lambda row: UTILITY_ORDER[row["utility"]]):
        if metadata["archive_status"] != "archived":
            raise ValueError(f"EEC adjustment source {metadata['source_id']} is not archived")
        source = manifest_path.parent / metadata["archive_path"]
        if not source.is_file():
            raise FileNotFoundError(source)
        if _sha256(source) != metadata["sha256"]:
            raise ValueError(f"EEC adjustment source hash mismatch: {metadata['source_id']}")
        parsed = parsers[metadata["utility"]](
            source, year=year, through_month=through_month
        )
        unit_source_id = _validate_unit_source(
            manifest_path, manifest, metadata["utility"]
        )
        rows.extend(
            {
                "utility": metadata["utility"],
                "true_up_month": month,
                "generation_rate_usd_per_kwh": f"{generation:.5f}",
                "delivery_rate_usd_per_kwh": f"{delivery:.5f}",
                "rate_unit": "USD/kWh",
                "source_sign_convention": sign_conventions[metadata["utility"]],
                "source_id": metadata["source_id"],
                "unit_source_id": unit_source_id,
            }
            for month, generation, delivery in parsed
        )
    return rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument("--through-month", type=int, required=True)
    args = parser.parse_args()

    rows = build_rows(args.manifest, year=args.year, through_month=args.through_month)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "utility",
                "true_up_month",
                "generation_rate_usd_per_kwh",
                "delivery_rate_usd_per_kwh",
                "rate_unit",
                "source_sign_convention",
                "source_id",
                "unit_source_id",
            ],
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    main()
