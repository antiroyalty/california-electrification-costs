"""Sensitivity parameter registry — pure, no I/O.

States which pipeline stages each parameter actually requires re-running.
This is where a real methodology question gets answered on purpose instead
of by accident: NBC currently affects only billing (step 12), not the LP's
price series in step 9b — so an NBC sweep does not need to re-solve the LP.
If that assumption should ever change (NBC should feed the LP's dispatch
signal), the fix is to flip `requires_lp_resolve` here, deliberately, not to
discover the gap later.

The orchestration that actually runs a sweep (calls the pipeline modules,
writes results) lives in `pipeline.sensitivity_runner`, which imports this
registry — kept separate so this module stays consistent with the rest of
evaluations/ (side-effect-free, safe to import and reason about anywhere).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict


@dataclass(frozen=True)
class SensitivityParameter:
    name: str
    config_field: str
    requires_lp_resolve: bool
    description: str


SENSITIVITY_PARAMETERS: Dict[str, SensitivityParameter] = {
    "discount_rate": SensitivityParameter(
        name="discount_rate",
        config_field="discount_rate",
        requires_lp_resolve=True,
        description=(
            "Real discount rate used for CRF/NPV annualization. Changes the "
            "LP's optimal PV/battery sizing (step 9b), not just EAC "
            "annualization at report time — a full resolve is required."
        ),
    ),
    "nbc_dollars_per_kwh": SensitivityParameter(
        name="nbc_dollars_per_kwh",
        config_field="nbc_dollars_per_kwh_override",
        requires_lp_resolve=False,
        description=(
            "Non-bypassable charge applied to electricity imports. Currently "
            "affects only billing (step 12), not the LP's price series in "
            "step 9b — the LP sizes PV/battery as if NBC were always 0. No "
            "resolve needed; only steps 10-14 (rates/capital) re-run. If NBC "
            "should ever feed the LP's dispatch signal, flip "
            "requires_lp_resolve to True here — deliberately, not by accident."
        ),
    ),
}
