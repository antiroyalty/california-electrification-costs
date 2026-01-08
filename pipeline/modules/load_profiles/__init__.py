from __future__ import annotations

import os
import runpy
from typing import Any

from ...config import Config


def _repo_root() -> str:
    # pipeline/modules/load_profiles/__init__.py -> pipeline/modules -> pipeline -> root
    here = os.path.dirname(__file__)
    return os.path.dirname(os.path.dirname(os.path.dirname(here)))


def run(cfg: Config) -> None:
    """Run Module 1: retrieve buildings and construct load profiles.

    Delegates to 1_retrieve-buildings-and-construct-load-profiles/run.py for now.
    """
    root = _repo_root()
    script = os.path.join(root, "1_retrieve-buildings-and-construct-load-profiles", "run.py")
    ns: dict[str, Any] = runpy.run_path(script, run_name="__not_main__")
    fn = ns.get("run")
    if not callable(fn):
        raise RuntimeError("run() not found in module 1 runner")

    # Derive input_dir/output_dir from cfg.base_input_dir (defaults to data/loadprofiles)
    base_lp = cfg.base_input_dir
    input_dir = os.path.dirname(base_lp) if base_lp.endswith("loadprofiles") else "data"
    fn(
        cfg.scenario,
        cfg.housing_type,
        cfg.counties,
        input_dir=input_dir,
        output_dir=base_lp,
    )


__all__ = ["run"]

