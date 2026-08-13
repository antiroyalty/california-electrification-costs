"""Tests for the LP co-optimization core (step9b_cooptimize_core.py).

These tests cover behavioral correctness of the LP optimizer and the data
integrity of the ACC export rate tables. The existing co_optimization_test.py
only checks saved CSV outputs after a full pipeline run; these tests exercise
the LP logic directly with synthetic and real-data inputs.

Test groups
-----------
H1  Analytical baseline — no solar, no storage: pure import cost (ground truth)
H2  Export credit matches flows — fixed sizing, verify accounting identity
H3  Battery responds to price signal — store vs export based on p_exp vs p_imp
H4  ACC rate range for Alameda — data validation: rates are ACC, not retail
H5  ACC vs retail in production path — p_exp < p_imp for every hour of 2018

Design note: H=24 synthetic profiles are used for H1–H3 rather than 8760
because the cyclic SOC constraint applies to the full horizon, and a 24-hour
cycle is the natural periodic unit. Capex is zero in H1–H3 (c_pv_kw=0,
c_batt_kwh=0) so total_cost = import_cost - export_credit, making assertions
analytically exact.
"""
import os
import sys

import pytest

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from pipeline.steps.step9b_cooptimize_core import (
    CooptInputs,
    SOLVER_OUTPUT_ABSOLUTE_TOLERANCE,
    _meter_direction_hours,
    _normalize_nonnegative_solver_value,
    _solve_lp,
)
from tariffs import NBTScenario, TariffCatalog
from tariffs.calendar import full_year_hourly_index
from evaluations.eac import crf, alpha_batt_npv

# Profile for H1–H3: 24 hours, flat 1 kWh/hr load, solar only during hours 8–15.
# pv_gen_per_kw = 1.0 during peak hours → 2 kW PV generates 2 kWh/hr during sun hours.
# Without battery: 8 hrs × (2 − 1) = 8 kWh exported, 16 hrs × 1 = 16 kWh imported.
H24_LOAD      = [1.0] * 24
H24_PV_PER_KW = [0.0] * 8 + [1.0] * 8 + [0.0] * 8  # hours 8–15 only
P_IMP         = [0.40] * 24
P_EXP_ACC     = [0.08] * 24   # ACC-like: far below import rate
P_EXP_RETAIL  = [0.40] * 24   # retail parity: same as import rate


def _zero_capex_kwargs():
    """Return LP keyword args with zero capex so total_cost = operating cost only."""
    return dict(c_pv_kw=0.0, c_batt_kwh=0.0, c_batt_kw=0.0)


@pytest.mark.parametrize(
    "value",
    [
        -SOLVER_OUTPUT_ABSOLUTE_TOLERANCE,
        -1e-12,
        0.0,
        1e-12,
        SOLVER_OUTPUT_ABSOLUTE_TOLERANCE,
    ],
)
def test_solver_scale_values_are_normalized_to_physical_zero(value):
    assert _normalize_nonnegative_solver_value(value, label="flow[7]") == 0.0


def test_materially_negative_solver_output_fails_instead_of_being_clamped():
    value = -(SOLVER_OUTPUT_ABSOLUTE_TOLERANCE + 1e-12)

    with pytest.raises(RuntimeError, match=r"flow\[7\].*below the allowed"):
        _normalize_nonnegative_solver_value(value, label="flow[7]")


def test_positive_flow_above_solver_tolerance_is_preserved_exactly():
    value = SOLVER_OUTPUT_ABSOLUTE_TOLERANCE + 1e-12
    assert _normalize_nonnegative_solver_value(value, label="flow[7]") == value


# ---------------------------------------------------------------------------
# H1 — Analytical baseline: no solar, no storage
# ---------------------------------------------------------------------------

class TestLPAnalyticalBaseline:
    """With zero solar potential, the LP installs no PV and no battery.

    With no solar generation and flat import prices (no time-of-use arbitrage),
    neither PV nor battery is economic. The LP naturally chooses pv_kw=0 and
    batt_kwh=0. Every kWh of load is served by grid_to_load, so import_cost =
    Σ load[h] * p_imp[h] exactly. Used as ground truth for the accounting path.

    Note: fixed_pv_kw=0.0 is NOT used here because it creates a degenerate LP
    (B_P becomes a free variable with no cost, and CBC may not assign it a value,
    corrupting solution extraction). Instead, the tests rely on economic signals:
    zero solar yield means PV capex yields no savings → LP chooses pv_kw=0.
    """

    def test_import_cost_equals_load_times_price(self):
        """24 kWh of flat load at $0.40/kWh → import_cost = $9.60 exactly."""
        inputs = CooptInputs(
            load_kwh=H24_LOAD,
            pv_gen_per_kw=[0.0] * 24,   # no solar yield → LP installs 0 PV
            import_rates=P_IMP,
            export_rates=P_EXP_ACC,
        )
        result = _solve_lp(inputs)

        assert result.pv_kw == pytest.approx(0.0, abs=1e-3), (
            f"Zero solar yield: expected pv_kw=0, got {result.pv_kw:.4f}"
        )
        assert result.export_credit == pytest.approx(0.0, abs=1e-4), (
            f"No PV/battery: expected export_credit=0, got {result.export_credit:.4f}"
        )
        expected_import = sum(H24_LOAD[h] * P_IMP[h] for h in range(24))  # 9.60
        assert result.import_cost == pytest.approx(expected_import, abs=1e-3), (
            f"import_cost: expected ${expected_import:.2f}, got ${result.import_cost:.2f}"
        )

    def test_all_load_served_from_grid_when_no_solar(self):
        """With no solar yield, grid_to_load must equal load at every hour."""
        inputs = CooptInputs(
            load_kwh=H24_LOAD,
            pv_gen_per_kw=[0.0] * 24,
            import_rates=P_IMP,
            export_rates=P_EXP_ACC,
        )
        result = _solve_lp(inputs)

        for h, (g2l, load) in enumerate(zip(result.flows.grid_to_load, H24_LOAD)):
            assert g2l == pytest.approx(load, abs=1e-3), (
                f"Hour {h}: grid_to_load={g2l:.4f}, expected load={load:.4f}"
            )


# ---------------------------------------------------------------------------
# H2 — Export credit matches flows (accounting identity)
# ---------------------------------------------------------------------------

class TestLPExportCreditMatchesFlows:
    """export_credit must equal Σ (pv2grid[h] + batt2grid[h]) * p_exp[h].

    With 2 kW PV and no battery, the profile forces 8 kWh of exports during
    daylight hours (PV=2, load=1 → 1 kWh/hr excess × 8 hours). The export
    credit should equal exactly 8 * p_exp — verifying that the accounting
    identity holds in the LP result, not just in the internal constraints.
    """

    def _run(self, p_exp_val: float):
        inputs = CooptInputs(
            load_kwh=H24_LOAD,
            pv_gen_per_kw=H24_PV_PER_KW,
            import_rates=P_IMP,
            export_rates=[p_exp_val] * 24,
        )
        return _solve_lp(inputs, fixed_pv_kw=2.0, fixed_batt_kwh=0.0, **_zero_capex_kwargs())

    def test_export_credit_matches_flow_weighted_sum(self):
        """export_credit == Σ (pv2grid[h] + batt2grid[h]) * p_exp[h]."""
        p_exp_val = 0.08
        result = self._run(p_exp_val)

        flow_credit = sum(
            (result.flows.pv_to_grid[h] + result.flows.batt_to_grid[h]) * p_exp_val
            for h in range(24)
        )
        assert result.export_credit == pytest.approx(flow_credit, abs=1e-4), (
            f"export_credit {result.export_credit:.4f} != "
            f"flow-computed {flow_credit:.4f}"
        )

    def test_export_credit_scales_with_export_price(self):
        """Same dispatch, different p_exp → export_credit scales proportionally.

        With no battery, dispatch is determined by load/PV balance alone (8 kWh
        of forced exports). export_credit at 0.16 should be exactly 2× credit
        at 0.08. This verifies that p_exp enters the accounting correctly.
        """
        result_low  = self._run(0.08)
        result_high = self._run(0.16)

        assert result_high.export_credit == pytest.approx(
            2 * result_low.export_credit, rel=0.01
        ), (
            f"export_credit at 0.16 should be 2× at 0.08. "
            f"Got low={result_low.export_credit:.4f}, high={result_high.export_credit:.4f}"
        )

    def test_exact_export_volume_with_no_battery(self):
        """With 2 kW fixed PV and no battery, exactly 8 kWh is exported.

        During hours 8–15 (8 hours): PV generates 2 kWh, load is 1 kWh → 1 kWh
        forced to grid per hour = 8 kWh total. No battery means no other option.
        """
        result = self._run(0.08)
        total_exported = sum(
            result.flows.pv_to_grid[h] + result.flows.batt_to_grid[h]
            for h in range(24)
        )
        assert total_exported == pytest.approx(8.0, abs=0.05), (
            f"Expected 8 kWh exported with 2 kW fixed PV, got {total_exported:.3f} kWh"
        )


# ---------------------------------------------------------------------------
# H3 — Battery responds to export price signal
# ---------------------------------------------------------------------------

class TestLPBatteryRespondsToPriceSignal:
    """Battery dispatch shifts between store-for-self-consumption and export
    based on whether p_exp is below or equal to p_imp.

    Profile: 2 kW fixed PV, 12 kWh fixed battery (usable SOC window 0.2–0.9
    = 8.4 kWh, enough to absorb all daytime excess without hitting max SOC).
    8 hours of generation × (2−1) kWh excess = 8 kWh excess per day.

    When p_exp < p_imp (ACC-like): storing and discharging saves p_imp per kWh
    (minus round-trip losses); exporting earns only p_exp. Storing dominates.
    Expected: pv2grid ≈ 0 (or very small due to SOC boundary effects),
    export_credit ≈ 0.

    When p_exp = p_imp: exporting earns the same per kWh as avoiding an import,
    but without round-trip losses. Exporting weakly dominates storing (RTE<1).
    Expected: pv2grid > 0, export_credit > 0.

    The key assertion is directional: high p_exp → more exports than low p_exp.
    """

    def _run(self, p_exp: list[float]):
        inputs = CooptInputs(
            load_kwh=H24_LOAD,
            pv_gen_per_kw=H24_PV_PER_KW,
            import_rates=P_IMP,
            export_rates=p_exp,
        )
        return _solve_lp(
            inputs,
            fixed_pv_kw=2.0,
            fixed_batt_kwh=12.0,
            **_zero_capex_kwargs(),
        )

    def test_zero_export_price_battery_stores_excess(self):
        """With p_exp=0, there is no incentive to export: export_credit must be 0.

        When exports earn nothing, the LP will either curtail excess PV or route
        it to the battery; it will never actively choose to export. export_credit
        = Σ flows * p_exp = Σ flows * 0 = 0 regardless of dispatch.
        """
        result = self._run([0.0] * 24)
        assert result.export_credit == pytest.approx(0.0, abs=1e-4), (
            f"p_exp=0: expected export_credit=0, got {result.export_credit:.4f}"
        )

    def test_retail_export_price_produces_more_exports_than_acc(self):
        """p_exp=retail produces higher export_credit and more pv2grid than p_exp=ACC.

        This is the core behavioral test: the LP objective must use p_exp to
        decide dispatch. If p_exp were ignored (e.g., hardcoded to retail), the
        two runs would produce the same flows regardless of the passed rates.
        """
        result_acc    = self._run(P_EXP_ACC)     # p_exp=0.08 < p_imp=0.40: store
        result_retail = self._run(P_EXP_RETAIL)  # p_exp=0.40 = p_imp=0.40: export

        exports_acc    = sum(result_acc.flows.pv_to_grid)
        exports_retail = sum(result_retail.flows.pv_to_grid)

        assert exports_retail > exports_acc + 0.5, (
            f"Retail export rate should lead to more pv2grid than ACC rate. "
            f"Got acc={exports_acc:.3f} kWh, retail={exports_retail:.3f} kWh. "
            f"If equal, the LP is ignoring the export price signal."
        )
        assert result_retail.export_credit > result_acc.export_credit + 0.1, (
            f"export_credit with retail p_exp ({result_retail.export_credit:.3f}) "
            f"should exceed ACC p_exp ({result_acc.export_credit:.3f})"
        )

    def test_lower_export_price_leads_to_more_self_consumption(self):
        """With ACC export rates, the battery reduces grid imports more than with retail.

        When exporting is less valuable, the optimizer stores more in the battery
        for nighttime self-consumption, which reduces grid imports at night.
        """
        result_acc    = self._run(P_EXP_ACC)
        result_retail = self._run(P_EXP_RETAIL)

        # ACC run stores more → less grid imports at night
        assert result_acc.import_cost < result_retail.import_cost + 0.01, (
            f"ACC run (stores more) should have lower import_cost than retail run. "
            f"Got acc={result_acc.import_cost:.3f}, retail={result_retail.import_cost:.3f}"
        )


# ---------------------------------------------------------------------------
# H4 — Official NBT schedule shape and range
# ---------------------------------------------------------------------------

class TestACCRatesForAlameda:
    """The production path uses a utility schedule, not a county climate zone."""

    @pytest.fixture(scope="class")
    def alameda_rates(self):
        schedule = TariffCatalog().export_schedule("PG&E", NBTScenario())
        return schedule.rows[schedule.rows["component"] == "total"]["rate_usd_per_kwh"].tolist()

    def test_all_acc_rates_are_non_negative(self, alameda_rates):
        """All 576 weekday/weekend-holiday entries are non-negative."""
        negatives = [(i, v) for i, v in enumerate(alameda_rates) if v < 0.0]
        assert not negatives, (
            f"Found {len(negatives)} negative ACC rates (first: {negatives[0]}). "
            f"ACC rates should always be ≥ 0."
        )

    def test_official_schedule_has_low_average_and_real_evening_spikes(self, alameda_rates):
        """NBT averages are low even though some late-summer hours exceed retail."""
        assert 0.07 < sum(alameda_rates) / len(alameda_rates) < 0.12
        assert max(alameda_rates) == pytest.approx(1.19289)

    def test_acc_table_has_576_values(self, alameda_rates):
        """The schedule is 12 months × 2 day types × 24 hours."""
        assert len(alameda_rates) == 576, (
            f"Expected 576 ACC rate entries, "
            f"got {len(alameda_rates)}"
        )

    def test_some_nonzero_acc_rates_exist(self, alameda_rates):
        """At least some hours should have non-zero ACC rates.

        Night hours (no solar) may have zero ACC value, but daytime/peak hours
        should have positive rates. A table of all-zeros would mean the export
        incentive is completely absent — which would be a data error, not a
        legitimate ACC schedule.
        """
        nonzero = [v for v in alameda_rates if v > 0.0]
        assert len(nonzero) > 50, (
            f"Only {len(nonzero)} non-zero ACC rates found. Expected many more — "
            f"daytime hours across all months should have positive ACC values."
        )


# ---------------------------------------------------------------------------
# H5 — Official price spikes cannot create meter arbitrage
# ---------------------------------------------------------------------------

class TestACCExportRatesBelowRetailImport:
    """High export values are real; physical meter direction is the safeguard."""

    @pytest.fixture(scope="class")
    def alameda_price_series(self):
        bundle = TariffCatalog().bundle("PG&E", NBTScenario())
        ts_index = full_year_hourly_index(2026)
        p_exp = [
            rate + bundle.acc_plus_rate
            for rate in bundle.export_schedule.rates_for(ts_index)
        ]
        p_imp = bundle.import_schedule.rates_for(ts_index)
        return p_imp, p_exp

    def test_some_official_export_prices_exceed_retail(self, alameda_price_series):
        """Pin the counterintuitive feature that exposed the old LP exploit."""
        p_imp, p_exp = alameda_price_series
        violations = [
            (h, p_exp[h], p_imp[h])
            for h in range(8760)
            if p_exp[h] > p_imp[h] + 1e-6
        ]
        assert violations
        assert len(violations) == 216

    def test_only_nonconvex_price_hours_are_binary_candidates(self, alameda_price_series):
        p_imp, p_exp = alameda_price_series
        inputs = CooptInputs(
            load_kwh=[1.0] * 8760,
            pv_gen_per_kw=[1.0] * 8760,
            import_rates=p_imp,
            export_rates=p_exp,
        )
        candidates = _meter_direction_hours(inputs)
        assert len(candidates) == 216
        assert all(p_exp[hour] > p_imp[hour] for hour in candidates)

    def test_acc_rates_substantially_below_retail(self, alameda_price_series):
        """Annual average export compensation remains below retail imports."""
        p_imp, p_exp = alameda_price_series
        avg_imp = sum(p_imp) / len(p_imp)
        avg_exp = sum(p_exp) / len(p_exp)
        gap = avg_imp - avg_exp

        assert gap > 0.10, (
            f"Average gap between retail and ACC should exceed $0.10/kWh "
            f"(avg_imp={avg_imp:.4f}, avg_exp={avg_exp:.4f}, gap={gap:.4f}). "
            f"A small gap would undermine the NEM3 economic penalty argument."
        )

    def test_lp_never_imports_and_exports_in_same_high_value_interval(self):
        inputs = CooptInputs(
            load_kwh=[1.0, 1.0],
            pv_gen_per_kw=[1.0, 0.0],
            import_rates=[0.20, 0.20],
            export_rates=[2.00, 0.05],
        )
        result = _solve_lp(
            inputs,
            fixed_pv_kw=2.0,
            fixed_batt_kwh=0.0,
            **_zero_capex_kwargs(),
        )
        for hour in range(2):
            imported = result.flows.grid_to_load[hour] + result.flows.grid_to_batt[hour]
            exported = result.flows.pv_to_grid[hour] + result.flows.batt_to_grid[hour]
            assert not (imported > 1e-6 and exported > 1e-6)
        assert result.meter_binary_count == 1
        assert result.solver_rounds == 2


def test_explicit_battery_capacity_bound_is_enforced():
    inputs = CooptInputs(
        load_kwh=[0.0, 1.0],
        pv_gen_per_kw=[1.0, 0.0],
        import_rates=[0.40, 0.40],
        export_rates=[0.0, 0.0],
    )
    result = _solve_lp(
        inputs,
        fixed_pv_kw=1.0,
        c_pv_kw=0.0,
        c_batt_kwh=0.0,
        c_batt_kw=0.0,
        max_battery_kwh=0.5,
    )
    assert 0.0 <= result.batt_kwh <= 0.5 + 1e-8


# ---------------------------------------------------------------------------
# H6 — LP capex coefficients must match the shared evaluations.eac primitives
#
# _solve_lp used to re-derive its NPV-framing capex coefficients (alpha_pv,
# alpha_batt) inline instead of calling evaluations.eac.crf / alpha_batt_npv.
# The two were mathematically identical by construction but nothing enforced
# that they stay identical — a change to one formula could silently diverge
# from the other. This test pins fixed PV/battery sizes (removing solver
# choice as a variable) and asserts the LP's reported capex_annual equals the
# primitive-computed value directly, for non-default rate/lifetimes so the
# test can't pass by coincidentally matching a hardcoded default elsewhere.
# ---------------------------------------------------------------------------
class TestCapexMatchesEvaluationsPrimitives:
    def test_lp_capex_annual_matches_crf_and_alpha_batt_npv(self):
        inputs = CooptInputs(
            load_kwh=H24_LOAD,
            pv_gen_per_kw=H24_PV_PER_KW,
            import_rates=P_IMP,
            export_rates=P_EXP_ACC,
        )
        fixed_pv_kw = 3.0
        fixed_batt_kwh = 5.0
        c_pv_kw = 3000.0
        c_batt_kwh = 900.0
        discount_rate = 0.05
        pv_life_yrs = 20
        batt_life_yrs = 8

        result = _solve_lp(
            inputs,
            fixed_pv_kw=fixed_pv_kw,
            fixed_batt_kwh=fixed_batt_kwh,
            c_pv_kw=c_pv_kw,
            c_batt_kwh=c_batt_kwh,
            c_batt_kw=0.0,
            pv_life_yrs=pv_life_yrs,
            batt_life_yrs=batt_life_yrs,
            discount_rate=discount_rate,
        )

        expected_capex = (
            fixed_pv_kw * c_pv_kw * crf(discount_rate, pv_life_yrs)
            + fixed_batt_kwh * c_batt_kwh * alpha_batt_npv(discount_rate, batt_life_yrs, pv_life_yrs)
        )

        assert result.capex_annual == pytest.approx(expected_capex, rel=1e-9), (
            "LP capex_annual has drifted from evaluations.eac.crf/alpha_batt_npv — "
            "the LP must compute its NPV-framing capex coefficients via the shared "
            "primitives, not a local re-derivation."
        )


# ---------------------------------------------------------------------------
# H7 — LP sizing price must match step14's reporting price
#
# Bug found 2026-07-06: the LP sized PV/battery against stale hardcoded
# defaults ($2,830/kW, $800/kWh) while step14 (via SolarSystemAppliance,
# BatteryStorageAppliance) reported capex for that same system at the real,
# cited values (~$3,300/kW, ~$1,461/kWh gross). Demonstrated live: a
# discount-rate sweep at r=0.03 sized a 2.13 kWh battery as "worth it" at
# $800/kWh, but the reported capex_storage only reconciled at ~$1,023/kWh net
# of ITC — a price the LP never evaluated the decision against.
#
# Refinement 2026-07-07: reconciling to *gross* cost left a second, smaller
# inconsistency — the paper's default/headline scenario reports capex net of
# the 30% ITC (full_incentives), not gross. The LP's sizing signal should
# match whichever incentive scenario is actually reported, so these defaults
# (assumed when a caller doesn't specify otherwise) are now net of
# full_incentives, matching Config's own default incentive scenario.
# ---------------------------------------------------------------------------
class TestLPSizingPriceMatchesReportingPrice:
    def test_core_lp_defaults_match_appliance_classes(self):
        from appliances.electric_base import IncentiveScenario
        from pipeline.steps.step9b_cooptimize_core import (
            _DEFAULT_PV_CAPEX_PER_KW,
            _DEFAULT_BATT_CAPEX_PER_KWH,
        )
        from appliances.solar_system import SolarSystemAppliance
        from appliances.battery_storage import BatteryStorageAppliance

        assert _DEFAULT_PV_CAPEX_PER_KW == pytest.approx(
            SolarSystemAppliance.per_kw_cost_net(IncentiveScenario.FULL_INCENTIVES)
        )
        assert _DEFAULT_BATT_CAPEX_PER_KWH == pytest.approx(
            BatteryStorageAppliance.per_kwh_cost_net(IncentiveScenario.FULL_INCENTIVES)
        )

    def test_process_defaults_match_appliance_classes(self):
        from appliances.electric_base import IncentiveScenario
        from pipeline.steps.step9b_cooptimize_pv_battery import (
            DEFAULT_PV_CAPEX_PER_KW,
            DEFAULT_BATT_CAPEX_PER_KWH,
        )
        from appliances.solar_system import SolarSystemAppliance
        from appliances.battery_storage import BatteryStorageAppliance

        assert DEFAULT_PV_CAPEX_PER_KW == pytest.approx(
            SolarSystemAppliance.per_kw_cost_net(IncentiveScenario.FULL_INCENTIVES)
        )
        assert DEFAULT_BATT_CAPEX_PER_KWH == pytest.approx(
            BatteryStorageAppliance.per_kwh_cost_net(IncentiveScenario.FULL_INCENTIVES)
        )

    def test_lp_default_battery_price_is_not_the_old_stale_value(self):
        """The old bug's hardcoded $800/kWh was well below the real net
        reporting price (~$1,022/kWh). Assert the default has actually moved,
        not just that it's internally self-consistent (which a re-introduced
        bug could also be, if someone hardcoded the same wrong number in both
        places)."""
        from pipeline.steps.step9b_cooptimize_core import _DEFAULT_BATT_CAPEX_PER_KWH

        assert _DEFAULT_BATT_CAPEX_PER_KWH > 950, (
            f"Default battery $/kWh is {_DEFAULT_BATT_CAPEX_PER_KWH}, suspiciously close to "
            f"the old stale $800/kWh default. Confirm "
            f"BatteryStorageAppliance.per_kwh_cost_net(FULL_INCENTIVES) still reflects real "
            f"market pricing."
        )
