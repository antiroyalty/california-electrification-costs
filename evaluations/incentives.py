from __future__ import annotations

from typing import Tuple


def apply_pv_storage_incentives(
    pv_capex: float,
    storage_capex: float,
    pv_incentives_full: float = 0.0,
    storage_incentives_full: float = 0.0,
    *,
    incentive: str = "full_incentives",
) -> Tuple[float, float]:
    """Return net upfront (pv_net, storage_net) given an incentive scenario.

    Scenarios supported: 'full_incentives', 'half_incentives', 'no_incentives'.
    """
    inc = (incentive or "").lower()
    pv_capex = float(pv_capex or 0.0)
    st_capex = float(storage_capex or 0.0)
    pv_inc = float(pv_incentives_full or 0.0)
    st_inc = float(storage_incentives_full or 0.0)

    if inc == "full_incentives":
        return pv_capex - pv_inc, st_capex - st_inc
    if inc == "half_incentives":
        return pv_capex - (pv_inc * 0.5), st_capex - (st_inc * 0.5)
    return pv_capex, st_capex

