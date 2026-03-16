"""Tests for NEM3 billing accounting and cost reconciliation.

These tests establish confidence in two functions that have no existing
test coverage and directly produce the paper's headline numbers:

1. calculate_nem3_annual_costs (step12): monthly carry-forward credits,
   export credit rate lookup, fixed charges, consistency with retail billing.

2. calculate_total_annual_costs (step13): arithmetic correctness, NEM3
   column pass-through, NaN propagation for rows without solar.

Background: The paper's core finding is that NEM3 is neutral-to-negative
for solar+storage in CA utility territory. These tests confirm that the
NEM3 billing function correctly credits solar exports and applies carry-
forward logic — so the finding cannot be attributed to a billing error.

Tests 1 (TestNEM3NoSolarEqualsRetail), 2 (TestNEM3CarryForward), and
5 (TestNEM3BOECrossCheck) are the paper-critical tests. The others are
supporting hygiene.

NBC simplification: NEM3Options.nbc_dollars_per_kwh = 0.0 for all
utilities (see helpers/nem3_export_rates.py). Real NBCs (~$0.02–0.03/kWh)
cannot be offset by export credits. Setting them to zero makes NEM3 look
slightly better than reality — the neutral-to-negative finding is therefore
conservative.
"""
import os
import sys

import numpy as np
import pandas as pd
import pytest

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from helpers.electricity_rate_helpers import PGE_RATE_PLANS
from helpers.nem3_export_rates import NEM3Options
from pipeline.steps.step12_evaluate_electricity_rates import (
    _hourly_import_rate as _step12_rate,
    calculate_annual_costs_electricity,
    calculate_nem3_annual_costs,
)
from pipeline.steps.step13_combine_total_annual_costs import (
    calculate_total_annual_costs,
)

YEAR_2018 = pd.date_range("2018-01-01", periods=8760, freq="h")
ZEROS_8760 = [0.0] * 8760


def _zeros_acc_table():
    """Return a 12×24 all-zero ACC table (no export compensation)."""
    return {m: [0.0] * 24 for m in range(1, 13)}


# ---------------------------------------------------------------------------
# Group A: NEM3 accounting (calculate_nem3_annual_costs)
# ---------------------------------------------------------------------------


class TestNEM3NoSolarEqualsRetail:
    """Test 1 — paper-critical.

    With zero exports, the NEM3 billing path must produce the same annual
    electricity cost as the retail billing path. Any divergence means the
    NEM3 path adds phantom costs or omits charges when there is no solar.

    If this fails, the NEM3 vs non-NEM3 comparison is not apples-to-apples
    and the paper's headline finding cannot be trusted.

    Uses the first 8760 rows of real Alameda load data (default.electricity.kwh
    — no solar, no storage). Timestamps are set to YEAR_2018 to match the
    year used by both billing functions for weekday/season determination.
    """

    LOAD_PATH = os.path.join(
        REPO_ROOT,
        "data", "loadprofiles", "baseline_coopt",
        "single-family-detached", "alameda",
        "loadprofiles_for_rates_alameda.csv",
    )

    @pytest.fixture(scope="class")
    def alameda_default_load(self):
        df = pd.read_csv(self.LOAD_PATH)
        return df["default.electricity.kwh"].values[:8760].tolist()

    @pytest.mark.parametrize("plan", ["E-TOU-C", "E-TOU-D", "EV2-A", "EV-B", "E-ELEC"])
    def test_nem3_no_exports_matches_retail(self, alameda_default_load, plan):
        load = alameda_default_load
        zeros = [0.0] * len(load)

        retail = calculate_annual_costs_electricity(load, "PG&E", plan)[plan]
        nem3 = calculate_nem3_annual_costs(
            YEAR_2018, load, zeros, "PG&E", plan,
            export_table=_zeros_acc_table(),
        )[plan]

        assert nem3 == pytest.approx(retail, abs=1.0), (
            f"{plan}: NEM3 (no exports) ${nem3:.2f} vs retail ${retail:.2f} "
            f"(diff ${nem3 - retail:+.2f}) — must be within $1/yr"
        )


class TestNEM3CarryForward:
    """Test 2 — paper-critical.

    Verifies that export credits exceeding the energy charge in month 1
    carry forward and reduce month 2's bill by the correct amount.

    Setup:
      January 2018 (744 hrs): 0.5 kWh/hr import, 2.0 kWh/hr export.
        ACC rate = $0.10/kWh in January → export credit exceeds energy charge.
      February 2018 (672 hrs): 0.5 kWh/hr import, zero export, zero ACC.

    Expected: January bill = $0 (credit > charge, excess carries forward).
      February bill is reduced by the carry-forward amount vs a Feb-only run.
    """

    JAN_TS = pd.date_range("2018-01-01", periods=744, freq="h")
    FEB_TS = pd.date_range("2018-02-01", periods=672, freq="h")

    def _acc_with_jan_rate(self, rate=0.10):
        table = _zeros_acc_table()
        table[1] = [rate] * 24
        return table

    def test_carry_reduces_february_bill(self):
        all_ts = self.JAN_TS.append(self.FEB_TS)
        flat_import = [0.5] * len(all_ts)
        exports = [2.0] * 744 + [0.0] * 672
        acc = self._acc_with_jan_rate(rate=0.10)

        combined = calculate_nem3_annual_costs(
            all_ts, flat_import, exports, "PG&E", "E-TOU-D",
            export_table=acc,
        )["E-TOU-D"]

        feb_only = calculate_nem3_annual_costs(
            self.FEB_TS, [0.5] * 672, [0.0] * 672, "PG&E", "E-TOU-D",
            export_table=acc,
        )["E-TOU-D"]

        # Compute the expected carry from January
        plan = PGE_RATE_PLANS["E-TOU-D"]
        jan_energy_charge = sum(
            0.5 * _step12_rate(plan, ts.to_pydatetime())
            for ts in self.JAN_TS
        )
        jan_export_credit = 744 * 2.0 * 0.10  # all Jan hours × 2 kWh × $0.10
        expected_carry = max(0.0, jan_export_credit - jan_energy_charge)

        assert expected_carry > 0, (
            "Test setup error: Jan export credit must exceed energy charge "
            "to generate a carry-forward. Check JAN_TS hours and ACC rate."
        )

        # Combined run: Jan contributes $0 (covered by credit), Feb is reduced by carry
        expected_combined = max(0.0, feb_only - expected_carry)
        assert combined == pytest.approx(expected_combined, abs=0.10), (
            f"Jan+Feb combined: ${combined:.2f}. "
            f"Feb-only: ${feb_only:.2f}. "
            f"Jan energy charge: ${jan_energy_charge:.2f}, "
            f"Jan export credit: ${jan_export_credit:.2f}, "
            f"Expected carry: ${expected_carry:.2f}. "
            f"Expected combined (0 + feb − carry): ${expected_combined:.2f}."
        )

    def test_no_carry_without_export(self):
        """Without any exports, Jan+Feb combined bill equals Jan-only + Feb-only."""
        all_ts = self.JAN_TS.append(self.FEB_TS)
        flat_import = [0.5] * len(all_ts)
        no_export = [0.0] * len(all_ts)
        acc = _zeros_acc_table()

        combined = calculate_nem3_annual_costs(
            all_ts, flat_import, no_export, "PG&E", "E-TOU-D",
            export_table=acc,
        )["E-TOU-D"]

        jan_only = calculate_nem3_annual_costs(
            self.JAN_TS, [0.5] * 744, [0.0] * 744, "PG&E", "E-TOU-D",
            export_table=acc,
        )["E-TOU-D"]

        feb_only = calculate_nem3_annual_costs(
            self.FEB_TS, [0.5] * 672, [0.0] * 672, "PG&E", "E-TOU-D",
            export_table=acc,
        )["E-TOU-D"]

        assert combined == pytest.approx(jan_only + feb_only, abs=0.01), (
            f"No-export combined ${combined:.2f} != "
            f"Jan ${jan_only:.2f} + Feb ${feb_only:.2f} = ${jan_only + feb_only:.2f}"
        )


class TestNEM3ExportCreditRate:
    """Test 3: Export credit uses the correct ACC rate for each month and hour.

    Places a known nonzero rate at exactly one month/hour in a synthetic ACC
    table. Verifies the credit applied equals rate × kWh exported, so the
    rate lookup (table[month][hour]) is wired correctly.
    """

    def test_correct_acc_rate_applied(self):
        # Nonzero ACC rate at month=7 (July), hour=14 only
        acc = _zeros_acc_table()
        acc_rate = 0.08
        acc[7][14] = acc_rate

        # Two hours in July: hour 0 has import only, hour 14 has export only
        ts_h0  = pd.Timestamp(2018, 7, 1, 0)   # July 1, midnight — E-TOU-D off-peak
        ts_h14 = pd.Timestamp(2018, 7, 1, 14)  # July 1, 2 pm — E-TOU-D off-peak

        result = calculate_nem3_annual_costs(
            [ts_h0, ts_h14],
            [1.0, 0.0],   # 1 kWh imported at h0, nothing at h14
            [0.0, 1.0],   # nothing exported at h0, 1 kWh exported at h14
            "PG&E", "E-TOU-D",
            export_table=acc,
        )["E-TOU-D"]

        plan = PGE_RATE_PLANS["E-TOU-D"]
        energy_charge = 1.0 * _step12_rate(plan, ts_h0.to_pydatetime())
        export_credit = 1.0 * acc_rate
        expected = max(0.0, energy_charge - export_credit)

        assert result == pytest.approx(expected, abs=0.001), (
            f"1 kWh imported at off-peak (energy charge ${energy_charge:.4f}) "
            f"offset by 1 kWh exported at ACC rate ${acc_rate} "
            f"(credit ${export_credit:.4f}). "
            f"Expected bill ${expected:.4f}, got ${result:.4f}."
        )

    def test_wrong_hour_acc_rate_not_applied(self):
        """Export at hour 13 should NOT receive the ACC rate set for hour 14."""
        acc = _zeros_acc_table()
        acc[7][14] = 0.08  # only hour 14 has a rate

        ts_h0  = pd.Timestamp(2018, 7, 1, 0)
        ts_h13 = pd.Timestamp(2018, 7, 1, 13)  # export at wrong hour

        result_wrong_hour = calculate_nem3_annual_costs(
            [ts_h0, ts_h13],
            [1.0, 0.0],
            [0.0, 1.0],   # export at hour 13, not 14
            "PG&E", "E-TOU-D",
            export_table=acc,
        )["E-TOU-D"]

        plan = PGE_RATE_PLANS["E-TOU-D"]
        energy_charge = 1.0 * _step12_rate(plan, ts_h0.to_pydatetime())
        # No credit (ACC rate at hour 13 = 0): bill = full energy charge
        assert result_wrong_hour == pytest.approx(energy_charge, abs=0.001), (
            f"Export at hour 13 should get $0 credit (ACC only set at hour 14). "
            f"Expected full energy charge ${energy_charge:.4f}, got ${result_wrong_hour:.4f}."
        )


class TestNEM3FixedCharges:
    """Test 4: Fixed charges are included in the NEM3 billing path.

    EV2-A has fixedCharge = $0.79343/day (March 2026 tariff, AB 205
    restructuring, income Tier 3). With zero load and zero exports, the
    annual NEM3 bill should equal $0.79343 × 365 = $289.60.

    Verifies that _estimate_monthly_fixed_from_plan is called correctly
    inside calculate_nem3_annual_costs and its result accumulates properly.
    """

    EV2A_FIXED_PER_DAY = 0.79343
    EXPECTED_ANNUAL = EV2A_FIXED_PER_DAY * 365  # $289.60

    def test_zero_load_zero_export_bill_equals_fixed_charges(self):
        result = calculate_nem3_annual_costs(
            YEAR_2018,
            ZEROS_8760,
            ZEROS_8760,
            "PG&E", "EV2-A",
            export_table=_zeros_acc_table(),
        )["EV2-A"]

        assert result == pytest.approx(self.EXPECTED_ANNUAL, abs=1.0), (
            f"EV2-A zero load: NEM3 annual fixed ${result:.2f} vs "
            f"expected ${self.EXPECTED_ANNUAL:.2f} ($0.79343/day × 365 days)"
        )

    def test_fixed_charges_present_regardless_of_export_credits(self):
        """Fixed charges are not offset by export credits — they accumulate regardless."""
        acc = {m: [0.10] * 24 for m in range(1, 13)}  # generous export credit everywhere

        result_with_exports = calculate_nem3_annual_costs(
            YEAR_2018,
            ZEROS_8760,
            [1.0] * 8760,   # 1 kWh/hr export all year
            "PG&E", "EV2-A",
            export_table=acc,
        )["EV2-A"]

        # Energy charge = 0 (no imports). Export credit offsets $0 energy charge.
        # Fixed charges still apply: bill ≈ $289.60 regardless of export size.
        assert result_with_exports == pytest.approx(self.EXPECTED_ANNUAL, abs=1.0), (
            f"EV2-A with large exports: fixed charges should still be "
            f"~${self.EXPECTED_ANNUAL:.2f} (export credits only offset energy charge). "
            f"Got ${result_with_exports:.2f}."
        )


class TestNEM3BOECrossCheck:
    """Test 5 — paper-critical (the Duncan test).

    The end-to-end sanity check: with zero exports, the NEM3 annual bill
    must match the retail annual bill within $1/year for every PGE plan.

    This is the NEM3 equivalent of the existing TestPGEAnnualBillVsPDF and
    TestSCEAnnualBillVsPNG tests. It uses the same BOE methodology: run both
    billing functions on the same load profile and assert they agree.

    If this test fails, the NEM3 and retail billing paths diverge even when
    solar is absent — meaning the NEM3 vs non-NEM3 comparison in the paper
    has a systematic error unrelated to export compensation.
    """

    LOAD_PATH = os.path.join(
        REPO_ROOT,
        "data", "loadprofiles", "baseline_coopt",
        "single-family-detached", "alameda",
        "loadprofiles_for_rates_alameda.csv",
    )

    @pytest.fixture(scope="class")
    def alameda_default_load(self):
        df = pd.read_csv(self.LOAD_PATH)
        return df["default.electricity.kwh"].values[:8760].tolist()

    @pytest.mark.parametrize("plan", ["E-TOU-C", "E-TOU-D", "EV2-A", "EV-B", "E-ELEC"])
    def test_boe_nem3_no_exports_matches_retail(self, alameda_default_load, plan):
        load = alameda_default_load
        zeros = [0.0] * len(load)

        retail = calculate_annual_costs_electricity(load, "PG&E", plan)[plan]
        nem3 = calculate_nem3_annual_costs(
            YEAR_2018, load, zeros, "PG&E", plan,
            export_table=_zeros_acc_table(),
        )[plan]

        assert nem3 == pytest.approx(retail, abs=1.0), (
            f"{plan}: NEM3 (no exports) ${nem3:.2f} vs retail ${retail:.2f} "
            f"(diff ${nem3 - retail:+.2f}). "
            f"With zero exports, both billing paths must agree within $1/yr."
        )


# ---------------------------------------------------------------------------
# Group B: Cost reconciliation (calculate_total_annual_costs)
# ---------------------------------------------------------------------------


class TestCostReconciliationArithmetic:
    """Test 6: calculate_total_annual_costs correctly adds electricity and gas."""

    def test_single_plan_adds_correctly(self):
        idx = ["baseline", "baseline.solarstorage"]
        elec = pd.DataFrame(index=idx, data={
            "electricity.PG&E.E-TOU-D": [2000.0, 1500.0],
        })
        gas = pd.DataFrame(index=idx, data={"gas.PG&E.G-1": [500.0, 500.0]})
        totals = calculate_total_annual_costs(elec, gas)

        col = "total.PG&E.E-TOU-D+PG&E.G-1"
        assert col in totals.columns
        assert totals.loc["baseline", col] == pytest.approx(2500.0)
        assert totals.loc["baseline.solarstorage", col] == pytest.approx(2000.0)

    def test_multiple_electricity_plans_single_gas_gives_n_columns(self):
        """N electricity plans × 1 gas plan → N total columns (no Cartesian explosion)."""
        idx = ["baseline", "baseline.solarstorage"]
        elec = pd.DataFrame(index=idx, data={
            "electricity.PG&E.E-TOU-C": [3000.0, 2500.0],
            "electricity.PG&E.E-TOU-D": [2800.0, 2300.0],
            "electricity.PG&E.EV2-A":   [2700.0, 2200.0],
        })
        gas = pd.DataFrame(index=idx, data={"gas.PG&E.G-1": [500.0, 500.0]})
        totals = calculate_total_annual_costs(elec, gas)

        assert len(totals.columns) == 3, (
            f"Expected 3 total columns (one per electricity plan), got {len(totals.columns)}: "
            f"{list(totals.columns)}"
        )


class TestCostReconciliationNEM3Column:
    """Test 7: NEM3 electricity columns pass through the reconciliation correctly.

    The baseline row has NaN for NEM3 electricity (no solar in the baseline
    scenario). NaN must propagate to the NEM3 total column — not be replaced
    by 0 — so that downstream code can distinguish "no NEM3 scenario" from
    "$0 NEM3 cost".
    """

    def test_nem3_column_naming_and_values(self):
        idx = ["baseline_coopt", "baseline_coopt.solarstorage"]
        elec = pd.DataFrame(index=idx, data={
            "electricity.PG&E.E-TOU-D":      [3000.0, 2500.0],
            "electricity.PG&E.E-TOU-D_NEM3": [float("nan"), 2480.0],
        })
        gas = pd.DataFrame(index=idx, data={"gas.PG&E.G-1": [500.0, 500.0]})
        totals = calculate_total_annual_costs(elec, gas)

        nem3_col = "total.PG&E.E-TOU-D_NEM3+PG&E.G-1"
        assert nem3_col in totals.columns, (
            f"NEM3 total column '{nem3_col}' missing from output. "
            f"Columns present: {list(totals.columns)}"
        )

        # solarstorage row: NEM3 electricity ($2480) + gas ($500) = $2980
        assert totals.loc["baseline_coopt.solarstorage", nem3_col] == pytest.approx(2980.0)

        # baseline row: NaN (no NEM3 without solar) — must propagate as NaN, not 0
        baseline_val = totals.loc["baseline_coopt", nem3_col]
        assert pd.isna(baseline_val), (
            f"Baseline NEM3 total should be NaN (no solar in baseline), "
            f"got {baseline_val}. A value of 0 would silently misrepresent "
            f"the baseline cost as $0 under NEM3."
        )


class TestCostReconciliationNaNPropagation:
    """Test 8: Mismatched row indices produce detectable NaN, not silent zeros.

    If elec_df and gas_df have different scenario rows (e.g., from a partial
    re-run), pandas Series addition fills unmatched rows with NaN. This test
    documents that behavior so a data gap is detectable rather than silent.
    """

    def test_missing_gas_row_produces_nan_total(self):
        elec = pd.DataFrame(
            index=["scenario_a", "scenario_b"],
            data={"electricity.PG&E.E-TOU-D": [1000.0, 2000.0]},
        )
        gas = pd.DataFrame(
            index=["scenario_a"],   # scenario_b has no gas data
            data={"gas.PG&E.G-1": [500.0]},
        )
        totals = calculate_total_annual_costs(elec, gas)
        col = "total.PG&E.E-TOU-D+PG&E.G-1"

        # scenario_a has both electricity and gas → valid total
        assert not pd.isna(totals.loc["scenario_a", col]), (
            "scenario_a has both electricity and gas data — total should not be NaN"
        )
        assert totals.loc["scenario_a", col] == pytest.approx(1500.0)

        # scenario_b has electricity but no gas → NaN, not 0
        assert pd.isna(totals.loc["scenario_b", col]), (
            f"scenario_b is missing gas data — total should be NaN (detectable gap), "
            f"not 0 (silent wrong value). Got {totals.loc['scenario_b', col]}."
        )


# ---------------------------------------------------------------------------
# SCE NEM3 BOE cross-check
# ---------------------------------------------------------------------------


class TestNEM3BOECrossCheckSCE:
    """SCE equivalent of TestNEM3BOECrossCheck (Test 5) for LA County.

    With zero exports, the NEM3 annual bill must match the retail annual bill
    within $1/year for each SCE plan. This is the Duncan test for SCE territory.

    Uses real LA County load data (default.electricity.kwh — no solar, no storage).
    Timestamps are set to YEAR_2018 to match the year used by both billing
    functions for weekday/season determination.

    If this fails, there is a systematic discrepancy between the two billing
    paths for SCE that is unrelated to export compensation — every SCE NEM3
    number in the paper would have a systematic error.

    Note: calculate_annual_costs_electricity and calculate_nem3_annual_costs use
    different rate-dispatch code paths. Both are exercised here:
      - calculate_annual_costs_electricity: dayotw_rates dict lookups (step12 lines 99–108)
      - calculate_nem3_annual_costs: _hourly_import_rate helper
    Any divergence between these paths for SCE plans would show up here.
    """

    LOAD_PATH = os.path.join(
        REPO_ROOT,
        "data", "loadprofiles", "baseline_coopt",
        "single-family-detached", "los-angeles",
        "loadprofiles_for_rates_los-angeles.csv",
    )

    @pytest.fixture(scope="class")
    def la_default_load(self):
        df = pd.read_csv(self.LOAD_PATH)
        return df["default.electricity.kwh"].values[:8760].tolist()

    @pytest.mark.parametrize("plan", ["TOU-D-4-9PM", "TOU-D-5-8PM", "TOU-D-PRIME"])
    def test_boe_nem3_no_exports_matches_retail(self, la_default_load, plan):
        load = la_default_load
        zeros = [0.0] * len(load)

        retail = calculate_annual_costs_electricity(load, "SCE", plan)[plan]
        nem3 = calculate_nem3_annual_costs(
            YEAR_2018, load, zeros, "SCE", plan,
            export_table=_zeros_acc_table(),
        )[plan]

        assert nem3 == pytest.approx(retail, abs=1.0), (
            f"SCE {plan}: NEM3 (no exports) ${nem3:.2f} vs retail ${retail:.2f} "
            f"(diff ${nem3 - retail:+.2f}). "
            f"With zero exports, both billing paths must agree within $1/yr."
        )


# ---------------------------------------------------------------------------
# G7: NEM3 year-end carry drop
# ---------------------------------------------------------------------------

_JAN_TO_NOV_TS = pd.date_range("2018-01-01", periods=8016, freq="h")  # Jan–Nov: 334 days
_DEC_TS        = pd.date_range("2018-12-01", periods=744,  freq="h")  # Dec: 31 days


class TestNEM3YearEndCarryDrop:
    """G7: Unused export credit remaining in December is dropped at year-end.

    NEM3 carry-forward logic: each month's surplus export credit rolls to the
    next month. After December there is no next month, so any remaining credit
    is discarded — no NSC (Net Surplus Compensation) payout is modeled
    (nsc_dollars_per_kwh = 0.0 by default).

    This simplification is conservative: it makes NEM3 look slightly worse
    (households that over-generate in fall/winter get nothing for surplus).

    The test verifies that the year-end surplus does NOT reduce the annual
    total (no phantom refund). If the carry were accidentally paid out,
    full_year_with_dec_exports would be lower than expected.

    Uses E-TOU-D (zero fixed charge) to keep arithmetic clean.
    """

    ACC_RATE = 0.10  # generous ACC rate → large export credit in December

    def _dec_acc_table(self):
        table = _zeros_acc_table()
        table[12] = [self.ACC_RATE] * 24
        return table

    def test_december_surplus_carry_is_dropped(self):
        # Jan–Nov: 0.5 kWh/hr imports, no exports (builds up the baseline cost)
        # December: 0.5 kWh/hr imports, 5.0 kWh/hr exports → export_credit >> energy_charge
        #   Dec energy_charge ≈ 744 × 0.5 × 0.35 ≈ $130 (E-TOU-D winter off-peak)
        #   Dec export_credit = 744 × 5.0 × 0.10 = $372 → surplus ≈ $242 dropped at year-end
        all_ts  = _JAN_TO_NOV_TS.append(_DEC_TS)
        imports = [0.5] * 8760
        exports = [0.0] * 8016 + [5.0] * 744

        full_with_exports = calculate_nem3_annual_costs(
            all_ts, imports, exports, "PG&E", "E-TOU-D",
            export_table=self._dec_acc_table(),
        )["E-TOU-D"]

        # Reference: same year but with no December exports (Dec energy charge intact)
        full_no_exports = calculate_nem3_annual_costs(
            all_ts, imports, [0.0] * 8760, "PG&E", "E-TOU-D",
            export_table=_zeros_acc_table(),
        )["E-TOU-D"]

        # December standalone energy charge (no exports, no fixed → just energy)
        dec_energy_only = calculate_nem3_annual_costs(
            _DEC_TS, [0.5] * 744, [0.0] * 744, "PG&E", "E-TOU-D",
            export_table=_zeros_acc_table(),
        )["E-TOU-D"]

        # Correct: full_with_exports = full_no_exports - dec_energy_only
        #   (December energy is offset by exports; surplus carry is dropped, not refunded)
        # Wrong (if NSC payout): full_with_exports < full_no_exports - dec_energy_only
        expected = full_no_exports - dec_energy_only
        assert full_with_exports == pytest.approx(expected, abs=0.50), (
            f"Full year with Dec exports: ${full_with_exports:.2f}. "
            f"Full year no exports: ${full_no_exports:.2f}. "
            f"Dec energy: ${dec_energy_only:.2f}. "
            f"Expected (carry dropped): ${expected:.2f}. "
            f"If lower, December surplus was incorrectly paid out as NSC."
        )


# ---------------------------------------------------------------------------
# G8: NEM3 NBC charge path
# ---------------------------------------------------------------------------


class TestNEM3NBCCharges:
    """G8: Non-Bypassable Charges (NBCs) accumulate on imports and cannot be
    offset by export credits.

    NBCs = 0.0 by default in the pipeline (NEM3Options.nbc_dollars_per_kwh = 0.0).
    This test exercises the NBC code path by passing NEM3Options explicitly.

    In step12 calculate_nem3_annual_costs:
        energy_charge += kwh_imp * max(0.0, irate - opts.nbc_dollars_per_kwh)
        nbc_charge    += kwh_imp * max(0.0, opts.nbc_dollars_per_kwh)
        ...
        month_total = energy_net + nbc_charge + fixed

    Export credits offset energy_charge only. nbc_charge accumulates regardless.

    These tests must pass before NBC rates are set to real values in
    default_options_for_utility() — they lock in the intended behavior.
    """

    NBC_RATE = 0.03  # $/kWh, representative of real PGE NBC

    def test_nbc_accrues_on_imports(self):
        """With imports and no exports, NBC charge = imports × nbc_rate."""
        # Single July Sunday hour: 1 kWh imported at E-TOU-D off-peak
        ts = [pd.Timestamp(2018, 7, 1, 10)]  # July 1 = Sunday, hour 10: summer off-peak
        plan = PGE_RATE_PLANS["E-TOU-D"]
        irate = _step12_rate(plan, ts[0].to_pydatetime())

        opts = NEM3Options(nbc_dollars_per_kwh=self.NBC_RATE)
        result = calculate_nem3_annual_costs(
            ts, [1.0], [0.0], "PG&E", "E-TOU-D",
            options=opts, export_table=_zeros_acc_table(),
        )["E-TOU-D"]

        # energy_charge = 1 × (irate - NBC); nbc_charge = 1 × NBC
        # total = energy_charge + nbc_charge = irate (NBC splits the charge, not adds to it)
        assert result == pytest.approx(irate, abs=0.001), (
            f"1 kWh at {irate:.4f}/kWh with NBC={self.NBC_RATE}: "
            f"expected total ${irate:.4f} (NBC splits charge, not adds to it), "
            f"got ${result:.4f}"
        )

    def test_nbc_not_offset_by_export_credits(self):
        """Export credits offset energy_charge only — NBC charge persists even when
        exports fully cover the energy portion.

        Setup: 100 kWh imported, 300 kWh exported at a generous ACC rate.
        The export credit exceeds the energy charge (energy_net = $0, carry builds).
        But nbc_charge = 100 × 0.03 = $3 must still appear in the monthly total.
        """
        ts = [pd.Timestamp(2018, 7, 1, 10)]  # July Sunday off-peak
        plan = PGE_RATE_PLANS["E-TOU-D"]
        irate = _step12_rate(plan, ts[0].to_pydatetime())

        acc = _zeros_acc_table()
        acc[7][10] = irate * 5  # export credit = 5× energy charge → well above energy

        opts = NEM3Options(nbc_dollars_per_kwh=self.NBC_RATE)
        result = calculate_nem3_annual_costs(
            ts, [100.0], [300.0], "PG&E", "E-TOU-D",
            options=opts, export_table=acc,
        )["E-TOU-D"]

        # energy_charge = 100 × (irate - 0.03)
        # export_credit = 300 × (irate × 5) >> energy_charge → energy_net = $0
        # nbc_charge    = 100 × 0.03 = $3.00  ← cannot be offset
        # month_total   = $0 + $3.00 (no fixed on E-TOU-D)
        expected_nbc = 100.0 * self.NBC_RATE
        assert result == pytest.approx(expected_nbc, abs=0.001), (
            f"100 kWh import with large export credit: energy_net=$0, "
            f"but NBC=${expected_nbc:.2f} must still be charged. "
            f"Got ${result:.4f}. "
            f"If $0.00: NBC was incorrectly offset by export credit."
        )
