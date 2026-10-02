"""Declared physical and financial assumptions for PV/storage co-optimization."""

from __future__ import annotations

from dataclasses import dataclass
import math
from numbers import Real

from appliances.battery_storage import BatteryStorageAppliance
from appliances.electric_base import IncentiveScenario
from appliances.solar_system import SolarSystemAppliance
from evaluations.constants import DEFAULT_DISCOUNT_RATE
from evaluations.federal_credits import PVStorageCreditPolicy


DEFAULT_PV_CAPEX_USD_PER_KW = SolarSystemAppliance.per_kw_cost_net(
    IncentiveScenario.FULL_INCENTIVES
)
DEFAULT_BATTERY_CAPEX_USD_PER_KWH = BatteryStorageAppliance.per_kwh_cost_net(
    IncentiveScenario.FULL_INCENTIVES
)
DEFAULT_MAX_BATTERY_KWH = 40.0


def _finite_nonnegative(value: float, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, Real) or not math.isfinite(value):
        raise ValueError(f"{name} must be a finite nonnegative number")
    if value < 0:
        raise ValueError(f"{name} must be a finite nonnegative number")


@dataclass(frozen=True)
class CooptimizationAssumptions:
    """One solver-independent statement of the modeled equipment choices.

    Prices are caller-supplied net installed costs in the legacy mode. An
    explicit federal policy requires gross qualifying installed costs instead.
    Tariff schedules, hourly profiles, fixed sizes, chronology, and solver
    controls are separate inputs rather than equipment assumptions.
    """

    allow_grid_charging: bool = False
    allow_battery_export: bool = True
    pv_capex_usd_per_kw: float = DEFAULT_PV_CAPEX_USD_PER_KW
    battery_capex_usd_per_kwh: float = DEFAULT_BATTERY_CAPEX_USD_PER_KWH
    battery_power_capex_usd_per_kw: float = 0.0
    pv_lifetime_years: float = 25
    battery_lifetime_years: float = 15
    discount_rate: float = DEFAULT_DISCOUNT_RATE
    battery_degradation_usd_per_kwh: float = 0.0
    max_battery_kwh: float = DEFAULT_MAX_BATTERY_KWH
    max_pv_to_annual_load_ratio: float = 1.5
    federal_credit_policy: PVStorageCreditPolicy | None = None

    def __post_init__(self) -> None:
        for name in ("allow_grid_charging", "allow_battery_export"):
            if not isinstance(getattr(self, name), bool):
                raise ValueError(f"{name} must be a boolean")
        for name in (
            "pv_capex_usd_per_kw", "battery_capex_usd_per_kwh",
            "battery_power_capex_usd_per_kw", "discount_rate",
            "battery_degradation_usd_per_kwh", "max_battery_kwh",
        ):
            _finite_nonnegative(getattr(self, name), name)
        for name in ("pv_lifetime_years", "battery_lifetime_years"):
            value = getattr(self, name)
            if (isinstance(value, bool) or not isinstance(value, Real)
                    or not math.isfinite(value) or value <= 0):
                raise ValueError(f"{name} must be finite and positive")
        ratio = self.max_pv_to_annual_load_ratio
        if (isinstance(ratio, bool) or not isinstance(ratio, Real)
                or not math.isfinite(ratio) or ratio <= 0):
            raise ValueError("max_pv_to_annual_load_ratio must be finite and positive")
        if (self.federal_credit_policy is not None
                and not isinstance(self.federal_credit_policy, PVStorageCreditPolicy)):
            raise ValueError("federal_credit_policy must be a PVStorageCreditPolicy")
