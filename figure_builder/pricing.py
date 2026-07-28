"""Live capital costs, sourced from the same appliance-class primitives the
co-optimization LP prices against.

This exists so figure annotations can never drift from the model. The whole
Claim-1 rework began because a figure said "$1,022/kWh" while the model priced
storage at a different number. Read the price from one place, always.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LivePrices:
    """Net capital costs (after incentives) under one policy regime."""
    regime: str
    pv_net_per_kw: float
    batt_net_per_kwh: float

    def pv_lcoe(self, yield_per_kw: float, discount_rate: float = 0.07,
                life_years: int = 25) -> float:
        """Levelized cost of the marginal kWh of rooftop solar, $/kWh.

        Uses the repo's canonical capital recovery factor.
        """
        from evaluations.eac import crf
        return self.pv_net_per_kw * crf(discount_rate, life_years) / yield_per_kw


def live_prices(regime=None) -> LivePrices:
    """Net PV ($/kW) and battery ($/kWh) capital costs under `regime`.

    Defaults to current law (`DEFAULT_POLICY_REGIME`). Pass
    `PolicyRegime.ITC_2025` to price the pre-OBBBA before/after comparison.
    """
    from appliances.solar_system import SolarSystemAppliance
    from appliances.battery_storage import BatteryStorageAppliance
    from appliances.electric_base import IncentiveScenario
    from appliances.incentive_policy import DEFAULT_POLICY_REGIME

    reg = regime or DEFAULT_POLICY_REGIME
    return LivePrices(
        regime=getattr(reg, "value", str(reg)),
        pv_net_per_kw=float(
            SolarSystemAppliance.per_kw_cost_net(IncentiveScenario.FULL_INCENTIVES, reg)
        ),
        batt_net_per_kwh=float(
            BatteryStorageAppliance.per_kwh_cost_net(IncentiveScenario.FULL_INCENTIVES, reg)
        ),
    )
