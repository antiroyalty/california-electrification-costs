"""
Exports/NEM3 augmentation helpers for Step 9.

Provides functions to compute explicit export channels and to assemble a
comprehensive exports-only CSV capturing import/export flows and conveniences.
"""

from __future__ import annotations

from typing import List, Optional
import pandas as pd


def _ensure_length(values: Optional[List[float]], n: int = 8760, fill: float = 0.0) -> List[float]:
    if values is None:
        return [fill] * n
    vals = list(map(float, values))
    if len(vals) >= n:
        return vals[:n]
    return vals + [fill] * (n - len(vals))


def compute_excess_solar_exports(
    pv_ac_kwh: Optional[List[float]],
    system_to_load: Optional[List[float]],
    system_to_battery: Optional[List[float]],
) -> List[float]:
    """Compute hourly excess solar exported to grid: max(0, PV − PV→Load − PV→Battery)."""
    n = 8760
    pv = _ensure_length(pv_ac_kwh, n, 0.0)
    stl = _ensure_length(system_to_load, n, 0.0)
    stb = _ensure_length(system_to_battery, n, 0.0)
    return [max(0.0, float(p) - float(a) - float(b)) for p, a, b in zip(pv, stl, stb)]


def prepare_export_enabled_outputs(
    load_profile: Optional[List[float]] = None,
    pv_ac_kwh: Optional[List[float]] = None,
    system_to_load: Optional[List[float]] = None,
    battery_to_load: Optional[List[float]] = None,
    grid_to_load: Optional[List[float]] = None,
    system_to_battery: Optional[List[float]] = None,
    grid_to_battery: Optional[List[float]] = None,
    battery_soc_percent: Optional[List[float]] = None,
    battery_to_grid_kwh: Optional[List[float]] = None,
    pv_to_grid_kwh: Optional[List[float]] = None,
    # Additional optional channels/aliases for richer exports-only CSV
    battery_charge_stored_kwh: Optional[List[float]] = None,
    grid_demand_kwh: Optional[List[float]] = None,
    pv_used_onsite_kwh: Optional[List[float]] = None,
    start_timestamp: str = "2018-01-01",
) -> pd.DataFrame:
    n = 8760

    load = _ensure_length(load_profile, n, 0.0)
    pv = _ensure_length(pv_ac_kwh, n, 0.0)
    stl = _ensure_length(system_to_load, n, None if (load_profile and pv_ac_kwh) else 0.0)
    btl = _ensure_length(battery_to_load, n, 0.0)
    gtl = _ensure_length(grid_to_load, n, 0.0)
    stb = _ensure_length(system_to_battery, n, 0.0)
    gtb = _ensure_length(grid_to_battery, n, 0.0)
    soc = _ensure_length(battery_soc_percent, n, 0.0)
    btg = _ensure_length(battery_to_grid_kwh, n, 0.0)

    # If System to Load wasn't provided but both load and PV are, derive it.
    if system_to_load is None and pv_ac_kwh is not None and load_profile is not None:
        stl = [min(p, l) for p, l in zip(pv, load)]

    # PV to grid: prefer provided override; otherwise derive from inputs
    if pv_to_grid_kwh is not None:
        pv_to_grid = _ensure_length(pv_to_grid_kwh, n, 0.0)
    else:
        pv_to_grid = [max(0.0, float(p) - float(a) - float(b)) for p, a, b in zip(pv, stl, stb)]

    exports = [float(pg) + float(bg) for pg, bg in zip(pv_to_grid, btg)]
    solar_plus_batt_to_load = [float(a) + float(b) for a, b in zip(stl, btl)]
    total_supply = [float(a) + float(b) + float(c) for a, b, c in zip(stl, btl, gtl)]
    diff = [float(l) - float(ts) for l, ts in zip(load, total_supply)]
    net_grid_import = [float(gtl_h) + float(gtb_h) - float(exp_h) for gtl_h, gtb_h, exp_h in zip(gtl, gtb, exports)]

    # Optional channels and convenient aliases
    grid_demand = _ensure_length(grid_demand_kwh, n, None) if grid_demand_kwh is not None else [float(a) + float(b) for a, b in zip(gtl, gtb)]
    pv_used_onsite = _ensure_length(pv_used_onsite_kwh, n, None) if pv_used_onsite_kwh is not None else [float(a) + float(b) for a, b in zip(stl, stb)]
    batt_charge_stored = _ensure_length(battery_charge_stored_kwh, n, 0.0)

    date_range = pd.date_range(start=start_timestamp, periods=n, freq="H")
    df = pd.DataFrame(
        {
            "Load Profile": load,
            "System to Load": stl,
            "Solar to Load (kWh)": stl,
            "Battery to Load": btl,
            "Grid to Load": gtl,
            "System to Battery": stb,
            "Solar to Battery (kWh)": stb,
            "Grid to Battery": gtb,
            "Battery SOC": soc,
            "PV AC (kWh)": pv,
            "PV to Grid (kWh)": pv_to_grid,
            "Solar to Grid (kWh)": pv_to_grid,
            "Battery to Grid (kWh)": btg,
            "Exports to Grid (kWh)": exports,
            # Keep "System to Grid" for backward compatibility (alias PV to Grid)
            "System to Grid": pv_to_grid,
            "PV Used Onsite (kWh)": pv_used_onsite,
            "Grid Demand (kWh)": grid_demand,
            "Battery Charge Stored (kWh)": batt_charge_stored,
            "Solar + Battery to Load": solar_plus_batt_to_load,
            "Total Supply": total_supply,
            "Difference": diff,
            "Net Grid Import (kWh)": net_grid_import,
        },
        index=date_range,
    )
    return df

