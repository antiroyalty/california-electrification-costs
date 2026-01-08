from __future__ import annotations

import os
import runpy
from typing import Any

from ...config import Config


def _repo_root() -> str:
    here = os.path.dirname(__file__)
    return os.path.dirname(os.path.dirname(os.path.dirname(here)))


def run(cfg: Config) -> None:
    """Run Module 4: visualize and compare results.

    Delegates to 4_visualize-and-compare-results/run.py for now.
    """
    root = _repo_root()
    script = os.path.join(root, "4_visualize-and-compare-results", "run.py")
    ns: dict[str, Any] = runpy.run_path(script, run_name="__not_main__")
    fn = ns.get("run")
    if not callable(fn):
        raise RuntimeError("run() not found in module 4 runner")

    fn(
        cfg.scenario,
        cfg.housing_type,
        cfg.counties,
        base_input_dir=cfg.base_input_dir,
        output_dir=cfg.output_dir,
        electricity_variant=cfg.electricity_variant,
        plan_preference=None,
        desired_rate_plans=cfg.rate_plans,
        incentive=cfg.incentive,
        discount_rate=cfg.discount_rate,
        agg=cfg.agg,
    )


__all__ = ["run"]

