import argparse
import math
from pathlib import Path
import zipfile

import pandas as pd
import pytest

from scripts.build_nbt_export_schedules import (
    EXPECTED_KEYS,
    MONTHS,
    _parse_retrieved_on,
    _validate_component,
    _validate_pge_source_identity,
    parse_midas,
)


def _write_midas_zip(tmp_path: Path, rows: pd.DataFrame) -> Path:
    path = tmp_path / "source.zip"
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("source.csv", rows.to_csv(index=False))
    return path


def _minimal_sce_identity_rows(vintage: int) -> pd.DataFrame:
    suffix = vintage % 100
    return pd.DataFrame(
        {
            "RIN": [f"USCA-XXSC-NB{suffix:02d}-0000", f"USCA-SCXX-NB{suffix:02d}-0000"],
            "RateName": [f"NBT{suffix:02d}", f"NBT{suffix:02d}"],
            "DateStart": ["1/1/2026", "1/1/2026"],
            "TimeStart": ["8:00:00", "8:00:00"],
            "ValueName": ["Jan Weekend HS0", "Jan Weekend HS0"],
            "Value": [0.05, 0.01],
        }
    )


def _complete_sce_rows_with_one_masked_nan() -> pd.DataFrame:
    key_rows = EXPECTED_KEYS.to_frame(index=False)
    month_names = {number: name for name, number in MONTHS.items()}

    def component(rin: str, value: float) -> pd.DataFrame:
        rows = key_rows.copy()
        rows["RIN"] = rin
        rows["RateName"] = "NBT26"
        rows["DateStart"] = "1/1/2026"
        rows["TimeStart"] = "8:00:00"
        rows["ValueName"] = [
            f"{month_names[month]} "
            f"{'Weekday' if day_type == 'weekday' else 'Weekend'} HS{hour}"
            for month, day_type, hour in rows[["month", "day_type", "hour_start"]].itertuples(
                index=False, name=None
            )
        ]
        rows["Value"] = value
        return rows[["RIN", "RateName", "DateStart", "TimeStart", "ValueName", "Value"]]

    generation = component("USCA-XXSC-NB26-0000", 0.05)
    # Reproduce the dangerous case: one schedule key has a missing observation
    # plus a real duplicate. nunique(dropna=True) still reports one value, and
    # drop_duplicates keeps the first (missing) observation.
    generation.loc[0, "Value"] = math.nan
    real_duplicate = generation.iloc[[0]].copy()
    real_duplicate["Value"] = 0.05
    delivery = component("USCA-SCXX-NB26-0000", 0.01)
    return pd.concat([generation, real_duplicate, delivery], ignore_index=True)


def test_midas_parser_rejects_wrong_vintage_even_when_schedule_shape_could_pass(tmp_path):
    path = _write_midas_zip(tmp_path, _minimal_sce_identity_rows(2026))
    with pytest.raises(ValueError, match=r"RateName identity mismatch.*NBT24.*NBT26"):
        parse_midas(path, "SCE", billing_year=2026, vintage=2024)


def test_midas_parser_rejects_wrong_utility_identity(tmp_path):
    path = _write_midas_zip(tmp_path, _minimal_sce_identity_rows(2026))
    with pytest.raises(ValueError, match="RIN utility/vintage identity mismatch"):
        parse_midas(path, "SDG&E", billing_year=2026, vintage=2026)


def test_midas_parser_rejects_nan_hidden_by_duplicate_real_value(tmp_path):
    path = _write_midas_zip(tmp_path, _complete_sce_rows_with_one_masked_nan())
    with pytest.raises(ValueError, match="missing rate values"):
        parse_midas(path, "SCE", billing_year=2026, vintage=2026)


@pytest.mark.parametrize(
    "bad_value,message",
    [(math.nan, "missing rate values"), (math.inf, "non-finite rate values")],
)
def test_component_validation_rejects_missing_and_nonfinite_rates(bad_value, message):
    rows = EXPECTED_KEYS.to_frame(index=False)
    rows["rate_usd_per_kwh"] = 0.05
    rows.loc[0, "rate_usd_per_kwh"] = bad_value
    with pytest.raises(ValueError, match=message):
        _validate_component(rows, "test schedule")


def test_pge_pdf_identity_accepts_exact_billing_year_and_application_vintage():
    text = (
        "PG&E Solar Billing Plan "
        "2026 Energy Export Credit (EEC) Values: "
        "2024 Interconnection Application Year"
    )
    _validate_pge_source_identity(text, Path("pge.pdf"), billing_year=2026, vintage=2024)


@pytest.mark.parametrize(
    "billing_year,vintage",
    [(2025, 2024), (2026, 2026)],
)
def test_pge_pdf_identity_rejects_cli_year_or_vintage_mismatch(billing_year, vintage):
    text = (
        "PG&E Solar Billing Plan "
        "2026 Energy Export Credit (EEC) Values: "
        "2024 Interconnection Application Year"
    )
    with pytest.raises(ValueError, match="PG&E source identity mismatch"):
        _validate_pge_source_identity(text, Path("pge.pdf"), billing_year, vintage)


def test_retrieval_date_is_explicit_strict_iso_provenance():
    assert _parse_retrieved_on("2026-08-06") == "2026-08-06"
    for invalid in ("2026-8-6", "08/06/2026", "not-a-date"):
        with pytest.raises(argparse.ArgumentTypeError, match="retrieval date must be"):
            _parse_retrieved_on(invalid)
