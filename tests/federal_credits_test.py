"""Source-backed policy records and behavior preserved by their extraction."""

from dataclasses import FrozenInstanceError
from datetime import date
import os
from pathlib import Path
import subprocess
import sys

import pytest

from appliances import incentive_policy
from appliances.battery_storage import BatteryStorageAppliance
from appliances.electric_base import IncentiveScenario
from appliances.federal_credits import (
    FEDERAL_CREDITS, FEDERAL_ITC_25D, FEDERAL_25C, FEDERAL_30D,
)
from appliances.incentive_policy import PolicyRegime


def test_catalog_contains_only_the_three_modeled_federal_tax_credits():
    assert set(FEDERAL_CREDITS) == {"25D", "25C", "30D"}
    assert FEDERAL_CREDITS["25D"] is incentive_policy.FEDERAL_ITC_25D
    assert FEDERAL_CREDITS["25C"] is incentive_policy.FEDERAL_25C
    assert FEDERAL_CREDITS["30D"] is incentive_policy.FEDERAL_30D


def test_amounts_distinguish_percentage_annual_cap_and_vehicle_maximum():
    # IRS Forms 5695 and 8936 (2025); these are rules, not a claim of eligibility.
    assert FEDERAL_ITC_25D.fraction == 0.30
    assert FEDERAL_ITC_25D.annual_cap_usd is None
    assert FEDERAL_25C.fraction == 0.30
    assert FEDERAL_25C.annual_cap_usd == 2000.0
    assert FEDERAL_30D.fraction is None
    assert FEDERAL_30D.maximum_credit_usd == 7500.0


def test_date_records_preserve_distinct_storage_and_vehicle_windows():
    assert FEDERAL_ITC_25D.valid_from == "2022-01-01"
    assert FEDERAL_ITC_25D.storage_valid_from == "2023-01-01"
    assert FEDERAL_ITC_25D.valid_through == FEDERAL_25C.valid_through == "2025-12-31"
    assert FEDERAL_30D.valid_through == "2025-09-30"
    assert FEDERAL_30D.dealer_transfer_valid_from == "2024-01-01"
    for credit in FEDERAL_CREDITS.values():
        assert date.fromisoformat(credit.valid_from) <= date.fromisoformat(credit.valid_through)


def test_unused_credit_rules_are_not_shared_across_credit_families():
    assert FEDERAL_ITC_25D.claim_on_return_carryforward is True
    assert FEDERAL_25C.claim_on_return_carryforward is False
    assert FEDERAL_30D.claim_on_return_carryforward is False


def test_policy_records_cannot_be_modified_by_a_scenario():
    with pytest.raises(FrozenInstanceError):
        FEDERAL_ITC_25D.fraction = 0.0
    with pytest.raises(TypeError):
        FEDERAL_CREDITS["25D"] = FEDERAL_25C


@pytest.mark.parametrize("regime,expected", [
    (PolicyRegime.ITC_2025, (0.30, (0.30, 2000.0), 7500.0)),
    (PolicyRegime.POST_ITC_2026, (0.0, None, None)),
])
def test_existing_regime_helpers_keep_their_public_results(regime, expected):
    assert (
        incentive_policy.federal_itc_fraction(regime),
        incentive_policy.federal_25c_credit(regime),
        incentive_policy.federal_30d_amount(regime),
    ) == expected


@pytest.mark.parametrize("capacity_kwh,eligible", [(2.999, False), (3.0, True), (3.001, True)])
@pytest.mark.parametrize("regime", list(PolicyRegime))
def test_battery_constructor_preserves_the_sourced_capacity_boundary(capacity_kwh, eligible, regime):
    # Fractional units represent the continuous capacities already used by the model.
    battery = BatteryStorageAppliance(
        num_units=capacity_kwh / BatteryStorageAppliance.UNIT_CAPACITY_KWH,
        policy_regime=regime,
    )
    expected_credit = (
        battery.base_cost * 0.30
        if eligible and regime is PolicyRegime.ITC_2025 else 0.0
    )
    assert battery.calculate_total_incentives(
        IncentiveScenario.FULL_INCENTIVES,
    ) == pytest.approx(expected_credit)
    assert battery.get_net_cost(IncentiveScenario.FULL_INCENTIVES) == pytest.approx(
        battery.base_cost - expected_credit,
    )


def test_existing_policy_summary_runs_directly_without_pythonpath(tmp_path):
    script = Path(__file__).resolve().parents[1] / "appliances" / "incentive_policy.py"
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    result = subprocess.run(
        [sys.executable, str(script)], cwd=tmp_path, env=env,
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert "2,310.00" in result.stdout
    assert "1,022.45" in result.stdout
    assert "post_itc_2026" in result.stdout
