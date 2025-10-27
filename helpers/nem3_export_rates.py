"""
Helpers for NEM 3.0 (Net Billing Tariff) export rates and default options.

This module provides a lightweight interface to obtain hourly export
compensation tables (ACC-derived, month x hour) and default NEM3 options
per utility. The initial values here are placeholders so the pipeline can
run end-to-end. Replace with real tables sourced from CPUC/utility filings.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List


def _zeros_table() -> Dict[int, List[float]]:
    """Return a 12x24 table (dict) of zeros (dollars per kWh)."""
    return {m: [0.0] * 24 for m in range(1, 13)}


def get_export_rate_table(utility: str) -> Dict[int, List[float]]:
    """Return month->24hr ACC-based export rates ($/kWh) for the given utility.

    Replace the placeholder data below with the actual NBT export
    compensation tables (12x24) for the model year.
    """
    util = (utility or "").strip().upper()
    if "PG&E" in util or util == "PGE":
        return _zeros_table()
    if util == "SCE":
        return _zeros_table()
    if "SDG&E" in util or util in ("SDGE", "SDG&E"):
        return _zeros_table()
    # default
    return _zeros_table()


@dataclass
class NEM3Options:
    nbc_dollars_per_kwh: float = 0.0
    fixed_charge_monthly: float = 0.0
    minimum_bill_monthly: float = 0.0
    true_up_month: int = 12
    nsc_dollars_per_kwh: float = 0.0


def default_options_for_utility(utility: str) -> NEM3Options:
    util = (utility or "").strip().upper()
    if "PG&E" in util or util == "PGE":
        return NEM3Options(nbc_dollars_per_kwh=0.0, fixed_charge_monthly=0.0, minimum_bill_monthly=0.0)
    if util == "SCE":
        return NEM3Options(nbc_dollars_per_kwh=0.0, fixed_charge_monthly=0.0, minimum_bill_monthly=0.0)
    if "SDG&E" in util or util in ("SDGE", "SDG&E"):
        return NEM3Options(nbc_dollars_per_kwh=0.0, fixed_charge_monthly=0.0, minimum_bill_monthly=0.0)
    return NEM3Options()

