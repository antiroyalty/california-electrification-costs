from __future__ import annotations

import os
import runpy
from typing import Any

from ...config import Config


def _repo_root() -> str:
    here = os.path.dirname(__file__)
    return os.path.dirname(os.path.dirname(os.path.dirname(here)))


def run(cfg: Config) -> None:
    """Run Module 2: compute and co‑optimize solar and storage.

    Delegates to 2_compute-and-cooptimize-solar-storage/run.py for now.
    """
    root = _repo_root()
    script = os.path.join(root, "2_compute-and-cooptimize-solar-storage", "run.py")
    ns: dict[str, Any] = runpy.run_path(script, run_name="__not_main__")
    fn = ns.get("run")
    if not callable(fn):
        raise RuntimeError("run() not found in module 2 runner")

    fn(
        cfg.scenario,
        cfg.housing_type,
        cfg.counties,
        base_dir=cfg.base_input_dir,
        weather_year=2018,
    )


__all__ = ["run"]

