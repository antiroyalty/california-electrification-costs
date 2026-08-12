"""Preflight generated county profiles before an expensive NBT billing run.

Examples:
  python3 scripts/validate_nbt_run_inputs.py baseline_coopt --counties alameda
  python3 scripts/validate_nbt_run_inputs.py baseline_coopt --all-counties
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
from typing import Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tariffs import (
    NBTScenario,
    discover_nbt_profile_counties,
    preflight_nbt_run,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scenario", help="Scenario artifact directory to check")
    parser.add_argument("--base-input-dir", default="data/loadprofiles")
    parser.add_argument("--housing-type", default="single-family-detached")
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument("--counties", nargs="+", help="County names or slugs")
    selection.add_argument("--all-counties", action="store_true")
    parser.add_argument("--billing-year", type=int, default=2026)
    parser.add_argument("--nbt-vintage", type=int, default=2026)
    parser.add_argument("--true-up-month", default="2026-08")
    parser.add_argument("--tariff-snapshot-date", default="2026-08-09")
    parser.add_argument("--exclude-acc-plus", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    counties = (
        discover_nbt_profile_counties(
            args.base_input_dir,
            args.scenario,
            args.housing_type,
        )
        if args.all_counties
        else args.counties
    )
    nbt_scenario = NBTScenario(
        billing_year=args.billing_year,
        nbt_vintage=args.nbt_vintage,
        include_acc_plus=not args.exclude_acc_plus,
        tariff_snapshot_date=args.tariff_snapshot_date,
        true_up_month=args.true_up_month,
    )
    results, failures = preflight_nbt_run(
        base_input_dir=args.base_input_dir,
        scenario_name=args.scenario,
        housing_type=args.housing_type,
        counties=counties,
        nbt_scenario=nbt_scenario,
    )

    print(
        f"NBT preflight: scenario={args.scenario}, billing_year="
        f"{nbt_scenario.billing_year}, vintage={nbt_scenario.nbt_vintage}, "
        f"tariff_snapshot={nbt_scenario.tariff_snapshot_date}, "
        f"true_up_month={nbt_scenario.true_up_month}, "
        f"acc_plus={nbt_scenario.include_acc_plus}"
    )
    for result in results:
        true_up_sources = (
            f"{result.adjustment_source_id},{result.nsc_source_id}"
            if result.net_surplus_kwh > 0.0
            else "not-required"
        )
        print(
            f"PASS {result.county_slug}: {result.utility.value}; "
            f"rows={result.row_count}; annual_net_surplus="
            f"{result.net_surplus_kwh:,.1f} kWh; "
            f"import_source={result.import_source_id}; "
            f"export_sources={','.join(result.export_source_ids)}; "
            f"true_up_sources={true_up_sources}"
        )
    for failure in failures:
        print(f"FAIL {failure}", file=sys.stderr)
    print(f"Summary: {len(results)} passed; {len(failures)} failed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
