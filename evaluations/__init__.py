"""
Evaluation primitives and core metrics.

This package defines side‑effect‑free evaluation logic used by the pipeline
and visualization layers. Keep file I/O and plotting outside these modules.

Exports
- capital recovery and NPV helpers
- EAC components calculation from in‑memory inputs
- Payback period helpers
"""

from .npv import npv, annuity_factor
from .eac import (
    crf,
    EACComponents,
    compute_eac_from_inputs,
)
from .payback_periods import (
    choose_annual_savings,
    compute_payback_years,
)
from .lcoe import (
    present_value_energy,
    lcoe_crf_simple,
    lcoe_npv_from_params,
    lcoe_from_schedules,
)
from .sensitivity import SensitivityParameter, SENSITIVITY_PARAMETERS

__all__ = [
    "npv",
    "annuity_factor",
    "crf",
    "EACComponents",
    "compute_eac_from_inputs",
    "choose_annual_savings",
    "compute_payback_years",
    "present_value_energy",
    "lcoe_crf_simple",
    "lcoe_npv_from_params",
    "lcoe_from_schedules",
    "SensitivityParameter",
    "SENSITIVITY_PARAMETERS",
]
