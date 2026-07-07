from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from evaluations.constants import DEFAULT_DISCOUNT_RATE


@dataclass
class Config:
    """Shared configuration for pipeline runs.

    This intentionally mirrors the options used across existing scripts and
    cost_service, providing a single object to pass through module boundaries.
    """

    scenario: str
    housing_type: str
    counties: List[str] = field(default_factory=list)

    # Paths
    base_input_dir: str = "data/loadprofiles"
    output_dir: str = "analysis_results"

    # Rate planning and evaluation settings
    rate_plans: Optional[Dict[str, Dict[str, str]]] = None
    electricity_variant: str = "nem3"
    incentive: str = "full_incentives"
    discount_rate: float = DEFAULT_DISCOUNT_RATE
    agg: str = "mean"

    # Sensitivity override: non-bypassable charge ($/kWh). None = use each
    # utility's default (currently 0.0 for all three — see helpers/nem3_export_rates.py).
    nbc_dollars_per_kwh_override: Optional[float] = None

