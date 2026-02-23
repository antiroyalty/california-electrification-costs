#!/usr/bin/env python3
"""
run_all.py — Run step9b co-optimization for all (or selected) _coopt scenarios.

By default runs only step9b with default sweeps. Pass --include-cost-service
to also regenerate load profiles via cost_service.py first.

Note: cost_service.py is hardcoded to Alameda County.
      --counties controls which counties step9b runs for.

Usage
-----
  python3 run_all.py                                        # all coopt scenarios
  python3 run_all.py --scenarios baseline_coopt full_electric_ev_coopt
  python3 run_all.py --counties alameda los-angeles
  python3 run_all.py --include-cost-service                 # also regenerate load profiles
"""

import argparse
import subprocess
import sys
from pathlib import Path
from typing import List, Optional

from scenarios import SCENARIOS

COOPT_SCENARIOS: List[str] = [s for s in SCENARIOS if s.endswith("_coopt")]
BASE_SCENARIOS: List[str] = [s for s in SCENARIOS if not s.endswith("_coopt")]
REPO_ROOT = Path(__file__).parent


def run_cost_service(scenario: str) -> bool:
    """Run cost_service.py for a single scenario. Returns True on success."""
    print(f"\n{'=' * 60}")
    print(f"  cost_service: {scenario}")
    print(f"{'=' * 60}")
    result = subprocess.run(
        [sys.executable, "cost_service.py", scenario],
        cwd=REPO_ROOT,
    )
    if result.returncode != 0:
        print(f"[run_all] WARNING: cost_service.py failed for {scenario} (exit {result.returncode})")
        return False
    return True


def run_step9b(scenario: str, counties: Optional[List[str]] = None) -> bool:
    """Run step9b co-optimization with default sweeps for a single scenario."""
    print(f"\n{'=' * 60}")
    print(f"  step9b: {scenario}")
    print(f"{'=' * 60}")
    cmd = [
        sys.executable, "-m", "pipeline.steps.step9b_cooptimize_pv_battery",
        "--scenario", scenario,
        "--use-defaults",
    ]
    if counties:
        cmd += ["--counties"] + counties
    result = subprocess.run(cmd, cwd=REPO_ROOT)
    if result.returncode != 0:
        print(f"[run_all] WARNING: step9b failed for {scenario} (exit {result.returncode})")
        return False
    return True


def main() -> None:
    p = argparse.ArgumentParser(
        description="Run the full pipeline for all (or selected) scenarios.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"Coopt scenarios: {', '.join(COOPT_SCENARIOS)}\n"
               f"Base scenarios:  {', '.join(BASE_SCENARIOS)}",
    )
    p.add_argument(
        "--scenarios", nargs="*",
        help="Specific scenario name(s) to run (default: all)",
    )
    p.add_argument(
        "--counties", nargs="*", default=["alameda"],
        help="County slug(s) passed to step9b (default: alameda)",
    )
    p.add_argument(
        "--include-cost-service", action="store_true",
        help="Also run cost_service.py for all scenarios before step9b",
    )
    args = p.parse_args()

    # Determine which scenarios to run
    if args.scenarios:
        unknown = [s for s in args.scenarios if s not in SCENARIOS]
        if unknown:
            print(f"Error: unknown scenario(s): {', '.join(unknown)}")
            print(f"Available: {', '.join(SCENARIOS)}")
            sys.exit(1)
        scenarios_to_run = args.scenarios
    else:
        scenarios_to_run = COOPT_SCENARIOS

    coopt_to_run = [s for s in scenarios_to_run if s.endswith("_coopt")]

    failures: List[str] = []

    # Step 1: cost_service (opt-in only)
    if args.include_cost_service:
        print(f"\nRunning cost_service.py for {len(scenarios_to_run)} scenario(s)...")
        for scenario in scenarios_to_run:
            if not run_cost_service(scenario):
                failures.append(f"cost_service: {scenario}")

    # Step 2: step9b for coopt scenarios
    if coopt_to_run:
        print(f"\nRunning step9b for {len(coopt_to_run)} coopt scenario(s)...")
        for scenario in coopt_to_run:
            if not run_step9b(scenario, counties=args.counties):
                failures.append(f"step9b: {scenario}")

    # Summary
    print(f"\n{'=' * 60}")
    if failures:
        print(f"Completed with {len(failures)} failure(s):")
        for f in failures:
            print(f"  FAILED: {f}")
        sys.exit(1)
    else:
        total = len(scenarios_to_run) + len(coopt_to_run)
        print(f"All {total} run(s) completed successfully.")


if __name__ == "__main__":
    main()
