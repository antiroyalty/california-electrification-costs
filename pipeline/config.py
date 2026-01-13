from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional


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
    discount_rate: float = 0.07
    agg: str = "mean"

