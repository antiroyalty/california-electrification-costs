from __future__ import annotations

import os
import runpy
from typing import Any

from ...config import Config


def _repo_root() -> str:
    here = os.path.dirname(__file__)
    return os.path.dirname(os.path.dirname(os.path.dirname(here)))


def run(cfg: Config) -> None:
    """Run Module 3: compute rates and capital costs.

    Delegates to 3_compute_rates_and_capital_costs/run.py for now.
    """
    root = _repo_root()
    script = os.path.join(root, "3_compute_rates_and_capital_costs", "run.py")
    ns: dict[str, Any] = runpy.run_path(script, run_name="__not_main__")
    fn = ns.get("run")
    if not callable(fn):
        raise RuntimeError("run() not found in module 3 runner")

    fn(
        cfg.scenario,
        cfg.housing_type,
        cfg.counties,
        base_dir=cfg.base_input_dir,
    )


__all__ = ["run"]

