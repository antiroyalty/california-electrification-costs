import glob
import os
import sys

import pandas as pd
import pytest

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from helpers.main_helpers import slugify_county_name
from pipeline.steps.step22_build_county_diagnostics import (
    create_coopt_results_card,
    create_executive_summary_card,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _npv(
    *,
    baseline: float = 4_200,
    solar_cost: float = 1_800,
    ae_savings: float = 2_400,
    ae_capex: float = 18_000,
    ae_npv: float = 14_000,
    ss_savings: float = 2_000,
    ss_capex: float = 12_000,
    ss_npv: float = 10_000,
) -> dict:
    """Return a minimal npv_details dict for use in executive-summary tests."""
    return {
        "horizon_years": 25,
        "discount_rate": 0.07,
        "baseline_cost": baseline,
        "scenario_solar_cost": solar_cost,
        "all_electrification": {
            "annual_savings": ae_savings,
            "net_capex": ae_capex,
            "npv": ae_npv,
            "savings_definition": "baseline_cost - scenario_solar_cost",
        },
        "solar_storage": {
            "annual_savings": ss_savings,
            "net_capex": ss_capex,
            "npv": ss_npv,
            "savings_definition": "baseline_cost - scenario_solar_cost",
        },
    }


def _card(
    scenario: str = "heat_pump",
    county_slug: str = "alameda",
    npv_details: dict | None = None,
    assets_info: dict | None = None,
    statewide_savings: dict | None = None,
) -> str:
    return create_executive_summary_card(
        scenario,
        county_slug,
        npv_details if npv_details is not None else _npv(),
        assets_info,
        statewide_savings,
    )


# ---------------------------------------------------------------------------
# Executive summary card — unit tests (no I/O)
# ---------------------------------------------------------------------------

class TestExecutiveSummaryEmpty:
    def test_returns_empty_string_when_npv_details_is_none(self):
        assert create_executive_summary_card("heat_pump", "alameda", None) == ""

    def test_returns_empty_string_when_npv_details_is_empty_dict(self):
        assert create_executive_summary_card("heat_pump", "alameda", {}) == ""


class TestExecutiveSummaryVerdict:
    """The verdict label (Cost-saving / Near break-even / Higher cost) is driven solely
    by annual_savings vs. two fixed thresholds: $200 and -$200."""

    def test_cost_saving_when_savings_above_200(self):
        html = _card(npv_details=_npv(ae_savings=201))
        assert "Cost-saving" in html

    def test_near_breakeven_when_savings_exactly_at_upper_threshold(self):
        html = _card(npv_details=_npv(ae_savings=200))
        assert "Near break-even" in html

    def test_near_breakeven_when_savings_is_zero(self):
        html = _card(npv_details=_npv(ae_savings=0, ae_capex=None))
        assert "Near break-even" in html

    def test_near_breakeven_just_above_lower_threshold(self):
        # Boundary is strictly > -200, so -199 is still near break-even
        html = _card(npv_details=_npv(ae_savings=-199))
        assert "Near break-even" in html

    def test_higher_cost_when_savings_exactly_at_lower_threshold(self):
        # -200 is NOT > -200, so it falls through to higher cost
        html = _card(npv_details=_npv(ae_savings=-200))
        assert "Higher cost than baseline" in html

    def test_higher_cost_when_savings_below_negative_200(self):
        html = _card(npv_details=_npv(ae_savings=-201))
        assert "Higher cost than baseline" in html

    def test_cost_saving_verdict_shows_checkmark_icon(self):
        html = _card(npv_details=_npv(ae_savings=2_400))
        assert "✓" in html

    def test_higher_cost_verdict_shows_exclamation_icon(self):
        html = _card(npv_details=_npv(ae_savings=-500))
        assert "!" in html


class TestExecutiveSummaryPayback:
    """Payback period = net_capex / annual_savings (simple, undiscounted)."""

    def test_payback_is_capex_divided_by_savings(self):
        # $20 000 capex ÷ $4 000/yr savings = 5.0 years
        html = _card(npv_details=_npv(ae_savings=4_000, ae_capex=20_000))
        assert "5.0 years" in html

    def test_payback_non_integer_result(self):
        # $15 000 ÷ $4 000 = 3.75 → 3.8 years (one decimal place)
        html = _card(npv_details=_npv(ae_savings=4_000, ae_capex=15_000))
        assert "3.8 years" in html

    def test_payback_never_when_savings_are_zero(self):
        html = _card(npv_details=_npv(ae_savings=0, ae_capex=15_000))
        assert "Never" in html

    def test_payback_never_when_savings_are_negative(self):
        html = _card(npv_details=_npv(ae_savings=-500, ae_capex=15_000))
        assert "Never" in html

    def test_payback_na_when_capex_is_missing(self):
        details = _npv()
        details["all_electrification"]["net_capex"] = None
        details["solar_storage"]["net_capex"] = None
        html = _card(npv_details=details)
        assert "N/A" in html


class TestExecutiveSummaryFinancials:
    """Baseline cost, solar cost, and NPV must all appear formatted as dollar amounts."""

    def test_baseline_cost_appears(self):
        html = _card(npv_details=_npv(baseline=4_200))
        assert "$4,200" in html

    def test_solar_cost_appears(self):
        html = _card(npv_details=_npv(solar_cost=1_800))
        assert "$1,800" in html

    def test_positive_npv_appears_with_plus_sign(self):
        html = _card(npv_details=_npv(ae_npv=14_000))
        assert "+$14,000" in html

    def test_negative_npv_appears_with_minus_sign(self):
        html = _card(npv_details=_npv(ae_npv=-3_000, ae_savings=-500))
        assert "-$3,000" in html


class TestExecutiveSummarySizing:
    """Solar (kW) and battery (kWh) sizes come from assets_info, not npv_details."""

    def test_solar_size_shown_from_assets_info(self):
        html = _card(assets_info={"Solar Capacity (kW)": 6.5, "Battery Capacity (kWh)": 13.5})
        assert "6.5 kW" in html

    def test_battery_size_shown_from_assets_info(self):
        html = _card(assets_info={"Solar Capacity (kW)": 6.5, "Battery Capacity (kWh)": 13.5})
        assert "13.5 kWh" in html

    def test_na_shown_when_assets_info_is_none(self):
        html = _card(assets_info=None)
        assert "N/A" in html


class TestExecutiveSummaryFallback:
    """When all_electrification fields are None, the card must fall back to solar_storage."""

    def test_uses_solar_storage_savings_when_ae_savings_is_none(self):
        details = _npv(ss_savings=1_500, ss_capex=10_000)
        details["all_electrification"]["annual_savings"] = None
        details["all_electrification"]["net_capex"] = None
        details["all_electrification"]["npv"] = None
        html = _card(npv_details=details)
        # $10 000 ÷ $1 500/yr ≈ 6.7 years
        assert "6.7 years" in html

    def test_uses_solar_storage_npv_when_ae_npv_is_none(self):
        details = _npv(ss_npv=9_999)
        details["all_electrification"]["npv"] = None
        html = _card(npv_details=details)
        assert "+$9,999" in html


class TestExecutiveSummaryStatewideContext:
    """Statewide percentile context: shown only when the county appears in statewide_savings
    with at least 3 entries, and the percentile rank and median are computed correctly."""

    def _make_statewide(self, n: int, this_slug: str, this_savings: float) -> dict:
        """Create a statewide dict with n counties; this_slug is at value this_savings.
        Other counties have values 100, 200, ..., (n-1)*100 plus this_savings inserted."""
        others = {f"county-{i}": i * 100.0 for i in range(1, n)}
        others[this_slug] = this_savings
        return others

    def test_percentile_context_shown_when_county_in_statewide_savings(self):
        sw = self._make_statewide(10, "alameda", 900.0)
        html = _card(statewide_savings=sw)
        assert "percentile" in html

    def test_percentile_context_absent_when_county_not_in_statewide_savings(self):
        sw = {"other-county": 2_000.0, "another-county": 1_500.0, "third-county": 3_000.0}
        html = _card(county_slug="alameda", statewide_savings=sw)
        assert "percentile" not in html

    def test_percentile_context_absent_when_fewer_than_3_counties(self):
        sw = {"alameda": 2_000.0, "los-angeles": 1_500.0}
        html = _card(statewide_savings=sw)
        assert "percentile" not in html

    def test_statewide_median_shown_correctly(self):
        # 5 counties with savings 100, 200, 300, 400, 500 — median is the middle value: 300
        sw = {
            "county-a": 100.0, "county-b": 200.0, "alameda": 300.0,
            "county-d": 400.0, "county-e": 500.0,
        }
        html = _card(statewide_savings=sw)
        assert "$300" in html

    def test_highest_savings_county_is_100th_percentile(self):
        # Alameda has the highest savings among 10 counties → rank 10/10 → 100th percentile
        sw = {f"county-{i}": float(i * 100) for i in range(1, 10)}
        sw["alameda"] = 1_000.0  # highest
        html = _card(statewide_savings=sw)
        assert "100th" in html

    def test_lowest_savings_county_is_low_percentile(self):
        # Alameda has the lowest savings among 10 counties → rank 1/10 → 10th percentile
        sw = {f"county-{i}": float((i + 1) * 100) for i in range(1, 10)}
        sw["alameda"] = 50.0  # lowest
        html = _card(statewide_savings=sw)
        assert "10th" in html


class TestExecutiveSummaryPercentileOrdinalSuffixes:
    """The ordinal suffix for the percentile follows English rules:
    1st, 2nd, 3rd, 4th–20th (all 'th'), 21st, 22nd, 23rd, 100th.
    Note: the special case for 11th–13th (not 11st/12nd/13rd) is handled by
    the 4–20 catch-all range."""

    def _card_at_pct(self, pct_target: int) -> str:
        """Build a statewide dict of exactly 100 counties where alameda lands at pct_target.

        99 other counties get integer values 1–99.  Alameda is set to pct_target - 0.5 so
        there is no tie: exactly (pct_target - 1) other counties sit below it, giving
        rank = pct_target out of 100, i.e. pct = pct_target.
        """
        sw = {f"county-{i}": float(i) for i in range(1, 100)}
        sw["alameda"] = float(pct_target) - 0.5
        return _card(statewide_savings=sw)

    def test_1st_percentile(self):
        assert "1st" in self._card_at_pct(1)

    def test_2nd_percentile(self):
        assert "2nd" in self._card_at_pct(2)

    def test_3rd_percentile(self):
        assert "3rd" in self._card_at_pct(3)

    def test_11th_not_11st(self):
        assert "11th" in self._card_at_pct(11)

    def test_12th_not_12nd(self):
        assert "12th" in self._card_at_pct(12)

    def test_13th_not_13rd(self):
        assert "13th" in self._card_at_pct(13)

    def test_21st(self):
        assert "21st" in self._card_at_pct(21)

    def test_22nd(self):
        assert "22nd" in self._card_at_pct(22)

    def test_23rd(self):
        assert "23rd" in self._card_at_pct(23)

    def test_100th(self):
        assert "100th" in self._card_at_pct(100)


# ---------------------------------------------------------------------------
# Co-optimization card — integration tests (require data on disk)
# ---------------------------------------------------------------------------

BASE_INPUT_DIR = os.path.join(REPO_ROOT, "data", "loadprofiles")


def _find_coopt_capacity_csvs() -> list[str]:
    pattern = os.path.join(BASE_INPUT_DIR, "*", "*", "CAPITAL_COSTS", "electrified_assets.csv")
    candidates = sorted(glob.glob(pattern))
    return [p for p in candidates if "_coopt" in os.path.normpath(p)]


def _scenario_and_housing_from_path(path: str) -> tuple[str, str]:
    parts = os.path.normpath(path).split(os.sep)
    # .../data/loadprofiles/<scenario>/<housing_type>/CAPITAL_COSTS/electrified_assets.csv
    return parts[-4], parts[-3]


def _first_row_county_slug(df: pd.DataFrame) -> str:
    if "County" in df.columns:
        val = df.iloc[0]["County"]
    else:
        val = df.iloc[0][df.columns[0]]
    return slugify_county_name(str(val))


def test_step22_coopt_card_includes_cost_components() -> None:
    files = _find_coopt_capacity_csvs()
    if not files:
        pytest.skip("No co-optimization capacity CSVs found under data/loadprofiles.")
    path = files[0]
    df = pd.read_csv(path)
    if df.empty:
        pytest.skip(f"Co-optimization capacity CSV is empty: {path}")
    scenario, housing_type = _scenario_and_housing_from_path(path)
    county_slug = _first_row_county_slug(df)

    card_html = create_coopt_results_card(BASE_INPUT_DIR, scenario, housing_type, county_slug)
    if "Co-optimization results not found" in card_html:
        pytest.skip("Co-optimization results not found for selected county.")

    required_snippets = [
        "Battery Power",
        "Total Cost",
        "Storage Value",
        "Capex Annual",
        "Import Cost",
        "Export Credit",
        "Degradation Cost",
    ]
    for snippet in required_snippets:
        assert snippet in card_html, f"Missing '{snippet}' in co-opt results card"
