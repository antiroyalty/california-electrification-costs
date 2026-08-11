#!/usr/bin/env python3
"""Normalize monthly NSC rates from the archived official utility sources."""

from __future__ import annotations

import argparse
import csv
from datetime import datetime
from decimal import Decimal, InvalidOperation
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = ROOT / "data" / "tariffs" / "true_up_source_manifest.json"
DEFAULT_OUTPUT = ROOT / "data" / "tariffs" / "nsc_rates.csv"
UTILITY_ORDER = {"PG&E": 0, "SCE": 1, "SDG&E": 2}
MAX_NSC_RATE_USD_PER_KWH = Decimal("0.25")


class _HTMLTableParser(HTMLParser):
    """Collect plain-text cells from every HTML table row."""

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
    normalized = " ".join(label.replace("\xa0", " ").replace(".", "").split())
    for pattern in ("%B %Y", "%b %Y"):
        try:
            return datetime.strptime(normalized, pattern).strftime("%Y-%m")
        except ValueError:
            pass
    raise ValueError(f"Unrecognized NSC month label {label!r}")


def _rate(value: str, *, source: Path) -> Decimal:
    try:
        parsed = Decimal(value.strip())
    except InvalidOperation as exc:
        raise ValueError(f"Invalid NSC rate {value!r} in {source}") from exc
    if not parsed.is_finite():
        raise ValueError(f"Non-finite NSC rate {value!r} in {source}")
    if parsed < 0 or parsed > MAX_NSC_RATE_USD_PER_KWH:
        raise ValueError(
            f"NSC rate {parsed} USD/kWh in {source} is outside the 0 to "
            f"{MAX_NSC_RATE_USD_PER_KWH} normalization guardrail"
        )
    return parsed


def _expected_months(year: int, through_month: int) -> list[str]:
    if year < 2011:
        raise ValueError("NSC normalization year must be 2011 or later")
    if through_month not in range(1, 13):
        raise ValueError("through_month must be between 1 and 12")
    return [f"{year}-{month:02d}" for month in range(1, through_month + 1)]


def _select_complete_months(
    observed: list[tuple[str, Decimal]],
    *,
    year: int,
    through_month: int,
    source: Path,
) -> list[tuple[str, Decimal]]:
    expected = _expected_months(year, through_month)
    selected = [(month, rate) for month, rate in observed if month in expected]
    months = [month for month, _ in selected]
    duplicates = sorted({month for month in months if months.count(month) > 1})
    if duplicates:
        raise ValueError(f"Duplicate NSC months in {source}: {duplicates}")
    missing = sorted(set(expected) - set(months))
    if missing:
        raise ValueError(f"Missing NSC months in {source}: {missing}")
    return sorted(selected)


def _parse_pge_table(
    table: list[list[str | None]],
    *,
    source: Path,
    year: int,
    through_month: int,
) -> list[tuple[str, Decimal]]:
    if not table or len(table[0]) < 2:
        raise ValueError(f"PG&E NSC table is missing or malformed in {source}")
    headers = [" ".join((cell or "").split()) for cell in table[0]]
    if headers != ["True-up Month", "NSC Rate* ($/kWh)"]:
        raise ValueError(f"PG&E NSC table headers/units do not match: {headers}")
    observed = []
    for row in table[1:]:
        if len(row) < 2 or not row[0] or not row[1]:
            continue
        try:
            month = _month_key(row[0])
        except ValueError:
            continue
        observed.append((month, _rate(row[1], source=source)))
    return _select_complete_months(
        observed, year=year, through_month=through_month, source=source
    )


def parse_pge_pdf(source: Path, *, year: int, through_month: int):
    try:
        import pdfplumber
    except ImportError as exc:
        raise RuntimeError("Parsing the PG&E NSC source requires pdfplumber") from exc
    with pdfplumber.open(source) as document:
        if len(document.pages) != 1:
            raise ValueError(f"Expected one PG&E NSC PDF page, found {len(document.pages)}")
        text = document.pages[0].extract_text() or ""
        if "Net Surplus Compensation Rates for Energy" not in text:
            raise ValueError(f"PG&E NSC source identity marker is missing from {source}")
        table = document.pages[0].extract_table()
    return _parse_pge_table(
        table or [], source=source, year=year, through_month=through_month
    )


def _html_rows(source: Path) -> tuple[str, list[list[str]]]:
    html = source.read_text(encoding="utf-8")
    parser = _HTMLTableParser()
    parser.feed(html)
    return html, parser.rows


def parse_sce_html(source: Path, *, year: int, through_month: int):
    html, rows = _html_rows(source)
    if "Net Surplus Compensation Rate" not in html:
        raise ValueError(f"SCE NSC source identity marker is missing from {source}")
    if not any(
        row[:2] == ["For Relevant Period Ending", "NSCR Energy ($/kWh)"]
        for row in rows
    ):
        raise ValueError(f"SCE NSC table headers/units are missing from {source}")
    observed = []
    for row in rows:
        if len(row) < 2 or not re.search(r"\b\d{4}\b", row[0]):
            continue
        try:
            month = _month_key(row[0])
        except ValueError:
            continue
        observed.append((month, _rate(row[1], source=source)))
    return _select_complete_months(
        observed, year=year, through_month=through_month, source=source
    )


def parse_sdge_html(source: Path, *, year: int, through_month: int):
    html, rows = _html_rows(source)
    if "True Up Monthly Rate Table" not in html:
        raise ValueError(f"SDG&E NSC source identity marker is missing from {source}")
    if not any(row[:3] == ["Month", "Year", "$/kWh"] for row in rows):
        raise ValueError(f"SDG&E NSC table headers/units are missing from {source}")
    observed = []
    for row in rows:
        if len(row) < 3 or not re.fullmatch(r"\d{4}", row[1]):
            continue
        month = _month_key(f"{row[0]} {row[1]}")
        observed.append((month, _rate(row[2], source=source)))
    return _select_complete_months(
        observed, year=year, through_month=through_month, source=source
    )


def build_rows(manifest_path: Path, *, year: int, through_month: int) -> list[dict]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    sources = [
        source
        for source in manifest["sources"]
        if source["source_type"] == "monthly_nsc_rates"
    ]
    if {source["utility"] for source in sources} != set(UTILITY_ORDER):
        raise ValueError("NSC manifest must contain one monthly rate source for every utility")
    if len(sources) != len(UTILITY_ORDER):
        raise ValueError("NSC manifest contains duplicate monthly rate sources")

    parsers = {
        "PG&E": parse_pge_pdf,
        "SCE": parse_sce_html,
        "SDG&E": parse_sdge_html,
    }
    rows = []
    for metadata in sorted(sources, key=lambda row: UTILITY_ORDER[row["utility"]]):
        if metadata["archive_status"] != "archived":
            raise ValueError(f"NSC source {metadata['source_id']} is not archived")
        source = manifest_path.parent / metadata["archive_path"]
        if not source.is_file():
            raise FileNotFoundError(source)
        if _sha256(source) != metadata["sha256"]:
            raise ValueError(f"NSC source hash mismatch for {metadata['source_id']}")
        parsed = parsers[metadata["utility"]](
            source, year=year, through_month=through_month
        )
        rows.extend(
            {
                "utility": metadata["utility"],
                "true_up_month": month,
                "rate_usd_per_kwh": f"{rate:.5f}",
                "rate_unit": "USD/kWh",
                "source_id": metadata["source_id"],
            }
            for month, rate in parsed
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
                "rate_usd_per_kwh",
                "rate_unit",
                "source_id",
            ],
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    main()
