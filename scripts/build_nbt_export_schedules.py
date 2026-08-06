#!/usr/bin/env python3
"""Build normalized NBT export schedules from official utility source files.

This script deliberately has no fallback data. It validates every source into
12 months x 2 day types x 24 hours = 576 observations per component.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import zipfile
from pathlib import Path

import pandas as pd


MONTHS = {name: number for number, name in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],
    start=1,
)}
EXPECTED_KEYS = pd.MultiIndex.from_product(
    [range(1, 13), ["weekday", "weekend_holiday"], range(24)],
    names=["month", "day_type", "hour_start"],
)
SOURCE_URLS = {
    ("PG&E", 2024): "https://www.pge.com/assets/pge/docs/vanities/PGE-EEC-Price-Sheets.zip",
    ("PG&E", 2026): "https://www.pge.com/assets/pge/docs/vanities/PGE-EEC-Price-Sheets.zip",
    ("SCE", 2024): "https://edisonintl.sharepoint.com/:f:/t/Public/Misc/Euu_nWW5ZppGmW_tLUuFhjEBDeg7oBCyB5hEG47Q67O2hQ?e=rwNerm",
    ("SCE", 2026): "https://edisonintl.sharepoint.com/:f:/t/Public/Misc/Euu_nWW5ZppGmW_tLUuFhjEBDeg7oBCyB5hEG47Q67O2hQ?e=rwNerm",
    ("SDG&E", 2024): "https://www.sdge.com/sites/default/files/LY2024%20NBT%20Pricing%20Upload%20MIDAS.zip",
    ("SDG&E", 2026): "https://www.sdge.com/sites/default/files/LY2026%20NBT%20Pricing%20Upload%20MIDAS.zip",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_component(rows: pd.DataFrame, label: str) -> None:
    if len(rows) != 576:
        raise ValueError(f"{label}: expected 576 rows, found {len(rows)}")
    indexed = rows.set_index(["month", "day_type", "hour_start"])
    if indexed.index.has_duplicates:
        raise ValueError(f"{label}: duplicate month/day/hour keys")
    missing = EXPECTED_KEYS.difference(indexed.index)
    extra = indexed.index.difference(EXPECTED_KEYS)
    if len(missing) or len(extra):
        raise ValueError(f"{label}: missing keys={list(missing[:5])}; extra keys={list(extra[:5])}")
    if (rows["rate_usd_per_kwh"] < 0).any():
        raise ValueError(f"{label}: negative rate")


def _read_zip_csv(path: Path) -> pd.DataFrame:
    with zipfile.ZipFile(path) as archive:
        members = [name for name in archive.namelist() if name.lower().endswith(".csv")]
        if len(members) != 1:
            raise ValueError(f"{path}: expected one CSV member, found {members}")
        with archive.open(members[0]) as handle:
            return pd.read_csv(handle)


def parse_midas(path: Path, utility: str, billing_year: int, vintage: int) -> pd.DataFrame:
    data = _read_zip_csv(path)
    required = {"RIN", "DateStart", "TimeStart", "ValueName", "Value"}
    missing = required - set(data.columns)
    if missing:
        raise ValueError(f"{path}: missing MIDAS columns {sorted(missing)}")
    utc = pd.to_datetime(
        data["DateStart"].astype(str) + " " + data["TimeStart"].astype(str),
        utc=True,
        errors="raise",
    )
    local = utc.dt.tz_convert("America/Los_Angeles")
    data = data.loc[local.dt.year == billing_year].copy()
    extracted = data["ValueName"].str.extract(
        r"^(?P<month>[A-Z][a-z]{2}) (?P<day_type>Weekday|Weekend) HS(?P<hour_start>\d{1,2})$"
    )
    if extracted.isna().any().any():
        bad = data.loc[extracted.isna().any(axis=1), "ValueName"].head().tolist()
        raise ValueError(f"{path}: unrecognized ValueName rows {bad}")
    data["month"] = extracted["month"].map(MONTHS)
    data["day_type"] = extracted["day_type"].map(
        {"Weekday": "weekday", "Weekend": "weekend_holiday"}
    )
    data["hour_start"] = extracted["hour_start"].astype(int)
    data["rate_usd_per_kwh"] = pd.to_numeric(data["Value"], errors="raise")

    tags = {"SCE": ("XXSC", "SCXX"), "SDG&E": ("XXSD", "SDXX")}
    generation_tag, delivery_tag = tags[utility]
    components = []
    for component, tag in (("generation", generation_tag), ("delivery", delivery_tag)):
        subset = data[data["RIN"].str.contains(tag, regex=False)].copy()
        if subset.empty:
            raise ValueError(f"{path}: no {component} rows matching RIN tag {tag}")
        variation = subset.groupby(["month", "day_type", "hour_start"])["rate_usd_per_kwh"].nunique()
        if (variation != 1).any():
            raise ValueError(f"{path}: conflicting {component} values for the same schedule key")
        subset = subset.drop_duplicates(["month", "day_type", "hour_start"])
        subset["component"] = component
        components.append(subset[["month", "day_type", "hour_start", "component", "rate_usd_per_kwh"]])

    rows = pd.concat(components, ignore_index=True)
    for component in ("generation", "delivery"):
        _validate_component(rows[rows["component"] == component], f"{utility} NBT{vintage} {component}")
    total = (
        rows.pivot(index=["month", "day_type", "hour_start"], columns="component", values="rate_usd_per_kwh")
        .reset_index()
    )
    total["rate_usd_per_kwh"] = total["generation"] + total["delivery"]
    total["component"] = "total"
    rows = pd.concat(
        [rows, total[["month", "day_type", "hour_start", "component", "rate_usd_per_kwh"]]],
        ignore_index=True,
    )
    return add_dimensions(rows, utility, billing_year, vintage, f"{utility.lower().replace('&', '')}_nbt{vintage}")


def parse_pge_pdf(path: Path, billing_year: int, vintage: int) -> pd.DataFrame:
    try:
        import pdfplumber
    except ImportError as exc:
        raise RuntimeError("Parsing PG&E source PDFs requires pdfplumber") from exc

    with pdfplumber.open(path) as document:
        if len(document.pages) != 1:
            raise ValueError(f"{path}: expected one-page price sheet")
        text = document.pages[0].extract_text(layout=True, x_tolerance=1, y_tolerance=1)
    numeric_rows = []
    for line in text.splitlines():
        values = [float(value) for value in re.findall(r"\$?(-?\d+\.\d+)", line)]
        if len(values) == 24:
            numeric_rows.append(values)
    if len(numeric_rows) != 48:
        raise ValueError(f"{path}: expected 48 hourly rows, found {len(numeric_rows)}")

    records = []
    for position, values in enumerate(numeric_rows):
        day_type = "weekday" if position < 24 else "weekend_holiday"
        hour = position % 24
        for month in range(1, 13):
            generation = values[(month - 1) * 2]
            delivery = values[(month - 1) * 2 + 1]
            records.extend(
                [
                    (month, day_type, hour, "generation", generation),
                    (month, day_type, hour, "delivery", delivery),
                    (month, day_type, hour, "total", generation + delivery),
                ]
            )
    rows = pd.DataFrame(
        records,
        columns=["month", "day_type", "hour_start", "component", "rate_usd_per_kwh"],
    )
    for component in ("generation", "delivery", "total"):
        _validate_component(rows[rows["component"] == component], f"PG&E NBT{vintage} {component}")
    return add_dimensions(rows, "PG&E", billing_year, vintage, f"pge_nbt{vintage}")


def add_dimensions(
    rows: pd.DataFrame,
    utility: str,
    billing_year: int,
    vintage: int,
    source_id: str,
) -> pd.DataFrame:
    result = rows.copy()
    # Base EEC schedules do not vary by customer segment. The separate ACC
    # Plus adder does, and is resolved in tariffs/catalog.py.
    result.insert(0, "customer_segment", "all")
    result.insert(0, "service_type", "bundled")
    result.insert(0, "nbt_vintage", vintage)
    result.insert(0, "billing_year", billing_year)
    result.insert(0, "utility", utility)
    result["source_id"] = source_id
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pge-2024-pdf", type=Path, required=True)
    parser.add_argument("--pge-2026-pdf", type=Path, required=True)
    parser.add_argument("--sce-2024-zip", type=Path, required=True)
    parser.add_argument("--sce-2026-zip", type=Path, required=True)
    parser.add_argument("--sdge-2024-zip", type=Path, required=True)
    parser.add_argument("--sdge-2026-zip", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("data/tariffs/nbt_export_rates.csv"))
    parser.add_argument("--manifest", type=Path, default=Path("data/tariffs/source_manifest.json"))
    args = parser.parse_args()

    sources = [
        (args.pge_2024_pdf, "PG&E", 2026, 2024, parse_pge_pdf),
        (args.pge_2026_pdf, "PG&E", 2026, 2026, parse_pge_pdf),
        (args.sce_2024_zip, "SCE", 2026, 2024, parse_midas),
        (args.sce_2026_zip, "SCE", 2026, 2026, parse_midas),
        (args.sdge_2024_zip, "SDG&E", 2026, 2024, parse_midas),
        (args.sdge_2026_zip, "SDG&E", 2026, 2026, parse_midas),
    ]
    frames = []
    manifest_sources = []
    for path, utility, billing_year, vintage, loader in sources:
        if not path.exists():
            raise FileNotFoundError(path)
        if loader is parse_pge_pdf:
            frames.append(loader(path, billing_year, vintage))
        else:
            frames.append(loader(path, utility, billing_year, vintage))
        manifest_sources.append(
            {
                "utility": utility,
                "billing_year": billing_year,
                "nbt_vintage": vintage,
                "filename": path.name,
                "sha256": sha256(path),
                "source_url": SOURCE_URLS[(utility, vintage)],
                "retrieved_on": "2026-08-06",
            }
        )
    output = pd.concat(frames, ignore_index=True).sort_values(
        ["utility", "nbt_vintage", "component", "month", "day_type", "hour_start"]
    )
    expected_rows = 3 * 2 * 3 * 576
    if len(output) != expected_rows:
        raise ValueError(f"Expected {expected_rows} normalized rows, found {len(output)}")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    output.to_csv(args.output, index=False, float_format="%.6f")
    args.manifest.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "description": "Official NBT export schedules normalized for calendar-year 2026 billing",
                "sources": manifest_sources,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
