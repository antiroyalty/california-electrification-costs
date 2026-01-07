from __future__ import annotations

from .constants import THERM_TO_KWH


def therms_to_kwh(therms: float) -> float:
    try:
        return float(therms or 0.0) * THERM_TO_KWH
    except Exception:
        return 0.0


def effective_price_per_kwh(annual_cost: float, annual_kwh: float) -> float:
    try:
        kwh = float(annual_kwh)
        if kwh <= 0:
            return 0.0
        return float(annual_cost) / kwh
    except Exception:
        return 0.0

