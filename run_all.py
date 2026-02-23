#!/usr/bin/env python3
"""
run_all.py — Run the full analysis pipeline for all (or selected) scenarios.

For every scenario:        runs cost_service.py  (pipeline steps 1–22, Alameda only)
For every _coopt scenario: additionally runs step9b with default sweeps

Note: cost_service.py is currently hardcoded to Alameda County.
      --counties only controls which counties step9b runs for.

Usage
-----
  python3 run_all.py                           # all scenarios, Alameda
  python3 run_all.py --coopt-only              # step9b only (skip cost_service)
  python3 run_all.py --skip-coopt              # cost_service only (skip step9b)
  python3 run_all.py --skip-cost-service       # step9b only (load profiles exist)
  python3 run_all.py --scenarios baseline_coopt full_electric_ev_coopt
  python3 run_all.py --counties alameda los-angeles
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
        "--coarse-sweeps",
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
        "--coopt-only", action="store_true",
        help="Only run step9b for _coopt scenarios; skip cost_service entirely",
    )
    p.add_argument(
        "--skip-coopt", action="store_true",
        help="Skip step9b; only run cost_service for all scenarios",
    )
    p.add_argument(
        "--skip-cost-service", action="store_true",
        help="Skip cost_service.py (use when load profiles are already generated)",
    )
    args = p.parse_args()

    if args.coopt_only and args.skip_coopt:
        print("Error: --coopt-only and --skip-coopt are mutually exclusive.")
        sys.exit(1)

    # Determine which scenarios to run
    if args.scenarios:
        unknown = [s for s in args.scenarios if s not in SCENARIOS]
        if unknown:
            print(f"Error: unknown scenario(s): {', '.join(unknown)}")
            print(f"Available: {', '.join(SCENARIOS)}")
            sys.exit(1)
        scenarios_to_run = args.scenarios
    elif args.coopt_only:
        scenarios_to_run = COOPT_SCENARIOS
    else:
        scenarios_to_run = list(SCENARIOS.keys())

    coopt_to_run = [s for s in scenarios_to_run if s.endswith("_coopt")]

    failures: List[str] = []

    # Step 1: cost_service for all scenarios
    if not args.coopt_only and not args.skip_cost_service:
        print(f"\nRunning cost_service.py for {len(scenarios_to_run)} scenario(s)...")
        for scenario in scenarios_to_run:
            if not run_cost_service(scenario):
                failures.append(f"cost_service: {scenario}")

    # Step 2: step9b for coopt scenarios
    if not args.skip_coopt and coopt_to_run:
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
