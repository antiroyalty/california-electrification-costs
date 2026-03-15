"""
Tests for the NPV and annuity factor formulas in evaluations/npv.py.

These tests verify the math from first principles using hand-calculated values.
The paper uses a 7% real discount rate over a 25-year horizon — those are the
parameters checked in the paper-relevant tests at the bottom.

Run with: pytest tests/npv-test.py -v
"""

import os
import sys

import pytest

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from evaluations.npv import annuity_factor, npv, compute_npv_details_from_inputs


# ---------------------------------------------------------------------------
# annuity_factor
# ---------------------------------------------------------------------------

class TestAnnuityFactor:
    """annuity_factor(r, n) = r / (1 - (1+r)^-n)
    This is the capital recovery factor: multiply by NPV to get annualized cost."""

    def test_zero_rate_returns_one_over_n(self):
        # At 0% discount rate, annuity factor = 1/n (equal annual payments).
        assert annuity_factor(0.0, 25) == pytest.approx(1 / 25)

    def test_zero_years_returns_one(self):
        assert annuity_factor(0.07, 0) == pytest.approx(1.0)

    def test_known_value_7pct_25yr(self):
        # Hand-calculated: 0.07 / (1 - 1.07^-25)
        # 1.07^25 = 5.42743, so 1.07^-25 = 0.18425
        # 0.07 / (1 - 0.18425) = 0.07 / 0.81575 = 0.08581
        assert annuity_factor(0.07, 25) == pytest.approx(0.08581, rel=1e-3)

    def test_higher_rate_gives_higher_factor(self):
        # At a higher discount rate, future savings are worth less,
        # so the annualized cost of a given NPV is higher.
        assert annuity_factor(0.10, 25) > annuity_factor(0.07, 25)

    def test_longer_horizon_gives_lower_factor(self):
        # Spreading the same NPV over more years reduces the annual payment.
        assert annuity_factor(0.07, 30) < annuity_factor(0.07, 25)

    def test_matches_eac_crf(self):
        """evaluations.npv.annuity_factor and evaluations.eac.crf must agree."""
        from evaluations.eac import crf
        for r, n in [(0.07, 25), (0.05, 15), (0.10, 30)]:
            assert annuity_factor(r, n) == pytest.approx(crf(r, n), rel=1e-10)


# ---------------------------------------------------------------------------
# npv
# ---------------------------------------------------------------------------

class TestNPV:
    """npv(rate, cash_flows) discounts each flow at period t = 0, 1, 2, ..."""

    def test_single_cash_flow_at_t0_is_undiscounted(self):
        assert npv(0.07, [1000.0]) == pytest.approx(1000.0)

    def test_single_future_cash_flow_is_discounted(self):
        # $1000 one year from now at 7% = $1000 / 1.07 = $934.58
        assert npv(0.07, [0.0, 1000.0]) == pytest.approx(1000.0 / 1.07, rel=1e-6)

    def test_zero_cash_flows_give_zero_npv(self):
        assert npv(0.07, [0.0, 0.0, 0.0]) == pytest.approx(0.0)

    def test_three_year_annuity(self):
        # $1/yr for 3 years at 7%: 1/1.07 + 1/1.07² + 1/1.07³ = 2.6243
        assert npv(0.07, [0.0, 1.0, 1.0, 1.0]) == pytest.approx(2.6243, rel=1e-3)

    def test_negative_initial_investment(self):
        # Upfront cost with no future returns is negative NPV.
        assert npv(0.07, [-5000.0]) == pytest.approx(-5000.0)

    def test_profitable_investment_has_positive_npv(self):
        # $100 upfront, $50/yr for 3 years at 7%.
        result = npv(0.07, [-100.0, 50.0, 50.0, 50.0])
        assert result > 0

    def test_losing_investment_has_negative_npv(self):
        # $1000 upfront, $1/yr for 3 years — clearly losing money.
        result = npv(0.07, [-1000.0, 1.0, 1.0, 1.0])
        assert result < 0


# ---------------------------------------------------------------------------
# Consistency: npv and annuity_factor must agree
# ---------------------------------------------------------------------------

class TestNPVAndAnnuityFactorConsistency:
    """The two functions must be mathematically consistent.

    For a uniform annuity of S $/yr over n years at rate r:
      NPV of savings = S / annuity_factor(r, n)
      Annualizing back: NPV * annuity_factor(r, n) == S
    """

    def test_annualizing_npv_recovers_annual_savings(self):
        r, n, annual_savings = 0.07, 25, 2516.0
        pv_savings = npv(r, [0.0] + [annual_savings] * n)
        annualized = pv_savings * annuity_factor(r, n)
        assert annualized == pytest.approx(annual_savings, rel=1e-4)


# ---------------------------------------------------------------------------
# Paper-relevant case: 7% discount rate, 25-year horizon
# Based on the paper's $2,516/yr savings figure (full electrification + EV + co-opt)
# ---------------------------------------------------------------------------

class TestPaperRelevantNPV:

    def test_positive_npv_for_full_electrification(self):
        # $2,516/yr savings over 25 years at 7% with plausible net capex
        # should produce a positive NPV — i.e., electrification pencils out.
        result = compute_npv_details_from_inputs(
            baseline_cost=15135.0,
            scenario_cost=12619.0,
            scenario_solar_cost=12619.0,
            pv_storage_net_capex=8000.0,
            electrification_net_capex=5000.0,
            horizon_years=25,
            discount_rate=0.07,
        )
        assert result["all_electrification"]["npv"] > 0, (
            "Full electrification should have positive NPV given $2,516/yr savings "
            "over 25 years — if this fails, check capex assumptions or savings figures."
        )

    def test_higher_savings_gives_higher_npv(self):
        base_kwargs = dict(
            baseline_cost=15135.0,
            scenario_cost=12619.0,
            scenario_solar_cost=12619.0,
            pv_storage_net_capex=8000.0,
            electrification_net_capex=5000.0,
            horizon_years=25,
            discount_rate=0.07,
        )
        low_savings = compute_npv_details_from_inputs(**base_kwargs)
        # Increase savings by reducing scenario cost
        high_savings = compute_npv_details_from_inputs(
            **{**base_kwargs, "scenario_solar_cost": 11000.0}
        )
        assert (
            high_savings["all_electrification"]["npv"]
            > low_savings["all_electrification"]["npv"]
        )

    def test_annual_savings_definition_is_correct(self):
        # Annual savings for full electrification = baseline_cost - scenario_solar_cost
        result = compute_npv_details_from_inputs(
            baseline_cost=15135.0,
            scenario_cost=12619.0,
            scenario_solar_cost=12619.0,
            pv_storage_net_capex=0.0,
            electrification_net_capex=0.0,
            horizon_years=25,
            discount_rate=0.07,
        )
        assert result["all_electrification"]["annual_savings"] == pytest.approx(
            15135.0 - 12619.0
        )
