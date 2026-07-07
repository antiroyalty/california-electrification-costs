"""Regression test for the shared merge-on-write CSV helper.

Several pipeline outputs (capital_costs ledgers in step14, cross-scenario
exports in step18) are single shared files covering every county for a
scenario, but call sites are typically invoked with a subset of counties at a
time. Writing with a plain `to_csv` silently discarded every county not in
the current run (a real incident: an Alameda county row was lost this way
while extending a 1-county analysis to 3 more counties).
`merge_and_write_csv` must preserve untouched counties and only refresh rows
for the counties actually present in the current write. It lives in
helpers/main_helpers.py so step14 and step18 share one implementation instead
of two copies that could drift.
"""
import os
import sys

import pandas as pd

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from helpers.main_helpers import merge_and_write_csv


def test_second_write_preserves_first_countys_rows(tmp_path):
    path = os.path.join(tmp_path, "capital_costs_test_scenario.csv")

    first = pd.DataFrame({"county_slug": ["alameda"], "total_eac": [100.0]})
    merge_and_write_csv(first, path)

    second = pd.DataFrame({"county_slug": ["fresno", "los-angeles"], "total_eac": [200.0, 300.0]})
    merge_and_write_csv(second, path)

    result = pd.read_csv(path)
    assert set(result["county_slug"]) == {"alameda", "fresno", "los-angeles"}


def test_rewriting_an_existing_county_refreshes_not_duplicates(tmp_path):
    path = os.path.join(tmp_path, "capital_costs_test_scenario.csv")

    first = pd.DataFrame({"county_slug": ["alameda"], "total_eac": [100.0]})
    merge_and_write_csv(first, path)

    refreshed = pd.DataFrame({"county_slug": ["alameda"], "total_eac": [999.0]})
    merge_and_write_csv(refreshed, path)

    result = pd.read_csv(path)
    assert len(result) == 1
    assert result.iloc[0]["total_eac"] == 999.0


def test_first_write_with_no_existing_file(tmp_path):
    path = os.path.join(tmp_path, "capital_costs_test_scenario.csv")

    first = pd.DataFrame({"county_slug": ["san-diego"], "total_eac": [50.0]})
    merge_and_write_csv(first, path)

    result = pd.read_csv(path)
    assert list(result["county_slug"]) == ["san-diego"]


def test_composite_key_preserves_other_scenarios_for_same_county(tmp_path):
    """step18's by-county exports have one row per (scenario, county) — keying
    on county_slug alone would wrongly drop a county's other-scenario rows
    when a later run recomputes that county under a different scenario list.
    """
    path = os.path.join(tmp_path, "step18_eac_by_county_nem3.csv")

    first = pd.DataFrame({
        "scenario": ["baseline", "full_electric_ev"],
        "county_slug": ["alameda", "alameda"],
        "total_eac": [100.0, 200.0],
    })
    merge_and_write_csv(first, path, key_col=["scenario", "county_slug"])

    # A later run recomputes only "full_electric_ev" for alameda, plus a new county.
    second = pd.DataFrame({
        "scenario": ["full_electric_ev", "full_electric_ev"],
        "county_slug": ["alameda", "fresno"],
        "total_eac": [999.0, 300.0],
    })
    merge_and_write_csv(second, path, key_col=["scenario", "county_slug"])

    result = pd.read_csv(path)
    pairs = set(zip(result["scenario"], result["county_slug"]))
    assert pairs == {
        ("baseline", "alameda"),
        ("full_electric_ev", "alameda"),
        ("full_electric_ev", "fresno"),
    }
    refreshed = result[(result["scenario"] == "full_electric_ev") & (result["county_slug"] == "alameda")]
    assert refreshed.iloc[0]["total_eac"] == 999.0


def test_missing_key_column_in_existing_file_does_not_crash(tmp_path):
    """If an existing file predates the key column, don't error — just overwrite."""
    path = os.path.join(tmp_path, "legacy.csv")
    pd.DataFrame({"other_col": [1, 2]}).to_csv(path, index=False)

    incoming = pd.DataFrame({"county_slug": ["napa"], "total_eac": [10.0]})
    merge_and_write_csv(incoming, path)

    result = pd.read_csv(path)
    assert list(result["county_slug"]) == ["napa"]
