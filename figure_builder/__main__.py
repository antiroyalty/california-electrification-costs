#!/usr/bin/env python3
"""CLI driver for figure_builder.

    python3 -m figure_builder sweeps                 # (re)compute all county sweeps
    python3 -m figure_builder sweeps --counties alameda --force
    python3 -m figure_builder mechanism              # patch Claim-1 mechanism block
    python3 -m figure_builder counties               # patch Claim-1 county grid
    python3 -m figure_builder bridge                 # render bridge waterfall PNG
    python3 -m figure_builder split                  # split combined -> claim1/2/3.html
    python3 -m figure_builder all                    # sweeps + mechanism + counties + bridge + split

`all` writes a run_metadata.json (regime, git sha, prices, artifacts) so any
figure run is reproducible.
"""
from __future__ import annotations

import argparse
import json

from figure_builder import COMBINED_DOC, FIG_DIR, REPO
from figure_builder.datasets import collect_battery_capex_sweep
from figure_builder.dispatch import CLAIM1_COUNTIES
from figure_builder.pricing import live_prices


def _cmd_sweeps(args) -> list:
    slugs = args.counties or [s for s, _, _ in CLAIM1_COUNTIES]
    prices = live_prices()
    print(f"Regime {prices.regime}: solar fixed ${prices.pv_net_per_kw:,.0f}/kW, "
          f"battery ${prices.batt_net_per_kwh:,.0f}/kWh net")
    out = []
    for slug in slugs:
        print(f"\n{slug}:")
        df = collect_battery_capex_sweep(slug, force=args.force)
        out.append(str((REPO / "figure_builder" / "sweeps" / f"sweep_8760_{slug}.csv")))
    return out


def _cmd_mechanism(_args):
    from figure_builder.recipes import build_mechanism_block
    return [str(build_mechanism_block())]


def _cmd_counties(_args):
    from figure_builder.recipes import build_county_grid
    return [str(build_county_grid())]


def _cmd_bridge(_args):
    from figure_builder.recipes import build_bridge
    return [str(build_bridge())]


def _cmd_split(_args):
    from figure_builder.recipes import split_claims
    return [str(p) for p in split_claims()]


def _cmd_all(args):
    artifacts = []
    artifacts += _cmd_sweeps(args)
    artifacts += _cmd_mechanism(args)
    artifacts += _cmd_counties(args)
    artifacts += _cmd_bridge(args)
    artifacts += _cmd_split(args)
    _write_metadata(artifacts)
    return artifacts


def _git_sha() -> str:
    try:
        from helpers.main_helpers import git_short_sha
        return git_short_sha()
    except Exception:
        return "unknown"


def _write_metadata(artifacts) -> None:
    prices = live_prices()
    meta = {
        "regime": prices.regime,
        "git_sha": _git_sha(),
        "pv_net_per_kw": prices.pv_net_per_kw,
        "batt_net_per_kwh": prices.batt_net_per_kwh,
        "combined_doc": str(COMBINED_DOC),
        "artifacts": artifacts,
    }
    path = FIG_DIR / "run_metadata.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(meta, indent=2, sort_keys=True))
    print(f"\nWrote {path}")


_COMMANDS = {
    "sweeps": _cmd_sweeps, "mechanism": _cmd_mechanism, "counties": _cmd_counties,
    "bridge": _cmd_bridge, "split": _cmd_split, "all": _cmd_all,
}


def main() -> None:
    ap = argparse.ArgumentParser(prog="python3 -m figure_builder", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=list(_COMMANDS))
    ap.add_argument("--counties", nargs="*", default=None,
                    help="County slugs (default: all four Claim-1 counties).")
    ap.add_argument("--force", action="store_true",
                    help="Recompute sweeps even if cached.")
    args = ap.parse_args()
    artifacts = _COMMANDS[args.command](args)
    print("\nArtifacts:")
    for a in artifacts:
        print(f"  {a}")


if __name__ == "__main__":
    main()
